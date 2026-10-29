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
owned = re.compile(r'(\S+/hooks/(?:capture_session\.py|session_start\.sh|capture_backup\.sh|guardrails\.py|fetch_guard\.py))')
scripts = [m for c in cmds for m in owned.findall(c)]
here = os.path.realpath(os.path.join(root, "hooks"))
# A hook script that no longer exists makes python3 exit 2, which Claude Code treats as BLOCKING:
# every call of that tool (Bash, WebFetch) fails machine-wide until the hooks are reinstalled.
missing = sorted(set(m for m in scripts if not os.path.exists(m)))
homes = set(os.path.realpath(os.path.dirname(m)) for m in scripts)
if missing:
    print("MISSING " + ";".join(missing))
elif not homes:
    print("NONE")
else:
    foreign = sorted(h for h in homes if h != here)
    if foreign:
        print(";".join(foreign))
    # Added after the first hook generation: a machine installed before it has every other hook,
    # and the /curate WebFetch calls of the freshness agent then run without the fetch-time allowlist.
    elif not any(os.path.basename(m) == "fetch_guard.py" for m in scripts):
        print("OK-NOFETCH")
    else:
        print("OK")
PY
)"
  case "$hook_state" in
    OK)          ok "hooks in ~/.claude/settings.json execute this clone" ;;
    OK-NOFETCH)  ok "hooks in ~/.claude/settings.json execute this clone"
                 warn "freshness fetch guard hook not installed — re-run bootstrap.sh --install-tools to merge it" ;;
    NONE)        warn "no Bailiwick hooks in $SETTINGS — capture/guardrails not installed (bootstrap.sh --install-tools)" ;;
    UNPARSEABLE) warn "$SETTINGS is not valid JSON — cannot verify hook wiring" ;;
    MISSING\ *)  fail "hook scripts no longer exist (${hook_state#MISSING }) — Claude Code treats a missing hook script as a blocking hook error (for PreToolUse, every call of that tool fails); re-run bootstrap.sh --install-tools from this clone" ;;
    *)           fail "hooks execute a DIFFERENT clone (${hook_state}) — this clone's code is not live and its /curate cannot see what those hooks capture; re-run bootstrap.sh --install-tools from here" ;;
  esac
fi

# ---- 1b. Freshness fetch guard canary: both layers must actually refuse an off-registry URL ------
# Presence is not enough: a guard that cannot import its policy denies everything (fail-closed) and
# one that cannot see its caller allows everything. Each installed layer gets a synthetic call and
# must deny an off-registry URL AND allow a registry URL. This proves the installed commands and
# the policy; it cannot prove that Claude Code still sends `agent_type` (scripts/smoke_fetch_guard.sh).
if [ "$HAVE_PY" -eq 1 ]; then
  canary="$(python3 - "$SETTINGS" "$BAILIWICK_ROOT" <<'PY'
import json, os, subprocess, sys, tempfile
OFF = "https://evil.test/doctor-canary"
AGENT = "bailiwick-cloud-research-freshness"
root = sys.argv[2]
try:  # a registry URL that must pass: the first discovery URL, so a registry edit cannot fake a fault
    ON = json.load(open(os.path.join(root, "skills/curate/references/gcp-sources.json")))["sources"][0]["discovery_urls"][0]
except Exception:
    ON = "https://docs.cloud.google.com/iam/docs/release-notes"
# Synthetic denials must not land in the real audit log: doctor writes nothing.
SCRATCH = tempfile.mkdtemp(prefix="bw-doctor-canary-")

def decide(argv, url, shell=False):
    payload = {"agent_type": AGENT, "tool_name": "WebFetch", "tool_input": {"url": url, "prompt": "x"}}
    try:
        r = subprocess.run(argv, shell=shell, input=json.dumps(payload), capture_output=True,
                           text=True, timeout=20, env=dict(os.environ, BAILIWICK_HOME=SCRATCH))
    except Exception as exc:
        return "error:" + type(exc).__name__
    if r.returncode == 2:
        return "blocked"  # Claude Code treats exit 2 as a deny
    if r.returncode != 0:
        return "rc%d" % r.returncode
    try:
        return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] if r.stdout.strip() else "allow"
    except Exception:
        return "garbled"

def verdict(label, run):
    off, on = run(OFF), run(ON)
    if off in ("deny", "blocked") and on == "allow":
        print("OK\t" + label)
    else:
        print("BAD\t%s (off-registry: %s, registry: %s)" % (label, off, on))

