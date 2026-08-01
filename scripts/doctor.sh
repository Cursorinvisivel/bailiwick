#!/usr/bin/env bash
# bailiwick doctor — read-only preflight over the framework's wiring invariants.
#
# Every check here is an invariant that can go silently false — none of them raises an error at
# the moment it breaks; each surfaces days or weeks later as lost captures or stranded knowledge.
# Run this after cloning/moving the framework, changing machines or accounts, or whenever sync
# behaviour looks off. Writes nothing; network use is limited to `git fetch`/`git ls-remote` and
# read-only `gh` API calls.
#
#   ✓ pass   ⚠ degraded (works, but something is off)   ✗ broken (data loss / stranding risk)
#
# Exit 0 when nothing is broken; exit 1 when any ✗ fired.
set -uo pipefail

BAILIWICK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
cd "$BAILIWICK_ROOT"

ERR=0; WARN=0
ok()   { printf '  \342\234\223 %s\n' "$1"; }
warn() { printf '  \342\232\240 %s\n' "$1"; WARN=$((WARN+1)); }
fail() { printf '  \342\234\227 %s\n' "$1"; ERR=$((ERR+1)); }

echo "bailiwick doctor — $BAILIWICK_ROOT"

HAVE_PY=1
command -v python3 >/dev/null 2>&1 || { HAVE_PY=0; warn "python3 not found — JSON checks degrade to best-effort parsing"; }

# ---- 1. Hook wiring: the hooks the harness executes must live in THIS clone -------------------
# The framework can be cloned more than once (rename, migration, private fork). The hooks in
# ~/.claude/settings.json keep running from wherever they were installed — every fix pulled into
# this clone is dead code until the paths agree, and captures land wherever the OLD generation
# staged them, invisible to this clone's /curate.
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
if [ ! -f "$SETTINGS" ]; then
  warn "no $SETTINGS — Claude Code hooks not installed (run scripts/bootstrap.sh --install-tools)"
elif [ "$HAVE_PY" -eq 1 ]; then
  hook_state="$(python3 - "$SETTINGS" "$BAILIWICK_ROOT" <<'PY'
import json, os, re, sys
settings, root = sys.argv[1], os.path.realpath(sys.argv[2])
try:
    d = json.load(open(settings))
except Exception:
    print("UNPARSEABLE"); sys.exit()
cmds = [h.get("command", "") for v in (d.get("hooks") or {}).values()
        for g in v for h in g.get("hooks", [])]
owned = re.compile(r'(\S+/hooks/(?:capture_session\.py|session_start\.sh|capture_backup\.sh|guardrails\.py))')
homes = set()
for c in cmds:
    for m in owned.findall(c):
        homes.add(os.path.realpath(os.path.dirname(m)))
if not homes:
    print("NONE")
else:
    foreign = sorted(h for h in homes if h != os.path.realpath(os.path.join(root, "hooks")))
    print(";".join(foreign) if foreign else "OK")
PY
)"
  case "$hook_state" in
    OK)          ok "hooks in ~/.claude/settings.json execute this clone" ;;
    NONE)        warn "no Bailiwick hooks in $SETTINGS — capture/guardrails not installed (bootstrap.sh --install-tools)" ;;
    UNPARSEABLE) warn "$SETTINGS is not valid JSON — cannot verify hook wiring" ;;
    *)           fail "hooks execute a DIFFERENT clone (${hook_state}) — this clone's code is not live and its /curate cannot see what those hooks capture; re-run bootstrap.sh --install-tools from here" ;;
  esac
fi

# ---- 2. Per-machine config ---------------------------------------------------------------------
# .bailiwick-sync.json is gitignored by design, so a fresh clone silently loses it — and with it
# the machine role, encrypted capture backup, and gh account pinning, all reverting to defaults.
CFG="$BAILIWICK_ROOT/.bailiwick-sync.json"
role="satellite"; machine=""; cb_enabled=""; cb_recipients=""
if [ ! -f "$CFG" ]; then
  warn ".bailiwick-sync.json missing — role defaults to 'satellite', capture backup is OFF, gh account unpinned (copy .bailiwick-sync.example.json and fill it in)"
elif [ "$HAVE_PY" -eq 1 ]; then
  cfg_line="$(python3 - "$CFG" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("UNPARSEABLE"); sys.exit()
cb = d.get("capture_backup") or {}
recips = cb.get("gpg_recipients") or []
print("|".join([
    d.get("role") or "satellite",
    d.get("machine") or "",
    "1" if cb.get("enabled") else "0",
    " ".join(r for r in recips if isinstance(r, str)),
]))
PY
)"
  if [ "$cfg_line" = "UNPARSEABLE" ]; then
    fail ".bailiwick-sync.json is not valid JSON — every consumer silently falls back to defaults"
  else
    role="${cfg_line%%|*}"; rest="${cfg_line#*|}"
    machine="${rest%%|*}"; rest="${rest#*|}"
    cb_enabled="${rest%%|*}"; cb_recipients="${rest#*|}"
    ok ".bailiwick-sync.json present (role: ${role}${machine:+, machine: $machine})"
  fi
