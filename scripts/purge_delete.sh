#!/usr/bin/env bash
# bailiwick — the /purge delete step (skills/purge/SKILL.md Steps 5.2 and 5.6). Dry run by default.
#
#   purge_delete.sh --list <file> --from-file <file> --sha <approved-sha256> [--apply]
#   purge_delete.sh --list <file> --from-file <file> --print-sha
#
# Deletes ONLY the paths in an approved target list, ONLY inside the allowed roots, and ONLY when the
# list AND the from-file still hash to the sha256 the user approved (the hash is on the command line,
# so a guardrail prompt shows exactly which list it deletes). No target and no client token is ever on
# the command line: the list and the <from> name are read from files, because guarded commands are
# logged verbatim to the audit log. Output names line NUMBERS only, never paths: the acted command's
# own stdout/stderr is discarded and a FAILED line carries a path-free reason class instead.
#
# The approval hash binds both inputs: sha256 of the two lines "<sha256(list)>\n<sha256(from-file)>\n"
# (lowercase hex). `--print-sha` prints it (and nothing else). Both files are first copied into a
# private (umask 077) temp dir; the hash and every later read use that copy, so a list rewritten
# after the check is never the list that is acted on.
#
# Allowed roots (anything else prints `line N: skip (<reason>)` and is left alone):
#   tree     $B/knowledge/clients/<from>[/…], $B/definitions/clients/<from>[/…]   (git rm -r, then rm -r)
#   scoped   one tracked $B/knowledge/**/*.md outside clients/ whose frontmatter has
#            `scope: client:<from>` (a surfaced file; git rm, recoverable from git)
#   capture  a regular *.jsonl|*.md file DIRECTLY inside one of (no deeper subdirectory):
#              <repo>/.bailiwick-outputs/            seeded manual / learn-*.md captures
#              <repo>/.bailiwick-outputs/raw/        enforced raw captures
#              <repo>/.bailiwick-outputs/.curated/   curate-retired manual captures
#              <repo>/.bailiwick-outputs/raw/.curated/
#              $H/captures/<key>/                    shadow manual / learn-*.md captures
#              $H/captures/<key>/raw/                shadow raw captures
#              $H/captures/<key>/.curated/           curate-retired (shadow)
#              $H/captures/<key>/raw/.curated/
#            (<key> is exactly one path component; <repo> holds no .bailiwick-outputs component
#            itself), or a regular file under $B/.bailiwick-inbox/
# Refused before classification: empty or relative lines; `..`, `.`, or empty (`//`) components;
# glob characters (* ? [); symlinks (also with a trailing slash); a parent directory whose physical
# path differs from its textual path. Every git call uses --literal-pathspecs.
#
# $B is this clone (physical path), $H is ${BAILIWICK_HOME:-$HOME/.bailiwick}. List paths must be
# absolute and physical (`pwd -P` / realpath), or they are refused.
# Exit: 0 done (skips are reported, not errors); 1 refused as a whole (hash mismatch, bad <from>,
# unreadable list) with nothing deleted; 2 usage; 3 one or more lines FAILED under --apply (the
# summary counts them) — STOP: do not continue to the next purge step.
set -uo pipefail

B="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd -P)"
H="${BAILIWICK_HOME:-$HOME/.bailiwick}"
[ -d "$H" ] && H="$(cd -P -- "$H" && pwd -P)"

usage() {
  echo "usage: purge_delete.sh --list <file> --from-file <file> (--sha <approved-sha256> [--apply] | --print-sha)" >&2
  exit 2
}
LIST="" FROMF="" SHA="" APPLY=0 PRINT=0
while [ $# -gt 0 ]; do
  case "$1" in
    --list) [ $# -ge 2 ] || usage; LIST="$2"; shift 2 ;;
    --from-file) [ $# -ge 2 ] || usage; FROMF="$2"; shift 2 ;;
    --sha) [ $# -ge 2 ] || usage; SHA="$2"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    --print-sha) PRINT=1; shift ;;
    *) usage ;;
  esac
done
[ -n "$LIST" ] && [ -n "$FROMF" ] || usage
if [ "$PRINT" -eq 1 ]; then
  [ -z "$SHA" ] && [ "$APPLY" -eq 0 ] || usage
else
  [ -n "$SHA" ] || usage
  case "$SHA" in *[!0-9a-f]*) usage ;; esac
  [ "${#SHA}" -eq 64 ] || usage
fi
[ -f "$LIST" ] && [ -f "$FROMF" ] || { echo "STOP: list or from-file unreadable; nothing deleted" >&2; exit 1; }

umask 077
TMPD="$(mktemp -d "${TMPDIR:-/tmp}/purge_delete.XXXXXX")" || { echo "STOP: no private temp dir; nothing deleted" >&2; exit 1; }
trap 'rm -rf -- "$TMPD"' EXIT
cat -- "$LIST" > "$TMPD/list" 2>/dev/null && cat -- "$FROMF" > "$TMPD/from" 2>/dev/null \
  || { echo "STOP: list or from-file unreadable; nothing deleted" >&2; exit 1; }

sha_stdin() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum | cut -d' ' -f1
  else shasum -a 256 | cut -d' ' -f1; fi
}
BOUND="$(printf '%s\n%s\n' "$(sha_stdin < "$TMPD/list")" "$(sha_stdin < "$TMPD/from")" | sha_stdin)"
if [ "$PRINT" -eq 1 ]; then echo "$BOUND"; exit 0; fi
if [ "$BOUND" != "$SHA" ]; then
  echo "STOP: the target list and from-file do not hash to the approved sha256; nothing deleted" >&2
  exit 1
