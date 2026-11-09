#!/usr/bin/env bash
# bailiwick — purge verification & deep-removal preflight (read-only; writes nothing anywhere).
#
# Companion to /purge and docs/history-purge.md. Two modes:
#
#   purge_verify.sh residual <token>... [--tokens-file <file>] [--backup-path <prefix>]...
#       Measure what still EXISTS for the given identifier(s), honestly:
#         - working-tree hits (git grep) in this repo
#         - git-HISTORY hits (commits whose diff ever contained the token) — the recovery surface
#           /purge's working-tree scrub does not touch
#         - open refs/pull/* on origin (force-pushes never remove these; they pin old objects)
#         - with --backup-path: ciphertext blobs under that prefix in the backup repo's CURRENT
#           trees and its HISTORY (ciphertext cannot be grepped for tokens — measured by path)
#       Exit 0 = nothing found anywhere; exit 1 = residuals exist (each one printed).
#       A token of 4 characters or fewer matches on alphanumeric boundaries only (git grep -E,
#       git log -G), longer tokens as case-insensitive substrings — scripts/purge_scrub.py's rule.
#
#   purge_verify.sh preflight
#       Gate for the DEEP-REMOVAL procedure (history rewrite / squash / crypto-erasure): find
#       pending, un-curated captures across the fleet BEFORE history or keys are destroyed:
#         - this machine's local staging (.bailiwick-inbox/raw, ~/.bailiwick/captures/*/raw,
#           and every allowlisted shadow repo's .bailiwick-outputs/raw)
#         - a leftover ~/.bailiwick/purge-work/ (tokens and deleted-file copies of an unfinished
#           /purge run)
#         - every capture/* branch of the configured backup repo (blobs present = captures some
#           machine pushed that were never post-curation purged)
#         - health-shard freshness per machine (a recently active machine may hold local-only
#           captures this script cannot see — listed so you check it directly)
#       Exit 0 = fleet is drained; exit 1 = pending captures found — CURATE OR DRAIN FIRST.
#
# Read-only by construction: inspection clones go to a throwaway temp dir; nothing is pushed,
# deleted, or rewritten here. The deep-removal commands themselves live in docs/history-purge.md.
set -uo pipefail

BAILIWICK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
cd "$BAILIWICK_ROOT"
BW_HOME="${BAILIWICK_HOME:-$HOME/.bailiwick}"
CFG="${BW_CFG_FILE:-$BAILIWICK_ROOT/.bailiwick-sync.json}"

FOUND=0
ok()   { printf '  \342\234\223 %s\n' "$1"; }
hit()  { printf '  \342\234\227 %s\n' "$1"; FOUND=1; }
note() { printf '  \342\232\240 %s\n' "$1"; }

backup_repo() {  # configured capture_backup.repo, or empty
  [ -f "$CFG" ] || return 0
  command -v python3 >/dev/null 2>&1 || return 0
  python3 -c 'import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
print((d.get("capture_backup") or {}).get("repo") or "")' "$CFG" 2>/dev/null || true
}

short_ere() {  # <token> -> POSIX ERE matching it on alphanumeric boundaries (same rule as purge_scrub.py)
  printf '(^|[^A-Za-z0-9])%s([^A-Za-z0-9]|$)' "$(printf '%s' "$1" | sed 's/[][\.*^$+?(){}|]/\\&/g')"
}

clone_backup() {  # read-only inspection clone; prints its path or nothing
  _pv_repo="$(backup_repo)"
  [ -n "$_pv_repo" ] || return 0
  _pv_tmp="$(mktemp -d "${TMPDIR:-/tmp}/bw-purge-verify.XXXXXX")"
  if git clone --quiet "$_pv_repo" "$_pv_tmp/backup" 2>/dev/null; then
    printf '%s' "$_pv_tmp/backup"
  else
    rm -rf "$_pv_tmp"
    note "backup repo configured but unreachable ($_pv_repo) — its checks were SKIPPED, not passed"
  fi
}

MODE="${1:-}"
case "$MODE" in

