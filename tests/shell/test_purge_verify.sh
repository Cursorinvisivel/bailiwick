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

echo "== residual: a multi-word token is ONE phrase, not one hit per word"
out="$(pv residual "wombatclient zebrafoo")"; rc=$?
assert_exit "absent phrase is clean although one of its words is in history -> exit 0" 0 "$rc"
assert_contains "phrase reported whole" "'wombatclient zebrafoo': git history clean" "$out"

echo "== residual: a token with a regex metacharacter is a literal (no git error read as clean)"
echo "ticket acme[x] open" > "$INST/meta.md"
git -C "$INST" add meta.md && git -C "$INST" -c user.name=t -c user.email=t@l commit -qm "add meta"
out="$(pv residual "acme[x]")"; rc=$?
assert_exit "'[' token found in the working tree -> exit 1" 1 "$rc"
assert_contains "literal working-tree hit" "'acme[x]': 1 working-tree file(s) still match" "$out"

echo "== residual: --tokens-file reads one token per line (no token on the command line)"
printf 'acme[x]\n\nnever-was-here\r\n' > "$T_SANDBOX/tokens"
out="$(pv residual --tokens-file "$T_SANDBOX/tokens")"; rc=$?
assert_exit "tokens-file hit -> exit 1" 1 "$rc"
assert_contains "first token checked, by index" "token #1: 1 working-tree file(s)" "$out"
assert_contains "CRLF stripped, second token checked" "token #2: working tree clean" "$out"
assert_not_contains "file-sourced tokens never printed" "acme[x]" "$out"
git -C "$INST" rm -q meta.md && git -C "$INST" -c user.name=t -c user.email=t@l commit -qm "drop meta"

echo "== residual: a short token matches on alphanumeric boundaries only (never inside a word)"
echo "loading the radius module" > "$INST/words.md"
git -C "$INST" add words.md && git -C "$INST" -c user.name=t -c user.email=t@l commit -qm "add words"
out="$(pv residual adi)"; rc=$?
assert_exit "'adi' inside words is not a residual -> exit 0" 0 "$rc"
echo "the ADI rollout (adi-prod)" > "$INST/abbr.md"
git -C "$INST" add abbr.md && git -C "$INST" -c user.name=t -c user.email=t@l commit -qm "add abbr"
out="$(pv residual adi)"; rc=$?
assert_exit "standalone short token is a residual -> exit 1" 1 "$rc"
assert_contains "boundary rule named" "boundary match" "$out"
assert_contains "short-token history hit via -G" "git HISTORY" "$out"
git -C "$INST" rm -q words.md abbr.md && git -C "$INST" -c user.name=t -c user.email=t@l commit -qm "drop words"

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

echo "== preflight: a leftover purge-work/ (tokens of an unfinished /purge) blocks, without naming its files"
mkdir -p "$BAILIWICK_HOME/purge-work/deleted"
printf 'wombatclient\n' > "$BAILIWICK_HOME/purge-work/tokens"
touch "$BAILIWICK_HOME/purge-work/deleted/wombatclient-notes.md"
out="$(pv preflight)"; rc=$?
assert_exit "leftover purge-work -> exit 1" 1 "$rc"
assert_contains "leftover named with its file count" "leftover purge-work/ under" "$out"
assert_contains "file count reported" "(2 file(s)" "$out"
assert_not_contains "no token-bearing file name printed" "wombatclient" "$out"
rm -rf "$BAILIWICK_HOME/purge-work"

echo "== preflight: drained fleet passes, with the per-machine confirm notes"
mkdir -p "$BAILIWICK_HOME/health"
printf '{"ts":"2026-08-01T10:00:00","machine":"m1","component":"x","event":"info","detail":"d"}\n' > "$BAILIWICK_HOME/health/m1.jsonl"
out="$(pv preflight)"; rc=$?
assert_exit "drained -> exit 0" 0 "$rc"
assert_contains "capture branches reported drained" "every capture/* branch is drained" "$out"
assert_contains "known machine listed for manual confirmation" "machine 'm1' last health event" "$out"

t_summary
