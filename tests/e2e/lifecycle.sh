#!/usr/bin/env bash
# E2E lifecycle: one satellite machine's life, fully sandboxed (no network, no secrets).
#
#   install hooks -> doctor healthy -> a session gets captured -> the capture gets an
#   encrypted off-machine copy -> curated knowledge syncs out on a PR branch -> the
#   ciphertext round-trips back on the curating side.
#
# This is the integration pass over the same components the tests/shell/ suites cover in
# isolation — the value here is that the OUTPUT of each stage is the INPUT of the next.
set -u
. "$(dirname "$0")/../shell/lib.sh"
t_sandbox

export GH_STUB_ACCOUNTS="alice"
export GH_STUB_CANREAD="tok_alice"

INST="$T_SANDBOX/inst"; t_make_instance "$INST"
SETTINGS="$HOME/.claude/settings.json"
GNUPG="$T_SANDBOX/gnupg"
FPR="$(t_gen_gpg_key "$GNUPG" e2e-key)"
[ -n "$FPR" ] || { echo "SKIP: could not generate gpg key"; exit 0; }
export GNUPGHOME="$GNUPG"
git init -q --bare "$T_SANDBOX/holding.git"

echo "== 1. hook install: fresh, then idempotent"
out="$(python3 "$INST/hooks/install_hooks.py" "$SETTINGS" "$INST/hooks/settings.template.json")"
assert_contains "first run installs" "INSTALLED" "$out"
assert_contains "installed commands point at THIS instance" "$INST/hooks/capture_session.py" "$SETTINGS"
out="$(python3 "$INST/hooks/install_hooks.py" "$SETTINGS" "$INST/hooks/settings.template.json")"
assert_contains "second run is idempotent" "PRESENT" "$out"

echo "== 2. doctor: healthy on the freshly wired machine"
cat > "$INST/.bailiwick-sync.json" <<EOF
{ "role": "satellite", "machine": "e2esat",
  "capture_backup": { "enabled": true, "confidentiality_ack": true,
    "repo": "file://$T_SANDBOX/holding.git", "gpg_recipients": ["$FPR"],
    "branch": "capture/e2esat", "throttle_minutes": 0 } }
EOF
out="$(CLAUDE_SETTINGS="$SETTINGS" bash "$INST/scripts/doctor.sh" 2>&1)"; rc=$?
assert_exit "doctor exits 0" 0 "$rc"
assert_contains "hook wiring healthy" "execute this clone" "$out"

echo "== 3. a substantive session in a wired project gets captured"
PROJ="$T_SANDBOX/proj"; mkdir -p "$PROJ"
printf 'wired: $BAILIWICK\n' > "$PROJ/CLAUDE.local.md"
TR="$T_SANDBOX/transcript.jsonl"
{ printf '%s\n' '{"message":{"content":[{"type":"tool_use","name":"Write","input":{"file_path":"main.tf"}}]}}'
  printf '%s\n' '{"message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"git commit -m done"}}]}}'; } > "$TR"
printf '{"hook_event_name":"SessionEnd","session_id":"e2e-sess","transcript_path":"%s","cwd":"%s"}' "$TR" "$PROJ" \
  | CLAUDE_PROJECT_DIR="$PROJ" python3 "$INST/hooks/capture_session.py"
assert_file "capture staged in the project dirty zone" "$PROJ/.bailiwick-outputs/raw/e2e-sess.jsonl"

echo "== 4. the capture gets a durable encrypted copy off-machine"
echo '{"hook_event_name":"SessionEnd"}' | CLAUDE_PROJECT_DIR="$PROJ" bash "$INST/hooks/capture_backup.sh" push >/dev/null 2>&1
assert_contains "ciphertext on the holding branch" "e2e-sess.jsonl.gpg" \
  "$(git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/e2esat 2>/dev/null)"
assert_file "source capture still present after backup" "$PROJ/.bailiwick-outputs/raw/e2e-sess.jsonl"

echo "== 5. curated knowledge syncs out on the machine branch, with a PR"
echo "distilled fact" > "$INST/topic-e2e.md"
git -C "$INST" add topic-e2e.md
git -C "$INST" -c user.name=bw-test -c user.email=test@local commit -qm "knowledge: e2e topic"
rm -f "$GH_STUB_LOG"
bash "$INST/hooks/sync_knowledge.sh" >/dev/null 2>&1
assert_exit "sync exits 0" 0 "$?"
assert_eq "knowledge parked on sync/e2esat at origin" \
  "$(git -C "$INST" rev-parse HEAD)" "$(git -C "$INST" ls-remote "file://$INST.origin.git" sync/e2esat | cut -f1)"
assert_contains "PR opened for the branch" "pr create" "$GH_STUB_LOG"

echo "== 6. doctor still healthy with the branch parked under an open PR"
out="$(GH_STUB_PR_LIST=1 CLAUDE_SETTINGS="$SETTINGS" bash "$INST/scripts/doctor.sh" 2>&1)"; rc=$?
assert_exit "doctor exits 0 (parked branch has its PR)" 0 "$rc"

echo "== 7. the curating side recovers the capture from ciphertext alone"
bash "$INST/hooks/capture_backup.sh" pull "$T_SANDBOX/inbox" >/dev/null 2>&1
rec="$(find "$T_SANDBOX/inbox" -name 'e2e-sess.jsonl' 2>/dev/null | head -1)"
if [ -n "$rec" ] && cmp -s "$rec" "$PROJ/.bailiwick-outputs/raw/e2e-sess.jsonl"; then
  t_ok "decrypted capture is byte-identical to the source"
else
  t_fail "decrypted capture missing or differs from source"
fi

t_summary
