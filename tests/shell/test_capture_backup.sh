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
# Every contract test below asserts on the remote right after a push, so SessionEnd runs in the
# foreground here. The detached SessionEnd path has its own section at the end (unsets it).
export BW_BACKUP_SYNC=1

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
assert_dir()    { if [ -d "$2" ]; then t_ok "$1"; else t_fail "$1 (missing dir $2)"; fi; }
assert_no_dir() { if [ -d "$2" ]; then t_fail "$1 (unexpected dir $2)"; else t_ok "$1"; fi; }
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

echo "== no TTY: GPG_TTY is never set to tty's 'not a tty' text, so the pull preflight still fires"
# stdin </dev/null: `tty` fails. The old `${GPG_TTY:-$(tty || true)}` stored "not a tty" and made
# the `[ -z GPG_TTY ]` preflight dead code. Test keys carry no passphrase, so none is cached.
out="$(env -u DISPLAY -u WAYLAND_DISPLAY -u GPG_TTY bash "$INST/hooks/capture_backup.sh" pull "$T_SANDBOX/inbox-notty" </dev/null 2>&1)"
assert_contains "no-TTY preflight names the fix" "cannot decrypt here" "$out"
assert_not_contains "no 'not a tty' leaks into the run" "not a tty" "$out"

echo "== purge is surgical: named blob only, source untouched"
rel="$(git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat | grep 's1\.jsonl\.gpg$' | head -1)"
bash "$INST/hooks/capture_backup.sh" purge "$rel" >/dev/null 2>&1
after="$(git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat)"
assert_not_contains "purged blob removed from branch" "s1.jsonl.gpg" "$after"
assert_contains "other blobs survive the purge" "s2.jsonl.gpg" "$after"
assert_file "purge NEVER touches the source capture" "$PROJ/.bailiwick-outputs/raw/s1.jsonl"

echo "== purged blob stays purged: an un-retired source must not resurrect it"
# The source capture s1 still sits in the repo's raw staging (retirement is manual/cross-repo);
# without the tombstone the next push re-encrypts it and undoes the purge. A fresh s6 in the
# same run proves the loop continues past the skip — purged old capture + new session on the
# same repo is exactly the production mix.
echo "SECRET-PAYLOAD-FOXTROT" > "$PROJ/.bailiwick-outputs/raw/s6.jsonl"
echo '{"hook_event_name":"SessionEnd"}' | CLAUDE_PROJECT_DIR="$PROJ" bash "$INST/hooks/capture_backup.sh" push >/dev/null 2>&1
assert_exit "mixed skip+encrypt push exits 0" 0 "$?"
after="$(git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat)"
assert_not_contains "purged blob NOT re-pushed while its source is un-retired" "s1.jsonl.gpg" "$after"
assert_contains "new capture in the same run still pushed" "s6.jsonl.gpg" "$after"
assert_contains "tombstone manifest lives on the branch" ".purged" "$after"
manifest="$(git -C "$T_SANDBOX/holding.git" show capture/testsat:.purged 2>/dev/null)"
assert_not_contains "manifest is de-identified (hashed entries, no repo-key)" "proj" "$manifest"
assert_file "source still untouched after the skipped push" "$PROJ/.bailiwick-outputs/raw/s1.jsonl"

echo "== cross-machine: pull and purge reach another machine's branch"
# Machine 2 (testsat2): own instance, own mirror cache, own project — pushes to its own branch.
INST2="$T_SANDBOX/inst2"; t_make_instance "$INST2"
cat > "$INST2/.bailiwick-sync.json" <<EOF
{ "role": "satellite", "machine": "testsat2",
  "capture_backup": { "enabled": true, "confidentiality_ack": true,
    "repo": "file://$T_SANDBOX/holding.git", "gpg_recipients": ["$FPR"],
    "branch": "capture/testsat2", "throttle_minutes": 0 } }