home = os.environ.get("BAILIWICK_HOME") or os.path.join(os.path.expanduser("~"), ".bailiwick")
launcher = os.path.join(home, "hooks", "fetch_guard.py")
if os.path.isfile(launcher):
    verdict("agent-scoped launcher " + launcher,
            lambda url: decide([sys.executable, "-I", launcher, "--scoped"], url))
else:
    print("NOLAUNCHER\t" + launcher)
try:
    groups = json.load(open(sys.argv[1])).get("hooks", {}).get("PreToolUse", [])
except Exception:
    groups = []
cmds = [h.get("command", "") for g in groups if g.get("matcher") == "WebFetch"
        for h in g.get("hooks", []) if "fetch_guard.py" in h.get("command", "")]
for cmd in cmds:
    verdict("global settings hook", lambda url, c=cmd: decide(c, url, shell=True))
import shutil
shutil.rmtree(SCRATCH, ignore_errors=True)
PY
)"
  while IFS="$(printf '\t')" read -r state detail; do
    case "$state" in
      OK)         ok "freshness fetch guard refuses off-registry URLs: $detail" ;;
      BAD)        fail "freshness fetch guard is not enforcing the registry: $detail — re-run bootstrap.sh --install-tools" ;;
      NOLAUNCHER) warn "freshness fetch launcher missing ($detail) — the freshness agent's fetches are all blocked until bootstrap.sh --install-tools" ;;
    esac
  done <<EOF
$canary
EOF
fi

# ---- 2. Per-machine config ---------------------------------------------------------------------
# .bailiwick-sync.json is gitignored by design, so a fresh clone silently loses it — and with it
# the machine role, encrypted capture backup, and gh account pinning, all reverting to defaults.
CFG="$BAILIWICK_ROOT/.bailiwick-sync.json"
role="satellite"; machine=""; cb_enabled=""; cb_branch=""; cb_recipients=""
if [ ! -f "$CFG" ]; then
  # The silent demotion: a reinstalled central comes back as a satellite, the fleet is left with no
  # merge authority, and every sync/* PR waits forever (see the stale-PR check in section 6).
  warn ".bailiwick-sync.json missing — role defaults to 'satellite', capture backup is OFF, gh account unpinned. If this machine is (or was, before a reinstall) your CENTRAL, restore it: scripts/bootstrap.sh --role central; otherwise scripts/bootstrap.sh --role satellite"
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
    cb.get("branch") or "",
    " ".join(r for r in recips if isinstance(r, str)),
]))
PY
)"
  if [ "$cfg_line" = "UNPARSEABLE" ]; then
    fail ".bailiwick-sync.json is not valid JSON — every consumer silently falls back to defaults"
  else
    role="${cfg_line%%|*}"; rest="${cfg_line#*|}"
    machine="${rest%%|*}"; rest="${rest#*|}"
    cb_enabled="${rest%%|*}"; rest="${rest#*|}"
    cb_branch="${rest%%|*}"; cb_recipients="${rest#*|}"
    ok ".bailiwick-sync.json present (role: ${role}${machine:+, machine: $machine})"
  fi
else
  role="$(grep -oE '"role"[[:space:]]*:[[:space:]]*"[^"]+"' "$CFG" 2>/dev/null | head -1 | sed -E 's/.*"([^"]+)"$/\1/')"
  role="${role:-satellite}"
  ok ".bailiwick-sync.json present (role: ${role}; full validation needs python3)"
fi
# Same derivation as hooks/sync_knowledge.sh — both call the shared bw_machine_token, so the
# stranding check always looks at the branch the sync script actually pushes.
. "$BAILIWICK_ROOT/hooks/config_common.sh" 2>/dev/null || true
if command -v bw_machine_token >/dev/null 2>&1; then
  machine="$(bw_machine_token "${machine:-}")"
else
  [ -n "$machine" ] || machine="$(hostname 2>/dev/null || echo unknown)"
  machine="$(printf '%s' "$machine" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9._-')"
