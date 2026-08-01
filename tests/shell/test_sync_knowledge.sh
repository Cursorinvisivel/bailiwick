#!/usr/bin/env bash
# Contract tests for hooks/sync_knowledge.sh — outbound propagation, exit codes, ADR-009.
#
# Exit-code contract (script header): 0 synced / nothing to do; 1 push refused or failed;
# 2 satellite push succeeded but PR creation failed (knowledge stranded until a PR exists).
set -u
. "$(dirname "$0")/lib.sh"
t_sandbox

export GH_STUB_ACCOUNTS="alice"
export GH_STUB_CANREAD="tok_alice"

new_inst() {  # fresh instance + bare origin; prints instance dir
  local inst="$T_SANDBOX/inst$1"
  t_make_instance "$inst" >/dev/null
  printf '%s' "$inst"
}
commit_knowledge() {  # <inst> <name>
  echo "fact" > "$1/$2.md"
  git -C "$1" add -A && git -C "$1" -c user.name=bw-test -c user.email=test@local commit -qm "knowledge: $2"
}
HEALTH_DIR="$BAILIWICK_HOME/health"

echo "== nothing to propagate"
I="$(new_inst 0)"
out="$(bash "$I/hooks/sync_knowledge.sh" 2>&1)"; rc=$?
assert_exit "no-op exits 0" 0 "$rc"
assert_contains "says nothing to propagate" "nothing to propagate" "$out"

echo "== central: pushes HEAD straight to origin/main"
I="$(new_inst 1)"
echo '{ "role": "central", "machine": "ctest" }' > "$I/.bailiwick-sync.json"
commit_knowledge "$I" topic-a
out="$(bash "$I/hooks/sync_knowledge.sh" 2>&1)"; rc=$?
assert_exit "central sync exits 0" 0 "$rc"
assert_eq "origin/main advanced" "$(git -C "$I" rev-parse HEAD)" "$(git -C "$I" ls-remote "file://$I.origin.git" main | cut -f1)"

echo "== satellite: parks on sync/<machine>, opens a PR, resets local main"
I="$(new_inst 2)"
echo '{ "role": "satellite", "machine": "sattest" }' > "$I/.bailiwick-sync.json"
commit_knowledge "$I" topic-b
rm -f "$GH_STUB_LOG"
out="$(bash "$I/hooks/sync_knowledge.sh" 2>&1)"; rc=$?
assert_exit "satellite sync exits 0" 0 "$rc"
assert_eq "sync/sattest pushed to origin" "$(git -C "$I" rev-parse HEAD)" "$(git -C "$I" ls-remote "file://$I.origin.git" sync/sattest | cut -f1)"
assert_eq "local main reset to origin/main" "$(git -C "$I" rev-parse main)" "$(git -C "$I" ls-remote "file://$I.origin.git" main | cut -f1)"
assert_contains "PR created via the resolved account with an explicit --repo" "pr create --repo" "$GH_STUB_LOG"

echo "== satellite: PR creation failure is LOUD and exits 2 (the stranding contract)"
I="$(new_inst 3)"
echo '{ "role": "satellite", "machine": "sattest" }' > "$I/.bailiwick-sync.json"
commit_knowledge "$I" topic-c
export GH_STUB_PR_CREATE_RC=1
out="$(bash "$I/hooks/sync_knowledge.sh" 2>&1)"; rc=$?
unset GH_STUB_PR_CREATE_RC
assert_exit "pr-create failure exits 2" 2 "$rc"
assert_contains "stderr names the stranding consequence" "STRANDED" "$out"
assert_contains "stderr gives the exact manual command" "gh pr create" "$out"
assert_contains "health logs an error (not a quiet warn)" '"event":"error"' "$HEALTH_DIR/sattest.jsonl"
assert_eq "commits are still durably pushed despite exit 2" "$(git -C "$I" rev-parse HEAD)" "$(git -C "$I" ls-remote "file://$I.origin.git" sync/sattest | cut -f1)"

echo "== satellite: existing open PR is reused, not duplicated"
I="$(new_inst 4)"
echo '{ "role": "satellite", "machine": "sattest" }' > "$I/.bailiwick-sync.json"
commit_knowledge "$I" topic-d
export GH_STUB_PR_LIST="7"
rm -f "$GH_STUB_LOG"
out="$(bash "$I/hooks/sync_knowledge.sh" 2>&1)"; rc=$?
unset GH_STUB_PR_LIST
assert_exit "reuse path exits 0" 0 "$rc"
assert_contains "reports the open PR" "PR #7 already open" "$out"
assert_not_contains "no duplicate pr create call" "pr create" "$GH_STUB_LOG"

echo "== ADR-009: a public-origin clone refuses to propagate (commits stay local)"
I="$(new_inst 5)"
echo '{ "role": "central", "machine": "ctest" }' > "$I/.bailiwick-sync.json"
commit_knowledge "$I" topic-e
slug="$(cd "$I" && . hooks/public_origin.sh && bw_origin_slug .)"
before="$(git -C "$I" ls-remote "file://$I.origin.git" main | cut -f1)"
out="$(BW_CANONICAL_SLUG="$slug" bash "$I/hooks/sync_knowledge.sh" 2>&1)"; rc=$?
assert_exit "public-origin propagation refused with exit 1" 1 "$rc"
assert_contains "refusal is explicit" "REFUSED" "$out"
assert_eq "origin/main NOT advanced (knowledge never published)" "$before" "$(git -C "$I" ls-remote "file://$I.origin.git" main | cut -f1)"

echo "== ADR-009 layer 2: a public FORK origin (not the canonical slug) is refused"
I="$(new_inst 6)"
echo '{ "role": "central", "machine": "ctest" }' > "$I/.bailiwick-sync.json"
commit_knowledge "$I" topic-f
before="$(git -C "$I" ls-remote "file://$I.origin.git" main | cut -f1)"
out="$(GH_STUB_API_JSON=false bash "$I/hooks/sync_knowledge.sh" 2>&1)"; rc=$?
assert_exit "public fork origin refused with exit 1" 1 "$rc"
assert_contains "names the public-repo reason" "PUBLIC GitHub repository" "$out"
assert_eq "origin/main NOT advanced" "$before" "$(git -C "$I" ls-remote "file://$I.origin.git" main | cut -f1)"

echo "== ADR-009 override: allow_public_push permits the maintainer seed-update path"
I="$(new_inst 7)"
echo '{ "role": "central", "machine": "ctest", "allow_public_push": true }' > "$I/.bailiwick-sync.json"
commit_knowledge "$I" topic-g
out="$(GH_STUB_API_JSON=false bash "$I/hooks/sync_knowledge.sh" 2>&1)"; rc=$?
assert_exit "override lets central push" 0 "$rc"
assert_eq "origin/main advanced under the override" "$(git -C "$I" rev-parse HEAD)" "$(git -C "$I" ls-remote "file://$I.origin.git" main | cut -f1)"

echo "== public_origin.sh standalone check: exit 3 on a canonical-slug clone"
I="$(new_inst 8)"
slug="$(cd "$I" && . hooks/public_origin.sh && bw_origin_slug .)"
BW_CANONICAL_SLUG="$slug" bash "$I/hooks/public_origin.sh" check >/dev/null 2>&1
assert_exit "check exits 3 (contribute-only)" 3 "$?"
bash "$I/hooks/public_origin.sh" check >/dev/null 2>&1
assert_exit "check exits 0 on a private-origin clone" 0 "$?"

t_summary
