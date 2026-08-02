#!/usr/bin/env bash
# Contract tests for hooks/capture_backup.sh — the ciphertext durability path.
#
# The invariant under test, end to end: A CAPTURE IS NEVER LOST. The source file in
# .bailiwick-outputs/raw/ survives every failure mode (unusable key, unreachable remote,
# missing secret key at decrypt time) and survives SUCCESS too — only /curate's explicit
# purge removes anything, and that removes the remote blob, never the source. Every failure
# leaves a health-log event (no silent death) and the data stays replayable.
set -u
. "$(dirname "$0")/lib.sh"
t_sandbox

SAT_GNUPG="$T_SANDBOX/gnupg-sat"
FPR="$(t_gen_gpg_key "$SAT_GNUPG" backup-test-key)"
[ -n "$FPR" ] || { echo "SKIP: could not generate gpg key"; exit 0; }
export GNUPGHOME="$SAT_GNUPG"

INST="$T_SANDBOX/inst"; t_make_instance "$INST"
git init -q --bare "$T_SANDBOX/holding.git"

write_cfg() {  # <ack> <recipient> [repo] [throttle-minutes]
  cat > "$INST/.bailiwick-sync.json" <<EOF
{ "role": "satellite", "machine": "testsat",
  "capture_backup": { "enabled": true, "confidentiality_ack": $1,
    "repo": "${3:-file://$T_SANDBOX/holding.git}", "gpg_recipients": ["$2"],
    "branch": "capture/testsat", "throttle_minutes": ${4:-0} } }
EOF
}

PROJ="$T_SANDBOX/proj"
mkdir -p "$PROJ/.bailiwick-outputs/raw"
echo "SECRET-PAYLOAD-ALPHA" > "$PROJ/.bailiwick-outputs/raw/s1.jsonl"
push() { echo '{"hook_event_name":"SessionEnd"}' | CLAUDE_PROJECT_DIR="$PROJ" bash "$INST/hooks/capture_backup.sh" push; }
HEALTH="$BAILIWICK_HOME/health/testsat.jsonl"
MIRROR="$XDG_CACHE_HOME/bailiwick/capture-mirror"

echo "== refuses without confidentiality_ack, source intact"
write_cfg false "$FPR"
out="$(push 2>&1)"; rc=$?
assert_exit "ack=false exits 0 (hook must not fail)" 0 "$rc"
assert_contains "ack=false refuses loudly" "confidentiality_ack" "$out"
assert_eq "no blob pushed without ack" "" "$(git -C "$T_SANDBOX/holding.git" branch --list 2>/dev/null)"
assert_file "source survives refusal" "$PROJ/.bailiwick-outputs/raw/s1.jsonl"

echo "== happy path: pushes ciphertext, source NOT deleted"
write_cfg true "$FPR"
push >/dev/null 2>&1
assert_exit "push exits 0" 0 "$?"
blob="$(git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat 2>/dev/null | grep 's1\.jsonl\.gpg$' | head -1)"
assert_contains "ciphertext blob on the capture branch" "s1.jsonl.gpg" "${blob:-<none>}"
assert_file "SOURCE SURVIVES successful push (only /curate purges)" "$PROJ/.bailiwick-outputs/raw/s1.jsonl"
git -C "$T_SANDBOX/holding.git" show "capture/testsat:$blob" > "$T_SANDBOX/blob.bin" 2>/dev/null
if LC_ALL=C grep -q "SECRET-PAYLOAD-ALPHA" "$T_SANDBOX/blob.bin" 2>/dev/null; then
  t_fail "blob is ciphertext, not plaintext"
else
  t_ok "blob is ciphertext, not plaintext"
fi
assert_contains "health logs push ok" "push ok" "$HEALTH"

echo "== idempotency: unchanged capture is not re-encrypted"
# Commit count may legitimately grow (the health shard grows every run) — the invariant is that
# the CAPTURE blob is not re-encrypted, i.e. its git object id is stable across pushes.
h1="$(git -C "$T_SANDBOX/holding.git" rev-parse "capture/testsat:$blob")"
push >/dev/null 2>&1
h2="$(git -C "$T_SANDBOX/holding.git" rev-parse "capture/testsat:$blob")"
assert_eq "sha sidecar skips unchanged file (blob object id stable)" "$h1" "$h2"

