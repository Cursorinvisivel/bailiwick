#!/usr/bin/env bash
# Contract tests for scripts/doctor.sh — the invariants must fail LOUDLY when false.
# Each case drives one check to its broken state and asserts the ✗ and the exit code.
set -u
. "$(dirname "$0")/lib.sh"
t_sandbox

export GH_STUB_ACCOUNTS="alice"
export GH_STUB_CANREAD="tok_alice"

INST="$T_SANDBOX/inst"; t_make_instance "$INST"
SETTINGS="$T_SANDBOX/claude-settings.json"

own_settings() {  # settings whose hooks run from THIS instance
  cat > "$SETTINGS" <<EOF
{ "hooks": { "Stop": [ { "hooks": [ { "type": "command", "command": "python3 $INST/hooks/capture_session.py" } ] } ] } }
EOF
}
doctor() { CLAUDE_SETTINGS="$SETTINGS" bash "$INST/scripts/doctor.sh" 2>&1; }

echo "== hooks executing a different clone is BROKEN (exit 1)"
mkdir -p "$T_SANDBOX/other-clone/hooks"; touch "$T_SANDBOX/other-clone/hooks/capture_session.py"
cat > "$SETTINGS" <<EOF
{ "hooks": { "Stop": [ { "hooks": [ { "type": "command", "command": "python3 $T_SANDBOX/other-clone/hooks/capture_session.py" } ] } ] } }
EOF
echo '{ "role": "satellite", "machine": "doctest" }' > "$INST/.bailiwick-sync.json"
out="$(doctor)"; rc=$?
assert_exit "foreign hooks -> exit 1" 1 "$rc"
assert_contains "names the foreign clone loudly" "DIFFERENT clone" "$out"

echo "== healthy baseline (own hooks, config present) exits 0"
own_settings
out="$(doctor)"; rc=$?
assert_exit "healthy -> exit 0" 0 "$rc"
assert_contains "hook wiring passes" "execute this clone" "$out"
assert_contains "config recognised" "role: satellite, machine: doctest" "$out"

echo "== missing per-machine config is only degraded (warn), not broken"
rm "$INST/.bailiwick-sync.json"
out="$(doctor)"; rc=$?
assert_exit "missing config still exits 0" 0 "$rc"
assert_contains "warns about the missing config" ".bailiwick-sync.json missing" "$out"

echo "== capture backup enabled with a missing recipient key is BROKEN"
cat > "$INST/.bailiwick-sync.json" <<'EOF'
{ "role": "satellite", "machine": "doctest",
  "capture_backup": { "enabled": true, "gpg_recipients": ["DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEF"] } }
EOF
GNUPG="$T_SANDBOX/gnupg"; mkdir -p "$GNUPG" && chmod 700 "$GNUPG"
out="$(GNUPGHOME="$GNUPG" doctor)"; rc=$?
assert_exit "bad recipient key -> exit 1" 1 "$rc"
assert_contains "the failure names capture backup" "capture backup pushes will fail" "$out"

echo "== a present but sign-only recipient key is BROKEN (the encrypt probe's quiet case)"
SGN="$T_SANDBOX/gnupg-signonly"; mkdir -p "$SGN" && chmod 700 "$SGN"
# usage 'sign' is what matters: a primary with no [E] subkey, which --list-keys still reports
# as a perfectly present key. Some gpg builds can't generate this fixture non-interactively
# (observed on the macOS runner) — that's a SKIP with the reason shown, not a failure: the
# discriminating coverage still runs wherever the fixture generates (ubuntu CI).
gen_err="$(GNUPGHOME="$SGN" gpg --batch --passphrase '' --quick-generate-key doctor-signonly default sign never 2>&1 >/dev/null || true)"
SFPR="$(GNUPGHOME="$SGN" gpg --list-keys --with-colons 2>/dev/null | awk -F: '/^fpr/{print $10; exit}')"
if [ -n "$SFPR" ]; then
  cat > "$INST/.bailiwick-sync.json" <<EOC
{ "role": "satellite", "machine": "doctest",
  "capture_backup": { "enabled": true, "gpg_recipients": ["$SFPR"] } }
EOC
  out="$(GNUPGHOME="$SGN" doctor)"; rc=$?
  assert_exit "sign-only key -> exit 1" 1 "$rc"
  assert_contains "flagged UNUSABLE (present, cannot encrypt), not missing" "UNUSABLE" "$out"
else
  echo "  SKIP sign-only probe case — this gpg cannot generate the fixture: $(printf '%s' "$gen_err" | tail -1)"
fi
echo '{ "role": "satellite", "machine": "doctest" }' > "$INST/.bailiwick-sync.json"

echo "== satellite telemetry delta is BROKEN (telemetry is central-owned)"
echo '{ "role": "satellite", "machine": "doctest" }' > "$INST/.bailiwick-sync.json"
echo '{}' > "$INST/.telemetry.json"
git -C "$INST" add .telemetry.json && git -C "$INST" -c user.name=bw-test -c user.email=test@local commit -qm "seed telemetry"
git -C "$INST" push -q origin main
echo '{"drift": true}' > "$INST/.telemetry.json"
out="$(doctor)"; rc=$?
assert_exit "telemetry delta -> exit 1" 1 "$rc"
assert_contains "names central ownership" "central-owned" "$out"
git -C "$INST" checkout -q -- .telemetry.json

