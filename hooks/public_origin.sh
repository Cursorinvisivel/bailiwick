#!/usr/bin/env bash
# bailiwick — ADR-009 public-origin detection (contribute-only instances).
#
# A user's instance of the framework is private by nature: knowledge/ is TRACKED in git, so
# whichever remote `origin` points at is where curated (possibly client-derived) knowledge lands.
# A clone whose origin is the public OSS repo — or any public fork of it — is CONTRIBUTE-ONLY:
# it may be pushed FROM by the maintainer, but the framework's own automation must never
# propagate knowledge INTO it.
#
# Detection is layered, exactly as ADR-009 §2 specifies:
#   1. canonical-slug match on `git remote get-url origin`, host- and protocol-agnostic (always on,
#      no network needed — survives SSH host aliases like git@github-cursor:owner/repo);
#   2. when `gh` is available and authenticated, ANY origin resolving to a public GitHub repo
#      (covers forks). Fail-open if `gh` is absent/unauthenticated — layer 1 still holds.
#
# Override: "allow_public_push": true in the gitignored .bailiwick-sync.json. Machine-local,
# maintainer-only, exists solely to update the public SEED library. Never set it on an instance
# holding private or client-derived knowledge.
#
# Usage as a library:   . hooks/public_origin.sh   then   bw_public_origin_block && ...
# Usage as a command:   bash hooks/public_origin.sh check    (exit 0 = safe, 3 = contribute-only)

BW_CANONICAL_SLUG="${BW_CANONICAL_SLUG:-Cursorinvisivel/bailiwick}"

# Print `owner/repo` for a remote URL, host- and protocol-agnostic. Empty if it has no such shape.
bw_origin_slug() {
  local root="${1:-.}" url
  url="$(git -C "$root" remote get-url origin 2>/dev/null || true)"
  [ -n "$url" ] || return 1
  url="${url%.git}"; url="${url%/}"
  printf '%s' "$url" | awk -F'[/:]' 'NF>=2 {printf "%s/%s", $(NF-1), $NF}'
}

# 0 when the machine-local override is set.
bw_allow_public_push() {
  local cfg="${1:-}"
  [ -f "$cfg" ] || return 1
  # Delegates to the shared bool read; a missing helper fails CLOSED (no override honoured) —
  # the safe direction for a publish-prevention control.
  . "$(dirname "${BASH_SOURCE[0]:-$0}")/config_common.sh" 2>/dev/null || true
  command -v bw_cfg_bool >/dev/null 2>&1 || return 1
  BW_CFG_FILE="$cfg" bw_cfg_bool allow_public_push
}

