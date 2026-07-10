#!/usr/bin/env bash
# bailiwick — encrypted dirty-zone backup (durability for un-curated captures).
#
# The dirty zone (.bailiwick-outputs/) is local + gitignored. This adds an OFF-MACHINE,
# ENCRYPTED copy so nothing is lost before /curate, even on disk failure. Only
# CIPHERTEXT ever leaves the machine; the gpg private key never does.
#
# Modes:
#   push (default)   encrypt new/changed .bailiwick-outputs captures and push ciphertext to the
#                    per-machine branch of the dedicated PRIVATE backup repo.
#   pull [dest]      decrypt every blob into <dest> (default $BAILIWICK_ROOT/.bailiwick-inbox/raw) for /curate.
#   purge <relpath>  remove one ciphertext blob from the backup branch (post-curate cleanup).
#
# Config: $BAILIWICK_ROOT/.bailiwick-sync.json -> "capture_backup": { enabled, repo, gpg_recipients[],
#         branch, throttle_minutes, confidentiality_ack }. Disabled/absent => no-op.
set -euo pipefail

BAILIWICK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
CFG="$BAILIWICK_ROOT/.bailiwick-sync.json"
MODE="${1:-push}"
# Framework-health logging (best-effort; no-op fallback if the helper is missing).
. "$BAILIWICK_ROOT/hooks/health_common.sh" 2>/dev/null || true
command -v bw_health >/dev/null 2>&1 || bw_health() { :; }

command -v python3 >/dev/null 2>&1 || exit 0
[ -f "$CFG" ] || exit 0

ENABLED=0; ACK=0; REPO=""; BRANCH=""; THROTTLE=5; MACHINE="unknown"; RCPTS=()
while IFS= read -r line; do
  case "$line" in
    ENABLED=*) ENABLED="${line#ENABLED=}";;
    ACK=*) ACK="${line#ACK=}";;
    REPO=*) REPO="${line#REPO=}";;
    BRANCH=*) BRANCH="${line#BRANCH=}";;
    THROTTLE=*) THROTTLE="${line#THROTTLE=}";;
    MACHINE=*) MACHINE="${line#MACHINE=}";;
    RCPT=*) RCPTS+=("${line#RCPT=}");;
  esac
done < <(python3 - "$CFG" <<'PY' 2>/dev/null || true
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: sys.exit(0)
b=d.get("capture_backup") or {}
print("ENABLED="+("1" if b.get("enabled") else "0"))
print("ACK="+("1" if b.get("confidentiality_ack") else "0"))
print("REPO="+(b.get("repo") or ""))
print("BRANCH="+(b.get("branch") or ""))
print("THROTTLE="+str(b.get("throttle_minutes",5)))
print("MACHINE="+(d.get("machine") or "unknown"))
for r in (b.get("gpg_recipients") or []): print("RCPT="+str(r))
PY
)

[ "$ENABLED" = "1" ] || exit 0
[ -n "$REPO" ] || { echo "[backup] enabled but no repo configured" >&2; exit 0; }
[ "${#RCPTS[@]}" -gt 0 ] || { echo "[backup] enabled but no gpg_recipients configured" >&2; exit 0; }
command -v gpg >/dev/null 2>&1 || { echo "[backup] gpg not installed" >&2; exit 0; }

mtoken="$(printf '%s' "$MACHINE" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9._-')"
[ -n "$BRANCH" ] || BRANCH="capture/$mtoken"
MIRROR="${XDG_CACHE_HOME:-$HOME/.cache}/bailiwick/capture-mirror"
BW_HOME="${BAILIWICK_HOME:-$HOME/.bailiwick}"