else
  role="$(grep -oE '"role"[[:space:]]*:[[:space:]]*"[^"]+"' "$CFG" 2>/dev/null | head -1 | sed -E 's/.*"([^"]+)"$/\1/')"
  role="${role:-satellite}"
  ok ".bailiwick-sync.json present (role: ${role}; full validation needs python3)"
fi
# Fallback MUST match hooks/sync_knowledge.sh exactly (full `hostname`, not -s) — a divergent
# derivation makes the stranding check look at a branch the sync script never pushes.
[ -n "$machine" ] || machine="$(hostname 2>/dev/null || echo unknown)"
machine="$(printf '%s' "$machine" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9._-')"

# ---- 3. Capture backup keys --------------------------------------------------------------------
# enabled + no public key  => every encrypt (so every off-machine push) fails: captures pile up
#                             locally with no durable copy, exactly what the feature exists to stop.
# central + no secret key  => the pool can be filled but never drained: no machine can decrypt,
#                             so nothing in the holding repo is ever curated.
if [ "$cb_enabled" = "1" ]; then
  if ! command -v gpg >/dev/null 2>&1; then
    fail "capture_backup enabled but gpg is not installed — captures cannot be encrypted or pushed"
  elif [ -z "$cb_recipients" ]; then
    fail "capture_backup enabled but gpg_recipients is empty — nothing to encrypt to"
  else
    for fpr in $cb_recipients; do
      # Real encrypt probe, with the SAME flags capture_backup.sh uses — presence alone lies:
      # --list-keys succeeds for expired, revoked, and sign-only keys, every one of which makes
      # the push fail while doctor stays green. --trust-model always is load-bearing: a freshly
      # imported recipient key has [unknown] validity (the normal satellite state) and gpg would
      # refuse without it — a false alarm the hook itself never raises.
      if printf 'x' | gpg --batch --yes --no-tty --trust-model always \
           --encrypt -r "$fpr" -o /dev/null 2>/dev/null; then
        ok "gpg encrypt probe OK for recipient $fpr"
      elif gpg --list-keys "$fpr" >/dev/null 2>&1; then
        fail "gpg key for $fpr is present but UNUSABLE for encryption (expired, revoked, or no encryption subkey) — capture backup pushes will fail (re-key or extend it)"
      else
        fail "gpg public key MISSING for recipient $fpr — capture backup pushes will fail (gpg --import it)"
      fi
      if [ "$role" = "central" ]; then
        if gpg --list-secret-keys "$fpr" >/dev/null 2>&1; then
          ok "gpg SECRET key present for $fpr — central can decrypt the capture pool"
        else
          fail "role is 'central' but the gpg SECRET key for $fpr is absent — NO machine can decrypt the capture pool; restore the key here or re-key the fleet"
        fi
      fi
    done
    [ "$role" = "satellite" ] && ok "satellite is encrypt-only (secret key intentionally absent here)"
  fi
fi

# Refresh origin/main once, up front — the telemetry and sync-state checks below diff against it,
# and a stale (or absent) ref turns them into false positives/negatives.
FETCH_OK=0
git fetch origin main --quiet 2>/dev/null && FETCH_OK=1

# ---- 4. Telemetry ownership --------------------------------------------------------------------
# .telemetry.json is central-owned (append-heavy, conflict-prone). A satellite delta rides the next
# sync PR and collides with central's reconcile — central seeds rows for satellite files on merge.
if [ "$role" = "satellite" ] && [ -f ".telemetry.json" ]; then
  if git rev-parse -q --verify origin/main >/dev/null 2>&1; then
    if [ -n "$(git status --porcelain -- .telemetry.json 2>/dev/null)" ] \
       || ! git diff --quiet origin/main...HEAD -- .telemetry.json 2>/dev/null; then
      fail "satellite has local .telemetry.json changes — telemetry is central-owned; drop them before syncing (central seeds rows on merge)"
    else
      ok "no satellite telemetry delta (.telemetry.json untouched)"
    fi
  else
    warn "no origin/main ref locally — telemetry ownership check skipped"
  fi
fi

# ---- 5. gh account reachability ----------------------------------------------------------------
# Bare `gh` acts as the globally ACTIVE account; on multi-account machines that account may not
# even see this repo, so PR creation 404s while git pushes (riding the SSH alias) succeed.
# Resolved once here; the sync-state checks below reuse it.
HAVE_GH=0; repo_args=""
. "$BAILIWICK_ROOT/hooks/gh_account.sh" 2>/dev/null || true
if ! command -v gh >/dev/null 2>&1; then
  warn "gh not installed — satellite PRs must be opened manually"
elif ! command -v bw_resolve_gh_account >/dev/null 2>&1; then
  warn "hooks/gh_account.sh missing or unsourceable — gh runs as the globally ACTIVE account (the multi-account 404 risk this check exists for)"
