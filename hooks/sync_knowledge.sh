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
#
# Exit codes: 0 = synced (or nothing to do); 1 = push refused/failed (commits stay local);
# 2 = satellite push succeeded but PR creation failed — the knowledge is durably on
# sync/<machine> yet STRANDED until a PR to main exists (other machines only ever
# fast-forward from origin/main). The no-`gh` path stays exit 0: opening the PR manually
# is the documented flow there, not a failure.
set -euo pipefail

BAILIWICK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
cd "$BAILIWICK_ROOT"
# Framework-health logging (best-effort; no-op fallback if the helper is missing).
. "$BAILIWICK_ROOT/hooks/health_common.sh" 2>/dev/null || true
command -v bw_health >/dev/null 2>&1 || bw_health() { :; }

# Role + branch-safe machine token from the shared primitives (hooks/config_common.sh — the
# single implementation of the config read and the token normalization).
. "$BAILIWICK_ROOT/hooks/config_common.sh" 2>/dev/null || true
if command -v bw_cfg_get >/dev/null 2>&1; then
  role="$(bw_cfg_get role satellite)"
  machine="$(bw_machine_token)"
else
  echo "[sync] hooks/config_common.sh missing — cannot determine role/machine; aborting." >&2
  exit 1
fi

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
  # Multi-account machines: bare `gh` talks to the API as the globally ACTIVE account, which may
  # not even see this repo (the push above rode the SSH alias; the API call does not). Resolve the
  # right account and target the repo explicitly so PR creation cannot silently 404 while the push
  # succeeds — the failure mode that strands satellite knowledge for weeks.
  . "$BAILIWICK_ROOT/hooks/gh_account.sh" 2>/dev/null || true
  repo_args=""
  if command -v bw_resolve_gh_account >/dev/null 2>&1; then
    bw_resolve_gh_account "$BAILIWICK_ROOT"
    repo_args="$(bw_gh_repo_args)"
    [ -n "${BW_GH_USER:-}" ] && echo "[sync] gh: acting as '${BW_GH_USER}' on ${BW_GH_HOST} (${BW_GH_DECIDED})"
    [ -n "${BW_GH_WARN:-}" ] && echo "[sync] ⚠ gh: ${BW_GH_WARN}" >&2
  else
    bw_health sync_knowledge warn "hooks/gh_account.sh missing — gh runs as the active account"
    bw_gh() { gh "$@"; }
    bw_gh_open_pr() { gh pr list --head "$1" --state open --json number --jq '.[0].number // empty' 2>/dev/null || true; }
  fi
  # Reuse the PR only if one is actually OPEN for this branch (bw_gh_open_pr owns the state
  # filter — a MERGED/CLOSED PR must not count, or new commits strand with no route to main).
  open_num="$(bw_gh_open_pr "$branch")"
  if [ -n "$open_num" ]; then
    echo "[sync] PR #${open_num} already open for ${branch} (updated by the push)."
  else
    # shellcheck disable=SC2086
    bw_gh pr create $repo_args --base main --head "$branch" \
      --title "knowledge: sync from ${machine}" \
      --body "Automated knowledge sync from \`${machine}\`. Curated + human-approved on the satellite. Telemetry is central-owned and intentionally excluded — central reconciles rows on merge." \
      && echo "[sync] opened a new PR for ${branch}." \
      || {
        bw_health sync_knowledge error "gh pr create failed for $branch (push succeeded — knowledge STRANDED until a PR to main exists)"
        {
          echo "[sync] ✗ push succeeded but PR creation FAILED — the new knowledge is STRANDED on ${branch}."
          echo "[sync]   Other machines fast-forward from origin/main only; until a PR to main exists and is"
          echo "[sync]   merged on central, nothing else will ever see these commits. Open it now:"
          echo "[sync]     gh pr create ${repo_args:+$repo_args }--base main --head ${branch} --title 'knowledge: sync from ${machine}'"
          if [ -z "${BW_GH_USER:-}" ]; then
            echo "[sync]   No logged-in gh account could read ${BW_GH_REPO:-the repo} — check 'gh auth status',"
            echo "[sync]   or pin an account in .bailiwick-sync.json (\"github_account\" or \"github_account_map\")."
          fi
        } >&2
        exit 2
      }
  fi
else
  bw_health sync_knowledge warn "gh not installed — PR for $branch must be opened manually"
  echo "[sync] pushed ${branch}. 'gh' not installed — open a PR to main manually."
fi
echo "[sync] done. You remain on ${branch}; local main mirrors origin/main."
