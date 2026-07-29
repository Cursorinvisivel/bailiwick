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
  if command -v python3 >/dev/null 2>&1; then
    [ "$(python3 -c 'import json,sys;print(str(json.load(open(sys.argv[1])).get("allow_public_push",False)).lower())' \
        "$cfg" 2>/dev/null || echo false)" = "true" ]
  else
    grep -qE '"allow_public_push"[[:space:]]*:[[:space:]]*true' "$cfg"
  fi
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
  if command -v gh >/dev/null 2>&1; then
    private="$(gh api "repos/$slug" --jq '.private' 2>/dev/null || true)"
    if [ "$private" = "false" ]; then
      printf 'origin (%s) is a PUBLIC GitHub repository' "$slug"
      return 0
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
