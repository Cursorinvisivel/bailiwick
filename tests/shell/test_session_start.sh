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

t_summary
