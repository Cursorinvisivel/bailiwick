#!/usr/bin/env bash
# bailiwick — outbound knowledge sync.
#
# Propagates curated, human-approved knowledge commits from this machine to the
# central repo. Role-aware (see .bailiwick-sync.json):
#   central   → push HEAD straight to origin/main (this machine is the merge authority).
#   satellite → move the new commits onto branch sync/<machine>, push it
#               (--force-with-lease), and open/refresh a PR to main. Local main is
#               reset to origin/main so it always fast-forwards. Telemetry is
#               central-owned, so satellites must not produce telemetry deltas
#               (curate skips the telemetry step on satellites — see SKILL.md).
#
# Invoked by /curate after an approved knowledge: commit, or run manually.
# Safe to re-run: idempotent (force-with-lease on a machine-owned branch; PR reused).
set -euo pipefail

BAILIWICK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
cd "$BAILIWICK_ROOT"
# Framework-health logging (best-effort; no-op fallback if the helper is missing).
. "$BAILIWICK_ROOT/hooks/health_common.sh" 2>/dev/null || true
command -v bw_health >/dev/null 2>&1 || bw_health() { :; }

CFG="$BAILIWICK_ROOT/.bailiwick-sync.json"
role="satellite"
machine="$(hostname 2>/dev/null || echo unknown)"
if [ -f "$CFG" ]; then
  m=""
  if command -v python3 >/dev/null 2>&1; then
    role="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("role","satellite"))' "$CFG" 2>/dev/null || echo satellite)"
    m="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("machine") or "")' "$CFG" 2>/dev/null || true)"
  else  # no python3: best-effort grep parse
    role="$(grep -oE '"role"[[:space:]]*:[[:space:]]*"[^"]+"' "$CFG" | head -1 | sed -E 's/.*"([^"]+)"$/\1/')"
    m="$(grep -oE '"machine"[[:space:]]*:[[:space:]]*"[^"]+"' "$CFG" | head -1 | sed -E 's/.*"([^"]+)"$/\1/')"
  fi
  role="${role:-satellite}"
  [ -n "${m:-}" ] && machine="$m"
fi
# normalise machine token for a branch-safe name
machine="$(printf '%s' "$machine" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9._-')"

git fetch origin main --quiet || { bw_health sync_knowledge warn "cannot reach origin - commits stay local"; echo "[sync] cannot reach origin — aborting (commits stay local)"; exit 0; }

ahead="$(git rev-list --count origin/main..HEAD 2>/dev/null || echo 0)"
if [ "$ahead" -eq 0 ]; then
  echo "[sync] nothing to propagate (HEAD not ahead of origin/main)."
  exit 0
fi

# ADR-009: a public-origin clone is contribute-only — refuse to propagate, commits stay local.
# Checked AFTER the ahead-count so a no-op sync on a contribute-only clone stays quiet, and BEFORE
# either role's push so neither path can publish.
. "$BAILIWICK_ROOT/hooks/public_origin.sh" 2>/dev/null || true
if command -v bw_public_origin_block >/dev/null 2>&1; then
  if reason="$(bw_public_origin_block "$BAILIWICK_ROOT")"; then
    bw_public_origin_notice "$reason"
    bw_health sync_knowledge error "propagation refused: $reason ($ahead commit(s) stay local)"
    echo "[sync] REFUSED — $ahead commit(s) stay local (ADR-009 contribute-only)." >&2
    exit 1
  fi
else
  bw_health sync_knowledge warn "public-origin check unavailable (hooks/public_origin.sh missing)"
  echo "[sync] WARNING: ADR-009 public-origin check unavailable — verify 'origin' before pushing." >&2
fi

if [ "$role" = "central" ]; then
  echo "[sync] central: pushing $ahead commit(s) to origin/main…"
  git push origin HEAD:main || { bw_health sync_knowledge error "central push to origin/main failed ($ahead commit(s) local)"; echo "[sync] push FAILED — commits stay local." >&2; exit 1; }
  echo "[sync] done."
  exit 0
fi

# ---- satellite ----
branch="sync/${machine}"
echo "[sync] satellite '${machine}': moving $ahead commit(s) onto ${branch} + PR…"

# Park the new commits on the per-machine branch; keep local main clean/ff-able.
git checkout -B "$branch" >/dev/null 2>&1        # branch at current HEAD; tree unchanged
git branch -f main origin/main                    # reset main ref (not checked out, tree untouched)

git push -u origin "$branch" --force-with-lease || { bw_health sync_knowledge error "satellite push of $branch failed ($ahead commit(s) parked locally)"; echo "[sync] push of ${branch} FAILED — commits parked locally." >&2; exit 1; }

if command -v gh >/dev/null 2>&1; then
  # Reuse the PR only if one is actually OPEN for this branch. The branch name is reused across
  # syncs, so a previous PR may be MERGED/CLOSED — checking mere existence (gh pr view) would treat
  # a merged PR as still-open and skip creation, stranding the new commits with no route to main.
  open_num="$(gh pr list --head "$branch" --state open --json number --jq '.[0].number // empty' 2>/dev/null || true)"
  if [ -n "$open_num" ]; then
    echo "[sync] PR #${open_num} already open for ${branch} (updated by the push)."
  else
    gh pr create --base main --head "$branch" \
      --title "knowledge: sync from ${machine}" \
      --body "Automated knowledge sync from \`${machine}\`. Curated + human-approved on the satellite. Telemetry is central-owned and intentionally excluded — central reconciles rows on merge." \
      && echo "[sync] opened a new PR for ${branch}." \
      || { bw_health sync_knowledge warn "gh pr create failed for $branch (push succeeded)"; echo "[sync] push succeeded; 'gh pr create' failed — open the PR for ${branch} manually."; }
  fi
else
  echo "[sync] pushed ${branch}. 'gh' not installed — open a PR to main manually."
fi
echo "[sync] done. You remain on ${branch}; local main mirrors origin/main."
