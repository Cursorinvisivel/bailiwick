#!/usr/bin/env bash
# Seed a /curate drill: a fresh sandbox (lib/sandbox.sh) + an existing KB topic the captures
# duplicate + synthetic raw captures (plant.py; answer_key.json lists what a good run promotes).
#
#   seed.sh [--small] [--parent DIR] [--variant new|baseline|no-delegation] [--baseline-ref SHA]
#           [--no-bootstrap] [--no-bash-sandbox]
#     (default)                2 captures, one > 200 KB -> Step 2a delegates to bailiwick-memory (arm A)
#     --variant baseline       the skill text at --baseline-ref (default a5a2feb), SAME command (arm B);
#                              an unresolvable ref is a hard error (exit 4)
#     --variant no-delegation  the new skill with Step 2a forced off: same input as A, inline (arm D)
#     --small                  the same 2 captures, unpadded: below the threshold, inline (arm C)
#   Env: BW_DRILL_CLAUDE_HOME  the drill's Claude Code config dir (default ~/.cache/bailiwick-drill-claude)
# Prints the operator instructions; the sandbox root is the last line of stdout.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
. "$HERE/../lib/sandbox.sh"

small=""
pass=()
for a in "$@"; do
  if [ "$a" = "--small" ]; then small="--small"; else pass+=("$a"); fi
done

root="$(drill_sandbox --drill curate ${pass[@]+"${pass[@]}"} | tail -1)"
[ -n "$root" ] || { echo "seed: sandbox creation failed" >&2; exit 1; }
eval "$(drill_env "$root")"
python3 "$HERE/plant.py" "$root" $small >/dev/null
drill_banner "$root" >&2
echo "$root"
