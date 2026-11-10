#!/usr/bin/env bash
# Contract tests for hooks/session_start.sh — the hook that fires in EVERY project.
#
# The most dangerous regression is the inert contract: this hook runs in unrelated repos on
# every session, so "unwired => silent exit 0" breaking silently would leak framework banners
# (and knowledge-index content) into projects that never opted in.
set -u
. "$(dirname "$0")/lib.sh"
t_sandbox

export GH_STUB_ACCOUNTS="alice"
export GH_STUB_CANREAD="tok_alice"

INST="$T_SANDBOX/inst"; t_make_instance "$INST"
mkdir -p "$INST/knowledge"
echo "INDEX-SENTINEL-LINE topics/foo.md" > "$INST/knowledge/INDEX.md"
SS="$INST/hooks/session_start.sh"

echo "== unwired repo: inert — exit 0, not one byte of output"
P0="$T_SANDBOX/plain"; mkdir -p "$P0"
out="$(CLAUDE_PROJECT_DIR="$P0" bash "$SS" 2>/dev/null)"; rc=$?
assert_exit "inert exit 0" 0 "$rc"
assert_eq "inert: empty stdout" "" "$out"

echo "== seeded repo: defaults banner + knowledge index injected"
P1="$T_SANDBOX/wired"; mkdir -p "$P1"
printf 'uses $BAILIWICK\n' > "$P1/CLAUDE.local.md"
out="$(CLAUDE_PROJECT_DIR="$P1" bash "$SS" 2>/dev/null)"; rc=$?
assert_exit "wired exit 0" 0 "$rc"
assert_contains "defaults banner present" "Framework defaults active" "$out"
assert_contains "banner makes the lead skill the default for substantial work" "runs under the lead skill by default" "$out"
assert_contains "banner keeps trivial work inline" "trivial single-file edits stay inline" "$out"
assert_contains "knowledge index injected (the map)" "INDEX-SENTINEL-LINE" "$out"

echo "== pending-capture nag counts raw transcripts"
mkdir -p "$P1/.bailiwick-outputs/raw"
touch "$P1/.bailiwick-outputs/raw/a.jsonl" "$P1/.bailiwick-outputs/raw/b.jsonl"
# Written at the real default path, and removed each time: the sync tests below need a clean tree.
CFG="$INST/.bailiwick-sync.json"
CENTRAL_CFG='{"role":"central"}'
run_cfg() {  # <json, or - for no config file> <project>: one session against that config
  rm -f "$CFG"
  [ "$1" = "-" ] || printf '%s\n' "$1" > "$CFG"
  CLAUDE_PROJECT_DIR="$2" bash "$SS" 2>/dev/null
  _rc=$?
  rm -f "$CFG"
  return $_rc
}
LOCAL_ONLY="2 raw session capture(s) are on this machine only and will not reach the central machine"
PENDING="2 raw session capture(s) pending curation"
BACKUP_REMEDY="set capture_backup enabled and confidentiality_ack to true in .bailiwick-sync.json"

out="$(run_cfg "$CENTRAL_CFG" "$P1")"; rc=$?
assert_exit "central: exit 0" 0 "$rc"
assert_contains "central: nag reports 2 pending captures" "$PENDING" "$out"
assert_contains "central: nag still says to run /curate" "Run /curate to review and promote (human-gated)." "$out"
assert_not_contains "central: no local-only warning" "on this machine only" "$out"

echo "== central with backup enabled: still today's nag (backups land here to be curated)"
out="$(run_cfg '{"role":"central","capture_backup":{"enabled":true}}' "$P1")"
assert_contains "central+backup: nag kept" "$PENDING" "$out"

echo "== satellite with backup enabled: silent (the backup carries captures to central)"
out="$(run_cfg '{"role":"satellite","capture_backup":{"enabled":true,"confidentiality_ack":true}}' "$P1")"; rc=$?
assert_exit "satellite+backup: exit 0" 0 "$rc"
assert_contains "satellite+backup: session still starts" "Framework defaults active" "$out"
assert_not_contains "satellite+backup: no pending nag" "pending curation" "$out"
assert_not_contains "satellite+backup: no local-only warning" "on this machine only" "$out"

