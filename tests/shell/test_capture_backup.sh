#!/usr/bin/env bash
# Contract tests for hooks/capture_backup.sh — the ciphertext durability path.
#
# The invariant under test, end to end: A CAPTURE IS NEVER LOST. The source file in
# .bailiwick-outputs/raw/ survives every failure mode (unusable key, unreachable remote,
# missing secret key at decrypt time) and survives SUCCESS too — only /curate's explicit
# purge removes anything, and that removes the remote blob, never the source (a later push moves
# a tombstoned source to raw/.curated/, it does not delete it). Every failure
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
for m in push pull purge retract compact; do
  before="$(git -C "$T_SANDBOX/holding.git" rev-parse capture/testsat)"
  arg=""; [ "$m" = purge ] && arg="testsat/$PKEY/held.jsonl.gpg"; [ "$m" = compact ] && arg="--dry-run"
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

echo "== compact-capable marker: added by the script's own commits, ignored by pull, kept by purge"
assert_eq "tracked marker on a branch this script commits to" "1" "$(git -C "$T_SANDBOX/holding.git" show capture/testsat:.compact-capable 2>/dev/null)"
assert_no_file "pull does not decrypt the marker" "$T_SANDBOX/inbox/.compact-capable"
ppath="testsat/$PKEY/stale.jsonl.gpg"
bash "$INST/hooks/capture_backup.sh" purge "$ppath" >/dev/null 2>&1
assert_eq "purge leaves the marker in place" "1" "$(git -C "$T_SANDBOX/holding.git" show capture/testsat:.compact-capable 2>/dev/null)"

# ---- compact ------------------------------------------------------------------------------------
# A dedicated bare repo, central instance and seed clone: histories are built with faked commit and
# author dates, since the 30-day window is the whole point. The "ciphertext" is never decrypted.
CBARE="$T_SANDBOX/compact.git"; git init -q --bare "$CBARE"
CINST="$T_SANDBOX/inst-central"; t_make_instance "$CINST"
CCACHE="$T_SANDBOX/cache-central"
CMIRROR="$CCACHE/bailiwick/capture-mirror"
write_central() {  # <ack> <role>
  cat > "$CINST/.bailiwick-sync.json" <<EOF
{ "role": "$2", "machine": "central",
  "capture_backup": { "enabled": true, "confidentiality_ack": $1, "retain_days": 3650,
    "repo": "file://$CBARE", "gpg_recipients": ["$FPR"], "branch": "capture/central", "throttle_minutes": 0 } }
EOF
}
write_central true central
compact_c() { XDG_CACHE_HOME="$CCACHE" bash "$CINST/hooks/capture_backup.sh" compact "$@"; }
SEED="$T_SANDBOX/seed"; git init -q -b seed-base "$SEED"
sg() { git -C "$SEED" -c user.name=seed -c user.email=seed@local -c commit.gpgsign=false "$@"; }
bare() { git -C "$CBARE" "$@"; }
sha_of() { printf '%s' "$1" | sha256sum | awk '{print $1}'; }
epoch_ago() { echo "$(( $(date +%s) - $1 * 86400 ))"; }
commit_at() {  # <days-ago> <message>
  local ts; ts="$(epoch_ago "$1")"
  GIT_AUTHOR_DATE="@$ts +0000" GIT_COMMITTER_DATE="@$ts +0000" sg commit -q --allow-empty -m "$2"
}
seed_branch() {  # <branch>: fresh orphan with the marker staged
  sg checkout -q --orphan "$1" 2>/dev/null
  sg read-tree --empty
  sg clean -fdxq
  printf '1\n' > "$SEED/.compact-capable"; sg add -A
}
seed_add() {  # <days-ago> <relpath>
  mkdir -p "$(dirname "$SEED/$2")"
  printf 'ciphertext %s\n' "$2" > "$SEED/$2"; printf 'sha %s\n' "$2" > "$SEED/$2.sha256"
  sg add -A; commit_at "$1" "capture: seed/$(printf '%012d' "$1") 2026-01-01T00:00:00Z"
}
seed_rm() {  # <days-ago> <relpath> [no-tombstone]: a curate purge
  sg rm -qf -- "$2" "$2.sha256"
  [ -n "${3:-}" ] || sha_of "$2" >> "$SEED/.purged"
  sg add -A; commit_at "$1" "purge: $(printf '%012d' "$1") (curated)"
}
seed_push() { sg push -q "file://$CBARE" "$1:refs/heads/$1"; }
objs() { git -C "$1" rev-list --objects "$2" 2>/dev/null | awk '{print $2}' | sort -u; }
RK="repo-key-abc123"

# capture/sat1 — one of every case. Oldest first; 30 days ago falls between day-40 and day-10.
seed_branch capture/sat1
seed_add 60 "sat1/$RK/old.jsonl.gpg"
seed_add 58 "sat1/$RK/uncurated.jsonl.gpg"
seed_rm  55 "sat1/$RK/old.jsonl.gpg"
seed_add 50 "sat1/$RK/notomb.jsonl.gpg"
seed_rm  45 "sat1/$RK/notomb.jsonl.gpg" no-tombstone
seed_add 40 "sat1/$RK/late.jsonl.gpg"
seed_add 10 "sat1/$RK/recent.jsonl.gpg"
seed_rm   5 "sat1/$RK/late.jsonl.gpg"
seed_rm   5 "sat1/$RK/recent.jsonl.gpg"
seed_add  2 "sat1/$RK/open.jsonl.gpg"
seed_push capture/sat1
SAT1_OLD="$(bare rev-parse capture/sat1)"
SAT1_OLD_PURGED="$(bare show capture/sat1:.purged | sort)"

# capture/central — the run's own branch; capture/nomark — no marker; capture/leasebr — loses the race.
seed_branch capture/central
seed_add 45 "central/$RK/c-old.jsonl.gpg"
seed_add 40 "central/$RK/c-stays.jsonl.gpg"
seed_rm   3 "central/$RK/c-old.jsonl.gpg"
seed_push capture/central
seed_branch capture/nomark
sg rm -qf .compact-capable
seed_add 45 "nomark/$RK/n.jsonl.gpg"
seed_add  1 "nomark/$RK/n2.jsonl.gpg"
seed_push capture/nomark
NOMARK_TIP="$(bare rev-parse capture/nomark)"
seed_branch capture/leasebr
seed_add 50 "lease/$RK/l0.jsonl.gpg"
seed_add 45 "lease/$RK/l.jsonl.gpg"
seed_add  1 "lease/$RK/l2.jsonl.gpg"
seed_push capture/leasebr
seed_add  0 "lease/$RK/racer.jsonl.gpg"
sg push -q "file://$CBARE" "capture/leasebr:refs/heads/race-hold"
RACE_TIP="$(bare rev-parse race-hold)"

echo "== compact: refusals"
write_central false central
out="$(compact_c --retain-days 30 2>&1)"; rc=$?
assert_eq "no confidentiality_ack: refused, exit 1" "1" "$rc"
assert_contains "ack refusal names the reason" "confidentiality_ack" "$out"
write_central true satellite
out="$(compact_c --retain-days 30 2>&1)"; rc=$?
assert_eq "satellite role: refused, exit 1" "1" "$rc"
assert_contains "role refusal is explicit" "only the central machine" "$out"
assert_eq "refused runs moved no branch" "$SAT1_OLD" "$(bare rev-parse capture/sat1)"
write_central true central
out="$(compact_c --retain-days x 2>&1)"; rc=$?
assert_eq "invalid --retain-days: usage, exit 2" "2" "$rc"

echo "== compact: nothing older than the window is a no-op; retain_days comes from the config"
out="$(compact_c 2>&1)"; rc=$?
assert_eq "no-op run exits 0" "0" "$rc"
assert_contains "config retain_days (3650) leaves the branch alone" "noop:nothing-old-enough" "$out"
assert_eq "no-op run moved no branch" "$SAT1_OLD" "$(bare rev-parse capture/sat1)"

