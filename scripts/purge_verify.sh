#!/usr/bin/env bash
# bailiwick — purge verification & deep-removal preflight (read-only; writes nothing anywhere).
#
# Companion to /purge and docs/history-purge.md. Two modes:
#
#   purge_verify.sh residual <token> [<token>...] [--backup-path <prefix>]...
#       Measure what still EXISTS for the given identifier(s), honestly:
#         - working-tree hits (git grep) in this repo
#         - git-HISTORY hits (commits whose diff ever contained the token) — the recovery surface
#           /purge's working-tree scrub does not touch
#         - open refs/pull/* on origin (force-pushes never remove these; they pin old objects)
#         - with --backup-path: ciphertext blobs under that prefix in the backup repo's CURRENT
#           trees and its HISTORY (ciphertext cannot be grepped for tokens — measured by path)
#       Exit 0 = nothing found anywhere; exit 1 = residuals exist (each one printed).
#
#   purge_verify.sh preflight
#       Gate for the DEEP-REMOVAL procedure (history rewrite / squash / crypto-erasure): find
#       pending, un-curated captures across the fleet BEFORE history or keys are destroyed:
#         - this machine's local staging (.bailiwick-inbox/raw, ~/.bailiwick/captures/*/raw,
#           and every allowlisted shadow repo's .bailiwick-outputs/raw)
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
  tokens=""
  bpaths=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --backup-path) bpaths="$bpaths $2"; shift 2 ;;
      *) tokens="$tokens $1"; shift ;;
    esac
  done
  [ -n "$tokens" ] || { echo "usage: purge_verify.sh residual <token>... [--backup-path <prefix>]..." >&2; exit 2; }

  echo "purge residual check — $BAILIWICK_ROOT"
  for t in $tokens; do
    n="$(git grep -Ili -- "$t" 2>/dev/null | wc -l | tr -d ' ')"
    if [ "${n:-0}" -gt 0 ]; then hit "'$t': $n working-tree file(s) still match (git grep -li -- '$t')"; else ok "'$t': working tree clean"; fi
    # -S finds every commit whose diff added/removed the token — the honest history surface.
    h="$(git log --all -S"$t" -i --oneline 2>/dev/null | wc -l | tr -d ' ')"
    if [ "${h:-0}" -gt 0 ]; then
      hit "'$t': $h commit(s) in git HISTORY still carry it — recoverable via 'git log -S' until the history is rewritten/squashed (docs/history-purge.md)"
    else
      ok "'$t': git history clean"
    fi
  done
  # refs/pull pins: a force-push rewrites branches, never these — old objects stay fetchable.
  prn="$(git ls-remote origin 'refs/pull/*/head' 2>/dev/null | wc -l | tr -d ' ')"
  if [ "${prn:-0}" -gt 0 ]; then
    note "origin holds $prn refs/pull/* head(s) — merged/closed PRs pin pre-rewrite objects even after a force-push; full removal needs the host's support (docs/history-purge.md §GitHub residuals)"
  fi
  if [ -n "$bpaths" ]; then
    bdir="$(clone_backup)"
    if [ -n "$bdir" ]; then
      for p in $bpaths; do
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