EOF
PROJ2="$T_SANDBOX/proj2"; mkdir -p "$PROJ2/.bailiwick-outputs/raw"
echo "SECRET-PAYLOAD-GOLF" > "$PROJ2/.bailiwick-outputs/raw/r1.jsonl"
push2() { echo '{"hook_event_name":"SessionEnd"}' | CLAUDE_PROJECT_DIR="$PROJ2" XDG_CACHE_HOME="$T_SANDBOX/cache-m2" bash "$INST2/hooks/capture_backup.sh" push; }
push2 >/dev/null 2>&1
rel2="$(git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat2 2>/dev/null | grep 'r1\.jsonl\.gpg$' | head -1)"
assert_contains "machine 2 pushed to its own branch" "testsat2/" "${rel2:-<none>}"
bash "$INST/hooks/capture_backup.sh" pull "$T_SANDBOX/inbox-x" >/dev/null 2>&1
xrec="$(find "$T_SANDBOX/inbox-x" -name 'r1.jsonl' | head -1)"
assert_eq "pull from machine 1 decrypts machine 2's blob" "SECRET-PAYLOAD-GOLF" "$(cat "${xrec:-/dev/null}" 2>/dev/null)"
bash "$INST/hooks/capture_backup.sh" purge "$rel2" >/dev/null 2>&1
after2="$(git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat2)"
assert_not_contains "cross-machine purge removes the blob from the OTHER machine's branch" "r1.jsonl.gpg" "$after2"
assert_contains "tombstone manifest on the other machine's branch" ".purged" "$after2"
assert_file "cross-machine purge NEVER touches machine 2's source" "$PROJ2/.bailiwick-outputs/raw/r1.jsonl"
# Machine 2's next push (stale mirror, un-retired source, fresh capture): the reject -> rebase ->
# push cycle must carry the new capture through WITHOUT resurrecting the remotely purged blob.
echo "SECRET-PAYLOAD-HOTEL" > "$PROJ2/.bailiwick-outputs/raw/r2.jsonl"
push2 >/dev/null 2>&1
after2="$(git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat2)"
assert_contains "machine 2's new capture still lands after the remote purge" "r2.jsonl.gpg" "$after2"
assert_not_contains "purged blob does NOT resurrect from machine 2's un-retired source" "r1.jsonl.gpg" "$after2"

echo "== remote purge vs an unpushed local rewrite of the same blob: rebase reconciles, never wedges"
# The production wedge: this mirror holds an unpushed commit that rewrote a blob (resumed session,
# earlier push failed) while /curate on another machine purged that blob on origin. The reject ->
# rebase replay is a modify/delete conflict, which no -X strategy resolves; left in progress it
# broke every later Stop hook at ensure_mirror's checkout.
purge_from_m2() { XDG_CACHE_HOME="$T_SANDBOX/cache-m2" bash "$INST2/hooks/capture_backup.sh" purge "$1" >/dev/null 2>&1; }
echo "SECRET-PAYLOAD-INDIA" > "$PROJ/.bailiwick-outputs/raw/s7.jsonl"
push >/dev/null 2>&1
rel7="$(git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat | grep 's7\.jsonl\.gpg$' | head -1)"
assert_contains "s7 landed before the race" "s7.jsonl.gpg" "${rel7:-<none>}"
echo "rewritten-ciphertext" >> "$MIRROR/$rel7"
git -C "$MIRROR" -c user.name=t -c user.email=t@t -c commit.gpgsign=false commit -q -am "capture: unpushed rewrite"
purge_from_m2 "$rel7"
echo "SECRET-PAYLOAD-JULIET" > "$PROJ/.bailiwick-outputs/raw/s8.jsonl"
out="$(push 2>&1)"; rc=$?
assert_exit "push across the modify/delete conflict exits 0" 0 "$rc"
after="$(git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat)"
assert_contains "new capture lands despite the conflict" "s8.jsonl.gpg" "$after"
assert_not_contains "deletion wins: purged blob not resurrected by the replayed rewrite" "s7.jsonl.gpg" "$after"
assert_no_dir "no conflicted rebase left in the mirror" "$MIRROR/.git/rebase-merge"
assert_no_file "purged blob gone from the mirror worktree too" "$MIRROR/$rel7"