echo "== compact --dry-run changes nothing on the remote and reports hash-only counts"
# Origin fully fetched first, so the mirror's object count below measures the rewrite alone: a dry
# run's own fetch legitimately adds objects, which the section after this one pins.
git -C "$CMIRROR" fetch -q origin '+refs/heads/*:refs/remotes/origin/*'
refs_before="$(bare for-each-ref)"; objs_before="$(find "$CBARE/objects" -type f | wc -l)"
mobjs_before="$(find "$CMIRROR/.git/objects" -type f | wc -l)"
out="$(compact_c --retain-days 30 --dry-run 2>&1)"; rc=$?
assert_eq "dry run exits 0" "0" "$rc"
assert_eq "dry run leaves the bare repo's refs untouched" "$refs_before" "$(bare for-each-ref)"
assert_eq "dry run adds no object to the bare repo" "$objs_before" "$(find "$CBARE/objects" -type f | wc -l)"
assert_eq "with origin already fetched, the rewrite adds no object to the mirror" "$mobjs_before" "$(find "$CMIRROR/.git/objects" -type f | wc -l)"
hsat1="$(printf '%s' capture/sat1 | sha256sum | cut -c1-12)"
line="$(printf '%s\n' "$out" | grep "branch=$hsat1")"
assert_contains "dry run reports commits old->new" "commits=10->5" "$line"
assert_contains "dry run reports D (3 blobs + 3 sidecars)" "D=6" "$line"
assert_contains "dry run reports the marker" "marker=yes" "$line"
assert_contains "dry run reports the no-marker branch" "marker=no" "$out"
assert_contains "dry run reports disk use" "disk=" "$line"
assert_eq "dry run makes no undo ref" "" "$(git -C "$CMIRROR" for-each-ref refs/bw)"
for leak in "$RK" ".gpg" "capture/" "sat1/" "uncurated"; do
  assert_not_contains "compact output carries no identifier ($leak)" "$leak" "$out"
done

echo "== compact --dry-run: the fetch is its one write (remote-tracking refs and objects), never the remote"
seed_branch capture/dryfetch
seed_add 1 "dryfetch/$RK/f.jsonl.gpg"
seed_push capture/dryfetch
refs_before="$(bare for-each-ref)"
compact_c --retain-days 30 --dry-run >/dev/null 2>&1
assert_eq "dry run leaves the remote's refs untouched" "$refs_before" "$(bare for-each-ref)"
assert_eq "dry run refreshes the remote-tracking ref" "$(bare rev-parse capture/dryfetch)" \
  "$(git -C "$CMIRROR" rev-parse -q --verify refs/remotes/origin/capture/dryfetch)"
bare update-ref -d refs/heads/capture/dryfetch
git -C "$CMIRROR" update-ref -d refs/remotes/origin/capture/dryfetch

echo "== compact: curated-and-old removed, everything else preserved"
SHIM="$T_SANDBOX/shim"; mkdir -p "$SHIM"
cat > "$SHIM/git" <<EOF
#!/usr/bin/env bash
# Another machine's push lands between compact's fetch and its force-push on capture/leasebr.
case "\$*" in *--force-with-lease=refs/heads/capture/leasebr:*)
  "$(command -v git)" -C "$CBARE" update-ref refs/heads/capture/leasebr "$RACE_TIP";; esac
exec "$(command -v git)" "\$@"
EOF
chmod +x "$SHIM/git"
out="$(PATH="$SHIM:$PATH" compact_c --retain-days 30 2>&1)"; rc=$?
assert_eq "compact exits 0" "0" "$rc"
SAT1_NEW="$(bare rev-parse capture/sat1)"
assert_eq "history folded: root + 4 replayed commits" "5" "$(bare rev-list --count capture/sat1)"
assert_eq "a single parentless root" "1" "$(bare rev-list --count --max-parents=0 capture/sat1)"
assert_contains "root message is identifier-free" "compact: " "$(bare log -1 --format=%s "$(bare rev-list --max-parents=0 capture/sat1)")"
hist="$(objs "$CBARE" capture/sat1)"
assert_not_contains "old curated blob gone from history" "old.jsonl.gpg" "$hist"
assert_not_contains "its sidecar gone too" "old.jsonl.gpg.sha256" "$hist"
assert_not_contains "pre-tombstone purge gone from history" "notomb.jsonl.gpg" "$hist"
assert_not_contains "capture 40 days old, curated 5 days ago, removed" "late.jsonl.gpg" "$hist"
assert_contains "curated inside the window: still in history" "recent.jsonl.gpg" "$hist"
tiptree="$(bare ls-tree -r --name-only capture/sat1)"
assert_contains "uncurated 58-day-old capture survives on the tip" "uncurated.jsonl.gpg" "$tiptree"
assert_contains "uncurated capture's sidecar survives" "uncurated.jsonl.gpg.sha256" "$tiptree"
assert_contains "open capture survives" "open.jsonl.gpg" "$tiptree"
assert_eq "tip tree unchanged apart from .purged" ".purged" "$(bare diff-tree -r --name-only "$SAT1_OLD" "$SAT1_NEW")"
manifest="$(bare show capture/sat1:.purged)"
assert_contains "tombstone added for the pre-tombstone purge" "$(sha_of "sat1/$RK/notomb.jsonl.gpg")" "$manifest"
assert_contains "tombstone present for a curated blob" "$(sha_of "sat1/$RK/late.jsonl.gpg")" "$manifest"
assert_eq "manifest keeps all its old lines" "" "$(comm -23 <(printf '%s\n' "$SAT1_OLD_PURGED") <(printf '%s\n' "$manifest" | sort))"
assert_eq "manifest stays sorted and unique" "$(printf '%s\n' "$manifest" | sort -u)" "$manifest"
assert_eq "root tree has no D path either" "" "$(bare ls-tree -r --name-only "$(bare rev-list --max-parents=0 capture/sat1)" | grep -E 'old\.jsonl|notomb|late' || true)"
dmeta="$(bare log --format='%s|%at %ct' --grep='^capture: seed/000000000010 ' capture/sat1)"
assert_contains "replayed commit keeps its hashed message" "capture: seed/000000000010 " "$dmeta"
assert_eq "replayed commit keeps author and committer dates" "$(sg log -1 --format='%at %ct' --grep='^capture: seed/000000000010 ' capture/sat1)" "${dmeta##*|}"
assert_eq "undo ref holds the old tip" "$SAT1_OLD" "$(git -C "$CMIRROR" rev-parse refs/bw/pre-compact/capture/sat1)"

echo "== compact: own branch moves the mirror; marker-less branch skipped; lease loss skipped"
assert_eq "own branch: mirror HEAD follows the new tip" "$(bare rev-parse capture/central)" "$(git -C "$CMIRROR" rev-parse HEAD)"
assert_eq "own branch: clean worktree" "" "$(git -C "$CMIRROR" status --porcelain)"
assert_eq "own branch: 2 commits left (root + day-3 purge)" "2" "$(bare rev-list --count capture/central)"
assert_contains "own branch: c-stays on the tip" "c-stays.jsonl.gpg" "$(bare ls-tree -r --name-only capture/central)"
assert_eq "own branch: D blob not on tip" "" "$(bare ls-tree -r --name-only capture/central | grep c-old || true)"
assert_contains "no-marker branch reported" "status=skipped:no-marker" "$out"
assert_eq "no-marker branch untouched" "$NOMARK_TIP" "$(bare rev-parse capture/nomark)"
assert_contains "lease loss reported" "status=skipped:push-rejected" "$out"
assert_eq "lease loss: the racer's commit stands" "$RACE_TIP" "$(bare rev-parse capture/leasebr)"
assert_eq "lease loss: no undo ref left behind" "" "$(git -C "$CMIRROR" for-each-ref refs/bw/pre-compact/capture/leasebr)"
assert_contains "lease loss reaches the health shard, hashed" "compact skipped" "$BAILIWICK_HOME/health/central.jsonl"
assert_not_contains "health carries no relpath or repo key" "$RK" "$(cat "$BAILIWICK_HOME/health/central.jsonl")"

echo "== compact: a second run is a no-op; a capture curated later leaves on the next run"
out="$(compact_c --retain-days 30 2>&1)"
assert_eq "second run changes nothing" "$SAT1_NEW" "$(bare rev-parse capture/sat1)"
assert_eq "second run still 5 commits" "5" "$(bare rev-list --count capture/sat1)"
sg checkout -q capture/sat1 2>/dev/null; sg fetch -q "file://$CBARE" "capture/sat1"; sg reset -q --hard FETCH_HEAD
seed_rm 1 "sat1/$RK/uncurated.jsonl.gpg"
seed_push capture/sat1
compact_c --retain-days 30 >/dev/null 2>&1
hist="$(objs "$CBARE" capture/sat1)"
assert_not_contains "blob from the old root, curated since, removed on the next compact" "uncurated.jsonl.gpg" "$hist"

echo "== compact: own branch still ahead after a failed drain is skipped, unpushed work intact"
git -C "$CMIRROR" -c user.name=t -c user.email=t@t -c commit.gpgsign=false commit -q --allow-empty -m "capture: stranded"
AHEAD_TIP="$(git -C "$CMIRROR" rev-parse HEAD)"; OWN_REMOTE="$(bare rev-parse capture/central)"
printf '#!/bin/sh\nexit 1\n' > "$CMIRROR/.git/hooks/pre-push"; chmod +x "$CMIRROR/.git/hooks/pre-push"
out="$(compact_c --retain-days 30 2>&1)"
mv "$CMIRROR/.git/hooks/pre-push" "$CMIRROR/.git/hooks/pre-push.off"
assert_contains "own branch skipped while ahead" "status=skipped:unpushed-commits" "$out"
assert_eq "unpushed mirror commit kept" "$AHEAD_TIP" "$(git -C "$CMIRROR" rev-parse HEAD)"
assert_eq "own remote branch not moved" "$OWN_REMOTE" "$(bare rev-parse capture/central)"
compact_c --retain-days 30 >/dev/null 2>&1   # drains the stranded commit
assert_eq "stranded commit drained once the push works" "0" "$(git -C "$CMIRROR" rev-list --count origin/capture/central..capture/central 2>/dev/null)"