fi

F="$(head -n1 "$TMPD/from" | tr -d '\r')"
case "$F" in ""|.|..|*[!A-Za-z0-9._-]*) echo "STOP: bad <from> in the from-file; nothing deleted" >&2; exit 1 ;; esac

g() { git --literal-pathspecs -C "$B" "$@"; }

has_scope() {  # <file>: frontmatter carries `scope: client:<from>`
  awk -v want="client:$F" '
    NR == 1 { if ($0 != "---") exit 1; next }
    $0 == "---" { exit found ? 0 : 1 }
    /^scope:/ { v = $0; sub(/^scope:[ \t]*/, "", v); gsub(/["\047 \t\r]/, "", v); if (v == want) found = 1 }
    END { exit found ? 0 : 1 }' "$1" 2>/dev/null
}

is_capture() {  # <path>: a *.jsonl|*.md directly inside one of the enumerated capture dirs (header)
  _n="${1##*/}"; _d="${1%/*}"
  case "$_n" in ?*.jsonl|?*.md) ;; *) return 1 ;; esac
  case "$_d" in
    "$H"/captures/*)
      _r="${_d:$((${#H} + 10))}"   # strip "$H/captures/"
      case "$_r" in */*) _k="${_r%%/*}"; _s="${_r#*/}" ;; *) _k="$_r"; _s="" ;; esac
      case "$_k" in ""|.*) return 1 ;; esac
      case "$_s" in ""|raw|.curated|raw/.curated) return 0 ;; esac
      return 1 ;;
    */.bailiwick-outputs|*/.bailiwick-outputs/raw|*/.bailiwick-outputs/.curated|*/.bailiwick-outputs/raw/.curated)
      _r="${_d%/.bailiwick-outputs*}"
      [ -n "$_r" ] || return 1
      case "$_r/" in */.bailiwick-outputs/*) return 1 ;; esac
      return 0 ;;
  esac
  return 1
}

i=0 done_n=0 fail_n=0 skip_n=0 why=""
skip() { echo "line $i: skip ($1)"; skip_n=$((skip_n + 1)); }
act() {  # <kind> <command...>: the command's own output is discarded (it would name the path)
  _k="$1"; shift
  if [ "$APPLY" -ne 1 ]; then echo "line $i: would delete ($_k)"; done_n=$((done_n + 1)); return; fi
  why="command failed"
  if "$@" </dev/null >/dev/null 2>&1; then echo "line $i: deleted ($_k)"; done_n=$((done_n + 1))
  else echo "line $i: FAILED ($_k: $why)"; fail_n=$((fail_n + 1)); fi
}
git_rm() { g rm -q "$@" || { why="git rm refused (local changes or index state)"; return 1; }; }
rm_file() { rm -- "$1" || { why="rm failed"; return 1; }; }
rm_tree() {
  git_rm -r --ignore-unmatch -- "$1" || return 1
  [ ! -e "$1" ] || rm -r -- "$1" || { why="rm failed (untracked leftovers)"; return 1; }
}

while IFS= read -r p || [ -n "$p" ]; do
  i=$((i + 1)); p="${p%$'\r'}"
  [ -n "$p" ] || { skip "empty line"; continue; }
  case "$p" in /*) ;; *) skip "relative path"; continue ;; esac
  case "$p" in *[*?[]*) skip "glob character"; continue ;; esac
  while [ "${#p}" -gt 1 ] && [ "${p%/}" != "$p" ]; do p="${p%/}"; done
  case "$p/" in */../*|*/./*|*//*) skip "dot or empty path component"; continue ;; esac
  [ -L "$p" ] && { skip "symlink"; continue; }
  [ -e "$p" ] || { skip "missing"; continue; }
  parent="${p%/*}"; [ -n "$parent" ] || parent="/"
  phys="$(cd -P -- "$parent" 2>/dev/null && pwd -P)" || { skip "parent unreadable"; continue; }
  [ "$phys" = "$parent" ] || { skip "path runs through a symlink"; continue; }
  case "$p" in
    "$B/knowledge/clients/$F"|"$B/knowledge/clients/$F/"*|"$B/definitions/clients/$F"|"$B/definitions/clients/$F/"*)
      act tree rm_tree "$p" ;;
    "$B/knowledge/clients/"*|"$B/definitions/"*)
      skip "outside allowed roots" ;;
    "$B/knowledge/"*.md)
      if [ ! -f "$p" ]; then skip "not a file"
      elif ! g ls-files --error-unmatch -- "$p" >/dev/null 2>&1; then skip "untracked"
      elif ! has_scope "$p"; then skip "scope is not client:<from>"
      else act scoped git_rm -- "$p"; fi ;;
    "$B"/.bailiwick-inbox/*)
      if [ -f "$p" ]; then act capture rm_file "$p"; else skip "not a regular file"; fi ;;
    *)
      if ! is_capture "$p"; then skip "outside allowed roots"
      elif [ -f "$p" ]; then act capture rm_file "$p"
      else skip "not a regular file"; fi ;;
  esac
done < "$TMPD/list"

if [ "$APPLY" -eq 1 ]; then
  echo "purge_delete: $done_n deleted, $fail_n failed, $skip_n skipped"
  if [ "$fail_n" -gt 0 ]; then
    echo "STOP: $fail_n line(s) FAILED; do not continue to the next purge step" >&2
    exit 3
  fi
else echo "purge_delete: dry run — $done_n would be deleted, $skip_n skipped (re-run with --apply)"; fi
exit 0