echo "== a mirror wedged mid-rebase by an older run self-heals on the next push"
# Isolate from the section above: a clean mirror at origin, so only the wedge built here is in play.
git -C "$MIRROR" rebase --abort >/dev/null 2>&1 || true
git -C "$MIRROR" fetch -q origin "+refs/heads/capture/testsat:refs/remotes/origin/capture/testsat"
git -C "$MIRROR" reset -q --hard origin/capture/testsat
echo "SECRET-PAYLOAD-KILO" > "$PROJ/.bailiwick-outputs/raw/s9.jsonl"
push >/dev/null 2>&1
rel9="$(git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat | grep 's9\.jsonl\.gpg$' | head -1)"
echo "rewritten-ciphertext" >> "$MIRROR/$rel9"
git -C "$MIRROR" -c user.name=t -c user.email=t@t -c commit.gpgsign=false commit -q -am "capture: unpushed rewrite"
purge_from_m2 "$rel9"
git -C "$MIRROR" fetch -q origin "+refs/heads/capture/testsat:refs/remotes/origin/capture/testsat"
git -C "$MIRROR" -c user.name=t -c user.email=t@t -c commit.gpgsign=false rebase -q origin/capture/testsat >/dev/null 2>&1
assert_dir "precondition: mirror is wedged mid-rebase" "$MIRROR/.git/rebase-merge"
echo "SECRET-PAYLOAD-LIMA" > "$PROJ/.bailiwick-outputs/raw/s10.jsonl"
out="$(push 2>&1)"; rc=$?
assert_exit "push on a wedged mirror exits 0" 0 "$rc"
assert_not_contains "no 'resolve your current index' hook error" "resolve your current index" "$out"
after="$(git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat)"
assert_contains "new capture lands after self-heal" "s10.jsonl.gpg" "$after"
assert_not_contains "purged blob stays purged after self-heal" "s9.jsonl.gpg" "$after"
assert_no_dir "wedge cleared" "$MIRROR/.git/rebase-merge"
assert_contains "self-heal logs a health warning" "conflicted rebase" "$HEALTH"

echo "== SessionEnd detaches: hook returns fast, the push still lands"
# Claude Code bounds ALL SessionEnd hooks to ~1.5 s on quit; fetch+gpg+push can't fit, so the
# hook must hand off to a detached child and return immediately.
wait_for_blob() {  # <name> : poll the remote up to 30 s
  local i=0
  while [ "$i" -lt 60 ]; do
    git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat 2>/dev/null | grep -q "$1" && return 0
    sleep 0.5; i=$((i + 1))
  done
  return 1
}
# Portable clocks/timestamps: BSD date has no %N, BSD touch has no relative -d, macOS has no timeout.
now_ms() { python3 -c 'import time; print(int(time.time() * 1000))'; }
age_minutes() { python3 -c 'import os, sys, time; t = time.time() - 60 * int(sys.argv[2]); os.utime(sys.argv[1], (t, t))' "$1" "$2"; }
echo "SECRET-PAYLOAD-MIKE" > "$PROJ/.bailiwick-outputs/raw/s11.jsonl"
t0=$(now_ms)
echo '{"hook_event_name":"SessionEnd"}' | env -u BW_BACKUP_SYNC BW_BACKUP_SETTLE_S=0 \
  CLAUDE_PROJECT_DIR="$PROJ" bash "$INST/hooks/capture_backup.sh" push >/dev/null 2>&1
rc=$?; ms=$(( $(now_ms) - t0 ))
assert_exit "detached SessionEnd exits 0" 0 "$rc"
if [ "$ms" -lt 1000 ]; then t_ok "detached SessionEnd returns in < 1000 ms (${ms} ms)"; else t_fail "detached SessionEnd took ${ms} ms (budget 1500 ms)"; fi
if wait_for_blob 's11\.jsonl\.gpg$'; then t_ok "detached child still pushes the capture"; else t_fail "detached child never pushed s11"; fi

echo "== SessionEnd releases the hook's stdout/stderr (no inherited pipe)"
# A child that keeps the pipe open makes the harness wait for it — the same timeout again.
echo "SECRET-PAYLOAD-NOVEMBER" > "$PROJ/.bailiwick-outputs/raw/s12.jsonl"
# The child sleeps 5 s before pushing, so a reader still blocked after 3 s means the pipe is held.
( echo '{"hook_event_name":"SessionEnd"}' | env -u BW_BACKUP_SYNC BW_BACKUP_SETTLE_S=5 \
    CLAUDE_PROJECT_DIR="$PROJ" bash "$INST/hooks/capture_backup.sh" push 2>&1 | cat >/dev/null ) &