echo "== satellite recovery: unpushed captures kept, D never resurrected, remote gains only those commits"
RINST="$T_SANDBOX/inst-rec"; t_make_instance "$RINST"
cat > "$RINST/.bailiwick-sync.json" <<EOF
{ "role": "satellite", "machine": "recsat",
  "capture_backup": { "enabled": true, "confidentiality_ack": true,
    "repo": "file://$CBARE", "gpg_recipients": ["$FPR"], "branch": "capture/recsat", "throttle_minutes": 0 } }
EOF
RPROJ="$T_SANDBOX/rec-proj"; mkdir -p "$RPROJ/.bailiwick-outputs/raw"; RRAW="$RPROJ/.bailiwick-outputs/raw"
RCACHE="$T_SANDBOX/cache-rec"; RMIRROR="$RCACHE/bailiwick/capture-mirror"
rpush() { echo '{"hook_event_name":"SessionEnd"}' | XDG_CACHE_HOME="$RCACHE" CLAUDE_PROJECT_DIR="$RPROJ" bash "$RINST/hooks/capture_backup.sh" push; }
RKEY="$(PYTHONPATH="$RINST/hooks" python3 -c 'import sys, capture_session; sys.stdout.write(capture_session.repo_key(sys.argv[1]))' "$RPROJ")"
DREL="recsat/$RKEY/gone.jsonl.gpg"
seed_branch capture/recsat
seed_add 50 "$DREL"
seed_add 45 "recsat/$RKEY/keep.jsonl.gpg"
seed_rm  40 "$DREL"
seed_add 2  "recsat/$RKEY/recent.jsonl.gpg"
seed_push capture/recsat
DOID="$(printf 'ciphertext %s\n' "$DREL" | git hash-object --stdin)"
echo "SECRET-REC-1" > "$RRAW/f1.jsonl"
rpush >/dev/null 2>&1
assert_contains "satellite pushed on top of the seeded history" "f1.jsonl.gpg" "$(bare ls-tree -r --name-only capture/recsat)"
mv "$CBARE" "$CBARE.off"
echo "SECRET-REC-2" > "$RRAW/f2.jsonl"
rpush >/dev/null 2>&1
mv "$CBARE.off" "$CBARE"
assert_eq "precondition: f2 is unpushed in the mirror" "" "$(bare ls-tree -r --name-only capture/recsat | grep f2.jsonl.gpg || true)"
assert_contains "precondition: f2 committed locally" "f2.jsonl.gpg" "$(git -C "$RMIRROR" ls-files)"
assert_eq "precondition: mirror still holds the old blob" "0" "$(git -C "$RMIRROR" cat-file -e "$DOID" >/dev/null 2>&1; echo $?)"
compact_c --retain-days 30 >/dev/null 2>&1
T0="$(bare rev-parse capture/recsat)"
assert_eq "precondition: compact rewrote the satellite's branch" "1" "$(bare rev-list --count --max-parents=0 capture/recsat)"
# The un-retired source of the removed blob must not be re-encrypted; a half-finished push is
# simulated by a dirty worktree: untracked ciphertext plus a modified .purged.
echo "SECRET-GONE" > "$RRAW/gone.jsonl"
echo "ciphertext half" > "$RMIRROR/recsat/$RKEY/half.jsonl.gpg"
sha_of "dirty-line" >> "$RMIRROR/.purged"
echo "SECRET-REC-3" > "$RRAW/f3.jsonl"
out="$(rpush 2>&1)"; rc=$?
assert_eq "recovery push exits 0" "0" "$rc"
assert_no_dir "recovery leaves no rebase behind" "$RMIRROR/.git/rebase-merge"
assert_not_contains "no 'resolve your current index' wedge" "resolve your current index" "$out"
RTIP="$(bare rev-parse capture/recsat)"
assert_eq "new history kept: compact's tip is an ancestor" "0" "$(bare merge-base --is-ancestor "$T0" "$RTIP"; echo $?)"
assert_eq "remote gained exactly the unpushed work (f2, the dirty worktree, this push)" "3" "$(bare rev-list --count "$T0..$RTIP")"
rtree="$(bare ls-tree -r --name-only capture/recsat)"
assert_contains "unpushed capture landed" "f2.jsonl.gpg" "$rtree"
assert_contains "capture written after the rewrite landed" "f3.jsonl.gpg" "$rtree"
assert_contains "dirty ciphertext landed" "half.jsonl.gpg" "$rtree"
assert_not_contains "removed blob not resurrected by its un-retired source" "gone.jsonl.gpg" "$rtree"
assert_not_contains "removed blob nowhere in the remote's history" "gone.jsonl.gpg" "$(objs "$CBARE" capture/recsat)"
assert_contains "dirty .purged line survived the recovery" "$(sha_of dirty-line)" "$(bare show capture/recsat:.purged)"
assert_contains "tombstone for the removed blob" "$(sha_of "$DREL")" "$(bare show capture/recsat:.purged)"
assert_eq "satellite undo ref dropped once the recovery pushed" "" "$(git -C "$RMIRROR" for-each-ref refs/bw/pre-compact)"
assert_file "gc is owed to the detached child" "$RMIRROR/.git/bw-gc-pending"
assert_eq "inline run did not gc the mirror" "0" "$(git -C "$RMIRROR" cat-file -e "$DOID" >/dev/null 2>&1; echo $?)"
echo '{"hook_event_name":"SessionEnd"}' | env -u BW_BACKUP_SYNC BW_BACKUP_SETTLE_S=0 XDG_CACHE_HOME="$RCACHE" \
  CLAUDE_PROJECT_DIR="$RPROJ" bash "$RINST/hooks/capture_backup.sh" push >/dev/null 2>&1
i=0; while { [ -f "$RMIRROR/.git/bw-gc-pending" ] || [ -d "$RMIRROR.lock" ]; } && [ "$i" -lt 60 ]; do sleep 0.5; i=$((i + 1)); done
assert_no_file "the detached child settled the gc" "$RMIRROR/.git/bw-gc-pending"
assert_eq "gc removed the old blob from the mirror" "1" "$(git -C "$RMIRROR" cat-file -e "$DOID" >/dev/null 2>&1; echo $?)"
assert_contains "health reports the recovery" "mirror recovered" "$BAILIWICK_HOME/health/recsat.jsonl"

echo "== push_branch never rebases across a rewritten origin; the next run recovers by overlay"
RINST3="$T_SANDBOX/inst-race"; t_make_instance "$RINST3"
cat > "$RINST3/.bailiwick-sync.json" <<EOF
{ "role": "satellite", "machine": "racesat",
  "capture_backup": { "enabled": true, "confidentiality_ack": true,
    "repo": "file://$CBARE", "gpg_recipients": ["$FPR"], "branch": "capture/racesat", "throttle_minutes": 0 } }
