#!/usr/bin/env bash
# Seed a /purge drill: a fresh sandbox (lib/sandbox.sh) + the synthetic client `acme-drill` planted
# on every purge surface (plant.py; answer_key.json lists each trace).
#
#   seed.sh [--parent DIR] [--variant new|baseline] [--baseline-ref SHA] [--no-bootstrap] [--no-bash-sandbox]
#     --variant new       the skill as it stands in the working tree under test (review stages)
#     --variant baseline  the skill text at --baseline-ref (default a5a2feb, the branch base) — the
#                         pre-change behaviour, installed under the SAME command; an unresolvable ref
#                         is a hard error (exit 4), never a silent fallback
#   Env: BW_DRILL_CLAUDE_HOME  the drill's Claude Code config dir (default ~/.cache/bailiwick-drill-claude)
# Prints the operator instructions; the sandbox root is the last line of stdout.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
. "$HERE/../lib/sandbox.sh"

root="$(drill_sandbox --drill purge "$@" | tail -1)"
[ -n "$root" ] || { echo "seed: sandbox creation failed" >&2; exit 1; }
eval "$(drill_env "$root")"
python3 "$HERE/plant.py" "$root" >/dev/null
drill_banner "$root" >&2
echo "$root"
