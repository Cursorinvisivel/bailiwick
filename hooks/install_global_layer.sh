#!/usr/bin/env bash
# Install/refresh an bailiwick private operator layer into a user's GLOBAL instruction file,
# once per machine — e.g. ~/.codex/AGENTS.md (Codex) or ~/.gemini/GEMINI.md (Gemini). The analogue
# of installing the capture hooks into ~/.claude/settings.json.
#
# Why global, not per-repo: tools like Codex (one instruction file per directory) or Gemini's
# VS Code agent (no guaranteed loader for an arbitrary filename) cannot take a repo-root complement
# safely. So the framework's guidance lives in the personal GLOBAL layer (loaded first, so a repo's
# own file still takes precedence) and activates per-repo via the untracked .bailiwick.local.md
# marker referenced inside the template.
#
# Safe-merge: the framework's content is wrapped in BEGIN/END markers. An existing block is
# REPLACED in place; otherwise the block is APPENDED. Hand-written content outside the markers is
# never touched. Idempotent.
#
# Usage: install_global_layer.sh <bailiwick-abs-path> <template-abs-path> <dest-file> [label]
set -euo pipefail

BAILIWICK_ROOT="${1:?usage: install_global_layer.sh <bailiwick> <template> <dest> [label]}"
TMPL="${2:?usage: install_global_layer.sh <bailiwick> <template> <dest> [label]}"
DEST="${3:?usage: install_global_layer.sh <bailiwick> <template> <dest> [label]}"
LABEL="${4:-global layer}"
BEGIN="<!-- BEGIN bailiwick"
END="<!-- END bailiwick -->"

[ -f "$TMPL" ] || { echo "error: template not found: $TMPL" >&2; exit 1; }

# Render the managed block with the real Bailiwick path substituted in.
BLOCK="$(sed "s#__BAILIWICK__#${BAILIWICK_ROOT}#g" "$TMPL")"

mkdir -p "$(dirname "$DEST")"


if [ -f "$DEST" ] && grep -qF "$BEGIN" "$DEST" 2>/dev/null; then
  # Replace the existing managed block in place, preserving everything around it.
  python3 - "$DEST" "$BEGIN" "$END" <<'PY' "$BLOCK"
import re, sys
dest, begin, end = sys.argv[1], sys.argv[2], sys.argv[3]
block = sys.argv[4]
text = open(dest, encoding="utf-8").read()
pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
new = pattern.sub(lambda _: block, text, count=1)
open(dest, "w", encoding="utf-8").write(new)
PY
  echo "  ${LABEL}: refreshed managed block in $DEST"
else
  # Append (creating the file if needed), separated by a blank line from any prior content.
  { [ -s "$DEST" ] && printf '\n'; printf '%s\n' "$BLOCK"; } >> "$DEST"
  echo "  ${LABEL}: installed managed block into $DEST"
fi
