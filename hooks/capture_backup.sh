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
#   pull [dest]      decrypt every blob — this machine's worktree AND every other capture/*
#                    branch — into <dest> (default $BAILIWICK_ROOT/.bailiwick-inbox/raw) for /curate.
#   purge <relpath>  remove one ciphertext blob from whichever machine's branch holds it
#                    (post-curate cleanup) and tombstone it in that branch's root .purged
#                    manifest so push never re-encrypts it while the source capture is still
#                    un-retired somewhere.
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

# One python3 spawn per run: this heredoc parses the config AND (in push mode) the hook payload
# from stdin — the payload used to cost 1-2 additional interpreter startups on EVERY Stop event,
# including throttled no-ops. pull/purge must not touch stdin (they may run interactively).
PAYLOAD_JSON=""
if [ "$MODE" = "push" ]; then PAYLOAD_JSON="$(cat 2>/dev/null || true)"; fi
ENABLED=0; ACK=0; REPO=""; BRANCH=""; THROTTLE=5; MACHINE="unknown"; EVENT=""; PAYLOAD_CWD=""; RCPTS=()
while IFS= read -r line; do
  case "$line" in
    ENABLED=*) ENABLED="${line#ENABLED=}";;
    ACK=*) ACK="${line#ACK=}";;
    REPO=*) REPO="${line#REPO=}";;
    BRANCH=*) BRANCH="${line#BRANCH=}";;
    THROTTLE=*) THROTTLE="${line#THROTTLE=}";;
    MACHINE=*) MACHINE="${line#MACHINE=}";;
    EVENT=*) EVENT="${line#EVENT=}";;
    CWD=*) PAYLOAD_CWD="${line#CWD=}";;
    RCPT=*) RCPTS+=("${line#RCPT=}");;
  esac
