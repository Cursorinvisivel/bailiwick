#!/usr/bin/env bash
# SessionStart hook for the bailiwick.
#  1. Asserts the framework defaults (knowledge always on, orchestration proportional).
#  2. Nags when raw session captures are pending curation.
# stdout from a SessionStart hook is injected into the session context.
set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
RAW_DIR="$PROJECT_DIR/.bailiwick-outputs/raw"
RAW_LABEL=".bailiwick-outputs/raw/"
BW_HOME="${BAILIWICK_HOME:-$HOME/.bailiwick}"
# Locate the framework by this script's own path (portable across machines — the
# satellite clones live at different absolute paths than the central one).
BAILIWICK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
INDEX="$BAILIWICK_ROOT/knowledge/INDEX.md"
# Framework-health logging (best-effort; no-op fallback if the helper is missing).
. "$BAILIWICK_ROOT/hooks/health_common.sh" 2>/dev/null || true
command -v bw_health >/dev/null 2>&1 || bw_health() { :; }

# Self-gating guard: the hooks are installed once at user level and fire in every
# project. Stay inert unless this repo is bailiwick-wired — i.e. it carries a hidden framework
# complement file (CLAUDE.local.md / .bailiwick.local.md / the Copilot instructions) that
# references $BAILIWICK. The team's own shared CLAUDE.md/AGENTS.md are never relied on.
is_bailiwick_repo() {
  local f
  for f in \
    "$PROJECT_DIR/.bailiwick.local.md" \
    "$PROJECT_DIR/CLAUDE.local.md" \
    "$PROJECT_DIR/.github/instructions/bailiwick.instructions.md"; do
    if [ -f "$f" ] && grep -q 'BAILIWICK' "$f" 2>/dev/null; then
      return 0
    fi
  done
  return 1
}
# Shadow activation (no in-repo marker; FRAMEWORK.md §7.1): BAILIWICK_SHADOW=1 (per-shell) or a
# repo-root match in ~/.bailiwick/allowlist (one absolute path per line; # comments). Lets the
# framework attach to a repo left completely untouched (e.g. a client clone).
is_shadow_repo() {
  [ "${BAILIWICK_SHADOW:-}" = "1" ] && return 0
  local list="$BW_HOME/allowlist" here line
  [ -f "$list" ] || return 1
  here="$(cd "$PROJECT_DIR" 2>/dev/null && pwd -P || echo "$PROJECT_DIR")"
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%%#*}"
    line="${line#"${line%%[![:space:]]*}"}"; line="${line%"${line##*[![:space:]]}"}"
    line="${line%/}"
    if [ -n "$line" ] && [ "$here" = "$line" ]; then return 0; fi
  done < "$list"
  return 1
}

SEEDED=0; SHADOW=0
if is_bailiwick_repo;   then SEEDED=1; fi
if is_shadow_repo; then SHADOW=1; fi
[ "$SEEDED" = 1 ] || [ "$SHADOW" = 1 ] || exit 0

# Shadow-only repos stage captures centrally (repo untouched); seeded repos stage in-repo.
if [ "$SEEDED" = 0 ] && [ "$SHADOW" = 1 ]; then
  # Call capture_session.py's repo_key() directly — the single source of truth for the central
  # staging key (collision-resistant: readable basename + short hash of the git remote / repo
  # realpath), so the nag always looks exactly where the writer stages. If python3 is absent there
  # are no captures to nag about anyway (the writer is python3), so the fallback is inconsequential.
  repo_key="$(PYTHONPATH="$BAILIWICK_ROOT/hooks" python3 -c 'import sys, capture_session; sys.stdout.write(capture_session.repo_key(sys.argv[1]))' "$PROJECT_DIR" 2>/dev/null || true)"
  [ -n "$repo_key" ] || repo_key="$(basename "${PROJECT_DIR%/}")"
  RAW_DIR="$BW_HOME/captures/$repo_key/raw"
  RAW_LABEL="$RAW_DIR"
fi

# The guardrail + capture hooks are python3; if it is missing they exit 127 and the harness fails
# open with no signal. Make that state loudly visible in-session (detectability, not enforcement).
if ! command -v python3 >/dev/null 2>&1; then
  echo "[bailiwick] WARNING: python3 not found on PATH — guardrails.py and capture_session.py CANNOT run."
  echo "[bailiwick] Dangerous-command enforcement and session capture are INACTIVE until python3 is installed."
  bw_health session_start error "python3 missing - guardrail and capture inactive"
fi

cat <<'EOF'
[bailiwick] Framework defaults active for this session:
- Knowledge library + conventions are always in play. The current knowledge index is included below; use it to judge relevance, then load the topics/patterns it lists on-demand (max 5 files). Do not re-read files already in context.
- Orchestration is proportional: the Lead (orchestrator) drives the Quality Workflow — route substantial or multi-step work through it; handle trivial edits and direct questions inline with knowledge loaded. Stating a substantial task IS the invocation; no prefix is required. Say "run the full Quality Workflow" to force it.
- Capture is enforced via hooks; promotion to the knowledge library stays human-gated via /curate.
EOF

# ADR-009: on a public-origin (contribute-only) clone, tell BOTH user and agent up front that
# ingestion is blocked — so /curate is not attempted and its refusal is not a surprise.
if . "$BAILIWICK_ROOT/hooks/public_origin.sh" 2>/dev/null \
   && command -v bw_public_origin_block >/dev/null 2>&1 \
   && co_reason="$(bw_public_origin_block "$BAILIWICK_ROOT")"; then
  cat <<EOF
- CONTRIBUTE-ONLY instance ($co_reason): knowledge ingestion is blocked here. /curate must not promote and hooks/sync_knowledge.sh will refuse to push — knowledge/ is tracked, so propagating would publish it. Generic contributions are fine; move private work to a clone whose origin is a private repo you own (docs/staying-private.md).
EOF
fi

# --- Inbound knowledge sync: keep the Bailiwick clone current (ff-only, throttled, non-fatal) ---
sync_inbound() {
  command -v git >/dev/null 2>&1 || return 0
  git -C "$BAILIWICK_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0
  local fh now last branch behind dirty
  fh="$(git -C "$BAILIWICK_ROOT" rev-parse --git-path FETCH_HEAD 2>/dev/null || echo '')"
  now="$(date +%s)"; last=0
  [ -n "$fh" ] && [ -f "$BAILIWICK_ROOT/$fh" ] && last="$(stat -c %Y "$BAILIWICK_ROOT/$fh" 2>/dev/null || echo 0)"
  [ -n "$fh" ] && [ -f "$fh" ] && last="$(stat -c %Y "$fh" 2>/dev/null || echo "$last")"
  if [ $(( now - last )) -gt 1800 ]; then
    timeout 8 git -C "$BAILIWICK_ROOT" fetch origin main --quiet >/dev/null 2>&1 || return 0
  fi
  branch="$(git -C "$BAILIWICK_ROOT" symbolic-ref --short -q HEAD || echo DETACHED)"
  behind="$(git -C "$BAILIWICK_ROOT" rev-list --count HEAD..origin/main 2>/dev/null || echo 0)"
  [ "${behind:-0}" -eq 0 ] && return 0
  dirty="$(git -C "$BAILIWICK_ROOT" status --porcelain 2>/dev/null | head -1)"
  if [ "$branch" = "main" ] && [ -z "$dirty" ]; then
    if timeout 8 git -C "$BAILIWICK_ROOT" merge --ff-only --quiet origin/main >/dev/null 2>&1; then
      printf '\n[bailiwick] Knowledge library updated: fast-forwarded %s commit(s) from origin/main.\n' "$behind"
    else
      printf '\n[bailiwick] Knowledge library is %s commit(s) behind origin/main (auto-ff failed). Pull when ready.\n' "$behind"
      bw_health session_start warn "inbound auto-ff failed (${behind} behind origin/main)"
    fi
  else
    printf '\n[bailiwick] Knowledge library is %s commit(s) behind origin/main (on %s%s). Rebase/merge when ready.\n' \
      "$behind" "$branch" "$([ -n "$dirty" ] && echo ', uncommitted')"
  fi
}
sync_inbound || true

if [ -d "$RAW_DIR" ]; then
  count=$(find "$RAW_DIR" -maxdepth 1 -name '*.jsonl' 2>/dev/null | wc -l | tr -d ' ')
  if [ "${count:-0}" -gt 0 ]; then
    printf '\n[bailiwick] %s raw session capture(s) pending curation in %s. Run /curate to review and promote (human-gated).\n' "$count" "$RAW_LABEL"
  fi
fi

# Framework-health nag: surface recent errors (last ~24h, this machine's shard only) so silent
# fail-open failures become visible. Signal only — details live in /metrics [framework health].
health_nag() {
  local hdir="$BW_HOME/health" today yday n
  [ -d "$hdir" ] || return 0
  today="$(date +%Y-%m-%d)"; yday="$(date -d yesterday +%Y-%m-%d 2>/dev/null || echo "$today")"
  n="$(grep -h '"event":"error"' "$hdir"/*.jsonl 2>/dev/null | grep -c -e "\"ts\":\"$today" -e "\"ts\":\"$yday" || true)"
  if [ "${n:-0}" -gt 0 ]; then
    printf '\n[bailiwick] %s framework error(s) logged in the last ~24h (hooks/sync/backup). Run /metrics for the health view.\n' "$n"
  fi
}
health_nag || true

# Inject the knowledge index so relevance can be judged without a blind read.
# Individual topic/pattern files (and domain sub-indexes) are NOT injected — load on-demand (max 5).
if [ -f "$INDEX" ]; then
  bytes=$(wc -c < "$INDEX" 2>/dev/null | tr -d ' ')
  if [ "${bytes:-0}" -gt 20000 ]; then
    printf '\n[bailiwick] Knowledge INDEX.md is %s bytes (> 20KB target) and is injected every session. Run /curate to shard a large domain into indexes/index_<domain>.md.\n' "$bytes"
  fi
  printf '\n===== bailiwick Knowledge Index (map only — load listed files & domain sub-indexes on-demand, max 5) =====\n'
  cat "$INDEX"
fi

exit 0
