#!/usr/bin/env bash
# Contract tests for the ADR-009 Amendment 1 split: cached banner / live enforcement.
#
# The security ruling's constraint 1 is the critical one — the cache must be reachable ONLY from
# the banner path (BW_PO_CACHE=1). The regression that would matter most is an enforcement call
# silently riding a stale "private" verdict; case (e) below pins that it never does.
set -u
. "$(dirname "$0")/lib.sh"
t_sandbox

export GH_STUB_ACCOUNTS="alice"
export GH_STUB_CANREAD="tok_alice"

INST="$T_SANDBOX/inst"; t_make_instance "$INST"
URL="$(git -C "$INST" remote get-url origin)"
CACHE_DIR="$BAILIWICK_HOME/cache"

banner_block() {  # runs the block exactly as session_start does (cache on, 5s timeout)
  ( cd "$INST" && . hooks/public_origin.sh && BW_PO_CACHE=1 BW_PO_TIMEOUT=5 bw_public_origin_block "$INST" )
}
api_calls() { grep -c ":: api" "$GH_STUB_LOG" 2>/dev/null || true; }

echo "== (a) private verdict is cached; a fresh cache skips the probe"
rm -f "$GH_STUB_LOG"
GH_STUB_API_JSON=true banner_block >/dev/null; rc=$?
assert_exit "private origin -> no block" 1 "$rc"
assert_eq "first call probed" "1" "$(api_calls)"
cache="$(find "$CACHE_DIR" -name 'public-origin-*' 2>/dev/null | head -1)"
assert_eq "negative verdict cached, fixed token" "private" "$(sed -n 1p "${cache:-/dev/null}" 2>/dev/null)"
assert_eq "cache keyed by the exact origin URL" "$URL" "$(sed -n 2p "${cache:-/dev/null}" 2>/dev/null)"
perms="$(stat -c %a "$cache" 2>/dev/null || stat -f %Lp "$cache" 2>/dev/null)"
assert_eq "cache file is 0600" "600" "$perms"
GH_STUB_API_JSON=true banner_block >/dev/null
assert_eq "second call served from cache — NO new probe" "1" "$(api_calls)"

echo "== (b) expired cache probes again"
touch_old() {  # portable mtime-backdate (GNU + BSD touch)
  touch -d '@1' "$1" 2>/dev/null || touch -t 202001010000 "$1"
}
touch_old "$cache"
GH_STUB_API_JSON=true banner_block >/dev/null
assert_eq "expired entry -> probe re-fired" "2" "$(api_calls)"

echo "== (c) origin URL change is a cache miss"
printf 'private\nsome-other-url\n' > "$cache"
GH_STUB_API_JSON=true banner_block >/dev/null
assert_eq "url mismatch -> probe re-fired" "3" "$(api_calls)"

echo "== (d) malformed cache is a miss"
printf 'GARBAGE CONTENT\n' > "$cache"
GH_STUB_API_JSON=true banner_block >/dev/null
assert_eq "malformed entry -> probe re-fired" "4" "$(api_calls)"

echo "== (e) CRITICAL: enforcement ('check' entry point) probes live even with a warm cache"
GH_STUB_API_JSON=true banner_block >/dev/null   # rewarm the cache (call 5)
rm -f "$GH_STUB_LOG"
GH_STUB_API_JSON=true bash "$INST/hooks/public_origin.sh" check >/dev/null 2>&1
assert_exit "check: private origin -> exit 0 (safe)" 0 "$?"
assert_eq "check IGNORED the warm cache and probed live" "1" "$(api_calls)"
GH_STUB_API_JSON=false bash "$INST/hooks/public_origin.sh" check >/dev/null 2>&1
assert_exit "check: repo flipped public -> refused IMMEDIATELY despite warm cache" 3 "$?"

echo "== (f) 'public' is NEVER cached — the banner re-warns every session"
rm -f "$CACHE_DIR"/public-origin-* "$GH_STUB_LOG"
GH_STUB_API_JSON=false banner_block >/dev/null; rc=$?
assert_exit "public origin -> block (banner shows)" 0 "$rc"
assert_eq "no cache entry written for a public verdict" "" "$(find "$CACHE_DIR" -name 'public-origin-*' 2>/dev/null | head -1)"
GH_STUB_API_JSON=false banner_block >/dev/null
assert_eq "public verdict re-probed every call" "2" "$(api_calls)"

echo "== (g) probe timeout: fail-open, nothing cached, health warn at the enforcement site"
rm -f "$CACHE_DIR"/public-origin-* "$BAILIWICK_HOME/health"/*.jsonl 2>/dev/null
out="$(cd "$INST" && . hooks/health_common.sh && . hooks/public_origin.sh \
  && GH_STUB_SLEEP=3 BW_PO_TIMEOUT=1 BW_PO_HEALTH_COMPONENT=sync_knowledge bw_public_origin_block "$INST"; echo "rc=$?")"
assert_contains "timeout fails open (no block)" "rc=1" "$out"
assert_eq "timeout result never cached" "" "$(find "$CACHE_DIR" -name 'public-origin-*' 2>/dev/null | head -1)"
assert_contains "degradation visible in the health log" "probe timed out" \
  "$(cat "$BAILIWICK_HOME"/health/*.jsonl 2>/dev/null)"

t_summary