# 0 (blocked) when this clone is contribute-only; prints the reason. 1 when propagation is safe.
# $1: framework root (default: parent of this script).
bw_public_origin_block() {
  local root="${1:-$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)}" slug private
  slug="$(bw_origin_slug "$root" || true)"
  [ -n "$slug" ] || return 1   # no origin / not a recognisable slug — nothing to protect against

  if bw_allow_public_push "$root/.bailiwick-sync.json"; then
    return 1                   # deliberate, machine-local maintainer override
  fi

  # Layer 1 — canonical slug, case-insensitive (GitHub slugs are case-insensitive).
  if [ "$(printf '%s' "$slug" | tr '[:upper:]' '[:lower:]')" \
     = "$(printf '%s' "$BW_CANONICAL_SLUG" | tr '[:upper:]' '[:lower:]')" ]; then
    printf 'origin is the public OSS repo (%s)' "$slug"
    return 0
  fi

  # Layer 2 — any public GitHub origin (catches forks). Fail-open without gh.
  #
  # Caching (security-review ruling, ADR-009 amendment): the live probe is a network round-trip,
  # and session_start pays it on EVERY session. When — and only when — the caller sets
  # BW_PO_CACHE=1 (the BANNER path; enforcement callers never set it), a fresh NEGATIVE verdict
  # ("origin is a private repo") suppresses the probe for up to 24h. Only the negative is ever
  # cached: "public" must re-warn every session, and errors/timeouts/gh-absent are never cached.
  # The cache stores a fixed token + the exact origin URL (strict parse; anything else = miss) —
  # reason strings are always regenerated from code, never read from the cache.
  if command -v gh >/dev/null 2>&1; then
    _po_url="$(git -C "$root" remote get-url origin 2>/dev/null || true)"
    _po_cache=""
    if [ "${BW_PO_CACHE:-0}" = "1" ] && [ -n "$_po_url" ]; then
      _po_cache="${BAILIWICK_HOME:-$HOME/.bailiwick}/cache/public-origin-$(printf '%s' "$_po_url" | cksum | tr ' ' '-')"
      if [ -f "$_po_cache" ]; then
        # fresh = mtime within 24h; verified against the EXACT url (cksum is only a filename aid)
        _po_age=$(( $(date +%s) - $(stat -c %Y "$_po_cache" 2>/dev/null || stat -f %m "$_po_cache" 2>/dev/null || echo 0) ))
        if [ "$_po_age" -lt 86400 ] \
           && [ "$(sed -n 1p "$_po_cache" 2>/dev/null)" = "private" ] \
           && [ "$(sed -n 2p "$_po_cache" 2>/dev/null)" = "$_po_url" ]; then
          return 1  # fresh negative verdict — skip the probe this session
        fi
      fi
    fi
    # Probe with a timeout: an API/DNS stall must not hang the caller. rc 124 (timed out) is
    # surfaced via BW_PO_PROBE_TIMED_OUT so the ENFORCEMENT site can health-log the degradation.
    BW_PO_PROBE_TIMED_OUT=0
    if command -v timeout >/dev/null 2>&1; then
      private="$(timeout "${BW_PO_TIMEOUT:-15}" gh api "repos/$slug" --jq '.private' 2>/dev/null)" || {
        if [ $? -eq 124 ]; then
          BW_PO_PROBE_TIMED_OUT=1
          # Enforcement callers set BW_PO_HEALTH_COMPONENT so the fail-open degradation is
          # visible in /metrics (the block usually runs in a command substitution, so an
          # in-function health call is the only reliable channel out).
          if [ -n "${BW_PO_HEALTH_COMPONENT:-}" ] && command -v bw_health >/dev/null 2>&1; then
            bw_health "$BW_PO_HEALTH_COMPONENT" warn "gh visibility probe timed out — ADR-009 layer 2 skipped (canonical-slug check only)"
          fi
        fi
        private=""
      }
    else
      private="$(gh api "repos/$slug" --jq '.private' 2>/dev/null || true)"
    fi
    if [ "$private" = "false" ]; then
      printf 'origin (%s) is a PUBLIC GitHub repository' "$slug"
      return 0
    fi
    if [ "$private" = "true" ] && [ -n "$_po_cache" ]; then
      # Definitive negative — cache it (0600) for the banner path only.
      mkdir -p "$(dirname "$_po_cache")" 2>/dev/null || true
      { printf 'private\n%s\n' "$_po_url" > "$_po_cache" && chmod 600 "$_po_cache"; } 2>/dev/null || true
    fi
  fi
  return 1
}

# Shared operator message, so every enforcement point says the same thing.
bw_public_origin_notice() {
  local reason="$1"
  cat >&2 <<EOF
[bailiwick] CONTRIBUTE-ONLY instance — $reason.
            knowledge/ is tracked in git, so propagating here would PUBLISH it. A public push
            is a publish: it may be cached or indexed even if reverted afterwards.
            Fix: point 'origin' at a private repo you own and keep the OSS as a pull-only
            'upstream' (docs/staying-private.md). Maintainers updating the public seed library:
            set "allow_public_push": true in .bailiwick-sync.json on this machine only.
EOF
}

# Standalone entry point, for callers that cannot source shell (skills, PowerShell, docs).
if [ "${BASH_SOURCE[0]:-$0}" = "$0" ] && [ "${1:-}" = "check" ]; then
  _root="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
  if _reason="$(bw_public_origin_block "$_root")"; then
    bw_public_origin_notice "$_reason"
    exit 3
  fi
  echo "[bailiwick] origin is not a public OSS remote — propagation permitted."
  exit 0
fi