EOF
RAPROJ="$T_SANDBOX/race-proj"; mkdir -p "$RAPROJ/.bailiwick-outputs/raw"; RARAW="$RAPROJ/.bailiwick-outputs/raw"
RACACHE="$T_SANDBOX/cache-race"; RAMIRROR="$RACACHE/bailiwick/capture-mirror"
racepush() { echo '{"hook_event_name":"SessionEnd"}' | XDG_CACHE_HOME="$RACACHE" CLAUDE_PROJECT_DIR="$RAPROJ" bash "$RINST3/hooks/capture_backup.sh" push; }
echo "SECRET-RACE-1" > "$RARAW/r1.jsonl"
racepush >/dev/null 2>&1
echo "SECRET-RACE-2" > "$RARAW/r2.jsonl"
racepush >/dev/null 2>&1
BEFORE_RACE="$(git -C "$RAMIRROR" rev-list --count HEAD)"
ROOT_RACE="$(git -C "$RAMIRROR" rev-list --max-parents=0 HEAD)"
seed_branch race-orphan
seed_add 1 "racesat/seed/orphan.jsonl.gpg"
sg push -q "file://$CBARE" "race-orphan:refs/heads/race-orphan"
ORPHAN="$(bare rev-parse race-orphan)"
cat > "$RAMIRROR/.git/hooks/pre-push" <<EOF
#!/bin/sh
[ -f "$T_SANDBOX/race-fired" ] && exit 0
: > "$T_SANDBOX/race-fired"
GIT_DIR="$CBARE" git update-ref refs/heads/capture/racesat "$ORPHAN"
EOF
chmod +x "$RAMIRROR/.git/hooks/pre-push"
echo "SECRET-RACE-3" > "$RARAW/r3.jsonl"
out="$(racepush 2>&1)"; rc=$?
assert_eq "a push rejected by a rewrite exits 0" "0" "$rc"
assert_contains "the push reports the failure" "push failed" "$out"
assert_eq "origin keeps the rewrite (no bloat)" "$ORPHAN" "$(bare rev-parse capture/racesat)"
assert_eq "local history was not rebased across it" "$ROOT_RACE" "$(git -C "$RAMIRROR" rev-list --max-parents=0 HEAD)"
assert_eq "local commits kept (one new, none lost)" "$((BEFORE_RACE + 1))" "$(git -C "$RAMIRROR" rev-list --count HEAD)"
assert_no_dir "no rebase left behind" "$RAMIRROR/.git/rebase-merge"
out="$(racepush 2>&1)"; rc=$?
assert_eq "next run exits 0" "0" "$rc"
RATIP="$(bare rev-parse capture/racesat)"
assert_eq "recovery sits on top of the rewrite" "0" "$(bare merge-base --is-ancestor "$ORPHAN" "$RATIP"; echo $?)"
ratree="$(bare ls-tree -r --name-only capture/racesat)"
assert_contains "overlay carries the unpushed capture" "r3.jsonl.gpg" "$ratree"
assert_contains "overlay carries the older capture too" "r1.jsonl.gpg" "$ratree"
assert_contains "the rewrite's own content is kept" "orphan.jsonl.gpg" "$ratree"
assert_eq "recovery added a handful of commits, not the old history" "1" "$( [ "$(bare rev-list --count "$ORPHAN..$RATIP")" -le 2 ] && echo 1 || echo 0)"
assert_contains "health reports the overlay recovery" "mirror recovered (overlay)" "$BAILIWICK_HOME/health/racesat.jsonl"

# ---- each section below reproduces one way compact or recovery lost, resurrected or leaked data.
new_sat() {  # <machine>: a satellite on the compact repo; sets NS_INST NS_PROJ NS_RAW NS_CACHE NS_MIRROR
  NS_INST="$T_SANDBOX/inst-$1"; t_make_instance "$NS_INST"
  cat > "$NS_INST/.bailiwick-sync.json" <<EOF
{ "role": "satellite", "machine": "$1",
  "capture_backup": { "enabled": true, "confidentiality_ack": true,
    "repo": "file://$CBARE", "gpg_recipients": ["$FPR"], "branch": "capture/$1", "throttle_minutes": 0 } }
EOF
  NS_PROJ="$T_SANDBOX/proj-$1"; NS_RAW="$NS_PROJ/.bailiwick-outputs/raw"; mkdir -p "$NS_RAW"
  NS_CACHE="$T_SANDBOX/cache-$1"; NS_MIRROR="$NS_CACHE/bailiwick/capture-mirror"
}
ns_push() { echo '{"hook_event_name":"SessionEnd"}' | XDG_CACHE_HOME="$NS_CACHE" CLAUDE_PROJECT_DIR="$NS_PROJ" bash "$NS_INST/hooks/capture_backup.sh" push; }
ns_key() { PYTHONPATH="$NS_INST/hooks" python3 -c 'import sys, capture_session; sys.stdout.write(capture_session.repo_key(sys.argv[1]))' "$NS_PROJ"; }
ns_git() { git -C "$NS_MIRROR" -c user.name=t -c user.email=t@t -c commit.gpgsign=false "$@"; }
days_ago() {  # <days> <command...>: every commit the command makes carries that date
  local ts; ts="$(epoch_ago "$1")"; shift
  GIT_AUTHOR_DATE="@$ts +0000" GIT_COMMITTER_DATE="@$ts +0000" "$@"
}
tree_has() { printf '%s\n' "$1" | grep -Fxc -- "$2"; }   # exact path: a blob's name is a prefix of its sidecar's
big_manifest() {  # <file> <hash...>: the given hashes first, then 3200 more valid lines
  python3 -c '
import hashlib, sys
with open(sys.argv[1], "w") as f:
    for h in sys.argv[2:]:
        f.write(h + "\n")
    for i in range(3200):
        f.write(hashlib.sha256(str(i).encode()).hexdigest() + "\n")' "$@"
}

echo "== compact: a blob lost to a failed encrypt is not curated: stays in history, gets no tombstone"
# The real sequence: the source of a backed-up capture changes, gpg fails for that one file, the push
# loop deletes its blob and keeps the sidecar, and another file makes the run commit the deletion.
new_sat gfsat
GF_KEY="$(ns_key)"; GF_BLOB="gfsat/$GF_KEY/victim.jsonl.gpg"
echo "SECRET-GF-VICTIM" > "$NS_RAW/victim.jsonl"
echo "SECRET-GF-CURATED" > "$NS_RAW/curated.jsonl"
days_ago 60 ns_push >/dev/null 2>&1
days_ago 50 env XDG_CACHE_HOME="$NS_CACHE" bash "$NS_INST/hooks/capture_backup.sh" purge "gfsat/$GF_KEY/curated.jsonl.gpg" >/dev/null 2>&1
GSHIM="$T_SANDBOX/shim-gpg"; mkdir -p "$GSHIM"
cat > "$GSHIM/gpg" <<EOF
#!/usr/bin/env bash
# One file fails to encrypt; the rest of the run (and the health shard) works.
prev=""
for a in "\$@"; do
  if [ "\$prev" = "--output" ]; then case "\$a" in *victim.jsonl.gpg) exit 2;; esac; fi
  prev="\$a"
done
exec "$(command -v gpg)" "\$@"
EOF
chmod +x "$GSHIM/gpg"
echo "SECRET-GF-VICTIM-RESUMED" >> "$NS_RAW/victim.jsonl"
echo "SECRET-GF-OTHER" > "$NS_RAW/other.jsonl"
PATH="$GSHIM:$PATH" days_ago 5 ns_push >/dev/null 2>&1
gftree="$(bare ls-tree -r --name-only capture/gfsat)"
assert_eq "precondition: the failed encrypt took the blob off the tip" "0" "$(tree_has "$gftree" "$GF_BLOB")"
assert_eq "precondition: and left its sidecar there" "1" "$(tree_has "$gftree" "$GF_BLOB.sha256")"
out="$(compact_c --retain-days 30 2>&1)"
assert_contains "the branch was rewritten" "status=rewritten" "$(printf '%s\n' "$out" | grep "branch=$(printf '%s' capture/gfsat | sha256sum | cut -c1-12)")"
gfhist="$(objs "$CBARE" capture/gfsat)"
assert_eq "its older ciphertext is still in history" "1" "$(tree_has "$gfhist" "$GF_BLOB")"
assert_not_contains "no tombstone: it was never purged" "$(sha_of "$GF_BLOB")" "$(bare show capture/gfsat:.purged)"
assert_not_contains "a curated blob on the same branch still leaves" "curated.jsonl.gpg" "$gfhist"

echo "== recovery keeps both of two consecutive unpushed commits that conflict on .purged"
# Low hashes sort before the tombstone compact adds, so each replayed append meets it at the same
# place: the first replay conflicts, and --continue then stops on the second one's conflict.
zh() { printf '%063d%s' 0 "$1"; }
new_sat dblsat
DB_KEY="$(ns_key)"
seed_branch capture/dblsat
zh 1 > "$SEED/.purged"; echo >> "$SEED/.purged"
seed_add 50 "dblsat/$DB_KEY/gone.jsonl.gpg"
seed_rm  40 "dblsat/$DB_KEY/gone.jsonl.gpg" no-tombstone
seed_add  2 "dblsat/$DB_KEY/keep.jsonl.gpg"
seed_push capture/dblsat
echo "SECRET-DB-1" > "$NS_RAW/f1.jsonl"
ns_push >/dev/null 2>&1
for n in 2 3; do
  { zh "$n"; echo; } >> "$NS_MIRROR/.purged"
  ns_git add .purged; ns_git commit -qm "purge: 00000000000$n (curated)"
done
compact_c --retain-days 30 >/dev/null 2>&1
DB_T0="$(bare rev-parse capture/dblsat)"
assert_eq "precondition: compact rewrote the branch" "1" "$(bare rev-list --count --max-parents=0 capture/dblsat)"
echo "SECRET-DB-2" > "$NS_RAW/f2.jsonl"
out="$(ns_push 2>&1)"; rc=$?
assert_eq "recovery push exits 0" "0" "$rc"
assert_no_dir "no rebase left behind" "$NS_MIRROR/.git/rebase-merge"
dbman="$(bare show capture/dblsat:.purged)"
assert_contains "the first conflicting commit survived" "$(zh 2)" "$dbman"
assert_contains "the second conflicting commit survived" "$(zh 3)" "$dbman"
assert_contains "compact's own tombstone survived" "$(sha_of "dblsat/$DB_KEY/gone.jsonl.gpg")" "$dbman"
assert_eq "remote gained exactly both commits and this push's capture" "3" "$(bare rev-list --count "$DB_T0..capture/dblsat")"

