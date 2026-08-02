#!/usr/bin/env bash
# Contract tests for scripts/purge_verify.sh — the measurements deep removal depends on.
#
# Two lies this script exists to prevent: claiming "erased" while git history still answers
# `git log -S` (residual mode), and destroying history/keys while un-curated captures exist
# somewhere in the fleet (preflight mode). Both directions are pinned here.
set -u
. "$(dirname "$0")/lib.sh"
t_sandbox

export GH_STUB_ACCOUNTS="alice"
export GH_STUB_CANREAD="tok_alice"

INST="$T_SANDBOX/inst"; t_make_instance "$INST"
mkdir -p "$INST/scripts"
cp "$REPO_ROOT/scripts/purge_verify.sh" "$INST/scripts/"
pv() { bash "$INST/scripts/purge_verify.sh" "$@"; }

git init -q --bare "$T_SANDBOX/holding.git"
cat > "$INST/.bailiwick-sync.json" <<EOF
{ "role": "central", "machine": "pvtest",
  "capture_backup": { "enabled": true, "repo": "file://$T_SANDBOX/holding.git" } }
EOF

echo "== residual: purged from the tree but alive in history is a LOUD hit"
echo "client wombatclient project notes" > "$INST/notes.md"
git -C "$INST" add notes.md && git -C "$INST" -c user.name=t -c user.email=t@l commit -qm "add notes"
git -C "$INST" rm -q notes.md && git -C "$INST" -c user.name=t -c user.email=t@l commit -qm "purge notes"
out="$(pv residual wombatclient)"; rc=$?
assert_exit "history residual -> exit 1" 1 "$rc"
assert_contains "working tree reported clean" "working tree clean" "$out"
assert_contains "history hit named, with the recovery route" "git HISTORY" "$out"

echo "== residual: a token that never existed is clean everywhere"
out="$(pv residual never-was-here)"; rc=$?
assert_exit "unknown token -> exit 0" 0 "$rc"
assert_contains "clean verdict" "clean for the checked surfaces" "$out"

echo "== residual: backup-path finds ciphertext in current trees AND history"
work="$T_SANDBOX/holdwork"
git clone -q "file://$T_SANDBOX/holding.git" "$work" 2>/dev/null || { mkdir -p "$work"; git -C "$work" init -q; git -C "$work" remote add origin "file://$T_SANDBOX/holding.git"; }
git -C "$work" checkout -qb capture/m1
mkdir -p "$work/m1/repo-x"
echo "cipher" > "$work/m1/repo-x/s1.jsonl.gpg"
git -C "$work" add -A && git -C "$work" -c user.name=t -c user.email=t@l commit -qm "capture"
git -C "$work" push -q origin capture/m1
out="$(pv residual wombatclient --backup-path m1/repo-x/)"
assert_contains "blob found in CURRENT backup trees" "still in CURRENT branch trees" "$out"
git -C "$work" rm -q m1/repo-x/s1.jsonl.gpg && git -C "$work" -c user.name=t -c user.email=t@l commit -qm "purge blob" && git -C "$work" push -q origin capture/m1
out="$(pv residual never-was-here --backup-path m1/repo-x/)"; rc=$?
assert_exit "tree-purged blob still fails on HISTORY" 1 "$rc"
assert_contains "backup history hit names crypto-erasure" "crypto-erasure" "$out"

echo "== preflight: pending ciphertext on a capture branch BLOCKS deep removal"
mkdir -p "$work/m1/repo-x"   # the earlier git rm pruned the empty dir
echo "cipher2" > "$work/m1/repo-x/s2.jsonl.gpg"
git -C "$work" add -A && git -C "$work" -c user.name=t -c user.email=t@l commit -qm "capture2" && git -C "$work" push -q origin capture/m1
out="$(pv preflight)"; rc=$?
assert_exit "pending blob -> exit 1" 1 "$rc"
assert_contains "names the branch and the pending count" "pending curation" "$out"

echo "== preflight: local staging pending also blocks"
git -C "$work" rm -q m1/repo-x/s2.jsonl.gpg && git -C "$work" -c user.name=t -c user.email=t@l commit -qm "drain" && git -C "$work" push -q origin capture/m1
mkdir -p "$INST/.bailiwick-inbox/raw"
touch "$INST/.bailiwick-inbox/raw/pending.jsonl"
out="$(pv preflight)"; rc=$?
assert_exit "inbox pending -> exit 1" 1 "$rc"
assert_contains "inbox named" "bailiwick-inbox" "$out"
rm -rf "$INST/.bailiwick-inbox"

echo "== preflight: drained fleet passes, with the per-machine confirm notes"
mkdir -p "$BAILIWICK_HOME/health"
printf '{"ts":"2026-08-01T10:00:00","machine":"m1","component":"x","event":"info","detail":"d"}\n' > "$BAILIWICK_HOME/health/m1.jsonl"
out="$(pv preflight)"; rc=$?
assert_exit "drained -> exit 0" 0 "$rc"
assert_contains "capture branches reported drained" "every capture/* branch is drained" "$out"
assert_contains "known machine listed for manual confirmation" "machine 'm1' last health event" "$out"

t_summary