rpid=$!; i=0
while kill -0 "$rpid" 2>/dev/null && [ "$i" -lt 30 ]; do sleep 0.1; i=$((i + 1)); done
if kill -0 "$rpid" 2>/dev/null; then
  t_fail "hook output closes before the child finishes (reader still blocked after 3 s)"
  kill "$rpid" 2>/dev/null || true
else
  t_ok "hook output closes before the child finishes"
fi
wait "$rpid" 2>/dev/null || true
wait_for_blob 's12\.jsonl\.gpg$' || true
# Let any child finish before the lock tests below (it holds the mirror lock while it runs).
i=0; while [ -d "$MIRROR.lock" ] && [ "$i" -lt 60 ]; do sleep 0.5; i=$((i + 1)); done

stop_push() { echo '{"hook_event_name":"Stop"}' | CLAUDE_PROJECT_DIR="$PROJ" bash "$INST/hooks/capture_backup.sh" push; }

echo "== stranded commit drains even when nothing new was encrypted"
# A push killed after `git commit` (SessionEnd budget, crash, offline) must not wait for an
# unrelated future capture to change before it reaches origin.
echo "stranded" > "$MIRROR/stranded.txt"
git -C "$MIRROR" -c user.name=t -c user.email=t@t -c commit.gpgsign=false add stranded.txt
git -C "$MIRROR" -c user.name=t -c user.email=t@t -c commit.gpgsign=false commit -q -m "capture: stranded"
sc="$(git -C "$MIRROR" rev-parse HEAD)"
# The health shard grows on every push and is itself encrypted as "new" content — set it aside so
# this run truly has nothing new to encrypt, and only the drain can move the commit.
mv "$HEALTH" "$HEALTH.aside"
stop_push >/dev/null 2>&1
{ cat "$HEALTH.aside"; cat "$HEALTH" 2>/dev/null; } > "$HEALTH.merged"; mv "$HEALTH.merged" "$HEALTH"; rm -f "$HEALTH.aside"
if git -C "$T_SANDBOX/holding.git" merge-base --is-ancestor "$sc" capture/testsat 2>/dev/null; then
  t_ok "stranded mirror commit pushed by a no-new-capture Stop"
else
  t_fail "stranded mirror commit still not on origin"
fi

echo "== busy mirror lock: Stop skips without touching the throttle stamp"
STAMPF="$PROJ/.bailiwick-outputs/.backup-last"
echo 12345 > "$STAMPF"
echo "SECRET-PAYLOAD-OSCAR" > "$PROJ/.bailiwick-outputs/raw/s13.jsonl"
mkdir "$MIRROR.lock"
stop_push >/dev/null 2>&1
assert_exit "Stop with a busy lock exits 0" 0 "$?"
assert_eq "throttle stamp untouched (next Stop retries)" "12345" "$(cat "$STAMPF")"
assert_not_contains "nothing pushed while the lock is held" "s13.jsonl.gpg" \
  "$(git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat)"
assert_dir "a held lock is not stolen" "$MIRROR.lock"

echo "== stale mirror lock (>10 min) is taken over"
age_minutes "$MIRROR.lock" 20
stop_push >/dev/null 2>&1
assert_exit "Stop over a stale lock exits 0" 0 "$?"
assert_contains "stale lock takeover pushes the waiting capture" "s13.jsonl.gpg" \
  "$(git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat)"
assert_contains "stale lock takeover logs a health warning" "stale mirror lock" "$HEALTH"
assert_no_dir "lock released after the run" "$MIRROR.lock"