echo "== a tombstone near the start of a large manifest is honoured: push skip and tree sweep"
# grep -q stops at the match; a writer still feeding it dies of SIGPIPE, and pipefail reported a miss.
new_sat bigsat
BIG_KEY="$(ns_key)"; BIG_SWEPT="bigsat/$BIG_KEY/swept.jsonl.gpg"; BIG_SKIP="bigsat/$BIG_KEY/skipped.jsonl.gpg"
echo "SECRET-BIG-1" > "$NS_RAW/swept.jsonl"
ns_push >/dev/null 2>&1
assert_eq "precondition: the blob is on the tip" "1" "$(tree_has "$(bare ls-tree -r --name-only capture/bigsat)" "$BIG_SWEPT")"
big_manifest "$NS_MIRROR/.purged" "$(sha_of "$BIG_SWEPT")" "$(sha_of "$BIG_SKIP")"
assert_eq "manifest is large" "1" "$( [ "$(grep -c . "$NS_MIRROR/.purged")" -ge 3000 ] && echo 1 || echo 0)"
echo "SECRET-BIG-2" > "$NS_RAW/skipped.jsonl"
ns_push >/dev/null 2>&1
bigtree="$(bare ls-tree -r --name-only capture/bigsat)"
assert_eq "tombstoned blob swept from the tree" "0" "$(tree_has "$bigtree" "$BIG_SWEPT")"
assert_eq "its sidecar swept too" "0" "$(tree_has "$bigtree" "$BIG_SWEPT.sha256")"
assert_eq "tombstoned source not re-encrypted" "0" "$(tree_has "$bigtree" "$BIG_SKIP")"

echo "== overlay recovery: a tombstoned path stays out with its sidecar, and paths are literal"
# No usable old tip, so the overlay runs. The manifest is large and matches at its start, and `a*b`
# would pull in the tombstoned axb if it were read as a glob.
new_sat ovlsat
OVL_KEY="$(ns_key)"; OVL_GONE="ovlsat/$OVL_KEY/gone.jsonl.gpg"; OVL_GLOB="ovlsat/$OVL_KEY/a*b.jsonl.gpg"; OVL_MATCH="ovlsat/$OVL_KEY/axb.jsonl.gpg"
echo "SECRET-OVL-1" > "$NS_RAW/keep.jsonl"
echo "SECRET-OVL-2" > "$NS_RAW/gone.jsonl"
ns_push >/dev/null 2>&1
echo glob > "$NS_MIRROR/$OVL_GLOB"; echo match > "$NS_MIRROR/$OVL_MATCH"
ns_git add -A; ns_git commit -qm "capture: ovlsat/0123456789ab 2026-01-01T00:00:00Z"; ns_git push -q origin capture/ovlsat
seed_branch ovl-rewrite
big_manifest "$SEED/.purged" "$(sha_of "$OVL_GONE")" "$(sha_of "$OVL_MATCH")"
seed_add 1 "ovlsat/$OVL_KEY/seeded.jsonl.gpg"
sg push -q "file://$CBARE" "+ovl-rewrite:refs/heads/capture/ovlsat"
ns_git update-ref -d refs/remotes/origin/capture/ovlsat
# pull runs ensure_mirror but not the tombstone sweep, which would hide what the overlay restored.
out="$(XDG_CACHE_HOME="$NS_CACHE" bash "$NS_INST/hooks/capture_backup.sh" pull "$T_SANDBOX/inbox-ovl" 2>&1)"; rc=$?
assert_eq "overlay recovery exits 0" "0" "$rc"
ovltree="$(ns_git ls-tree -r --name-only HEAD)"
assert_eq "tombstoned blob not overlaid" "0" "$(tree_has "$ovltree" "$OVL_GONE")"
assert_eq "its sidecar not overlaid either" "0" "$(tree_has "$ovltree" "$OVL_GONE.sha256")"
assert_eq "live capture overlaid" "1" "$(tree_has "$ovltree" "ovlsat/$OVL_KEY/keep.jsonl.gpg")"
assert_eq "live capture's sidecar overlaid" "1" "$(tree_has "$ovltree" "ovlsat/$OVL_KEY/keep.jsonl.gpg.sha256")"
assert_eq "a path holding * is restored" "1" "$(tree_has "$ovltree" "$OVL_GLOB")"
assert_eq "and matches nothing else: its tombstoned neighbour stays out" "0" "$(tree_has "$ovltree" "$OVL_MATCH")"
assert_contains "health reports the overlay" "mirror recovered (overlay)" "$BAILIWICK_HOME/health/ovlsat.jsonl"
ns_push >/dev/null 2>&1
assert_eq "the recovery reaches origin" "1" "$(tree_has "$(bare ls-tree -r --name-only capture/ovlsat)" "ovlsat/$OVL_KEY/keep.jsonl.gpg")"

echo "== compact: a path git would quote gets the tombstone of its real name"
QPATH='qsat/repo"quoted/s.jsonl.gpg'; UPATH='qsat/repo-çã/u.jsonl.gpg'
seed_branch capture/quotedbr
seed_add 60 "$QPATH"
seed_add 58 "$UPATH"
seed_rm  50 "$QPATH" no-tombstone
seed_rm  45 "$UPATH" no-tombstone
seed_add  1 "qsat/keep.jsonl.gpg"
seed_push capture/quotedbr
compact_c --retain-days 30 >/dev/null 2>&1
qman="$(bare show capture/quotedbr:.purged)"
assert_contains "tombstone hashes the path with the quote" "$(sha_of "$QPATH")" "$qman"
assert_contains "tombstone hashes the path with non-ASCII" "$(sha_of "$UPATH")" "$qman"
qhist="$(objs "$CBARE" capture/quotedbr)"
assert_not_contains "quoted path gone from history" "repo\"quoted" "$qhist"
assert_not_contains "non-ASCII path gone from history" "repo-çã" "$qhist"

echo "== compact: only the hashed message forms survive a rewrite; dry run counts the rest"
seed_branch capture/legacy
seed_add 60 "lg/$RK/a.jsonl.gpg"
seed_rm  55 "lg/$RK/a.jsonl.gpg"
commit_at 5 "capture: lg/client-repo-key-abc 2026-10-01T00:00:00Z"
commit_at 4 "capture: lg/0123456789ab 2026-10-02T00:00:00Z"
commit_at 3 "capture: lg recovery 2026-10-03T00:00:00Z"
commit_at 3 "purge: 0123456789ab (curated)"
commit_at 2 "purge: 0123456789ab abcdefabcdef (purge-session)"
commit_at 1 "$(printf 'capture: lg/0123456789ab 2026-10-04T00:00:00Z\n\nbody naming client-repo-key-abc')"
seed_push capture/legacy
hlg="$(printf '%s' capture/legacy | sha256sum | cut -c1-12)"
LG_OLD="$(bare rev-parse capture/legacy)"
out="$(compact_c --retain-days 30 --dry-run 2>&1)"
assert_contains "dry run counts the messages it would redact" "redacted=2" "$(printf '%s\n' "$out" | grep "branch=$hlg")"
assert_contains "dry run summary totals them" "messages to redact" "$out"
assert_eq "dry run leaves the messages alone" "$LG_OLD" "$(bare rev-parse capture/legacy)"
compact_c --retain-days 30 >/dev/null 2>&1
lgmsgs="$(bare log --format=%B capture/legacy)"
assert_not_contains "plaintext repo key gone from every message" "client-repo-key-abc" "$lgmsgs"
assert_contains "hashed capture form kept" "capture: lg/0123456789ab 2026-10-02T00:00:00Z" "$lgmsgs"
assert_contains "recovery form kept" "capture: lg recovery 2026-10-03T00:00:00Z" "$lgmsgs"
assert_contains "curated purge form kept" "purge: 0123456789ab (curated)" "$lgmsgs"
assert_contains "purge-session form kept" "purge: 0123456789ab abcdefabcdef (purge-session)" "$lgmsgs"
assert_eq "both offenders replaced" "2" "$(printf '%s\n' "$lgmsgs" | grep -c '^legacy commit (message redacted)$')"