echo "== satellite with backup off: one line naming both remedies"
out="$(run_cfg '{"role":"satellite","capture_backup":{"enabled":false}}' "$P1")"; rc=$?
assert_exit "satellite, backup off: exit 0" 0 "$rc"
assert_contains "satellite, backup off: says local-only" "$LOCAL_ONLY" "$out"
assert_contains "satellite, backup off: names the backup remedy" "$BACKUP_REMEDY" "$out"
assert_contains "satellite, backup off: names the curate remedy" "or run /curate here" "$out"
assert_not_contains "satellite, backup off: not the central nag" "pending curation" "$out"
assert_eq "satellite, backup off: exactly one line" "1" "$(printf '%s\n' "$out" | grep -c 'on this machine only')"

echo "== satellite enabled without the confidentiality ack: nothing is pushed, so it warns"
out="$(run_cfg '{"role":"satellite","capture_backup":{"enabled":true,"confidentiality_ack":false}}' "$P1")"; rc=$?
assert_exit "satellite, no ack: exit 0" 0 "$rc"
assert_contains "satellite, no ack: says local-only" "$LOCAL_ONLY" "$out"
assert_contains "satellite, no ack: names the ack remedy" "$BACKUP_REMEDY" "$out"
assert_eq "satellite, no ack: exactly one line" "1" "$(printf '%s\n' "$out" | grep -c 'on this machine only')"
out="$(run_cfg '{"role":"satellite","capture_backup":{"enabled":true}}' "$P1")"
assert_contains "satellite, ack absent: same as false" "$LOCAL_ONLY" "$out"
out="$(run_cfg '{"role":"satellite","capture_backup":{"enabled":false,"confidentiality_ack":true}}' "$P1")"
assert_contains "satellite, ack without enabled: still local-only" "$LOCAL_ONLY" "$out"

echo "== config without a role: defaults to satellite, and the nested key decides"
out="$(run_cfg '{"capture_backup":{"enabled":true,"confidentiality_ack":true}}' "$P1")"
assert_not_contains "no role + backup on: silent" "on this machine only" "$out"
out="$(run_cfg '{"machine":"x"}' "$P1")"
assert_contains "no role + no backup block: local-only" "$LOCAL_ONLY" "$out"

echo "== missing or broken config: treated as a satellite without backup, fail-open"
out="$(run_cfg - "$P1")"; rc=$?
assert_exit "missing config: exit 0" 0 "$rc"
assert_contains "missing config: local-only" "$LOCAL_ONLY" "$out"
assert_contains "missing config: index still injected" "INDEX-SENTINEL-LINE" "$out"
out="$(run_cfg 'not json {' "$P1")"; rc=$?
assert_exit "malformed config: exit 0" 0 "$rc"
assert_contains "malformed config: local-only" "$LOCAL_ONLY" "$out"
out="$(run_cfg '{"role":"satellite","capture_backup":"yes"}' "$P1")"; rc=$?
assert_exit "non-object backup block: exit 0" 0 "$rc"
assert_contains "non-object backup block: off, as capture_backup.sh reads it" "$LOCAL_ONLY" "$out"

echo "== BW_CFG_FILE overrides the config path for role and backup alike"
ALT_CFG="$T_SANDBOX/alt-sync.json"
printf '%s\n' '{"role":"satellite","capture_backup":{"enabled":true,"confidentiality_ack":true}}' > "$ALT_CFG"
out="$(BW_CFG_FILE="$ALT_CFG" run_cfg - "$P1")"
assert_not_contains "override: backup read from BW_CFG_FILE" "on this machine only" "$out"
printf '%s\n' "$CENTRAL_CFG" > "$ALT_CFG"
out="$(BW_CFG_FILE="$ALT_CFG" run_cfg - "$P1")"
assert_contains "override: role read from BW_CFG_FILE" "$PENDING" "$out"

echo "== no captures: no nag in any role"
P3="$T_SANDBOX/no-captures"; mkdir -p "$P3/.bailiwick-outputs/raw"
printf 'uses $BAILIWICK\n' > "$P3/CLAUDE.local.md"
out="$(run_cfg - "$P3")"
assert_not_contains "zero captures, satellite: silent" "on this machine only" "$out"
out="$(run_cfg "$CENTRAL_CFG" "$P3")"
assert_not_contains "zero captures, central: silent" "pending curation" "$out"