echo "== /purge session: earlier backup blobs retracted, tombstoned, never re-pushed"
# A session that invokes /purge holds the identifiers being removed. An earlier Stop may already have
# captured AND pushed it; the Stop that sees the invocation must retract both. This also pins that
# capture_session.py derives the SAME blob relpath (<machine>/<repo_key>/<file>.gpg) push wrote.
write_cfg true "$FPR"
PPROJ="$T_SANDBOX/pproj"; mkdir -p "$PPROJ"; echo '$BAILIWICK' > "$PPROJ/CLAUDE.local.md"
PT="$T_SANDBOX/purge-session.jsonl"
work='{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Write","input":{"file_path":"a.tf"}}]}}'
# A USER-typed /purge (trusted): skip + retract + tombstone. An agent Skill(purge) call is only held.
purge_rec='{"type":"user","message":{"role":"user","content":"<command-message>purge</command-message>\n<command-name>/purge</command-name>\n<command-args>acme</command-args>"}}'
skill_rec='{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Skill","input":{"skill":"purge","args":"acme"}}]}}'
capture() {  # <session-id> [env...] : the Stop hook exactly as the harness runs it
  local sid="$1"; shift
  printf '{"hook_event_name":"Stop","session_id":"%s","transcript_path":"%s","cwd":"%s"}' "$sid" "$PT" "$PPROJ" \
    | env "$@" CLAUDE_PROJECT_DIR="$PPROJ" python3 "$INST/hooks/capture_session.py"
}
ppush() { echo '{"hook_event_name":"SessionEnd"}' | CLAUDE_PROJECT_DIR="$PPROJ" bash "$INST/hooks/capture_backup.sh" push; }
ptree() { git -C "$T_SANDBOX/holding.git" ls-tree -r --name-only capture/testsat; }
printf '%s\n' "$work" > "$PT"
capture psess
ppush >/dev/null 2>&1
assert_contains "precondition: the pre-purge capture was backed up" "psess.jsonl.gpg" "$(ptree)"
printf '%s\n%s\n' "$work" "$skill_rec" > "$PT"
capture psess   # unconfirmed trigger: held local, nothing deleted, nothing retracted
assert_file "agent Skill(purge): local capture kept" "$PPROJ/.bailiwick-outputs/raw/psess.jsonl"
assert_contains "agent Skill(purge): held by the hold line" "purge_detection: error" "$PPROJ/.bailiwick-outputs/raw/psess.md"
assert_contains "agent Skill(purge): backup blob not retracted" "psess.jsonl.gpg" "$(ptree)"
printf '%s\n%s\n' "$work" "$purge_rec" > "$PT"
capture psess   # BW_BACKUP_SYNC=1 (exported above): the retraction runs in the foreground
assert_no_file "local capture retracted" "$PPROJ/.bailiwick-outputs/raw/psess.jsonl"
assert_no_file "local header retracted" "$PPROJ/.bailiwick-outputs/raw/psess.md"
after="$(ptree)"
assert_not_contains "backup blob of the purge session removed" "psess.jsonl.gpg" "$after"
assert_not_contains "backup header blob of the purge session removed" "psess.md.gpg" "$after"
PKEY="$(PYTHONPATH="$INST/hooks" python3 -c 'import sys, capture_session; sys.stdout.write(capture_session.repo_key(sys.argv[1]))' "$PPROJ")"
sha() { printf '%s' "$1" | sha256sum | awk '{print $1}'; }
ph="$(sha "testsat/$PKEY/psess.jsonl.gpg")"; phm="$(sha "testsat/$PKEY/psess.md.gpg")"
assert_contains "purge-session blob tombstoned in .purged" "$ph" \
  "$(git -C "$T_SANDBOX/holding.git" show capture/testsat:.purged 2>/dev/null)"
assert_contains "purge-session header blob tombstoned in .purged" "$phm" \
  "$(git -C "$T_SANDBOX/holding.git" show capture/testsat:.purged 2>/dev/null)"