echo "== a parked sync branch with no open PR is BROKEN (the stranding check)"
git -C "$INST" checkout -q -b sync/doctest
echo "stranded" > "$INST/stranded.md"
# add ONLY the knowledge file — `add -A` would sweep the untracked .bailiwick-sync.json onto the
# branch and make it vanish from the worktree at checkout, silently changing the machine identity
git -C "$INST" add stranded.md && git -C "$INST" -c user.name=bw-test -c user.email=test@local commit -qm "knowledge: stranded"
git -C "$INST" push -q origin sync/doctest
git -C "$INST" checkout -q main
out="$(doctor)"; rc=$?
assert_exit "parked branch, no PR -> exit 1" 1 "$rc"
assert_contains "says the knowledge is stranded" "stranded" "$out"

echo "== the same parked branch WITH an open PR is fine (waiting on central)"
export GH_STUB_PR_LIST="9"
out="$(doctor)"; rc=$?
unset GH_STUB_PR_LIST
assert_exit "parked branch with PR -> exit 0" 0 "$rc"
assert_contains "reports it as waiting on the merge" "PR #9 open" "$out"

echo "== central sweeps OTHER machines' parked branches too"
cat > "$INST/.bailiwick-sync.json" <<'EOF'
{ "role": "central", "machine": "doccentral" }
EOF
out="$(doctor)"; rc=$?
assert_exit "central + foreign parked branch, no PR -> exit 1" 1 "$rc"
assert_contains "central sees sync/doctest parked" "sync/doctest" "$out"

# ---- MCP server runners -------------------------------------------------------------------------
# A registered server whose runner is absent fails only at connect time, as a bare "ENOENT" that
# names the SERVER and not the missing binary — doctor has to name the binary or the check is moot.
# Back to a role/machine with nothing parked, so these cases assert on the MCP check alone.
cat > "$INST/.bailiwick-sync.json" <<'EOF'
{ "role": "satellite", "machine": "doccentral" }
EOF
MCPCFG="$T_SANDBOX/claude.json"
doctor_mcp() { CLAUDE_SETTINGS="$SETTINGS" CLAUDE_CONFIG="$MCPCFG" bash "$INST/scripts/doctor.sh" 2>&1; }

echo "== a registered MCP server whose runner is not on PATH is BROKEN"
cat > "$MCPCFG" <<'EOF'
{ "mcpServers": { "bailiwick-ghost": { "command": "bw-definitely-absent", "args": [] } } }
EOF
out="$(doctor_mcp)"; rc=$?
assert_exit "absent runner -> exit 1" 1 "$rc"
assert_contains "names the missing BINARY, not just the server" "bw-definitely-absent" "$out"
assert_contains "connects the symptom to the cause" "ENOENT" "$out"

echo "== the sh -c wrapper is unwrapped to the real binary (not reported as 'sh')"
cat > "$MCPCFG" <<'EOF'
{ "mcpServers": { "bailiwick-github": { "command": "sh",
  "args": ["-c", "TOKEN=x exec bw-absent-wrapped stdio"] } } }
EOF
out="$(doctor_mcp)"; rc=$?
assert_exit "wrapped absent binary -> exit 1" 1 "$rc"
assert_contains "unwraps past sh to the exec'd binary" "bw-absent-wrapped" "$out"

echo "== non-bailiwick servers are none of doctor's business"
cat > "$MCPCFG" <<'EOF'
{ "mcpServers": { "some-third-party": { "command": "bw-absent-foreign", "args": [] },
  "bailiwick-filesystem": { "command": "sh", "args": [] } } }
EOF
out="$(doctor_mcp)"; rc=$?
assert_exit "foreign broken server -> still exit 0" 0 "$rc"
assert_not_contains "does not police servers it does not own" "bw-absent-foreign" "$out"

echo "== an UNPINNED mcp-server-fetch is degraded (starts, then dies on import vs SDK 2.x)"
cat > "$MCPCFG" <<'EOF'
{ "mcpServers": { "bailiwick-fetch": { "command": "sh", "args": ["mcp-server-fetch"] } } }
EOF
out="$(doctor_mcp)"; rc=$?
assert_exit "unpinned SDK is a warning, not broken -> exit 0" 0 "$rc"
assert_contains "flags the missing SDK pin" "does not pin the mcp SDK" "$out"

echo "== the pinned form is clean"
cat > "$MCPCFG" <<'EOF'
{ "mcpServers": { "bailiwick-fetch": { "command": "sh",
  "args": ["--with", "mcp<2", "mcp-server-fetch"] } } }
EOF
out="$(doctor_mcp)"; rc=$?
assert_exit "pinned + runner present -> exit 0" 0 "$rc"
assert_contains "reports the runner as present" "bailiwick-fetch runner on PATH" "$out"
assert_not_contains "no pin warning when pinned" "does not pin the mcp SDK" "$out"

t_summary