done < <(printf '%s' "$PAYLOAD_JSON" | python3 -c '
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
try:
    p=json.load(sys.stdin)
    if isinstance(p, dict):
        print("EVENT="+str(p.get("hook_event_name") or ""))
        print("CWD="+str(p.get("cwd") or ""))
except Exception:
    pass
' "$CFG" 2>/dev/null || true)

# Enabled-but-broken states must reach the health shard: from a hook, stderr goes nowhere,
# and a bare exit 0 here is a month-long backup outage /metrics never sees.
[ "$ENABLED" = "1" ] || exit 0
[ -n "$REPO" ] || { bw_health capture_backup error "enabled but no repo configured — backup inactive"; echo "[backup] enabled but no repo configured" >&2; exit 0; }
[ "${#RCPTS[@]}" -gt 0 ] || { bw_health capture_backup error "enabled but no gpg_recipients configured — backup inactive"; echo "[backup] enabled but no gpg_recipients configured" >&2; exit 0; }
command -v gpg >/dev/null 2>&1 || { bw_health capture_backup error "gpg not installed — backup inactive, captures local-only"; echo "[backup] gpg not installed" >&2; exit 0; }

# Shared primitives: machine token + shadow gate (hooks/config_common.sh — single bash
# implementation; without it the shadow-staged path is simply skipped, in-repo backup still runs).
. "$BAILIWICK_ROOT/hooks/config_common.sh" 2>/dev/null || true
if command -v bw_machine_token >/dev/null 2>&1; then
  mtoken="$(bw_machine_token "$MACHINE")"
else
  mtoken="$(printf '%s' "$MACHINE" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9._-')"
fi
[ -n "$BRANCH" ] || BRANCH="capture/$mtoken"
MIRROR="${XDG_CACHE_HOME:-$HOME/.cache}/bailiwick/capture-mirror"
BW_HOME="${BAILIWICK_HOME:-$HOME/.bailiwick}"

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
    # Payload was parsed alongside the config in the single spawn above.
    event="$EVENT"
    PROJECT_DIR="${CLAUDE_PROJECT_DIR:-}"
    [ -n "$PROJECT_DIR" ] || PROJECT_DIR="$PAYLOAD_CWD"
    [ -n "$PROJECT_DIR" ] || PROJECT_DIR="$PWD"
    RAW="$PROJECT_DIR/.bailiwick-outputs/raw"
    STAMP="$PROJECT_DIR/.bailiwick-outputs/.backup-last"
    # Shadow-only repos stage captures centrally (repo untouched; FRAMEWORK.md §7.1) — back those up.
    if [ ! -d "$RAW" ] && command -v bw_is_shadow_repo >/dev/null 2>&1 && bw_is_shadow_repo "$PROJECT_DIR"; then
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
    # Tombstoned relpaths — union of the worktree manifest and origin's: a purge issued from
    # ANOTHER machine lands on origin first, and this worktree only syncs at the next
    # push-reject→rebase. Reading both closes that window.
    PURGED="$( { cat "$MIRROR/.purged" 2>/dev/null || true; git -C "$MIRROR" show "origin/$BRANCH:.purged" 2>/dev/null || true; } | sort -u )"
    enc_args=(); for r in "${RCPTS[@]}"; do enc_args+=(--recipient "$r"); done
    changed=0
    shopt -s nullglob
    for f in "$RAW"/*.jsonl "$RAW"/*.md; do
      [ -f "$f" ] || continue
      base="$(basename "$f")"
      # Purged blobs must stay purged: a purge removes the sha sidecar, so without this check the
      # next push re-encrypts and resurrects the blob for as long as the source capture is
      # un-retired (curated from another repo/machine than the origin). Skip by relpath, not sha —
      # a resumed session rewriting the capture must not re-leak purged content.
      if [ -n "$PURGED" ]; then
        ph="$(printf '%s' "$mtoken/$repo_name/$base.gpg" | sha256sum | awk '{print $1}')"
        printf '%s\n' "$PURGED" | grep -qx "$ph" && continue
      fi
      sha="$(sha256sum "$f" | awk '{print $1}')"
      shaf="$destdir/$base.gpg.sha256"
      [ -f "$shaf" ] && [ "$(cat "$shaf")" = "$sha" ] && continue
      # Guarded: an unusable recipient key (missing, expired, sign-only) must not kill the hook
      # silently mid-loop under `set -e` — log it, keep the SOURCE capture untouched, and carry on
      # so the other files still get their durable copy. The sha sidecar is only written on
      # success, so a later run (after the key is fixed) retries this file automatically.
      if ! gpg --batch --yes --no-tty --trust-model always "${enc_args[@]}" --encrypt \
           --output "$destdir/$base.gpg" "$f" 2>/dev/null; then
        rm -f "$destdir/$base.gpg"
        bw_health capture_backup error "encrypt FAILED for $base (recipient key unusable/missing?) — capture stays local-only until fixed"
        echo "[backup] encrypt FAILED for $base — source capture kept; fix the recipient key (scripts/doctor.sh checks it)" >&2
        continue
      fi
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
    # Blobs are per-machine BRANCHES (capture/<machine>), and ensure_mirror fetches only ours —
    # the cross-machine pool /curate and /purge sweep lives on the other branches. Fetch them all
    # here (curate-time only, never on the push hot path) so the loops below can see every machine.
    git -C "$MIRROR" fetch --quiet origin '+refs/heads/*:refs/remotes/origin/*' 2>/dev/null || true
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
    # find, not a ** glob: globstar is bash 4+, and `shopt -s globstar` under `set -e` kills the
    # whole pull on macOS's system bash 3.2 before a single blob is decrypted.
    shopt -s nullglob
    n=0; fail=0
    while IFS= read -r blob; do
      [ -f "$blob" ] || continue
      rel="${blob#"$MIRROR"/}"
      case "$rel" in health/*|.git/*) continue;; esac   # health shards handled separately below
      out="$DEST/${rel%.gpg}"
      mkdir -p "$(dirname "$out")"
      [ -f "$out" ] && continue
      # Interactive path (curate-time): allow gpg-agent / pinentry for the passphrase —
      # do NOT use --batch/--no-tty here, or a protected private key can't be unlocked.
      if gpg --yes --quiet --decrypt --output "$out" "$blob"; then n=$((n+1)); else
        fail=$((fail+1)); rm -f "$out"   # drop any partial/empty output so a later run retries cleanly
        echo "[backup] decrypt failed for $rel" >&2
      fi
    done < <(find "$MIRROR" -type f -name '*.gpg' 2>/dev/null)
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
    # Other machines' branches: read-only via ls-tree + git show — no checkout, the worktree
    # stays on OUR branch (it may hold unpushed ciphertext the loops above already covered).
    while IFS= read -r br; do
      [ "$br" = "HEAD" ] && continue
      [ "$br" = "$BRANCH" ] && continue
      while IFS= read -r rel; do
        case "$rel" in health/*) continue;; *.gpg) ;; *) continue;; esac
        out="$DEST/${rel%.gpg}"
        mkdir -p "$(dirname "$out")"
        [ -f "$out" ] && continue
        if git -C "$MIRROR" show "origin/$br:$rel" 2>/dev/null | gpg --yes --quiet --decrypt --output "$out"; then n=$((n+1)); else
          fail=$((fail+1)); rm -f "$out"
          echo "[backup] decrypt failed for $br:$rel" >&2
        fi
      done < <(git -C "$MIRROR" ls-tree -r --name-only "origin/$br" 2>/dev/null)
      while IFS= read -r hrel; do
        hb="$(basename "${hrel%.gpg}")"
        [ "$hb" = "$mtoken.jsonl" ] && continue
        hout="$BW_HOME/health/remote/$hb"
        git -C "$MIRROR" show "origin/$br:$hrel" 2>/dev/null | gpg --yes --quiet --decrypt --output "$hout" 2>/dev/null || rm -f "$hout"
      done < <(git -C "$MIRROR" ls-tree -r --name-only "origin/$br" -- health 2>/dev/null | grep '\.jsonl\.gpg$' || true)
    done < <(git -C "$MIRROR" for-each-ref --format='%(refname:short)' refs/remotes/origin 2>/dev/null | sed 's|^origin/||')
    shopt -u nullglob
    if [ "$fail" -gt 0 ]; then
      echo "[backup] decrypted $n new blob(s) into $DEST ($fail failed — see the passphrase note above)"
    else
      echo "[backup] decrypted $n new blob(s) into $DEST"
    fi
    ;;
  purge)
    rel="${2:-}"; rel="${rel#./}"
    [ -n "$rel" ] || { echo "usage: capture_backup.sh purge <relpath-under-branch>" >&2; exit 2; }
    # A bare session name matches neither blob (two per session: .jsonl.gpg + .md.gpg) and
    # exits 0 as "nothing to purge" — warn before it fails quiet.
    case "$rel" in *.gpg) ;; *) echo "[backup] warning: relpath should end in .jsonl.gpg or .md.gpg — a bare session name never matches (two blobs per session)" >&2;; esac
    ensure_mirror
    # Another machine's blob lives on ITS branch (capture/<machine>), which our worktree never
    # checks out. Purge it there via a throwaway detached worktree — the main worktree must stay
    # on OUR branch, or the next push's `git add -A` would commit one machine's tree to another's.
    mach="${rel%%/*}"
    if [ "$mach" != "$mtoken" ]; then
      git -C "$MIRROR" fetch --quiet origin '+refs/heads/*:refs/remotes/origin/*' 2>/dev/null || true
      tbr="capture/$mach"
      if ! git -C "$MIRROR" rev-parse -q --verify "refs/remotes/origin/$tbr" >/dev/null 2>&1; then
        # Convention miss (custom branch name): find the branch that actually holds the blob.
        tbr=""
        while IFS= read -r b; do
          [ "$b" = "HEAD" ] && continue
          git -C "$MIRROR" cat-file -e "origin/$b:$rel" 2>/dev/null && { tbr="$b"; break; }
        done < <(git -C "$MIRROR" for-each-ref --format='%(refname:short)' refs/remotes/origin 2>/dev/null | sed 's|^origin/||')
        [ -n "$tbr" ] || { echo "[backup] no branch holds $rel — nothing to purge" >&2; exit 0; }
      fi
      wt="$(mktemp -d "${TMPDIR:-/tmp}/bw-purge-wt.XXXXXX")"
      if ! git -C "$MIRROR" worktree add -q --detach "$wt/w" "origin/$tbr" 2>/dev/null; then
        rm -rf "$wt"
        bw_health capture_backup warn "purge: cannot stage worktree for $tbr ($rel)"
        echo "[backup] cannot stage a worktree for $tbr — purge not applied" >&2; exit 0
      fi
      wid() { git -C "$wt/w" -c user.name=bailiwick -c user.email=backup@local "$@"; }
      wid rm -q --ignore-unmatch "$rel" "$rel.sha256" 2>/dev/null || true
      ph="$(printf '%s' "$rel" | sha256sum | awk '{print $1}')"
      grep -qx "$ph" "$wt/w/.purged" 2>/dev/null || { printf '%s\n' "$ph" >> "$wt/w/.purged"; wid add .purged; }
      if wid commit -q -m "purge: $rel (curated)" 2>/dev/null; then
        # No local branch to drain from later (the worktree is gone after this run) — a failed
        # push here is retried by simply re-running the same purge command.
        wid push -q origin "HEAD:refs/heads/$tbr" 2>/dev/null \
          && echo "[backup] purged $rel (branch $tbr)" \
          || { bw_health capture_backup warn "purge push failed ($rel on $tbr) — re-run to retry"; echo "[backup] purge push failed for $tbr — re-run to retry" >&2; }
      else
        echo "[backup] nothing new to purge: $rel"
      fi
      git -C "$MIRROR" worktree remove -f "$wt/w" 2>/dev/null || true
      git -C "$MIRROR" worktree prune 2>/dev/null || true
      rm -rf "$wt"
      exit 0
    fi
    git_id rm -q --ignore-unmatch "$rel" "$rel.sha256" 2>/dev/null || true
    # Tombstone in the branch-root manifest so push never re-encrypts this blob (see push loop).
    # Entries are sha256 of the blob relpath, NOT the path itself: a path-named marker would keep
    # the client-identifying repo-key in the current tree — exactly what purge_verify.sh residual
    # --backup-path greps for — while a hashed line matches no prefix and names no client.
    ph="$(printf '%s' "$rel" | sha256sum | awk '{print $1}')"
    grep -qx "$ph" "$MIRROR/.purged" 2>/dev/null || { printf '%s\n' "$ph" >> "$MIRROR/.purged"; git_id add .purged; }
    git_id commit -q -m "purge: $rel (curated)" 2>/dev/null || echo "[backup] nothing new to purge: $rel"
    # Always drain: a prior purge's push may have failed silently, leaving the mirror ahead —
    # "commit succeeded" and "push attempted" must stay decoupled or stranded commits never flush.
    git_id fetch -q origin "$BRANCH" 2>/dev/null || true
    if [ -n "$(git_id rev-list "origin/$BRANCH..$BRANCH" -n1 2>/dev/null)" ]; then
      bw_health capture_backup info "purge: draining unpushed mirror commit(s) ($rel)"
      git_id push -q origin "$BRANCH" 2>/dev/null \
        && echo "[backup] purged $rel" \
        || { bw_health capture_backup warn "purge push failed ($rel)"; echo "[backup] purge committed in mirror; push failed" >&2; }
    fi
    ;;
  *) echo "usage: capture_backup.sh [push | pull [dest] | purge <relpath>]" >&2; exit 2;;
esac
