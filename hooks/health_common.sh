#!/usr/bin/env bash
# bailiwick — shared framework-health logging (best-effort; NEVER fails the caller).
#
# Source this file, then:  bw_health <component> <event: error|warn|info> <detail>
#
# Appends one JSONL line to $BAILIWICK_HOME/health/<machine>.jsonl — the per-source health
# shard. Each machine writes ONLY its own shard (single-writer per source, like telemetry);
# `capture_backup.sh push` uploads it encrypted to the machine's dirty-repo branch, and the
# central machine aggregates the fleet in /metrics. Health data is machine-local ops state:
# never committed to the Bailiwick repo, ciphertext-only off-machine (ADR-002 posture).

BW_HEALTH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd || echo "")"

bw_health() {
  # Subshell + relaxed flags: health logging must never wedge a hook under `set -euo pipefail`.
  (
    set +e +u
    home="${BAILIWICK_HOME:-$HOME/.bailiwick}"
    machine=""
    if [ -n "$BW_HEALTH_ROOT" ] && [ -f "$BW_HEALTH_ROOT/.bailiwick-sync.json" ]; then
      machine="$(sed -n 's/.*"machine"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
        "$BW_HEALTH_ROOT/.bailiwick-sync.json" 2>/dev/null | head -1)"
    fi
    [ -n "$machine" ] || machine="$(hostname -s 2>/dev/null || echo unknown)"
    machine="$(printf '%s' "$machine" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9._-')"
    detail="$(printf '%s' "${3:-}" | tr '"\\' "''" | tr '\n\t' '  ' | cut -c1-300)"
    mkdir -p "$home/health" 2>/dev/null
    printf '{"ts":"%s","machine":"%s","component":"%s","event":"%s","detail":"%s"}\n' \
      "$(date +%Y-%m-%dT%H:%M:%S)" "$machine" "${1:-unknown}" "${2:-info}" "$detail" \
      >> "$home/health/$machine.jsonl" 2>/dev/null
  ) 2>/dev/null || true
}