echo "== compact: a failed verification aborts that branch: nothing moved, no undo ref"
seed_branch capture/verifybr
seed_add 50 "vf/$RK/a.jsonl.gpg"
seed_rm  45 "vf/$RK/a.jsonl.gpg"
seed_add  1 "vf/$RK/b.jsonl.gpg"
seed_push capture/verifybr
VF_TIP="$(bare rev-parse capture/verifybr)"
VSHIM="$T_SANDBOX/shim-verify"; mkdir -p "$VSHIM"
cat > "$VSHIM/git" <<EOF
#!/usr/bin/env bash
# The tip-tree comparison in cp_verify reports a path the rewrite should not have changed.
case "\$*" in *diff-tree*) echo unexpected/path; exit 0;; esac
exec "$(command -v git)" "\$@"
EOF
chmod +x "$VSHIM/git"
out="$(PATH="$VSHIM:$PATH" compact_c --retain-days 30 2>&1)"; rc=$?
assert_eq "verification failure still exits 0" "0" "$rc"
assert_contains "reported as verification-failed" "status=skipped:verification-failed" "$out"
assert_eq "the branch did not move" "$VF_TIP" "$(bare rev-parse capture/verifybr)"
assert_eq "no undo ref for it" "" "$(git -C "$CMIRROR" for-each-ref refs/bw/pre-compact/capture/verifybr)"
assert_contains "the failure reaches the health shard" "compact skipped" "$BAILIWICK_HOME/health/central.jsonl"
bare update-ref -d refs/heads/capture/verifybr

echo "== compact: an undo ref older than the window is dropped even with nothing to rewrite"
EMPTY_TREE="$(git -C "$CMIRROR" hash-object -w -t tree /dev/null)"
undo_commit() {  # <days-ago>
  local ts; ts="$(epoch_ago "$1")"
  GIT_AUTHOR_DATE="@$ts +0000" GIT_COMMITTER_DATE="@$ts +0000" git -C "$CMIRROR" commit-tree "$EMPTY_TREE" -m undo
}
git -C "$CMIRROR" update-ref refs/bw/pre-compact/capture/stale "$(undo_commit 40)"
git -C "$CMIRROR" update-ref refs/bw/pre-compact/capture/fresh "$(undo_commit 5)"
# An idle branch's undo ref: the tip is 40 days old, but the ref was made just now.
git -C "$CMIRROR" update-ref refs/bw/pre-compact/capture/justmade "$(undo_commit 40)"
mkdir -p "$CMIRROR/.git/bw-undo-stamp/capture"; date +%s > "$CMIRROR/.git/bw-undo-stamp/capture/justmade"
compact_c --retain-days 30 --dry-run >/dev/null 2>&1
assert_contains "dry run keeps even the old undo ref" "refs/bw/pre-compact/capture/stale" "$(git -C "$CMIRROR" for-each-ref refs/bw/pre-compact/capture/stale)"
out="$(compact_c --retain-days 30 2>&1)"
assert_contains "this run had nothing to rewrite" "rewrote 0" "$out"
assert_eq "old undo ref dropped" "" "$(git -C "$CMIRROR" for-each-ref refs/bw/pre-compact/capture/stale)"
assert_contains "fresh undo ref kept" "refs/bw/pre-compact/capture/fresh" "$(git -C "$CMIRROR" for-each-ref refs/bw/pre-compact/capture/fresh)"
assert_contains "the drop is reported" "old undo refs dropped 1" "$out"
assert_contains "undo ref age counts from its creation, not its tip" "refs/bw/pre-compact/capture/justmade" "$(git -C "$CMIRROR" for-each-ref refs/bw/pre-compact/capture/justmade)"
assert_contains "a rewrite stamps its undo ref" "sat1" "$(ls "$CMIRROR/.git/bw-undo-stamp/capture")"
git -C "$CMIRROR" update-ref -d refs/bw/pre-compact/capture/justmade
git -C "$CMIRROR" update-ref -d refs/bw/pre-compact/capture/fresh

echo "== compact: --retain-days is base 10, capped, and refused before any fetch"
out="$(compact_c --retain-days 010 --dry-run 2>&1)"; rc=$?
assert_eq "010 accepted" "0" "$rc"
assert_contains "010 means ten days, reported normalised" "retain 10d" "$out"
out="$(compact_c --retain-days 08 --dry-run 2>&1)"; rc=$?
assert_eq "08 accepted, not an octal error" "0" "$rc"
assert_contains "08 means eight days, reported normalised" "retain 8d" "$out"
out="$(compact_c --retain-days=3650 --dry-run 2>&1)"; rc=$?
assert_eq "the cap itself is accepted" "0" "$rc"
LSHIM="$T_SANDBOX/shim-log"; mkdir -p "$LSHIM"
cat > "$LSHIM/git" <<EOF
#!/usr/bin/env bash
echo "\$*" >> "$T_SANDBOX/git-calls.log"
exec "$(command -v git)" "\$@"
EOF
chmod +x "$LSHIM/git"
for bad in 99999999999999999999 3651 0 000; do
  : > "$T_SANDBOX/git-calls.log"
  out="$(PATH="$LSHIM:$PATH" compact_c --retain-days "$bad" 2>&1)"; rc=$?
  assert_eq "--retain-days $bad: exit 2" "2" "$rc"
  assert_contains "--retain-days $bad: names the range" "between 1 and 3650" "$out"
  assert_eq "--retain-days $bad: no git call at all" "0" "$(grep -c . "$T_SANDBOX/git-calls.log")"
done

echo "== refresh: central's mirror learns other machines' branches, and nothing else changes"
RFBARE="$T_SANDBOX/refresh.git"; git init -q --bare "$RFBARE"
RFINST="$T_SANDBOX/inst-refresh"; t_make_instance "$RFINST"
RFCACHE="$T_SANDBOX/cache-refresh"; RFMIRROR="$RFCACHE/bailiwick/capture-mirror"
RFSTAMP="$RFMIRROR/.git/bw-pool-refresh"
RFHEALTH="$BAILIWICK_HOME/health/rfcentral.jsonl"
RFPROJ="$T_SANDBOX/proj-refresh"; mkdir -p "$RFPROJ/.bailiwick-outputs/raw"
rf_cfg() {  # <enabled> <ack> <role>
  cat > "$RFINST/.bailiwick-sync.json" <<EOF
{ "role": "$3", "machine": "rfcentral",
  "capture_backup": { "enabled": $1, "confidentiality_ack": $2, "repo": "file://$RFBARE",
    "gpg_recipients": ["$FPR"], "branch": "capture/rfcentral", "throttle_minutes": 0 } }
EOF
}
rf() { XDG_CACHE_HOME="$RFCACHE" CLAUDE_PROJECT_DIR="$RFPROJ" bash "$RFINST/hooks/capture_backup.sh" refresh </dev/null; }
rf_tip() { git -C "$RFMIRROR" rev-parse -q --verify "refs/remotes/origin/capture/$1" 2>/dev/null; }
RFSEED="$T_SANDBOX/refresh-seed"; git init -q -b seed "$RFSEED"
rf_seed() {  # <branch> <file>: a new commit on capture/<branch>, as another machine's push would make
  echo "$2" > "$RFSEED/$2"
  git -C "$RFSEED" add -A
  git -C "$RFSEED" -c user.name=s -c user.email=s@s -c commit.gpgsign=false commit -qm "$2"
  git -C "$RFSEED" push -q -f "file://$RFBARE" "HEAD:refs/heads/capture/$1"
  git -C "$RFBARE" rev-parse "capture/$1"
}

rf_cfg true true central
out="$(rf 2>&1)"; rc=$?
assert_exit "refresh without a mirror exits 0" 0 "$rc"
assert_eq "refresh without a mirror is silent" "" "$out"
assert_no_dir "refresh never creates a mirror" "$RFMIRROR"
assert_no_dir "refresh without a mirror does not even make the cache dir" "$RFCACHE/bailiwick"
assert_no_file "refresh without a mirror attempts no fetch to warn about" "$RFHEALTH"

echo '{"a":1}' > "$RFPROJ/.bailiwick-outputs/raw/own.jsonl"
echo '{"hook_event_name":"SessionEnd"}' | XDG_CACHE_HOME="$RFCACHE" CLAUDE_PROJECT_DIR="$RFPROJ" \
  bash "$RFINST/hooks/capture_backup.sh" push >/dev/null 2>&1
assert_dir "the push created the mirror" "$RFMIRROR/.git"

OTHER1="$(rf_seed other first)"
for gate in "true true satellite:role=satellite" "true false central:no confidentiality_ack" "false true central:disabled"; do
  args="${gate%%:*}"; why="${gate#*:}"
  # shellcheck disable=SC2086
  rf_cfg $args
  out="$(rf 2>&1)"; rc=$?
  assert_exit "refresh skipped ($why) exits 0" 0 "$rc"
  assert_eq "refresh skipped ($why) is silent" "" "$out"
  assert_eq "refresh skipped ($why) fetches nothing" "" "$(rf_tip other)"
  assert_no_file "refresh skipped ($why) writes no stamp" "$RFSTAMP"
done
rf_cfg true true central

