#!/usr/bin/env bash
# Contract tests for hooks/gh_account.sh — account resolution + per-call token pinning.
# All gh behavior comes from tests/shell/stub-bin/gh (offline, env-driven).
set -u
. "$(dirname "$0")/lib.sh"
t_sandbox

INST="$T_SANDBOX/inst"
mkdir -p "$INST"
git -C "$INST" init -q -b main
git -C "$INST" remote add origin "git@github-teststub:TestOwner/testrepo.git"

resolve() {  # runs resolution in a subshell, prints the outcome fields
  ( . "$REPO_ROOT/hooks/gh_account.sh"
    bw_resolve_gh_account "$INST"
    printf 'USER=%s|HOST=%s|REPO=%s|DECIDED=%s|WARN=%s\n' \
      "$BW_GH_USER" "$BW_GH_HOST" "$BW_GH_REPO" "$BW_GH_DECIDED" "$BW_GH_WARN" )
}

echo "== probe: exactly one account can read the repo"
export GH_STUB_ACCOUNTS="alice"
export GH_STUB_CANREAD="tok_alice"
out="$(resolve)"
assert_contains "single-match probe picks alice" "USER=alice" "$out"
assert_contains "decided via probe" "DECIDED=probe" "$out"
assert_contains "owner/repo parsed from SSH-alias remote" "REPO=TestOwner/testrepo" "$out"

echo "== probe: nobody can read the repo -> unresolved, callers degrade to bare gh"
export GH_STUB_CANREAD=""
out="$(resolve)"
assert_contains "no access -> empty user" "USER=|" "$out"

echo "== probe: ambiguous -> active account wins, warn points at the map"
export GH_STUB_ACCOUNTS="alice bob"
export GH_STUB_CANREAD="tok_alice tok_bob"
out="$(resolve)"
assert_contains "active account wins the tie" "USER=alice" "$out"
assert_contains "flagged ambiguous" "DECIDED=ambiguous" "$out"
assert_contains "warn names github_account_map" "github_account_map" "$out"

echo "== override: config github_account is honoured without an access probe"
cat > "$INST/.bailiwick-sync.json" <<'EOF'
{ "github_account": "bob" }
EOF
out="$(resolve)"
assert_contains "override picks bob" "USER=bob" "$out"
assert_contains "decided via override" "DECIDED=override" "$out"

echo "== override with no usable token falls back to the probe, with a warning"
export GH_STUB_NOTOKEN="bob"
export GH_STUB_CANREAD="tok_alice"
out="$(resolve)"
assert_contains "fell back to the probed account" "USER=alice" "$out"
assert_contains "warns about the dead override" "no token" "$out"
unset GH_STUB_NOTOKEN

echo "== account map: owner -> login"
cat > "$INST/.bailiwick-sync.json" <<'EOF'
{ "github_account_map": { "TestOwner": "bob" } }
EOF
out="$(resolve)"
assert_contains "map picks bob for TestOwner" "USER=bob" "$out"
assert_contains "decided via account-map" "DECIDED=account-map" "$out"

echo "== BW_NO_GH_AUTH=1 skips resolution entirely"
out="$(BW_NO_GH_AUTH=1 resolve)"
assert_contains "skip leaves user empty" "USER=|" "$out"
assert_contains "skip leaves repo empty" "REPO=|" "$out"

echo "== bw_gh pins the resolved account's token on every call"
rm -f "$GH_STUB_LOG"
( . "$REPO_ROOT/hooks/gh_account.sh"
  bw_resolve_gh_account "$INST"
  bw_gh api repos/TestOwner/testrepo >/dev/null 2>&1 || true )
assert_contains "gh api ran with the pinned token" "GH_TOKEN=tok_bob :: api" "$GH_STUB_LOG"

t_summary