echo "== shadow-only repo: nag looks at CENTRAL staging via repo_key, not in-repo"
P2="$T_SANDBOX/shadowed"; mkdir -p "$P2" "$BAILIWICK_HOME"
printf '%s\n' "$P2" > "$BAILIWICK_HOME/allowlist"
key="$(PYTHONPATH="$INST/hooks" python3 -c 'import sys, capture_session; sys.stdout.write(capture_session.repo_key(sys.argv[1]))' "$P2")"
mkdir -p "$BAILIWICK_HOME/captures/$key/raw"
touch "$BAILIWICK_HOME/captures/$key/raw/s.jsonl"
out="$(run_cfg "$CENTRAL_CFG" "$P2")"
assert_contains "shadow repo activates" "Framework defaults active" "$out"
assert_contains "nag counts the CENTRALLY staged capture" "1 raw session capture(s) pending curation" "$out"
assert_contains "nag names the central path (writer/nag agreement)" "$BAILIWICK_HOME/captures/$key/raw" "$out"
rm -f "$BAILIWICK_HOME/allowlist"

# ---- central nag counts the backup pool of ALL machines --------------------------------------------
echo "== central+backup: pool of other machines' captures nags (mirror = sandbox XDG_CACHE_HOME)"
MIRROR="$XDG_CACHE_HOME/bailiwick/capture-mirror"
BK_CENTRAL='{"role":"central","capture_backup":{"enabled":true,"confidentiality_ack":true}}'
BK_SAT='{"role":"satellite","capture_backup":{"enabled":true,"confidentiality_ack":true}}'
mg() { git -C "$MIRROR" -c user.name=bw-test -c user.email=test@local "$@"; }
mirror_branch() {  # <machine> <path>...: a remote-tracking capture/<machine> tip holding those files
  local m="$1" f tree; shift
  rm -rf "$MIRROR/.stage"; mkdir -p "$MIRROR/.stage"
  for f in "$@"; do mkdir -p "$MIRROR/.stage/$(dirname "$f")"; : > "$MIRROR/.stage/$f"; done
  GIT_INDEX_FILE="$MIRROR/.git/idx-$m" git -C "$MIRROR" --work-tree="$MIRROR/.stage" add -A >/dev/null
  tree="$(GIT_INDEX_FILE="$MIRROR/.git/idx-$m" git -C "$MIRROR" write-tree)"
  mg update-ref "refs/remotes/origin/capture/$m" "$(mg commit-tree "$tree" -m "$m")"
  rm -rf "$MIRROR/.stage"
}
# Stub the refresh script in the instance (the real one is a copy of hooks/capture_backup.sh).
MARK="$T_SANDBOX/refresh.marker"
printf '#!/usr/bin/env bash\necho "$*" >> "%s"\n' "$MARK" > "$INST/hooks/capture_backup.sh"
wait_mark() { local i=0; while [ ! -s "$MARK" ] && [ $i -lt 50 ]; do sleep 0.1; i=$((i+1)); done; }
PENDING_BASE="2 raw session capture(s) pending curation"

rm -rf "$P1/.bailiwick-outputs/raw"; mkdir -p "$P1/.bailiwick-outputs/raw"
git init -q "$MIRROR"
mirror_branch laptop s1.jsonl.gpg s2.jsonl.gpg health/x.jsonl.gpg notes.txt
mirror_branch desktop s3.jsonl.gpg
rm -f "$MARK"
out="$(run_cfg "$BK_CENTRAL" "$P1")"; rc=$?
assert_exit "pool: exit 0" 0 "$rc"
assert_contains "pool, empty local: counts 3 across branches, excluding health/" "3 capture(s) pending curation (backup, all machines: 3; this repo, local: 0). Run /curate to review and promote (human-gated)." "$out"
wait_mark
assert_contains "central+backup (count 0 locally): refresh spawned" "refresh" "$(cat "$MARK" 2>/dev/null)"

touch "$P1/.bailiwick-outputs/raw/a.jsonl" "$P1/.bailiwick-outputs/raw/b.jsonl"
out="$(run_cfg "$BK_CENTRAL" "$P1")"
assert_contains "pool 3 + local 2: N is the larger" "3 capture(s) pending curation (backup, all machines: 3; this repo, local: 2)." "$out"
mirror_branch desktop s3.jsonl.gpg health/h.jsonl.gpg
mirror_branch laptop s1.jsonl.gpg health/y.jsonl.gpg
out="$(run_cfg "$BK_CENTRAL" "$P1")"
assert_contains "pool 2 + local 2: N=2" "2 capture(s) pending curation (backup, all machines: 2; this repo, local: 2)." "$out"
mirror_branch desktop health/h.jsonl.gpg; mirror_branch laptop health/y.jsonl.gpg
out="$(run_cfg "$BK_CENTRAL" "$P1")"
assert_contains "pool only health/: today's message" "$PENDING in" "$out"
assert_not_contains "pool only health/: no pool wording" "backup, all machines" "$out"