residual)
  shift
  # Arrays, not a space-joined string: an "<org name>" token keeps its spaces (one phrase, not
  # one hit per word).
  tokens=()
  labels=()   # what the output calls each token: itself, or `token #N` when read from a file
  bpaths=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --backup-path) bpaths+=("$2"); shift 2 ;;
      # One token per line (/purge's $W/tokens, every 3a variant included): the command line then
      # carries no token at all, and the output names these tokens by index only.
      --tokens-file)
        [ -f "${2:-}" ] || { echo "purge_verify: --tokens-file '${2:-}' not readable" >&2; exit 2; }
        while IFS= read -r tl || [ -n "$tl" ]; do
          tl="${tl%$'\r'}"
          if [ -n "$tl" ]; then tokens+=("$tl"); labels+=("token #${#tokens[@]}"); fi
        done < "$2"
        shift 2 ;;
      *) tokens+=("$1"); labels+=("'$1'"); shift ;;
    esac
  done
  [ "${#tokens[@]}" -gt 0 ] || { echo "usage: purge_verify.sh residual <token>... [--tokens-file <file>] [--backup-path <prefix>]..." >&2; exit 2; }

  echo "purge residual check — $BAILIWICK_ROOT"
  k=0
  for t in "${tokens[@]}"; do
    lab="${labels[$k]}"; k=$((k + 1))
    if [ "${#t}" -le 4 ]; then
      # Short token: alphanumeric boundaries only, the rule scripts/purge_scrub.py uses everywhere —
      # a substring match would hit `adi` in "loading" and never read clean.
      re="$(short_ere "$t")"
      n="$(git grep -IliE -- "$re" 2>/dev/null | wc -l | tr -d ' ')"; grc=$?
      how="git grep -liE, boundary match for a token of 4 chars or fewer"
      h="$(git log --all -G"$re" -i --oneline 2>/dev/null | wc -l | tr -d ' ')"
    else
      # -F: a token is a literal string. Without it a `[` makes git grep error out, which reads as
      # "no matches" — a false clean.
      n="$(git grep -IliF -- "$t" 2>/dev/null | wc -l | tr -d ' ')"; grc=$?
      how="git grep -liF"
      # -S finds every commit whose diff added/removed the token — the honest history surface.
      h="$(git log --all -S"$t" -i --oneline 2>/dev/null | wc -l | tr -d ' ')"
    fi
    # git grep: 0 = matches, 1 = none, anything else = it failed (never report that as clean).
    if [ "$grc" -gt 1 ]; then hit "$lab: git grep failed (exit $grc) — working tree NOT checked"
    elif [ "${n:-0}" -gt 0 ]; then hit "$lab: $n working-tree file(s) still match ($how)"
    else ok "$lab: working tree clean"; fi
    if [ "${h:-0}" -gt 0 ]; then
      hit "$lab: $h commit(s) in git HISTORY still carry it — recoverable via 'git log -S' until the history is rewritten/squashed (docs/history-purge.md)"
    else
      ok "$lab: git history clean"
    fi
  done
  # refs/pull pins: a force-push rewrites branches, never these — old objects stay fetchable.
  prn="$(git ls-remote origin 'refs/pull/*/head' 2>/dev/null | wc -l | tr -d ' ')"
  if [ "${prn:-0}" -gt 0 ]; then
    note "origin holds $prn refs/pull/* head(s) — merged/closed PRs pin pre-rewrite objects even after a force-push; full removal needs the host's support (docs/history-purge.md §GitHub residuals)"
  fi
  if [ "${#bpaths[@]}" -gt 0 ]; then
    bdir="$(clone_backup)"
    if [ -n "$bdir" ]; then
      for p in "${bpaths[@]}"; do
        cur=0; hist=0
        for br in $(git -C "$bdir" branch -r --format='%(refname:short)' | grep -v HEAD); do
          c="$(git -C "$bdir" ls-tree -r --name-only "$br" 2>/dev/null | grep -c "^$p" || true)"
          cur=$(( cur + ${c:-0} ))
        done
        hist="$(git -C "$bdir" log --all --oneline -- "$p" 2>/dev/null | wc -l | tr -d ' ')"
        if [ "$cur" -gt 0 ]; then hit "backup '$p': $cur ciphertext blob(s) still in CURRENT branch trees"; else ok "backup '$p': current trees clean"; fi
        if [ "${hist:-0}" -gt 0 ]; then
          hit "backup '$p': $hist commit(s) in backup HISTORY touch it — ciphertext recoverable while the old gpg key exists (crypto-erasure or rewrite: docs/history-purge.md)"
        else
          ok "backup '$p': backup history clean"
        fi
      done
      rm -rf "$(dirname "$bdir")"
    fi
    # `compact` keeps one undo generation per branch in the local mirror only, so the fresh clone above
    # cannot see it and its purged ciphertext would read as clean. Read-only: for-each-ref and log.
    mirror="${XDG_CACHE_HOME:-$HOME/.cache}/bailiwick/capture-mirror"
    if [ -d "$mirror/.git" ]; then
      urefs="$(git -C "$mirror" for-each-ref --format='%(refname)' refs/bw/pre-compact 2>/dev/null || true)"
      for p in "${bpaths[@]}"; do
        n=0
        while IFS= read -r uref; do
          [ -n "$uref" ] || continue
          u="$(git -C "$mirror" log --oneline "$uref" -- "$p" 2>/dev/null | wc -l | tr -d ' ')"
          n=$(( n + ${u:-0} ))
        done <<EOF