# Shadow-mode repos stage captures centrally, not in-repo (FRAMEWORK.md §7.1). Mirror the
# session_start.sh gate so this backup can find them.
is_shadow_repo() {  # $1 = repo dir
  [ "${BAILIWICK_SHADOW:-}" = "1" ] && return 0
  local list="$BW_HOME/allowlist" here line
  [ -f "$list" ] || return 1
  here="$(cd "$1" 2>/dev/null && pwd -P || echo "$1")"
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%%#*}"
    line="${line#"${line%%[![:space:]]*}"}"; line="${line%"${line##*[![:space:]]}"}"
    line="${line%/}"
    if [ -n "$line" ] && [ "$here" = "$line" ]; then return 0; fi
  done < "$list"
  return 1
}

ensure_mirror() {
  if [ ! -d "$MIRROR/.git" ]; then
    mkdir -p "$(dirname "$MIRROR")"
    git clone --quiet "$REPO" "$MIRROR" 2>/dev/null || {
      mkdir -p "$MIRROR"; git -C "$MIRROR" init -q
      git -C "$MIRROR" remote add origin "$REPO" 2>/dev/null || true
    }
  fi
  # Explicit refspec guarantees refs/remotes/origin/<branch> is created when it exists upstream
  # (a bare 'fetch origin <branch>' only updates FETCH_HEAD, which the checks below would miss).
  git -C "$MIRROR" fetch --quiet origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH" 2>/dev/null || true
  if git -C "$MIRROR" rev-parse --verify -q "refs/heads/$BRANCH" >/dev/null 2>&1; then
    # Local branch exists — keep it (never reset to origin; that would discard
    # unpushed ciphertext). Divergence is reconciled by rebase at push time.
    git -C "$MIRROR" checkout -q "$BRANCH"
  elif git -C "$MIRROR" rev-parse --verify -q "refs/remotes/origin/$BRANCH" >/dev/null 2>&1; then
    git -C "$MIRROR" checkout -q -b "$BRANCH" "origin/$BRANCH"
  else
    # Brand new: neither local nor remote branch exists. Safe to start clean.
    git -C "$MIRROR" checkout -q --orphan "$BRANCH" 2>/dev/null || git -C "$MIRROR" checkout -q -b "$BRANCH" 2>/dev/null || true
    git -C "$MIRROR" reset -q 2>/dev/null || true
    find "$MIRROR" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} + 2>/dev/null || true
  fi
}

git_id() { git -C "$MIRROR" -c user.name=bailiwick -c user.email=backup@local "$@"; }

case "$MODE" in
  push)
    payload="$(cat 2>/dev/null || true)"
    event="$(printf '%s' "$payload" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("hook_event_name",""))
except Exception: print("")' 2>/dev/null || true)"
    PROJECT_DIR="${CLAUDE_PROJECT_DIR:-}"
    [ -n "$PROJECT_DIR" ] || PROJECT_DIR="$(printf '%s' "$payload" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("cwd",""))