msgs="$(git -C "$T_SANDBOX/holding.git" log --format=%s capture/testsat)"
plabel="$(printf '%s\n%s\n' "$ph" "$phm" | sort | cut -c1-12 | paste -sd' ' -)"   # ledger order: sorted
assert_contains "purge-session commit is labelled and hash-only" "purge: $plabel (purge-session)" "$msgs"
assert_not_contains "no commit message names the session" "psess" "$msgs"
assert_not_contains "no commit message names the repo key" "$PKEY" "$msgs"
assert_no_file "ledger emptied once origin holds the tombstones" "$BAILIWICK_HOME/backup-retract.pending"
assert_contains "health logs the settled retraction by hash" "purge ok (${ph:0:12})" "$HEALTH"
ppush >/dev/null 2>&1
assert_not_contains "a later push never re-encrypts the purge session" "psess" "$(ptree)"
assert_contains "health records the skip, content-free" "capture skipped: purge session" "$HEALTH"
assert_not_contains "health names no purge-session blob" "psess" "$(cat "$HEALTH")"
assert_not_contains "health names no repo key" "$PKEY" "$(cat "$HEALTH")"

echo "== /purge session retraction that cannot reach origin stays pending; the next push settles it"
printf '%s\n' "$work" > "$PT"
capture psess3
ppush >/dev/null 2>&1
assert_contains "precondition: psess3 backed up" "psess3.jsonl.gpg" "$(ptree)"
mv "$T_SANDBOX/holding.git" "$T_SANDBOX/holding.off"   # origin unreachable
printf '%s\n%s\n' "$work" "$purge_rec" > "$PT"
capture psess3
assert_no_file "local capture retracted even offline" "$PPROJ/.bailiwick-outputs/raw/psess3.jsonl"
assert_eq "both blob hashes pending" "2" "$(grep -c . "$BAILIWICK_HOME/backup-retract.pending" 2>/dev/null)"
assert_not_contains "ledger holds hashes only" "psess3" "$(cat "$BAILIWICK_HOME/backup-retract.pending" 2>/dev/null)"
assert_contains "health reports the pending retraction" "retract: push failed — 2 retraction(s) pending" "$HEALTH"
assert_contains "skip line reports the pending count" "backup retractions pending: 2" "$HEALTH"
mv "$T_SANDBOX/holding.off" "$T_SANDBOX/holding.git"
ppush >/dev/null 2>&1   # any later push retries the ledger first
assert_not_contains "the next push removed the purge session's blobs" "psess3." "$(ptree)"
assert_no_file "ledger settled by the push" "$BAILIWICK_HOME/backup-retract.pending"

echo "== a spooled retraction (ledger lock was busy) is pending too, and is retracted + removed"
# capture_session.py never appends to the ledger unlocked: a busy lock spools the hashes to
# backup-retract.pending.spool-<ns>-<pid>. Every reader counts ledger ∪ spools.
printf '%s\n' "$work" > "$PT"
capture psess4
ppush >/dev/null 2>&1
assert_contains "precondition: psess4 backed up" "psess4.jsonl.gpg" "$(ptree)"
s4="$(sha "testsat/$PKEY/psess4.jsonl.gpg")"; s4m="$(sha "testsat/$PKEY/psess4.md.gpg")"
SPOOL="$BAILIWICK_HOME/backup-retract.pending.spool-1-1-0"
( umask 077; printf '%s\n%s\n' "$s4" "$s4m" > "$SPOOL" )
bash "$INST/hooks/capture_backup.sh" retract >/dev/null 2>&1
assert_not_contains "spooled hashes retracted from the backup" "psess4." "$(ptree)"
assert_contains "spooled hash tombstoned" "$s4" "$(git -C "$T_SANDBOX/holding.git" show capture/testsat:.purged 2>/dev/null)"
assert_no_file "spool removed once origin holds the tombstones" "$SPOOL"
assert_no_file "no ledger left behind" "$BAILIWICK_HOME/backup-retract.pending"
assert_contains "health logs the settled spooled retraction" "purge ok (${s4:0:12})" "$HEALTH"

echo "== a spool written during the retract (after drain, before pending_done) is never lost"
# The holding repo's pre-receive hook runs mid-push — after drain_pending, before pending_done's
# locked rewrite — and drops a spool with a hash this run never drained. It must survive the rewrite.
late="$(sha late)"
printf '%s\n' "$work" > "$PT"
capture psess5
ppush >/dev/null 2>&1
s5="$(sha "testsat/$PKEY/psess5.jsonl.gpg")"
( umask 077; printf '%s\n' "$s5" > "$BAILIWICK_HOME/backup-retract.pending.spool-2-2-0" )
PRE="$T_SANDBOX/holding.git/hooks/pre-receive"
printf '#!/bin/sh\ncat >/dev/null\numask 077\nprintf "%%s\\n" "%s" > "%s"\nexit 0\n' \
  "$late" "$BAILIWICK_HOME/backup-retract.pending.spool-3-3-0" > "$PRE"