echo "== pool: nothing extra on stdout when idle; no mirror = today's message"
rm -rf "$P1/.bailiwick-outputs/raw"; mkdir -p "$P1/.bailiwick-outputs/raw"
out="$(run_cfg "$BK_CENTRAL" "$P1")"
assert_not_contains "empty pool, no local: silent" "pending curation" "$out"
mv "$MIRROR" "$MIRROR.off"
touch "$P1/.bailiwick-outputs/raw/a.jsonl" "$P1/.bailiwick-outputs/raw/b.jsonl"
rm -f "$MARK"
out="$(run_cfg "$BK_CENTRAL" "$P1")"
assert_contains "no mirror: today's message" "$PENDING in" "$out"
assert_not_contains "no mirror: no pool wording" "backup, all machines" "$out"
wait_mark
assert_contains "no mirror: refresh still spawned (and exits quietly)" "refresh" "$(cat "$MARK" 2>/dev/null)"
mv "$MIRROR.off" "$MIRROR"

echo "== pool: satellite and central-without-backup neither count nor spawn"
mirror_branch laptop s1.jsonl.gpg s2.jsonl.gpg s9.jsonl.gpg
rm -f "$MARK"
out="$(run_cfg "$BK_SAT" "$P1")"
assert_not_contains "satellite: no pool nag" "pending curation" "$out"
out="$(run_cfg "$CENTRAL_CFG" "$P1")"
assert_contains "central, backup off: today's message" "$PENDING in" "$out"
assert_not_contains "central, backup off: no pool wording" "backup, all machines" "$out"
sleep 0.5
assert_eq "satellite / backup off: refresh never spawned" "" "$(cat "$MARK" 2>/dev/null)"

echo "== pool: a failing or hanging refresh script cannot leak output or delay the session"
printf '#!/usr/bin/env bash\necho NOISE; echo ERR >&2; sleep 5; exit 1\n' > "$INST/hooks/capture_backup.sh"
t0=$(date +%s)
out="$(run_cfg "$BK_CENTRAL" "$P1")"; rc=$?
assert_exit "slow failing refresh: exit 0" 0 "$rc"
assert_not_contains "refresh output never reaches SessionStart" "NOISE" "$out"
assert_not_contains "refresh stderr never reaches SessionStart" "ERR" "$out"
assert_eq "session did not wait for refresh" "1" "$([ $(( $(date +%s) - t0 )) -lt 4 ] && echo 1 || echo 0)"
rm -f "$INST/hooks/capture_backup.sh"
out="$(run_cfg "$BK_CENTRAL" "$P1")"; rc=$?
assert_exit "missing refresh script: exit 0" 0 "$rc"
assert_contains "missing refresh script: nag still shown" "capture(s) pending curation" "$out"

echo "== pool: a corrupt mirror is harmless"
rm -rf "$MIRROR"; mkdir -p "$MIRROR/.git"; echo garbage > "$MIRROR/.git/HEAD"
out="$(run_cfg "$BK_CENTRAL" "$P1")"; rc=$?
assert_exit "corrupt mirror: exit 0" 0 "$rc"
assert_contains "corrupt mirror: today's message" "$PENDING in" "$out"
assert_not_contains "corrupt mirror: no git noise" "fatal" "$out"
rm -rf "$MIRROR"
git -C "$INST" checkout -q -- hooks/capture_backup.sh
rm -rf "$P1/.bailiwick-outputs/raw"; mkdir -p "$P1/.bailiwick-outputs/raw"