fi

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
      elif gpg --list-secret-keys "$fpr" >/dev/null 2>&1; then
        # The decrypt key lives only on the curating machine — a satellite holding it is most
        # likely a central whose role was lost (reinstall, fresh clone).
        warn "role is 'satellite' but this machine holds the gpg SECRET key for $fpr — that key belongs on the curating (central) machine; if this IS your central, scripts/bootstrap.sh --role central"
      else
        ok "satellite is encrypt-only for $fpr (secret key intentionally absent here)"
      fi
    done
  fi
  # Local mirror health (read-only; compares against the last-fetched origin ref, no network).
  # A conflicted rebase left in the mirror kills every later push at its checkout, and a growing
  # unpushed backlog means pushes have been failing — both invisible until a Stop hook complains.
  CB_MIRROR="${XDG_CACHE_HOME:-$HOME/.cache}/bailiwick/capture-mirror"
  cb_branch="${cb_branch:-capture/$machine}"
  if [ -d "$CB_MIRROR/.git" ]; then
    if [ -d "$CB_MIRROR/.git/rebase-merge" ] || [ -d "$CB_MIRROR/.git/rebase-apply" ] || [ -f "$CB_MIRROR/.git/MERGE_HEAD" ]; then
      fail "capture mirror is wedged mid-rebase/merge ($CB_MIRROR) — backups stopped; the next push self-heals it, or now: git -C \"$CB_MIRROR\" rebase --abort"
    elif git -C "$CB_MIRROR" rev-parse -q --verify "refs/remotes/origin/$cb_branch" >/dev/null 2>&1; then
      unp="$(git -C "$CB_MIRROR" rev-list --count "origin/$cb_branch..$cb_branch" 2>/dev/null || echo 0)"
      if [ "$unp" -gt 3 ]; then
        fail "capture mirror has $unp unpushed commit(s) on $cb_branch — backup pushes are failing (ciphertext safe locally; see /metrics fleet view)"
      elif [ "$unp" -gt 0 ]; then
        warn "capture mirror has $unp unpushed commit(s) on $cb_branch — the next push should drain them"
      else
        ok "capture mirror in sync with origin/$cb_branch"
      fi
    fi
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
    repo_args="$(bw_gh_repo_args)"
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
# An open PR is not enough: one that CONFLICTS with main can never be merged as-is, so the knowledge
# is just as stranded as with no PR at all. And a mergeable PR that nobody merges for weeks usually
# means there is no central left to merge it (a lost .bailiwick-sync.json demotes it silently).
STALE_DAYS="${BW_DOCTOR_STALE_DAYS:-14}"
# check_parked <branch>: is the parked branch merged / PR'd / mergeable / stranded?
check_parked() {
  _pb="$1"
  git fetch origin "+refs/heads/${_pb}:refs/remotes/origin/${_pb}" --quiet 2>/dev/null || return 0
  _pb_ahead="$(git rev-list --count "origin/main..origin/${_pb}" 2>/dev/null || echo 0)"
  if [ "$_pb_ahead" -eq 0 ]; then
    ok "origin/${_pb} fully merged into origin/main"
    return 0
  fi
  _pb_behind="$(git rev-list --count "origin/${_pb}..origin/main" 2>/dev/null || echo 0)"
  _pb_oldest="$(git log --format=%ct --reverse "origin/main..origin/${_pb}" 2>/dev/null | head -1)"
  _pb_days=""
  [ -n "$_pb_oldest" ] && _pb_days=$(( ( $(date +%s) - _pb_oldest ) / 86400 ))
  if [ "$HAVE_GH" -eq 1 ]; then
    _pb_pr="$(bw_gh_open_pr "$_pb")"
    if [ -n "$_pb_pr" ]; then
      # shellcheck disable=SC2086  # intentional word-split of the --repo args
      _pb_merge="$(bw_gh pr view "$_pb_pr" $repo_args --json mergeable --jq '.mergeable' 2>/dev/null || true)"
      case "$_pb_merge" in
        CONFLICTING)
          fail "origin/${_pb} PR #${_pb_pr} is CONFLICTING with main (${_pb_behind} commit(s) behind${_pb_days:+; oldest commit ${_pb_days}d old}) — it cannot merge; on the machine that owns it: git fetch origin && git rebase origin/main ${_pb}, resolve, then git push --force-with-lease origin ${_pb} (the open PR updates itself)" ;;
        MERGEABLE)
          if [ -n "$_pb_days" ] && [ "$_pb_days" -ge "$STALE_DAYS" ]; then
            warn "origin/${_pb} PR #${_pb_pr} is mergeable but has waited ${_pb_days}d (${_pb_behind} behind main) — is there an active central to merge it? (a reinstalled central comes back as a satellite: scripts/bootstrap.sh --role central there)"
          else
            ok "origin/${_pb} is $_pb_ahead commit(s) ahead with PR #${_pb_pr} open and mergeable (waiting on central merge${_pb_days:+; oldest commit ${_pb_days}d old})"
          fi ;;
        *)
          # GitHub computes mergeability lazily — UNKNOWN right after a push is normal.
          warn "origin/${_pb} PR #${_pb_pr} is open but its mergeability is ${_pb_merge:-unknown} (GitHub computes it lazily — re-run shortly)${_pb_days:+; oldest commit ${_pb_days}d old}" ;;
      esac
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
  # Inbound (#37): SessionStart only fast-forwards a clone checked out on main. Being on
  # sync/<machine> is expected until central merges it (SessionStart then returns to main);
  # merged-but-still-there, or any other branch, means inbound knowledge has silently stalled.
  cur="$(git symbolic-ref --short -q HEAD || echo DETACHED)"
  cur_behind="$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)"
  case "$cur" in
    main) ok "framework clone is on main (SessionStart fast-forwards it)" ;;
    sync/*)
      if ! { command -v bw_sync_merged >/dev/null 2>&1 && bw_sync_merged "$BAILIWICK_ROOT"; }; then
        ok "framework clone is on ${cur} awaiting its PR merge — SessionStart returns it to main once merged"
      else
        warn "framework clone is still on ${cur}, already merged into origin/main (${cur_behind} behind) — inbound sync is stalled (uncommitted changes block the auto-switch); commit or stash, then: git checkout main && git merge --ff-only origin/main"
      fi ;;
    *) warn "framework clone is on '${cur}', not main (${cur_behind} behind origin/main) — SessionStart only fast-forwards main, so inbound knowledge is stalled: git checkout main && git merge --ff-only origin/main" ;;
  esac
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

# ---- 8. MCP server runners ---------------------------------------------------------------------
# bootstrap registers the bailiwick-* MCP servers by NAME; nothing verifies the runner exists. A
# missing one is invisible until a session tries to connect and reports a bare "ENOENT" naming the
# server but not the binary — the tools are simply absent, and the agent works on without them.
MCPCFG="${CLAUDE_CONFIG:-$HOME/.claude.json}"
if [ ! -f "$MCPCFG" ]; then
  warn "no $MCPCFG — cannot verify user-scope MCP server runners"
elif [ "$HAVE_PY" -eq 1 ]; then
  # command is the runner; for the `sh -c '… exec <bin> …'` wrapper the real binary is inside args.
  mcp_rows="$(python3 - "$MCPCFG" <<'PY'
import json, re, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("UNPARSEABLE"); sys.exit()
for name, s in sorted((d.get("mcpServers") or {}).items()):
    if not name.startswith("bailiwick-") or not isinstance(s, dict):
        continue
    cmd = s.get("command") or ""
    args = [a for a in (s.get("args") or []) if isinstance(a, str)]
    if cmd in ("sh", "bash", "/bin/sh", "/bin/bash"):
        m = re.search(r'\bexec\s+(\S+)', " ".join(args))
        if m:
            cmd = m.group(1)
    print("%s\t%s\t%s" % (name, cmd, " ".join(args)))
PY
)"
  if [ "$mcp_rows" = "UNPARSEABLE" ]; then
    warn "$MCPCFG is not valid JSON — cannot verify MCP server runners"
  elif [ -z "$mcp_rows" ]; then
    warn "no bailiwick-* MCP servers registered in $MCPCFG (run bootstrap.sh --install-tools)"
  else
    while IFS="$(printf '\t')" read -r m_name m_cmd m_args; do
      [ -n "$m_name" ] || continue
      if [ -z "$m_cmd" ]; then
        fail "$m_name has no command — it can never start; re-run bootstrap.sh --install-tools"
      elif command -v "$m_cmd" >/dev/null 2>&1; then
        ok "$m_name runner on PATH ($m_cmd)"
      else
        fail "$m_name runner '$m_cmd' NOT on PATH — the server fails at connect with 'ENOENT' and its tools are silently absent; re-run bootstrap.sh --install-tools (uvx: curl -LsSf https://astral.sh/uv/install.sh | sh)"
      fi
      # Upstream mcp-server-fetch is unpinned and breaks against mcp SDK 2.x (McpError renamed),
      # so it exits at import time — a start failure that looks nothing like a missing binary.
      case "$m_args" in
        *mcp-server-fetch*)
          case "$m_args" in
            *'mcp<2'*) : ;;
            *) warn "$m_name does not pin the mcp SDK — mcp-server-fetch fails on import against SDK 2.x; re-run bootstrap.sh --install-tools (it re-registers drifted definitions), or by hand: claude mcp remove --scope user $m_name && claude mcp add --scope user $m_name -- uvx --with 'mcp<2' mcp-server-fetch" ;;
          esac ;;
      esac
    done <<EOF
$mcp_rows
EOF
  fi
fi

echo
if [ "$ERR" -gt 0 ]; then
  echo "doctor: $ERR broken, $WARN degraded — fix the ✗ items before trusting capture/sync."
  exit 1
fi
echo "doctor: healthy ($WARN warning(s))."