chmod +x "$PRE"
bash "$INST/hooks/capture_backup.sh" retract >/dev/null 2>&1
rm -f "$PRE"
assert_not_contains "the drained spool's blob is retracted" "psess5.jsonl.gpg" "$(ptree)"
assert_no_file "the drained spool is gone" "$BAILIWICK_HOME/backup-retract.pending.spool-2-2-0"
late_left="$(cat "$BAILIWICK_HOME"/backup-retract.pending "$BAILIWICK_HOME"/backup-retract.pending.spool-* 2>/dev/null || true)"
assert_contains "the late spool's hash is still pending" "$late" "$late_left"
assert_not_contains "settled hash dropped from the pending set" "$s5" "$late_left"
ppush >/dev/null 2>&1   # the next push drains the late hash too
assert_no_file "late hash settled by the next push" "$BAILIWICK_HOME/backup-retract.pending"
assert_eq "no spool left" "" "$(ls "$BAILIWICK_HOME" | grep 'backup-retract.pending.spool-' || true)"

echo "== purge_detection: error header keeps a capture local-only until a human clears it"
HRAW="$PPROJ/.bailiwick-outputs/raw"
echo '{"x":1}' > "$HRAW/held.jsonl"
printf '# Raw capture — held\n\n- purge_detection: error\n- captured: x\n' > "$HRAW/held.md"
ppush >/dev/null 2>&1
assert_not_contains "held capture not pushed" "held.jsonl.gpg" "$(ptree)"
assert_not_contains "held header not pushed" "held.md.gpg" "$(ptree)"
assert_contains "health warns about the held capture" "held local-only: purge detection error" "$HEALTH"
printf '# Raw capture — held\n\n- captured: x\n' > "$HRAW/held.md"
ppush >/dev/null 2>&1
assert_contains "cleared capture pushed" "held.jsonl.gpg" "$(ptree)"

echo "== commit messages and health lines carry no repo key or relpath"
msgs="$(git -C "$T_SANDBOX/holding.git" log --all --format=%s)"
assert_not_contains "no commit message embeds a repo key (pproj)" "$PKEY" "$msgs"
assert_not_contains "no commit message embeds a relpath" ".gpg" "$msgs"
assert_contains "capture commit uses the hashed repo label" "capture: testsat/$(sha "$PKEY" | cut -c1-12)" "$msgs"
assert_not_contains "push ok line carries no repo key" "push ok ($PKEY" "$(cat "$HEALTH")"

echo "== a .purged conflict in the push rebase keeps BOTH sides' tombstones"
# Local purge committed while origin is unreachable; meanwhile machine 2 tombstones another blob on
# this branch. The reject -> rebase conflicts on .purged (both appended): a one-sided pick would drop
# a tombstone and let a later push resurrect that blob.
relA="testsat/$PKEY/held.md.gpg"; relB="testsat/$PKEY/held.jsonl.gpg"
mv "$T_SANDBOX/holding.git" "$T_SANDBOX/holding.off"
bash "$INST/hooks/capture_backup.sh" purge "$relA" >/dev/null 2>&1
mv "$T_SANDBOX/holding.off" "$T_SANDBOX/holding.git"
purge_from_m2 "$relB"
ppush >/dev/null 2>&1
man="$(git -C "$T_SANDBOX/holding.git" show capture/testsat:.purged 2>/dev/null)"
assert_contains "local tombstone survives the rebase" "$(sha "$relA")" "$man"
assert_contains "machine 2's tombstone survives the rebase" "$(sha "$relB")" "$man"
assert_not_contains "neither purged blob resurrected" "held.md.gpg" "$(ptree)"
assert_not_contains "neither purged blob resurrected (m2)" "held.jsonl.gpg" "$(ptree)"

