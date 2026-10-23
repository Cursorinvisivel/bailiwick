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
assert_contains "knowledge index injected (the map)" "INDEX-SENTINEL-LINE" "$out"

echo "== pending-capture nag counts raw transcripts"
mkdir -p "$P1/.bailiwick-outputs/raw"
touch "$P1/.bailiwick-outputs/raw/a.jsonl" "$P1/.bailiwick-outputs/raw/b.jsonl"
out="$(CLAUDE_PROJECT_DIR="$P1" bash "$SS" 2>/dev/null)"
assert_contains "nag reports 2 pending captures" "2 raw session capture(s) pending curation" "$out"

echo "== shadow-only repo: nag looks at CENTRAL staging via repo_key, not in-repo"
P2="$T_SANDBOX/shadowed"; mkdir -p "$P2" "$BAILIWICK_HOME"
printf '%s\n' "$P2" > "$BAILIWICK_HOME/allowlist"
key="$(PYTHONPATH="$INST/hooks" python3 -c 'import sys, capture_session; sys.stdout.write(capture_session.repo_key(sys.argv[1]))' "$P2")"
mkdir -p "$BAILIWICK_HOME/captures/$key/raw"
touch "$BAILIWICK_HOME/captures/$key/raw/s.jsonl"
out="$(CLAUDE_PROJECT_DIR="$P2" bash "$SS" 2>/dev/null)"
assert_contains "shadow repo activates" "Framework defaults active" "$out"
assert_contains "nag counts the CENTRALLY staged capture" "1 raw session capture(s) pending curation" "$out"
assert_contains "nag names the central path (writer/nag agreement)" "$BAILIWICK_HOME/captures/$key/raw" "$out"
rm -f "$BAILIWICK_HOME/allowlist"

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