echo '{}' > "$T_SANDBOX/.drill-sandbox"
out="$(BW_DRILL_SANDBOX="$T_SANDBOX" XDG_CACHE_HOME="$RFCACHE" CLAUDE_PROJECT_DIR="$RFPROJ" bash "$RFINST/hooks/capture_backup.sh" refresh </dev/null 2>&1)"; rc=$?
assert_exit "drill-foreign refresh exits 0 (spawned by a hook, like push)" 0 "$rc"
assert_eq "drill-foreign refresh is silent" "" "$out"
assert_eq "drill-foreign refresh fetches nothing" "" "$(rf_tip other)"
rm -f "$T_SANDBOX/.drill-sandbox"

mkdir "$RFMIRROR.lock"
out="$(rf 2>&1)"; rc=$?
assert_exit "refresh with a busy mirror exits 0" 0 "$rc"
assert_eq "refresh with a busy mirror is silent" "" "$out"
assert_eq "refresh with a busy mirror fetches nothing" "" "$(rf_tip other)"
rmdir "$RFMIRROR.lock"

before_refs="$(git -C "$RFMIRROR" for-each-ref refs/heads refs/bw)"
before_head="$(git -C "$RFMIRROR" rev-parse HEAD)"
before_remote="$(git -C "$RFBARE" for-each-ref)"
before_status="$(git -C "$RFMIRROR" status --porcelain)"
: > "$T_SANDBOX/git-calls.log"
out="$(PATH="$LSHIM:$PATH" rf 2>/dev/null)"; rc=$?
assert_exit "refresh exits 0" 0 "$rc"
assert_eq "refresh writes nothing to stdout" "" "$out"
assert_eq "refresh brings the other branch's tip" "$OTHER1" "$(rf_tip other)"
assert_eq "local branches untouched" "$before_refs" "$(git -C "$RFMIRROR" for-each-ref refs/heads refs/bw)"
assert_eq "HEAD untouched" "$before_head" "$(git -C "$RFMIRROR" rev-parse HEAD)"
assert_eq "worktree untouched" "$before_status" "$(git -C "$RFMIRROR" status --porcelain)"
assert_eq "the remote is untouched" "$before_remote" "$(git -C "$RFBARE" for-each-ref)"
assert_file "refresh writes its stamp" "$RFSTAMP"
assert_no_dir "refresh releases the lock" "$RFMIRROR.lock"
assert_eq "git is called exactly once" "1" "$(grep -c . "$T_SANDBOX/git-calls.log")"
assert_contains "that call is the capture/* fetch" 'fetch --quiet --no-auto-gc --prune origin +refs/heads/capture/*:refs/remotes/origin/capture/*' "$(cat "$T_SANDBOX/git-calls.log")"

OTHER2="$(rf_seed other second)"
stamp_before="$(cat "$RFSTAMP")"
rf >/dev/null 2>&1
assert_eq "inside the 30-minute window refresh is throttled" "$OTHER1" "$(rf_tip other)"
assert_eq "a throttled refresh leaves the stamp" "$stamp_before" "$(cat "$RFSTAMP")"
echo "$(( $(date +%s) - 29 * 60 ))" > "$RFSTAMP"
rf >/dev/null 2>&1
assert_eq "still throttled at 29 minutes" "$OTHER1" "$(rf_tip other)"
echo "$(( $(date +%s) - 31 * 60 ))" > "$RFSTAMP"
rf >/dev/null 2>&1
assert_eq "past 30 minutes refresh fetches" "$OTHER2" "$(rf_tip other)"
OTHER3="$(rf_seed other third)"
BW_BACKUP_REFRESH_MIN=0 rf >/dev/null 2>&1
assert_eq "the env override shortens the throttle" "$OTHER3" "$(rf_tip other)"
OTHER4="$(rf_seed other fourth)"
echo "$(( $(date +%s) + 86400 ))" > "$RFSTAMP"
rf >/dev/null 2>&1
assert_eq "a stamp from the future does not hold refresh off" "$OTHER4" "$(rf_tip other)"
OTHER5="$(rf_seed other fifth)"
echo garbage > "$RFSTAMP"
rf >/dev/null 2>&1
assert_eq "an unreadable stamp does not hold refresh off" "$OTHER5" "$(rf_tip other)"

rm -f "$RFSTAMP"
OTHER6="$(rf_seed other sixth)"
rf_url="$(git -C "$RFMIRROR" remote get-url origin)"
git -C "$RFMIRROR" remote set-url origin "file://$T_SANDBOX/does-not-exist.git"
out="$(rf 2>&1)"; rc=$?
assert_exit "a failed fetch exits 0" 0 "$rc"
assert_eq "a failed fetch is silent" "" "$out"
assert_no_file "a failed fetch writes no stamp" "$RFSTAMP"
assert_eq "exactly one health warn for the failed fetch" "1" "$(grep -c 'refresh: fetch failed' "$RFHEALTH")"
assert_no_dir "a failed fetch releases the lock" "$RFMIRROR.lock"
git -C "$RFMIRROR" remote set-url origin "$rf_url"
rf >/dev/null 2>&1
assert_eq "the next refresh after a failure recovers" "$OTHER6" "$(rf_tip other)"
assert_file "the stamp returns once a fetch works" "$RFSTAMP"

out="$(bash "$RFINST/hooks/capture_backup.sh" no-such-mode 2>&1 </dev/null)"; rc=$?
assert_exit "an unknown mode still exits 2" 2 "$rc"
assert_contains "the usage line names refresh" "refresh" "$out"

echo "== refresh over a rewritten origin: the next push keeps this machine's unpushed capture"
# The one refresh side effect worth pinning: it can move the own branch's tracking ref to a rewritten
# tip, replacing the last-known tip ensure_mirror keeps. Recovery must still lose nothing.
rf_git() { git -C "$RFMIRROR" -c user.name=t -c user.email=t@t -c commit.gpgsign=false "$@"; }
echo "unpushed" > "$RFMIRROR/rfcentral-unpushed.bin"
rf_git add -A; rf_git commit -qm "local only"
rf_seed rfcentral rewritten >/dev/null
BW_BACKUP_REFRESH_MIN=0 rf >/dev/null 2>&1
assert_eq "refresh moved the own tracking ref to the rewritten tip" "$(git -C "$RFBARE" rev-parse capture/rfcentral)" "$(rf_tip rfcentral)"
echo '{"hook_event_name":"SessionEnd"}' | XDG_CACHE_HOME="$RFCACHE" CLAUDE_PROJECT_DIR="$RFPROJ" \
  bash "$RFINST/hooks/capture_backup.sh" push >/dev/null 2>&1
assert_contains "the unpushed file reaches origin after recovery" "rfcentral-unpushed.bin" "$(git -C "$RFBARE" ls-tree -r --name-only capture/rfcentral)"
assert_contains "the recovery reports overlay" "mirror recovered (overlay)" "$RFHEALTH"

echo "== retire: a curated capture leaves raw/ for raw/.curated/, moved, never deleted"
new_sat retiresat
RT_RAW="$NS_RAW"; RT_CUR="$RT_RAW/.curated"; RT_HEALTH="$BAILIWICK_HOME/health/retiresat.jsonl"
rt_key="$(ns_key)"
rt_rel() { printf 'retiresat/%s/%s.gpg' "$rt_key" "$1"; }
# From the central instance, on purpose: the tombstone reaches this machine through origin's .purged
# only, the exact case of a capture curated on another machine.
rt_purge() { XDG_CACHE_HOME="$CCACHE" bash "$CINST/hooks/capture_backup.sh" purge "$(rt_rel "$1")" >/dev/null 2>&1; }
rt_tree() { git -C "$CBARE" ls-tree -r --name-only capture/retiresat; }
echo 'CURATED-JSONL' > "$RT_RAW/cur.jsonl"; echo 'CURATED-MD' > "$RT_RAW/cur.md"
echo 'KEEP-UNCURATED' > "$RT_RAW/keep.jsonl"
echo 'STILL-ACTIVE' > "$RT_RAW/live.jsonl"
ns_push >/dev/null 2>&1
rt_purge cur.jsonl; rt_purge cur.md; rt_purge live.jsonl
assert_not_contains "the purge reached the remote" "cur.jsonl.gpg" "$(rt_tree)"
assert_eq "this mirror has not seen the tombstones yet" "" "$(cat "$NS_MIRROR/.purged" 2>/dev/null)"
age_minutes "$RT_RAW/cur.jsonl" 120; age_minutes "$RT_RAW/cur.md" 120; age_minutes "$RT_RAW/keep.jsonl" 120
echo 'NEW-CAPTURE' > "$RT_RAW/new1.jsonl"
out="$(ns_push 2>/dev/null)"; rc=$?
assert_exit "the push with retirement exits 0" 0 "$rc"
assert_eq "retirement writes nothing to stdout" "" "$out"
assert_no_file "curated .jsonl left raw/" "$RT_RAW/cur.jsonl"
assert_no_file "curated .md left raw/" "$RT_RAW/cur.md"
assert_eq "curated .jsonl moved intact" "CURATED-JSONL" "$(cat "$RT_CUR/cur.jsonl" 2>/dev/null)"
assert_eq "curated .md moved intact" "CURATED-MD" "$(cat "$RT_CUR/cur.md" 2>/dev/null)"
assert_file "an uncurated capture stays, however old" "$RT_RAW/keep.jsonl"
assert_no_file "an uncurated capture is not retired" "$RT_CUR/keep.jsonl"
assert_file "a capture modified within the hour stays" "$RT_RAW/live.jsonl"
assert_no_file "a capture modified within the hour is not retired" "$RT_CUR/live.jsonl"
assert_contains "the push still carries new work" "new1.jsonl.gpg" "$(rt_tree)"
assert_not_contains "the retired .jsonl is not resurrected" "cur.jsonl.gpg" "$(rt_tree)"
assert_not_contains "the retired .md is not resurrected" "cur.md.gpg" "$(rt_tree)"
assert_not_contains "the recent file is skipped, not re-pushed" "live.jsonl.gpg" "$(rt_tree)"

