#!/usr/bin/env bash
# bailiwick drill sandbox — bash API over sandbox.py / guard.py (the single implementations).
#
# Source it for functions, or run it as a command:
#   drill_sandbox --drill purge|curate [--parent DIR] [--variant new|baseline|no-delegation] [--baseline-ref SHA]
#                                       create a sandbox; prints its root as the LAST stdout line
#   drill_guard check-root|check-target|check-knowledge|check-parent|check-source ...
#                                       exit 0 = allowed, 3 = refused
#   drill_env <root>                    export lines (BW_DRILL_SANDBOX, BAILIWICK, BAILIWICK_HOME, CLAUDE_CONFIG_DIR)
#   drill_cleanup <root>                remove the sandbox — only when its .drill-sandbox marker checks out
#
#   bash sandbox.sh create|env|banner|cleanup|guard ...
DRILL_LIB="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)"

drill_sandbox() { python3 "$DRILL_LIB/sandbox.py" create "$@"; }
drill_guard()   { python3 "$DRILL_LIB/guard.py" "$@"; }
drill_env()     { python3 "$DRILL_LIB/sandbox.py" env "$@"; }
drill_banner()  { python3 "$DRILL_LIB/sandbox.py" banner "$@"; }
drill_cleanup() { python3 "$DRILL_LIB/sandbox.py" cleanup "$@"; }

if [ "${BASH_SOURCE[0]:-$0}" = "$0" ]; then
  cmd="${1:-}"; [ $# -gt 0 ] && shift
  case "$cmd" in
    create)  drill_sandbox "$@" ;;
    env)     drill_env "$@" ;;
    banner)  drill_banner "$@" ;;
    cleanup) drill_cleanup "$@" ;;
    guard)   drill_guard "$@" ;;
    *) echo "usage: sandbox.sh create|env|banner|cleanup|guard ..." >&2; exit 2 ;;
  esac
fi