else
  bw_resolve_gh_account "$BAILIWICK_ROOT"
  if [ -n "${BW_GH_REPO:-}" ]; then
    repo_args="--repo ${BW_GH_HOST}/${BW_GH_REPO}"
    if bw_gh api --hostname "${BW_GH_HOST:-github.com}" "repos/${BW_GH_REPO}" >/dev/null 2>&1; then
      HAVE_GH=1
      ok "gh can reach ${BW_GH_REPO} as '${BW_GH_USER:-<active account>}'${BW_GH_DECIDED:+ (${BW_GH_DECIDED})}"
    else
      fail "no usable gh account can read ${BW_GH_REPO} on ${BW_GH_HOST:-github.com} — PR creation will fail; 'gh auth login' for the right account or pin it in .bailiwick-sync.json (github_account / github_account_map)"
    fi
    [ -n "${BW_GH_WARN:-}" ] && warn "gh: ${BW_GH_WARN}"
  else
    warn "could not derive owner/repo from the 'origin' remote — gh reachability unknown (PR calls would run without --repo)"
  fi
fi

# ---- 6. Outbound sync state --------------------------------------------------------------------
# The stranding check: a sync/<machine> branch ahead of origin/main with no open PR means curated
# knowledge is durably pushed yet unreachable — every other machine fast-forwards from origin/main
# and will never see it, and nothing about that state makes a sound on its own.
# check_parked <branch>: is the parked branch merged / PR'd / stranded?
check_parked() {
  _pb="$1"
  git fetch origin "+refs/heads/${_pb}:refs/remotes/origin/${_pb}" --quiet 2>/dev/null || return 0
  _pb_ahead="$(git rev-list --count "origin/main..origin/${_pb}" 2>/dev/null || echo 0)"
  if [ "$_pb_ahead" -eq 0 ]; then
    ok "origin/${_pb} fully merged into origin/main"
    return 0
  fi
  _pb_oldest="$(git log --format=%ct --reverse "origin/main..origin/${_pb}" 2>/dev/null | head -1)"
  _pb_days=""
  [ -n "$_pb_oldest" ] && _pb_days=$(( ( $(date +%s) - _pb_oldest ) / 86400 ))
  if [ "$HAVE_GH" -eq 1 ]; then
    # shellcheck disable=SC2086  # repo_args intentionally word-split; owner/repo has no spaces
    _pb_pr="$(bw_gh pr list $repo_args --head "$_pb" --state open --json number --jq '.[0].number // empty' 2>/dev/null || true)"
    if [ -n "$_pb_pr" ]; then
      ok "origin/${_pb} is $_pb_ahead commit(s) ahead with PR #${_pb_pr} open (waiting on central merge${_pb_days:+; oldest commit ${_pb_days}d old})"
    else
      fail "origin/${_pb} is $_pb_ahead commit(s) ahead of origin/main with NO open PR${_pb_days:+ (oldest commit ${_pb_days}d old)} — knowledge is stranded; open one: gh pr create ${repo_args:+$repo_args }--base main --head ${_pb}"
    fi
  else
    warn "origin/${_pb} is $_pb_ahead commit(s) ahead of origin/main${_pb_days:+ (oldest commit ${_pb_days}d old)} — could not verify a PR exists via gh; check manually"
  fi
}

if [ "$FETCH_OK" -eq 1 ]; then
  if [ "$role" = "central" ]; then
    ahead="$(git rev-list --count origin/main..HEAD 2>/dev/null || echo 0)"
    if [ "$ahead" -gt 0 ]; then
      warn "central is $ahead commit(s) ahead of origin/main — run hooks/sync_knowledge.sh to publish"
    else
      ok "central has nothing unpublished"
    fi
    # Central is the merge authority, so it sweeps EVERY parked sync/* branch — a satellite can
    # only check its own, and a stranded branch from a machine that never runs doctor would
    # otherwise stay invisible to the one machine that could merge it.
    found=0
    for rb in $(git ls-remote --heads origin 'sync/*' 2>/dev/null | awk '{print $2}' | sed 's|^refs/heads/||'); do
      found=1
      check_parked "$rb"
    done
    [ "$found" -eq 0 ] && ok "no sync/* branches parked on origin"
  else
    if git ls-remote --exit-code --heads origin "sync/${machine}" >/dev/null 2>&1; then
      check_parked "sync/${machine}"
    else
      ok "no sync/${machine} branch on origin (nothing parked)"
    fi
  fi
else
  warn "cannot reach origin — sync-state checks skipped (offline?)"
fi

# ---- 7. Shadow allowlist -----------------------------------------------------------------------
ALLOW="${BAILIWICK_HOME:-$HOME/.bailiwick}/allowlist"
if [ -f "$ALLOW" ]; then
  # grep -c prints its count even on exit 1 (zero matches) — no `|| echo 0`, it would double up.
  n="$(grep -cvE '^[[:space:]]*(#|$)' "$ALLOW" 2>/dev/null)" || :
  ok "shadow allowlist present ($n repo(s)) — $ALLOW"
else
  ok "no shadow allowlist (fine unless you expect shadow-mode repos; bootstrap.sh <repo> creates it)"
fi

echo
if [ "$ERR" -gt 0 ]; then
  echo "doctor: $ERR broken, $WARN degraded — fix the ✗ items before trusting capture/sync."
  exit 1
fi
echo "doctor: healthy ($WARN warning(s))."
