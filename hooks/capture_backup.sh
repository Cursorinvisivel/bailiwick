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
#   retract          drain the purge-session ledger ($BAILIWICK_HOME/backup-retract.pending plus any
#                    .pending.spool-* file, hashed relpaths only) on this machine's branch. Run
#                    detached by capture_session.py; every push retries what is left. Entries
#                    leave the ledger (and spools) once origin has them.
#
# BW_DRILL_SANDBOX applies (its .drill-sandbox marker exists and the project is inside it) and this
# clone is not "$BW_DRILL_SANDBOX/framework" => push is a silent no-op, every other mode exits 3.
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

# Drill self-defence: a drill declares its sandbox (BW_DRILL_SANDBOX, set in the drill project's
# settings `env`), and only the sandbox's own framework copy may act inside it. The real clone's
# global hook fires there too — it must not push, pull, or purge against the real backup repo.
# The variable counts only when "$BW_DRILL_SANDBOX/.drill-sandbox" exists AND the project
# (CLAUDE_PROJECT_DIR > BW_HOOK_CWD > cwd) resolves inside the sandbox: a stale or leaked export
# would otherwise turn every backup into a silent no-op. Ignored with a content-free warn.
# When it does apply: push (the hook) exits 0 quietly; every other mode says so on stderr and exits 3,
# so a manual run never "succeeds" having done nothing.
if [ -n "${BW_DRILL_SANDBOX:-}" ]; then
  sbx_root="$(cd "$BW_DRILL_SANDBOX" 2>/dev/null && pwd -P || true)"
  sbx_proj="$(cd "${CLAUDE_PROJECT_DIR:-${BW_HOOK_CWD:-$PWD}}" 2>/dev/null && pwd -P || true)"
  sbx_applies=0
  if [ -n "$sbx_root" ] && [ -f "$sbx_root/.drill-sandbox" ] && [ -n "$sbx_proj" ]; then
    case "$sbx_proj/" in "${sbx_root%/}"/*) sbx_applies=1;; esac
  fi
  if [ "$sbx_applies" = 1 ]; then
    own_root="$(cd "$BAILIWICK_ROOT" 2>/dev/null && pwd -P)"
    drill_root="$(cd "$sbx_root/framework" 2>/dev/null && pwd -P || true)"
    if [ -z "$drill_root" ] || [ "$own_root" != "$drill_root" ]; then
      bw_health capture_backup info "drill sandbox active and this is not its framework copy — $MODE skipped"
      [ "$MODE" = "push" ] && exit 0
      echo "[backup] drill sandbox active (BW_DRILL_SANDBOX) and this is not its framework copy — $MODE NOT run" >&2
      exit 3
    fi
  else
    bw_health capture_backup warn "BW_DRILL_SANDBOX set but no drill sandbox applies (no .drill-sandbox marker, or the project is outside it) — variable ignored"
  fi
fi

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
# A detached SessionEnd child (see push) has no stdin payload; the parent hands it over via env.
[ -n "${BW_HOOK_EVENT:-}" ] && EVENT="$BW_HOOK_EVENT"
[ -n "${BW_HOOK_CWD:-}" ] && PAYLOAD_CWD="$BW_HOOK_CWD"

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

# Serialise every writer of the mirror: a detached SessionEnd push can overlap the next session's
# Stop push or a /curate pull/purge. mkdir is atomic and portable (no flock on macOS).
# Usage: mirror_lock <max-wait-seconds>   — returns 1 if still busy after waiting.
LOCK="$MIRROR.lock"
mirror_lock() {
  local waited=0
  mkdir -p "$(dirname "$MIRROR")"
  while ! mkdir "$LOCK" 2>/dev/null; do
    # Stale-lock takeover: a holder killed hard (SIGKILL, reboot) never runs its trap.
    if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +10 2>/dev/null)" ]; then
      bw_health capture_backup warn "stale mirror lock (>10 min) — taken over"
      rm -rf "$LOCK"; continue
    fi
    [ "$waited" -lt "$1" ] || return 1
    sleep 1; waited=$((waited + 1))
  done
  trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT
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
  # A conflicted rebase left behind by an earlier run makes EVERY later run die at the checkout
  # below with "error: you need to resolve your current index first" — surfacing as a recurring
  # Stop hook failure in unrelated sessions, long after the run that wedged it. The mirror is a
  # derived cache and the abort keeps our unpushed commits, so recover unattended rather than
  # leaving the backup dead until a human goes looking.
  if [ -d "$MIRROR/.git/rebase-merge" ] || [ -d "$MIRROR/.git/rebase-apply" ]; then
    bw_health capture_backup warn "mirror had a conflicted rebase in progress — aborted and recovered"
    git -C "$MIRROR" rebase --abort 2>/dev/null || git -C "$MIRROR" rebase --quit 2>/dev/null || true
  fi
  if [ -f "$MIRROR/.git/MERGE_HEAD" ]; then git -C "$MIRROR" merge --abort 2>/dev/null || true; fi
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

# Identifier-free label for commit messages and health lines: sha256(<text>)[:12]. Repo keys open with
# the repo's (often client-named) basename and relpaths add the session id; the backup repo's commit
# messages are plaintext that crypto-erasure cannot reach, and the health shard is aggregated
# fleet-wide. Blob PATHS keep the readable layout (changing it would orphan every existing blob).
# Terminal echoes keep the readable name: local and interactive only.
id12() { printf '%s' "$1" | sha256sum | cut -c1-12; }

# Machine-generated ciphertext commits: never sign. Inheriting a user's global commit.gpgsign=true
# makes every Stop/SessionEnd hook fire a pinentry prompt (or hang/fail headless).
git_id() { git -C "$MIRROR" -c user.name=bailiwick -c user.email=backup@local -c commit.gpgsign=false "$@"; }

# Reconcile a conflicted mirror rebase unattended — and never leave one in progress. The conflict
# this mirror actually produces is a purge (upstream deletion) meeting a capture commit that still
# carries the blob. Deletion wins: resurrecting purged ciphertext is exactly what the tombstone
# exists to prevent. A content clash keeps the replayed (newer) ciphertext — in a rebase, --theirs
# is the commit being replayed. Anything still unresolved aborts — a stuck rebase breaks every
# later run at ensure_mirror's checkout.
rebase_resolve() {
  local guard=0 line st p
  while [ -d "$MIRROR/.git/rebase-merge" ] || [ -d "$MIRROR/.git/rebase-apply" ]; do
    guard=$((guard + 1)); [ "$guard" -le 50 ] || break
    while IFS= read -r line; do
      st="${line:0:2}"; p="${line:3}"
      # The tombstone manifest is append-only on every side: keep the UNION. Taking one side would
      # drop the other machine's (or a purge-session retraction's) tombstones, and a dropped
      # tombstone lets a later push resurrect purged ciphertext.
      if [ "$p" = ".purged" ] && { [ "$st" = "UU" ] || [ "$st" = "AA" ]; }; then
        { git -C "$MIRROR" show ":2:.purged" 2>/dev/null || true; git -C "$MIRROR" show ":3:.purged" 2>/dev/null || true; } \
          | grep -E '^[0-9a-f]{64}$' | sort -u > "$MIRROR/.purged" || true
        git_id add -- .purged >/dev/null 2>&1 || true
        continue
      fi
      case "$st" in
        DU|UD|DD) git_id rm -q -f --ignore-unmatch -- "$p" >/dev/null 2>&1 || true;;
        *) git -C "$MIRROR" checkout -q --theirs -- "$p" >/dev/null 2>&1 || true
           git_id add -- "$p" >/dev/null 2>&1 || true;;
      esac
    done < <(git -C "$MIRROR" status --porcelain 2>/dev/null | grep -E '^(DD|AU|UD|UA|DU|AA|UU)' || true)
    GIT_EDITOR=true git_id rebase --continue >/dev/null 2>&1 \
      || GIT_EDITOR=true git_id rebase --skip >/dev/null 2>&1 || break
  done
  if [ -d "$MIRROR/.git/rebase-merge" ] || [ -d "$MIRROR/.git/rebase-apply" ]; then
    git -C "$MIRROR" rebase --abort 2>/dev/null || git -C "$MIRROR" rebase --quit 2>/dev/null || true
    bw_health capture_backup warn "mirror rebase could not be auto-resolved — aborted (ciphertext safe locally)"
    return 1
  fi
  return 0
}

# Push our branch. 0 = pushed, 2 = nothing ahead of origin, 1 = failed (commits stay in the mirror).
# Push whenever the mirror is AHEAD of origin, not only when this run committed something: a push
# killed after commit (SessionEnd timeout, crash, offline) otherwise strands its ciphertext.
push_branch() {
  local ahead
  if git -C "$MIRROR" rev-parse -q --verify "refs/remotes/origin/$BRANCH" >/dev/null 2>&1; then
    ahead="$(git -C "$MIRROR" rev-list --count "origin/$BRANCH..$BRANCH" 2>/dev/null || echo 0)"
  else
    ahead="$(git -C "$MIRROR" rev-list --count "$BRANCH" 2>/dev/null || echo 0)"
  fi
  [ "${ahead:-0}" -gt 0 ] || return 2
  if ! git_id push -q origin "$BRANCH" 2>/dev/null; then
    if git -C "$MIRROR" fetch -q origin "$BRANCH" 2>/dev/null; then
      git_id rebase -q "origin/$BRANCH" >/dev/null 2>&1 || rebase_resolve || true
    fi
    git_id push -q origin "$BRANCH" 2>/dev/null || return 1
  fi
  return 0
}

# ---- purge-session retraction ledger ---------------------------------------------------------------
# capture_session.py appends sha256(<blob relpath>) — the hash only — when a /purge session's earlier
# capture must leave the backup. No plaintext relpath is stored: drain_pending finds the blob by
# hashing this mirror's own tree, and the `.purged` tombstone is the hash itself. Entries leave the
# ledger only once origin holds the tombstone; until then every push (and `retract`) retries them.
# The ledger is only written under the `$PENDING.lock` mkdir lock (python's append, the rewrite in
# pending_done). A python writer that finds the lock busy drops its hashes in a spool file,
# `$PENDING.spool-<time_ns>-<pid>-<n>` (renamed into place whole), so the PENDING SET is the ledger
# plus every spool; pending_done folds the spools it read into the ledger, under the lock, and deletes
# exactly those — a spool created meanwhile is left for the next run.
PENDING="$BW_HOME/backup-retract.pending"
PLOCK="$PENDING.lock"
DRAINED=""
# The spool files present now, one per line (glob, not find: bash 3.2 + BSD safe, and an unmatched
# pattern stays literal, which `-f` rejects).
pending_spools() {
  local f
  for f in "$PENDING".spool-*; do
    if [ -f "$f" ]; then printf '%s\n' "$f"; fi
  done
}
# Valid hash lines of the ledger and the given spool list (stdin), unsorted.
pending_lines() {
  local f
  grep -E '^[0-9a-f]{64}$' "$PENDING" 2>/dev/null || true
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    grep -E '^[0-9a-f]{64}$' "$f" 2>/dev/null || true
  done
}
pending_hashes() { pending_spools | pending_lines | sort -u; }
pending_count() { pending_hashes | grep -c . || true; }
pending_lock() {
  local waited=0
  while ! mkdir "$PLOCK" 2>/dev/null; do
    if [ -n "$(find "$PLOCK" -maxdepth 0 -mmin +1 2>/dev/null)" ]; then rm -rf "$PLOCK"; continue; fi
    [ "$waited" -lt 50 ] || return 1
    sleep 0.1; waited=$((waited + 1))
  done
}
# Stage + commit the retraction of every pending hash on OUR branch (a purge session's blobs were
# pushed by this machine): tombstone it, `git rm` whichever blob relpath hashes to it. Sets DRAINED.
# The commit message carries <hash12> only — never the relpath (it holds the repo key and session).
drain_pending() {
  local h ph p map
  DRAINED="$(pending_hashes)"
  [ -n "$DRAINED" ] || return 0
  map="$(git -C "$MIRROR" ls-files 2>/dev/null | grep '\.gpg$' | while IFS= read -r p; do
           printf '%s %s\n' "$(printf '%s' "$p" | sha256sum | awk '{print $1}')" "$p"; done || true)"
  while IFS= read -r h; do
    [ -n "$h" ] || continue
    grep -qx "$h" "$MIRROR/.purged" 2>/dev/null || { printf '%s\n' "$h" >> "$MIRROR/.purged"; git_id add .purged; }
    while IFS=' ' read -r ph p; do
      [ "$ph" = "$h" ] || continue
      git_id rm -q -f --ignore-unmatch -- "$p" "$p.sha256" >/dev/null 2>&1 || true
    done <<EOF
$map
EOF
  done <<EOF
$DRAINED
EOF
  if ! git -C "$MIRROR" diff --cached --quiet 2>/dev/null; then
    git_id commit -q -m "purge: $(printf '%s\n' "$DRAINED" | cut -c1-12 | paste -sd' ' -) (purge-session)" >/dev/null 2>&1 || true
  fi
}
# After origin has our branch: drop every DRAINED hash the committed tombstone manifest confirms.
# Under the lock the ledger is rebuilt as (ledger ∪ the spools listed now) minus the done hashes,
# then exactly those spools are deleted: no pending hash is ever dropped by the rewrite.
pending_done() {
  local h f spools done_list="" committed
  [ -n "$DRAINED" ] || return 0
  committed="$(git -C "$MIRROR" show "HEAD:.purged" 2>/dev/null || true)"
  while IFS= read -r h; do
    [ -n "$h" ] || continue
    printf '%s\n' "$committed" | grep -qx "$h" && done_list="$done_list$h
"
  done <<EOF
$DRAINED
EOF
  DRAINED=""
  [ -n "$done_list" ] || return 0
  pending_lock || { bw_health capture_backup warn "purge-session ledger busy — $(pending_count) retraction(s) stay pending (next push retries)"; return 0; }
  spools="$(pending_spools)"
  if [ -f "$PENDING" ] || [ -n "$spools" ]; then
    ( umask 077
      printf '%s\n' "$spools" | pending_lines \
        | { grep -vxF -f <(printf '%s' "$done_list") || true; } | sort -u > "$PENDING.tmp.$$" )
    if [ -s "$PENDING.tmp.$$" ]; then mv -f "$PENDING.tmp.$$" "$PENDING"; else rm -f "$PENDING.tmp.$$" "$PENDING"; fi
    while IFS= read -r f; do
      if [ -n "$f" ]; then rm -f "$f"; fi
    done <<EOF
$spools
EOF
  fi
  rmdir "$PLOCK" 2>/dev/null || true
  while IFS= read -r h; do
    [ -n "$h" ] && bw_health capture_backup info "purge ok (${h:0:12})"
  done <<EOF
$done_list
EOF
  return 0
}

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
    # SessionEnd runs under Claude Code's quit-time budget — 1500 ms by default
    # (CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS), NOT the 600 s per-hook default. fetch+gpg+push
    # cannot fit; the harness aborts it ("Hook cancelled"). Hand the network leg to a detached
    # child and return at once. stdout/stderr MUST be redirected: an inherited pipe keeps the hook
    # "running" until the child exits, which is the same timeout again.
    # BW_BACKUP_SYNC=1 keeps it in the foreground (tests, manual runs).
    if [ "$event" = "SessionEnd" ] && [ -z "${BW_BACKUP_DETACHED:-}" ] && [ -z "${BW_BACKUP_SYNC:-}" ]; then
      runner=(nohup); command -v setsid >/dev/null 2>&1 && runner=(setsid nohup)
      BW_BACKUP_DETACHED=1 BW_HOOK_EVENT="$event" BW_HOOK_CWD="$PROJECT_DIR" \
        "${runner[@]}" bash "${BASH_SOURCE[0]:-$0}" push </dev/null >/dev/null 2>&1 &
      disown 2>/dev/null || true
      exit 0
    fi
    # Detached child: let the parallel SessionEnd capture_session.py finish writing the final
    # capture first. The two hooks run concurrently, so without this the forced push can miss it.
    [ -n "${BW_BACKUP_DETACHED:-}" ] && sleep "${BW_BACKUP_SETTLE_S:-3}"
    # Stop must stay snappy: if another push holds the mirror, skip (don't touch STAMP, so the next
    # Stop retries). The detached child can afford to wait.
    if [ -n "${BW_BACKUP_DETACHED:-}" ]; then
      mirror_lock 120 || { bw_health capture_backup warn "mirror busy >120 s — SessionEnd push skipped (next Stop retries)"; exit 0; }
    else
      mirror_lock 0 || exit 0
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
    # Purge-session retractions still pending (the detached `retract` was busy/offline/rejected):
    # retry them FIRST, so their tombstones are in the manifest the sweep and loop below read.
    drain_pending
    # Tombstoned relpaths — union of the worktree manifest and origin's: a purge issued from
    # ANOTHER machine lands on origin first, and this worktree only syncs at the next
    # push-reject→rebase. Reading both closes that window.
    PURGED="$( { cat "$MIRROR/.purged" 2>/dev/null || true; git -C "$MIRROR" show "origin/$BRANCH:.purged" 2>/dev/null || true; } | sort -u )"
    enc_args=(); for r in "${RCPTS[@]}"; do enc_args+=(--recipient "$r"); done
    changed=0
    # Tombstoned blobs must LEAVE this mirror's tree, not merely be skipped on re-encrypt: a purge
    # pushed from elsewhere deletes them on origin only, and ensure_mirror never resets the worktree
    # to origin. A tree that still carries them makes the next `add -A` resurrect the ciphertext and
    # the next rebase conflict (modify/delete — which no -X strategy resolves). changed=1 so a
    # purge-only run commits the staged deletions instead of leaving them in the index.
    if [ -n "$PURGED" ]; then
      while IFS= read -r trel; do
        [ -n "$trel" ] || continue
        th="$(printf '%s' "$trel" | sha256sum | awk '{print $1}')"
        printf '%s\n' "$PURGED" | grep -qx "$th" || continue
        git_id rm -q -f --ignore-unmatch -- "$trel" "$trel.sha256" >/dev/null 2>&1 || true
        changed=1
      done < <(git -C "$MIRROR" ls-files 2>/dev/null | grep '\.gpg$' || true)
    fi
    # After the sweep, not before: `git rm` of a directory's last blob removes the directory too.
    mkdir -p "$destdir"
    shopt -s nullglob
    held=0
    for f in "$RAW"/*.jsonl "$RAW"/*.md; do
      [ -f "$f" ] || continue
      base="$(basename "$f")"
      # Purge detection failed on this session (capture_session.py wrote the header line): it may be
      # a /purge session, so both files stay LOCAL until a human reviews and removes the line.
      if grep -qx -- '- purge_detection: error' "$RAW/${base%.*}.md" 2>/dev/null; then
        held=$((held + 1)); continue
      fi
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
        bw_health capture_backup error "encrypt FAILED for $(id12 "$base") (recipient key unusable/missing?) — capture stays local-only until fixed"
        echo "[backup] encrypt FAILED for $base — source capture kept; fix the recipient key (scripts/doctor.sh checks it)" >&2
        continue
      fi
      printf '%s\n' "$sha" > "$shaf"
      changed=1
    done
    shopt -u nullglob
    if [ "$held" -gt 0 ]; then
      bw_health capture_backup warn "$held capture file(s) held local-only: purge detection error — review, then remove the 'purge_detection: error' header line"
    fi
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
    if [ "$changed" = "1" ]; then
      git_id add -A
      git_id commit -q -m "capture: $mtoken/$(id12 "$repo_name") $(date -u +%Y-%m-%dT%H:%M:%SZ)" || true
    fi
    prc=0; push_branch || prc=$?
    if [ "$prc" = 2 ]; then pending_done; exit 0; fi   # nothing ahead: origin already has it all
    if [ "$prc" = 1 ]; then
      unp="$(git -C "$MIRROR" rev-list --count "origin/$BRANCH..$BRANCH" 2>/dev/null || echo '?')"
      bw_health capture_backup error "push failed ($BRANCH; $unp unpushed commit(s); ciphertext safe in local mirror)"
      [ -z "$DRAINED" ] || bw_health capture_backup warn "purge-session retraction not pushed — $(pending_count) pending (next push retries)"
      echo "[backup] push failed (ciphertext safe in local mirror $MIRROR)" >&2; exit 0
    fi
    pending_done
    bw_health capture_backup info "push ok ($(id12 "$repo_name") -> $BRANCH)"
    # stderr, not stdout: Codex parses a Stop/SessionEnd hook's stdout as JSON, so a plain line
    # there marks the hook Failed. Same channel its failure sibling above already uses.
    echo "[backup] pushed '$repo_name' captures to $BRANCH" >&2
    ;;
  pull)
    DEST="${2:-$BAILIWICK_ROOT/.bailiwick-inbox/raw}"
    mkdir -p "$DEST"
    mirror_lock 120 || { echo "[backup] capture mirror busy — retry shortly" >&2; exit 1; }
    ensure_mirror
    # Blobs are per-machine BRANCHES (capture/<machine>), and ensure_mirror fetches only ours —
    # the cross-machine pool /curate and /purge sweep lives on the other branches. Fetch them all
    # here (curate-time only, never on the push hot path) so the loops below can see every machine.
    git -C "$MIRROR" fetch --quiet origin '+refs/heads/*:refs/remotes/origin/*' 2>/dev/null || true
    # Decrypt needs to UNLOCK the (passphrase-protected) private key, which means gpg-agent must be
    # able to prompt via pinentry. Tell gpg-agent which terminal to use, if we have one (harmless if
    # not — a GUI pinentry uses $DISPLAY instead). This makes the manual `… pull` path work in a plain
    # terminal without the caller having to remember `export GPG_TTY=$(tty)`. Exported ONLY when tty
    # succeeds: without a terminal `tty` prints "not a tty", which must not become GPG_TTY (it made
    # the no-TTY preflight below dead code). An `if`, so a failing tty is safe under `set -e`.
    if [ -z "${GPG_TTY:-}" ] && _tty=$(tty 2>/dev/null); then export GPG_TTY="$_tty"; fi
    # Preflight: pinentry can only prompt if there is a TTY (curses pinentry), a GUI display (graphical
    # pinentry), or the key is already unlocked in gpg-agent. If none hold, decryption cannot possibly
    # succeed — say so ONCE, with the fix, instead of emitting a failure line per blob.
    key_cached() { gpg-connect-agent 'keyinfo --list' /bye 2>/dev/null \
        | awk '$1=="S"&&$2=="KEYINFO"&&$7=="1"{f=1} END{exit f?0:1}'; }
    if [ -z "${GPG_TTY:-}" ] && [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ] && ! key_cached; then
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
    # Logged: capture_session.py also runs this detached (purge-session retraction), where stderr
    # goes nowhere — a busy mirror must not drop that request silently.
    mirror_lock 120 || { bw_health capture_backup warn "purge: mirror busy >120 s — not applied, re-run it"; echo "[backup] capture mirror busy — retry shortly" >&2; exit 1; }
    ensure_mirror
    # Health lines and commit messages name the blob by <sha256(relpath)[:12]>, never the relpath:
    # it carries the repo key (a client-identifying basename) and the session id, and both the
    # fleet-aggregated health shard and the backup repo's history outlive the purge. Terminal echoes
    # keep the relpath (local, interactive). Same reason the `.purged` tombstone is hashed.
    ph="$(printf '%s' "$rel" | sha256sum | awk '{print $1}')"; h12="$(id12 "$rel")"
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
        bw_health capture_backup warn "purge: cannot stage worktree for $tbr ($h12)"
        echo "[backup] cannot stage a worktree for $tbr — purge not applied" >&2; exit 0
      fi
      wid() { git -C "$wt/w" -c user.name=bailiwick -c user.email=backup@local -c commit.gpgsign=false "$@"; }
      wid rm -q --ignore-unmatch "$rel" "$rel.sha256" 2>/dev/null || true
      grep -qx "$ph" "$wt/w/.purged" 2>/dev/null || { printf '%s\n' "$ph" >> "$wt/w/.purged"; wid add .purged; }
      if wid commit -q -m "purge: $h12 (curated)" 2>/dev/null; then
        # No local branch to drain from later (the worktree is gone after this run) — a failed
        # push here is retried by simply re-running the same purge command.
        wid push -q origin "HEAD:refs/heads/$tbr" 2>/dev/null \
          && echo "[backup] purged $rel (branch $tbr)" \
          || { bw_health capture_backup warn "purge push failed ($h12 on $tbr) — re-run to retry"; echo "[backup] purge push failed for $tbr — re-run to retry" >&2; }
      else
        echo "[backup] nothing new to purge: $rel"
      fi
      git -C "$MIRROR" worktree remove -f "$wt/w" 2>/dev/null || true
      git -C "$MIRROR" worktree prune 2>/dev/null || true
      rm -rf "$wt"
      exit 0
    fi
    # Pending purge-session retractions ride along (own branch only — that is where they live).
    drain_pending
    git_id rm -q --ignore-unmatch "$rel" "$rel.sha256" 2>/dev/null || true
    # Tombstone in the branch-root manifest so push never re-encrypts this blob (see push loop).
    # Entries are sha256 of the blob relpath, NOT the path itself: a path-named marker would keep
    # the client-identifying repo-key in the current tree — exactly what purge_verify.sh residual
    # --backup-path greps for — while a hashed line matches no prefix and names no client.
    grep -qx "$ph" "$MIRROR/.purged" 2>/dev/null || { printf '%s\n' "$ph" >> "$MIRROR/.purged"; git_id add .purged; }
    git_id commit -q -m "purge: $h12 (curated)" 2>/dev/null || echo "[backup] nothing new to purge: $rel"
    # A manual purge of a blob the ledger still lists settles that entry too.
    if pending_hashes | grep -qx "$ph"; then DRAINED="$(printf '%s\n%s' "$DRAINED" "$ph" | grep . | sort -u || true)"; fi
    # Always drain: a prior purge's push may have failed silently, leaving the mirror ahead —
    # "commit succeeded" and "push attempted" must stay decoupled or stranded commits never flush.
    git_id fetch -q origin "$BRANCH" 2>/dev/null || true
    if [ -n "$(git_id rev-list "origin/$BRANCH..$BRANCH" -n1 2>/dev/null)" ]; then
      bw_health capture_backup info "purge: draining unpushed mirror commit(s) ($h12)"
      if git_id push -q origin "$BRANCH" 2>/dev/null; then
        echo "[backup] purged $rel"; pending_done
      else
        bw_health capture_backup warn "purge push failed ($h12)"; echo "[backup] purge committed in mirror; push failed" >&2
      fi
    elif git -C "$MIRROR" rev-parse -q --verify "refs/remotes/origin/$BRANCH" >/dev/null 2>&1; then
      pending_done   # not ahead of a KNOWN origin branch: origin already holds the tombstones
    fi
    ;;
  retract)
    # Purge-session retraction: drain the ledger (run detached by capture_session.py, no argument —
    # the ledger holds hashes, so no identifier reaches argv or `ps`). Gated like push.
    [ -n "$(pending_hashes)" ] || exit 0
    [ "$ACK" = "1" ] || { bw_health capture_backup warn "retract: confidentiality_ack is false — $(pending_count) retraction(s) stay pending"; exit 0; }
    mirror_lock 120 || { bw_health capture_backup warn "retract: mirror busy >120 s — $(pending_count) retraction(s) pending (next push retries)"; exit 0; }
    ensure_mirror
    drain_pending
    rrc=0; push_branch || rrc=$?
    if [ "$rrc" = 1 ]; then
      bw_health capture_backup warn "retract: push failed — $(pending_count) retraction(s) pending (next push retries)"
      exit 0
    fi
    pending_done
    ;;
  *) echo "usage: capture_backup.sh [push | pull [dest] | purge <relpath> | retract]" >&2; exit 2;;
esac