health_retire="$(grep -E 'retired [0-9]+|could not be retired' "$RT_HEALTH")"
assert_contains "health logs the count" "retired 2 curated capture file(s)" "$health_retire"
assert_not_contains "health names no capture file" "cur." "$health_retire"
assert_not_contains "health names no repo key" "$rt_key" "$(cat "$RT_HEALTH")"
assert_not_contains "health names no project path" "$NS_PROJ" "$(cat "$RT_HEALTH")"
assert_not_contains "health names no blob relpath" "$(rt_rel cur.jsonl)" "$(cat "$RT_HEALTH")"

age_minutes "$RT_RAW/live.jsonl" 59
ns_push >/dev/null 2>&1
assert_file "59 minutes old still stays" "$RT_RAW/live.jsonl"
age_minutes "$RT_RAW/live.jsonl" 120
ns_push >/dev/null 2>&1
assert_no_file "once older than the hour it leaves raw/" "$RT_RAW/live.jsonl"
assert_eq "once older than the hour it is retired" "STILL-ACTIVE" "$(cat "$RT_CUR/live.jsonl" 2>/dev/null)"
assert_not_contains "a retired capture never comes back" "live.jsonl.gpg" "$(rt_tree)"

echo "== retire: content written after its own tombstone is a resumed session, and stays"
echo 'ORIGINAL' > "$RT_RAW/res.jsonl"
ns_push >/dev/null 2>&1
GIT_COMMITTER_DATE="@$(epoch_ago 1) +0000" rt_purge res.jsonl
echo 'RESUMED-NOT-CURATED' > "$RT_RAW/res.jsonl"; age_minutes "$RT_RAW/res.jsonl" 90
ns_push >/dev/null 2>&1
assert_eq "resumed content stays in raw/" "RESUMED-NOT-CURATED" "$(cat "$RT_RAW/res.jsonl" 2>/dev/null)"
assert_no_file "resumed content is not retired" "$RT_CUR/res.jsonl"
rm -f "$RT_RAW/res.jsonl"

echo "== retire: an existing destination is overwritten only by a newer file"
# A resumed session wrote the capture again after it was retired.
echo 'RESUMED-LATER' > "$RT_RAW/cur.jsonl"; age_minutes "$RT_RAW/cur.jsonl" 90
ns_push >/dev/null 2>&1
assert_no_file "the newer capture left raw/" "$RT_RAW/cur.jsonl"
assert_eq "the newer capture replaced the older copy" "RESUMED-LATER" "$(cat "$RT_CUR/cur.jsonl")"
assert_not_contains "the resumed capture is not re-pushed" "cur.jsonl.gpg" "$(rt_tree)"
echo 'OLDER-THAN-DEST' > "$RT_RAW/cur.jsonl"; age_minutes "$RT_RAW/cur.jsonl" 300
ns_push >/dev/null 2>&1
assert_eq "an older source does not overwrite" "RESUMED-LATER" "$(cat "$RT_CUR/cur.jsonl")"
assert_eq "an older source is kept, not deleted" "OLDER-THAN-DEST" "$(cat "$RT_RAW/cur.jsonl")"
assert_contains "health counts the file left in raw" "1 curated capture file(s) could not be retired" "$RT_HEALTH"
rm -f "$RT_RAW/cur.jsonl"

echo "== retire: a move failure never aborts the push"
MVSHIM="$T_SANDBOX/shim-mv"; mkdir -p "$MVSHIM"
cat > "$MVSHIM/mv" <<EOF
#!/usr/bin/env bash
case "\$*" in *.curated*) exit 1;; esac
exec "$(command -v mv)" "\$@"
EOF
chmod +x "$MVSHIM/mv"
echo 'FAIL-MOVE' > "$RT_RAW/failmv.jsonl"
ns_push >/dev/null 2>&1
rt_purge failmv.jsonl
age_minutes "$RT_RAW/failmv.jsonl" 120
echo 'AFTER-FAILED-MOVE' > "$RT_RAW/zz-after.jsonl"
PATH="$MVSHIM:$PATH" ns_push >/dev/null 2>&1; rc=$?
assert_exit "a failed mv: push exits 0" 0 "$rc"
assert_file "a failed mv leaves the source in raw/" "$RT_RAW/failmv.jsonl"
assert_contains "a failed mv: a later file in the same run is still pushed" "zz-after.jsonl.gpg" "$(rt_tree)"
ns_push >/dev/null 2>&1
assert_file "the next push retries the move" "$RT_CUR/failmv.jsonl"
assert_no_file "the retried move empties raw/" "$RT_RAW/failmv.jsonl"
mv "$RT_CUR" "$RT_CUR.bak"; : > "$RT_CUR"
echo 'FAIL-MKDIR' > "$RT_RAW/failmk.jsonl"
ns_push >/dev/null 2>&1
rt_purge failmk.jsonl
age_minutes "$RT_RAW/failmk.jsonl" 120
echo 'AFTER-FAILED-MKDIR' > "$RT_RAW/zz-mkdir.jsonl"
ns_push >/dev/null 2>&1; rc=$?
assert_exit "an unusable .curated: push exits 0" 0 "$rc"
assert_file "an unusable .curated leaves the source in raw/" "$RT_RAW/failmk.jsonl"
assert_contains "an unusable .curated: the rest of the run is pushed" "zz-mkdir.jsonl.gpg" "$(rt_tree)"
rm -f "$RT_CUR"; mv "$RT_CUR.bak" "$RT_CUR"

echo "== retire: a purge_detection: error capture stays where it is, tombstoned or not"
echo '{"x":1}' > "$RT_RAW/heldrt.jsonl"
printf '# Raw capture\n\n- captured: x\n' > "$RT_RAW/heldrt.md"
ns_push >/dev/null 2>&1
rt_purge heldrt.jsonl; rt_purge heldrt.md
printf '# Raw capture\n\n- purge_detection: error\n- captured: x\n' > "$RT_RAW/heldrt.md"
age_minutes "$RT_RAW/heldrt.jsonl" 120; age_minutes "$RT_RAW/heldrt.md" 120
ns_push >/dev/null 2>&1
assert_file "a held .jsonl stays in raw/" "$RT_RAW/heldrt.jsonl"
assert_file "a held .md stays in raw/" "$RT_RAW/heldrt.md"
assert_no_file "a held .jsonl is not retired" "$RT_CUR/heldrt.jsonl"

echo "== retire: a shadow capture goes to its central staging .curated/"
SHPROJ="$T_SANDBOX/proj-shadow"; mkdir -p "$SHPROJ"
sh_key="$(PYTHONPATH="$NS_INST/hooks" python3 -c 'import sys, capture_session; sys.stdout.write(capture_session.repo_key(sys.argv[1]))' "$SHPROJ")"
SHRAW="$BAILIWICK_HOME/captures/$sh_key/raw"; mkdir -p "$SHRAW"
sh_push() { echo '{"hook_event_name":"SessionEnd"}' | BAILIWICK_SHADOW=1 XDG_CACHE_HOME="$NS_CACHE" CLAUDE_PROJECT_DIR="$SHPROJ" bash "$NS_INST/hooks/capture_backup.sh" push; }
echo 'SHADOW-CURATED' > "$SHRAW/sh.jsonl"
sh_push >/dev/null 2>&1
XDG_CACHE_HOME="$CCACHE" bash "$CINST/hooks/capture_backup.sh" purge "retiresat/$sh_key/sh.jsonl.gpg" >/dev/null 2>&1
age_minutes "$SHRAW/sh.jsonl" 120
sh_push >/dev/null 2>&1
assert_no_file "the shadow capture left raw/" "$SHRAW/sh.jsonl"
assert_eq "the shadow capture is in raw/.curated/" "SHADOW-CURATED" "$(cat "$SHRAW/.curated/sh.jsonl" 2>/dev/null)"
assert_no_dir "the seeded path is not created for a shadow repo" "$SHPROJ/.bailiwick-outputs"

t_summary