$urefs
EOF
        if [ "$n" -gt 0 ]; then
          hit "backup '$p': $n commit(s) in this machine's mirror undo refs (refs/bw/pre-compact/*) touch it — purged ciphertext stays here until the ref is dropped and gc runs, or the mirror is deleted (skills/purge/SKILL.md, erasure tiers)"
        else
          ok "backup '$p': this machine's mirror undo refs clean"
        fi
      done
    fi
  fi
  ;;

preflight)
  echo "deep-removal preflight — pending, un-curated captures must be drained BEFORE history or keys are destroyed"
  # 1. This machine's staging surfaces.
  n="$(find "$BAILIWICK_ROOT/.bailiwick-inbox/raw" -type f 2>/dev/null | wc -l | tr -d ' ')"
  if [ "${n:-0}" -gt 0 ]; then hit "this machine: $n decrypted blob(s) in .bailiwick-inbox/raw awaiting curation"; else ok "this machine: inbox empty"; fi
  n="$(find "$BW_HOME/captures" -path '*/raw/*' -name '*.jsonl' 2>/dev/null | wc -l | tr -d ' ')"
  if [ "${n:-0}" -gt 0 ]; then hit "this machine: $n shadow capture(s) pending under $BW_HOME/captures/"; else ok "this machine: central shadow staging empty"; fi
  if [ -f "$BW_HOME/allowlist" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
      line="${line%%#*}"; line="${line#"${line%%[![:space:]]*}"}"; line="${line%"${line##*[![:space:]]}"}"
      [ -n "$line" ] || continue
      n="$(find "$line/.bailiwick-outputs/raw" -name '*.jsonl' 2>/dev/null | wc -l | tr -d ' ')"
      [ "${n:-0}" -gt 0 ] && hit "allowlisted repo $line: $n capture(s) pending"
    done < "$BW_HOME/allowlist"
  fi
  # A leftover /purge work dir holds the tokens (and copies of deleted files): an aborted run whose
  # Step 5.7 never ran. Its file names are never printed — they can carry nothing but the count.
  if [ -d "$BW_HOME/purge-work" ]; then
    n="$(find "$BW_HOME/purge-work" -type f 2>/dev/null | wc -l | tr -d ' ')"
    hit "this machine: leftover purge-work/ under $BW_HOME ($n file(s): tokens / deleted-file copies of an unfinished /purge) — finish that purge's Step 5.7 or remove it: rm -r -- \"\${BAILIWICK_HOME:-\$HOME/.bailiwick}/purge-work\""
  else
    ok "this machine: no leftover purge-work/"
  fi
  note "seeded repos are not centrally enumerable — each machine's SessionStart nag / doctor must read clean there"
  # 2. The holding repo: blobs on any capture/* branch = pushed but never post-curation purged.
  bdir="$(clone_backup)"
  if [ -n "$bdir" ]; then
    any=0
    for br in $(git -C "$bdir" branch -r --format='%(refname:short)' | grep -v HEAD); do
      case "$br" in */capture/*|*capture/*) : ;; *) continue ;; esac
      n="$(git -C "$bdir" ls-tree -r --name-only "$br" 2>/dev/null | grep '\.gpg$' | grep -cv '^health/' || true)"
      if [ "${n:-0}" -gt 0 ]; then hit "backup branch $br: $n ciphertext blob(s) pending curation"; any=1; fi
    done
    [ "$any" -eq 0 ] && ok "backup repo: every capture/* branch is drained"
    rm -rf "$(dirname "$bdir")"
  fi
  # 3. Fleet visibility: which machines have been heard from (their local-only state is invisible here).
  for shard in "$BW_HOME"/health/*.jsonl "$BW_HOME"/health/remote/*.jsonl; do
    [ -f "$shard" ] || continue
    m="$(basename "$shard" .jsonl)"
    last="$(tail -1 "$shard" 2>/dev/null | sed -n 's/.*"ts":"\([^"]*\)".*/\1/p')"
    note "machine '$m' last health event: ${last:-unknown} — confirm ITS local staging is drained before proceeding"
  done
  ;;

*)
  echo "usage: purge_verify.sh residual <token>... [--backup-path <prefix>]...  |  purge_verify.sh preflight" >&2
  exit 2
  ;;
esac

echo
if [ "$FOUND" -ne 0 ]; then
  echo "purge_verify: RESIDUALS/PENDING FOUND — do not claim a higher erasure tier / do not start deep removal."
  exit 1
fi
echo "purge_verify: clean for the checked surfaces."