echo "== drill self-defence: a stale BW_DRILL_SANDBOX (no marker / project outside) is ignored, with a warn"
dpush() { echo '{"hook_event_name":"SessionEnd"}' | BW_DRILL_SANDBOX="$1" CLAUDE_PROJECT_DIR="$PPROJ" \
  bash "$INST/hooks/capture_backup.sh" push >/dev/null 2>&1; }
echo '{"x":3}' > "$HRAW/stale.jsonl"
dpush "$T_SANDBOX"                                   # no .drill-sandbox marker anywhere
assert_contains "stale var without a marker still pushes" "stale.jsonl.gpg" "$(ptree)"
assert_contains "stale var is reported" "BW_DRILL_SANDBOX set but no drill sandbox applies" "$HEALTH"
mkdir -p "$T_SANDBOX/elsewhere"; echo '{}' > "$T_SANDBOX/elsewhere/.drill-sandbox"
echo '{"x":4}' > "$HRAW/outside.jsonl"
dpush "$T_SANDBOX/elsewhere"                         # marker present, project outside it
assert_contains "marker present but project outside still pushes" "outside.jsonl.gpg" "$(ptree)"

echo "== drill self-defence: a foreign clone does nothing inside an applying drill sandbox"
echo '{}' > "$T_SANDBOX/.drill-sandbox"              # PPROJ lives under $T_SANDBOX
echo '{"x":2}' > "$HRAW/drill.jsonl"
for m in push pull purge retract; do
  before="$(git -C "$T_SANDBOX/holding.git" rev-parse capture/testsat)"
  arg=""; [ "$m" = purge ] && arg="testsat/$PKEY/held.jsonl.gpg"
  err="$(echo '{"hook_event_name":"SessionEnd"}' | BW_DRILL_SANDBOX="$T_SANDBOX" CLAUDE_PROJECT_DIR="$PPROJ" \
    bash "$INST/hooks/capture_backup.sh" $m $arg 2>&1 >/dev/null)"; rc=$?
  if [ "$m" = push ]; then
    assert_exit "drill-foreign push exits 0 (hook stays quiet)" 0 "$rc"
  else
    assert_exit "drill-foreign $m exits 3 (a manual run must not look successful)" 3 "$rc"
    assert_contains "drill-foreign $m says it did not run" "$m NOT run" "$err"
  fi
  assert_eq "drill-foreign $m leaves the backup branch untouched" "$before" "$(git -C "$T_SANDBOX/holding.git" rev-parse capture/testsat)"
done
assert_not_contains "drill-foreign push did not upload" "drill.jsonl.gpg" "$(ptree)"
assert_contains "health records the drill skip" "drill sandbox active and this is not its framework copy" "$HEALTH"
ln -s "$INST" "$T_SANDBOX/framework"
dpush "$T_SANDBOX"
assert_contains "the sandbox's own framework copy still pushes" "drill.jsonl.gpg" "$(ptree)"
rm -f "$T_SANDBOX/.drill-sandbox" "$T_SANDBOX/framework"

echo "== /purge session retraction is detached: the hook returns fast, the blob still goes"
printf '%s\n' "$work" > "$PT"
capture psess2
ppush >/dev/null 2>&1
assert_contains "precondition: psess2 backed up" "psess2.jsonl.gpg" "$(ptree)"
printf '%s\n%s\n' "$work" "$purge_rec" > "$PT"
t0=$(now_ms)
capture psess2 -u BW_BACKUP_SYNC >/dev/null 2>&1
ms=$(( $(now_ms) - t0 ))
if [ "$ms" -lt 1000 ]; then t_ok "purge-session Stop returns in < 1000 ms (${ms} ms)"; else t_fail "purge-session Stop took ${ms} ms (budget 1500 ms)"; fi
i=0; while ptree | grep -q 'psess2\.' && [ "$i" -lt 60 ]; do sleep 0.5; i=$((i + 1)); done
assert_not_contains "detached child removed the purge session's blobs" "psess2." "$(ptree)"
i=0; while [ -d "$MIRROR.lock" ] && [ "$i" -lt 60 ]; do sleep 0.5; i=$((i + 1)); done

t_summary