echo "== unusable recipient key: loud failure, source intact, retried after fix"
echo "SECRET-PAYLOAD-BRAVO" > "$PROJ/.bailiwick-outputs/raw/s2.jsonl"
write_cfg true "DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEF"
out="$(push 2>&1)"; rc=$?
assert_exit "encrypt failure exits 0 (hook fail-open)" 0 "$rc"
assert_contains "encrypt failure is loud on stderr" "encrypt FAILED" "$out"
assert_contains "encrypt failure logs a health error" "encrypt FAILED" "$HEALTH"
assert_file "source survives encrypt failure" "$PROJ/.bailiwick-outputs/raw/s2.jsonl"
assert_no_file "no sha sidecar on failure (so the file is retried)" "$MIRROR/testsat"/*/s2.jsonl.gpg.sha256
write_cfg true "$FPR"   # fix the key -> the same file must now make it out
push >/dev/null 2>&1
assert_contains "capture retried and pushed after key fix" "s2.jsonl.gpg" \
  "$(git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat)"

echo "== unreachable remote: ciphertext survives in local mirror, health error"
echo "SECRET-PAYLOAD-CHARLIE" > "$PROJ/.bailiwick-outputs/raw/s3.jsonl"
export XDG_CACHE_HOME="$T_SANDBOX/cache2"   # fresh mirror so the clone itself fails
write_cfg true "$FPR" "file://$T_SANDBOX/missing.git"
out="$(push 2>&1)"; rc=$?
assert_exit "push failure exits 0 (hook fail-open)" 0 "$rc"
assert_contains "push failure logs a health error" "push failed" "$HEALTH"
mblob="$(find "$XDG_CACHE_HOME/bailiwick/capture-mirror" -name 's3.jsonl.gpg' 2>/dev/null | head -1)"
assert_eq "ciphertext preserved in local mirror for replay" "s3.jsonl.gpg" "$(basename "${mblob:-none}")"
assert_file "source survives push failure" "$PROJ/.bailiwick-outputs/raw/s3.jsonl"
export XDG_CACHE_HOME="$T_SANDBOX/cache"
write_cfg true "$FPR"

echo "== throttle: Stop events inside the window are no-ops; SessionEnd bypasses it"
write_cfg true "$FPR" "" 60
rm -f "$PROJ/.bailiwick-outputs/.backup-last"
echo "SECRET-PAYLOAD-DELTA" > "$PROJ/.bailiwick-outputs/raw/s4.jsonl"
echo '{"hook_event_name":"Stop"}' | CLAUDE_PROJECT_DIR="$PROJ" bash "$INST/hooks/capture_backup.sh" push >/dev/null 2>&1
assert_contains "first Stop push goes through (no stamp yet)" "s4.jsonl.gpg" \
  "$(git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat)"
echo "SECRET-PAYLOAD-ECHO" > "$PROJ/.bailiwick-outputs/raw/s5.jsonl"
echo '{"hook_event_name":"Stop"}' | CLAUDE_PROJECT_DIR="$PROJ" bash "$INST/hooks/capture_backup.sh" push >/dev/null 2>&1
assert_not_contains "second Stop inside the 60-min window is a no-op" "s5.jsonl.gpg" \
  "$(git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat)"
assert_file "throttled capture still safe at source" "$PROJ/.bailiwick-outputs/raw/s5.jsonl"
echo '{"hook_event_name":"SessionEnd"}' | CLAUDE_PROJECT_DIR="$PROJ" bash "$INST/hooks/capture_backup.sh" push >/dev/null 2>&1
assert_contains "SessionEnd bypasses the throttle" "s5.jsonl.gpg" \
  "$(git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat)"
write_cfg true "$FPR"

echo "== key mismatch at decrypt: blob retained, recoverable once the right key arrives"
OTHER_GNUPG="$T_SANDBOX/gnupg-other"
OFPR="$(t_gen_gpg_key "$OTHER_GNUPG" wrong-key)"
out="$(GNUPGHOME="$OTHER_GNUPG" bash "$INST/hooks/capture_backup.sh" pull "$T_SANDBOX/inbox-wrong" 2>&1)"
assert_contains "wrong-key decrypt reports failure" "failed" "$out"
assert_no_file "no plaintext produced with the wrong key" "$T_SANDBOX/inbox-wrong/testsat"/*/s1.jsonl
rblob="$(find "$XDG_CACHE_HOME/bailiwick/capture-mirror" -name 's1.jsonl.gpg' 2>/dev/null | head -1)"
assert_eq "blob RETAINED in mirror after failed decrypt (replayable)" "s1.jsonl.gpg" "$(basename "${rblob:-none}")"
bash "$INST/hooks/capture_backup.sh" pull "$T_SANDBOX/inbox" >/dev/null 2>&1
rec="$(find "$T_SANDBOX/inbox" -name 's1.jsonl' | head -1)"
assert_eq "round-trip recovery: decrypted content equals original" "SECRET-PAYLOAD-ALPHA" "$(cat "${rec:-/dev/null}" 2>/dev/null)"

echo "== purge is surgical: named blob only, source untouched"
rel="$(git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat | grep 's1\.jsonl\.gpg$' | head -1)"
bash "$INST/hooks/capture_backup.sh" purge "$rel" >/dev/null 2>&1
after="$(git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat)"
assert_not_contains "purged blob removed from branch" "s1.jsonl.gpg" "$after"
assert_contains "other blobs survive the purge" "s2.jsonl.gpg" "$after"
assert_file "purge NEVER touches the source capture" "$PROJ/.bailiwick-outputs/raw/s1.jsonl"

t_summary