# ---- inbound sync: the satellite self-heal (#37) ------------------------------------------------
# sync_knowledge.sh leaves a satellite on sync/<machine>; SessionStart only fast-forwards main, so
# without the heal a clone stops receiving knowledge after its first sync — silently.
g() { git -C "$INST" -c user.name=bw-test -c user.email=test@local "$@"; }
CENTRAL="$T_SANDBOX/central"
g add -A && g commit -qm "index" && g push -q origin main  # a clean tree is a heal precondition
git clone -q -b main "file://$INST.origin.git" "$CENTRAL"
gc() { git -C "$CENTRAL" -c user.name=bw-test -c user.email=test@local "$@"; }
satellite_sync() {  # <name>: curate one note on sync/sstest and push it, as sync_knowledge.sh does
  g checkout -q -B sync/sstest
  echo "fact" > "$INST/$1.md"; g add "$1.md"; g commit -qm "knowledge: $1"
  g push -q -f origin sync/sstest
}
# Run from a DECOY repo whose FETCH_HEAD is fresh: the hook used to stat a cwd-relative
# .git/FETCH_HEAD — the project's — and skip fetching the framework clone (#37 regression).
DECOY="$T_SANDBOX/decoy"; git init -q "$DECOY"; touch "$DECOY/.git/FETCH_HEAD"
session() { rm -f "$INST/.git/FETCH_HEAD"; touch "$DECOY/.git/FETCH_HEAD"; (cd "$DECOY" && CLAUDE_PROJECT_DIR="$P1" bash "$SS" 2>/dev/null); }

echo "== unmerged sync branch: stay on it (the curated knowledge must stay visible)"
satellite_sync note-a
out="$(session)"
assert_eq "still on sync/sstest" "sync/sstest" "$(git -C "$INST" branch --show-current)"
assert_not_contains "no premature switch" "switched the framework clone back to main" "$out"

echo "== central merges with a merge commit: switch back to main and fast-forward"
gc fetch -q origin && gc merge -q --no-ff -m "merge sync" origin/sync/sstest && gc push -q origin main
out="$(session)"
assert_eq "back on main" "main" "$(git -C "$INST" branch --show-current)"
assert_contains "announces the switch" "switched the framework clone back to main" "$out"
assert_eq "main fast-forwarded to origin/main" "$(git -C "$CENTRAL" rev-parse HEAD)" "$(git -C "$INST" rev-parse HEAD)"

echo "== central rebase-merges (new SHAs): patch-equivalence still counts as merged"
satellite_sync note-b
gc fetch -q origin && gc cherry-pick origin/sync/sstest >/dev/null && gc push -q origin main
out="$(session)"
assert_eq "back on main after a rebase merge" "main" "$(git -C "$INST" branch --show-current)"
assert_eq "main fast-forwarded past the rebased commit" "$(git -C "$CENTRAL" rev-parse HEAD)" "$(git -C "$INST" rev-parse HEAD)"

echo "== central squash-merges SEVERAL commits: recognised by content, not by patch"
g checkout -q -B sync/sstest
for n in note-s1 note-s2; do echo "fact" > "$INST/$n.md"; g add "$n.md"; g commit -qm "knowledge: $n"; done
g push -q -f origin sync/sstest
gc fetch -q origin && gc merge -q --squash origin/sync/sstest && gc commit -qm "squash sync" && gc push -q origin main
out="$(session)"
assert_eq "back on main after a multi-commit squash" "main" "$(git -C "$INST" branch --show-current)"
assert_eq "main fast-forwarded past the squash" "$(git -C "$CENTRAL" rev-parse HEAD)" "$(git -C "$INST" rev-parse HEAD)"

echo "== multi-commit squash, then central edits one file: content differs, so stay (fail safe)"
g checkout -q -B sync/sstest
for n in note-t note-u; do echo "fact" > "$INST/$n.md"; g add "$n.md"; g commit -qm "knowledge: $n"; done
g push -q -f origin sync/sstest
gc fetch -q origin && gc merge -q --squash origin/sync/sstest && gc commit -qm "squash sync"
echo "edited on central" >> "$CENTRAL/note-t.md"; gc commit -qam "central edit" && gc push -q origin main
out="$(session)"
assert_eq "stays on sync/sstest when content cannot prove the merge" "sync/sstest" "$(git -C "$INST" branch --show-current)"
g checkout -q main && g merge -q --ff-only origin/main  # manual recovery, as documented

echo "== merged but uncommitted changes: never switch under the user's edits"
satellite_sync note-c
gc fetch -q origin && gc merge -q --no-ff -m "merge sync" origin/sync/sstest && gc push -q origin main
echo "wip" >> "$INST/note-c.md"
out="$(session)"
assert_eq "dirty tree stays on sync/sstest" "sync/sstest" "$(git -C "$INST" branch --show-current)"
assert_contains "still reports being behind" "behind origin/main (on sync/sstest, uncommitted)" "$out"
g checkout -q -- note-c.md

t_summary