except Exception: print("")' 2>/dev/null || true)"
    [ -n "$PROJECT_DIR" ] || PROJECT_DIR="$PWD"
    RAW="$PROJECT_DIR/.bailiwick-outputs/raw"
    STAMP="$PROJECT_DIR/.bailiwick-outputs/.backup-last"
    # Shadow-only repos stage captures centrally (repo untouched; FRAMEWORK.md §7.1) — back those up.
    if [ ! -d "$RAW" ] && is_shadow_repo "$PROJECT_DIR"; then
      # Same key as the writer/nag (capture_session.py repo_key) — else we'd back up the wrong dir.
      skey="$(PYTHONPATH="$BAILIWICK_ROOT/hooks" python3 -c 'import sys, capture_session; sys.stdout.write(capture_session.repo_key(sys.argv[1]))' "$PROJECT_DIR" 2>/dev/null || true)"
      [ -n "$skey" ] || skey="$(basename "$PROJECT_DIR")"
      RAW="$BW_HOME/captures/$skey/raw"
      STAMP="$BW_HOME/captures/$skey/.backup-last"
    fi
    [ -d "$RAW" ] || exit 0
    [ "$ACK" = "1" ] || { echo "[backup] confidentiality_ack is false — refusing to back up (may contain client data). Set it true to enable." >&2; exit 0; }
    now=$(date +%s)
    if [ "$event" != "SessionEnd" ] && [ -f "$STAMP" ]; then
      last=$(cat "$STAMP" 2>/dev/null || echo 0)
      [ $(( now - last )) -lt $(( THROTTLE * 60 )) ] && exit 0
    fi
    ensure_mirror
    # Destination blob dir is keyed by the SAME collision-resistant, ORIGIN-based key as central
    # staging and the pending-capture nag (capture_session.repo_key = basename + sha8 of the git
    # remote / realpath) — NOT a bare basename. Otherwise two different repos that share a name
    # (`infra`, `api`, …) commingle in one backup dir, and a purge can't tell them apart by path.
    # Reuse the shadow-branch key if it was already computed; else derive it (basename fallback).
    repo_name="${skey:-}"
    [ -n "$repo_name" ] || repo_name="$(PYTHONPATH="$BAILIWICK_ROOT/hooks" python3 -c 'import sys, capture_session; sys.stdout.write(capture_session.repo_key(sys.argv[1]))' "$PROJECT_DIR" 2>/dev/null || true)"
    [ -n "$repo_name" ] || repo_name="$(basename "$PROJECT_DIR")"
    destdir="$MIRROR/$mtoken/$repo_name"
    mkdir -p "$destdir"
    enc_args=(); for r in "${RCPTS[@]}"; do enc_args+=(--recipient "$r"); done
    changed=0
    shopt -s nullglob
    for f in "$RAW"/*.jsonl "$RAW"/*.md; do
      [ -f "$f" ] || continue
      base="$(basename "$f")"
      sha="$(sha256sum "$f" | awk '{print $1}')"
      shaf="$destdir/$base.gpg.sha256"
      [ -f "$shaf" ] && [ "$(cat "$shaf")" = "$sha" ] && continue
      gpg --batch --yes --no-tty --trust-model always "${enc_args[@]}" --encrypt --output "$destdir/$base.gpg" "$f"
      printf '%s\n' "$sha" > "$shaf"
      changed=1
    done
    shopt -u nullglob
    # Health-shard transport: upload this machine's health shard (encrypted, like captures) so the
    # central machine can aggregate a fleet view in /metrics. Sha-sidecar skips unchanged shards.
    hshard="$BW_HOME/health/$mtoken.jsonl"
    if [ -f "$hshard" ]; then
      mkdir -p "$MIRROR/health"
      hsha="$(sha256sum "$hshard" | awk '{print $1}')"
      hshaf="$MIRROR/health/$mtoken.jsonl.gpg.sha256"
      if [ ! -f "$hshaf" ] || [ "$(cat "$hshaf")" != "$hsha" ]; then
        if gpg --batch --yes --no-tty --trust-model always "${enc_args[@]}" --encrypt \
             --output "$MIRROR/health/$mtoken.jsonl.gpg" "$hshard" 2>/dev/null; then
          printf '%s\n' "$hsha" > "$hshaf"
          changed=1
        fi
      fi
    fi
    date +%s > "$STAMP"
    [ "$changed" = "1" ] || exit 0
    git_id add -A
    git_id commit -q -m "capture: $mtoken/$repo_name $(date -u +%Y-%m-%dT%H:%M:%SZ)" || exit 0
    if ! git_id push -q origin "$BRANCH" 2>/dev/null; then
      git -C "$MIRROR" fetch -q origin "$BRANCH" 2>/dev/null && git_id rebase -q "origin/$BRANCH" 2>/dev/null || true
      git_id push -q origin "$BRANCH" 2>/dev/null || {
        unp="$(git -C "$MIRROR" rev-list --count "origin/$BRANCH..$BRANCH" 2>/dev/null || echo '?')"
        bw_health capture_backup error "push failed ($BRANCH; $unp unpushed commit(s); ciphertext safe in local mirror)"
        echo "[backup] push failed (ciphertext safe in local mirror $MIRROR)" >&2; exit 0
      }
    fi
    bw_health capture_backup info "push ok ($repo_name -> $BRANCH)"
    echo "[backup] pushed '$repo_name' captures to $BRANCH"
    ;;
  pull)
    DEST="${2:-$BAILIWICK_ROOT/.bailiwick-inbox/raw}"
    mkdir -p "$DEST"
    ensure_mirror
    # Decrypt needs to UNLOCK the (passphrase-protected) private key, which means gpg-agent must be
    # able to prompt via pinentry. Tell gpg-agent which terminal to use, if we have one (harmless if
    # not — a GUI pinentry uses $DISPLAY instead). This makes the manual `… pull` path work in a plain
    # terminal without the caller having to remember `export GPG_TTY=$(tty)`.
    export GPG_TTY="${GPG_TTY:-$(tty 2>/dev/null || true)}"
    # Preflight: pinentry can only prompt if there is a TTY (curses pinentry), a GUI display (graphical
    # pinentry), or the key is already unlocked in gpg-agent. If none hold, decryption cannot possibly
    # succeed — say so ONCE, with the fix, instead of emitting a failure line per blob.
    key_cached() { gpg-connect-agent 'keyinfo --list' /bye 2>/dev/null \
        | awk '$1=="S"&&$2=="KEYINFO"&&$7=="1"{f=1} END{exit f?0:1}'; }
    if [ -z "$GPG_TTY" ] && [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ] && ! key_cached; then
      echo "[backup] cannot decrypt here: no TTY and no GUI display for a passphrase prompt, and the" >&2
      echo "         key is not unlocked in gpg-agent. Fix (any one):" >&2
      echo "           • run from a terminal:   export GPG_TTY=\$(tty); bash \"$0\" pull" >&2
      echo "           • install a GUI pinentry (pinentry-gnome3) so a prompt can appear without a TTY" >&2
      echo "           • prime gpg-agent once in a terminal, then re-run within the cache window" >&2
      echo "         See hooks/README.md → Encrypted dirty-zone backup." >&2
    fi
    shopt -s globstar nullglob
    n=0; fail=0
    for blob in "$MIRROR"/**/*.gpg; do
      [ -f "$blob" ] || continue
      rel="${blob#"$MIRROR"/}"
      case "$rel" in health/*) continue;; esac   # health shards handled separately below
      out="$DEST/${rel%.gpg}"
      mkdir -p "$(dirname "$out")"
      [ -f "$out" ] && continue
      # Interactive path (curate-time): allow gpg-agent / pinentry for the passphrase —
      # do NOT use --batch/--no-tty here, or a protected private key can't be unlocked.
      if gpg --yes --quiet --decrypt --output "$out" "$blob"; then n=$((n+1)); else
        fail=$((fail+1)); rm -f "$out"   # drop any partial/empty output so a later run retries cleanly
        echo "[backup] decrypt failed for $rel" >&2
      fi
    done
    # Fleet health shards: always re-decrypt (they grow over time, unlike immutable capture blobs)
    # into $BW_HOME/health/remote/ for /metrics aggregation. Own machine's shard is skipped —
    # its local plaintext is authoritative.
    mkdir -p "$BW_HOME/health/remote"
    for blob in "$MIRROR"/health/*.jsonl.gpg; do
      [ -f "$blob" ] || continue
      [ "$(basename "$blob")" = "$mtoken.jsonl.gpg" ] && continue
      hout="$BW_HOME/health/remote/$(basename "${blob%.gpg}")"
      gpg --yes --quiet --decrypt --output "$hout" "$blob" 2>/dev/null || rm -f "$hout"
    done
    shopt -u globstar nullglob
    if [ "$fail" -gt 0 ]; then
      echo "[backup] decrypted $n new blob(s) into $DEST ($fail failed — see the passphrase note above)"
    else
      echo "[backup] decrypted $n new blob(s) into $DEST"
    fi
    ;;
  purge)
    rel="${2:-}"; [ -n "$rel" ] || { echo "usage: capture_backup.sh purge <relpath-under-branch>" >&2; exit 2; }
    ensure_mirror
    git_id rm -q --ignore-unmatch "$rel" "$rel.sha256" 2>/dev/null || true
    git_id commit -q -m "purge: $rel (curated)" 2>/dev/null || { echo "[backup] nothing to purge: $rel"; exit 0; }
    git_id push -q origin "$BRANCH" 2>/dev/null || { bw_health capture_backup warn "purge push failed ($rel)"; echo "[backup] purge committed in mirror; push failed" >&2; }
    echo "[backup] purged $rel"
    ;;
  *) echo "usage: capture_backup.sh [push | pull [dest] | purge <relpath>]" >&2; exit 2;;
esac
