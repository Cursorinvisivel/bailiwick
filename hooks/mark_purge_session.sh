#!/usr/bin/env bash
# bailiwick — positive sentinel for a /purge session.
#
# /purge runs this as its FIRST action:   bash "$BAILIWICK/hooks/mark_purge_session.sh"
#
# The script itself does nothing: it writes no file, reads no config, and takes no argument, so the
# invocation carries no client identifier. What matters is the tool call that ran it. The Stop and
# SessionEnd hook (capture_session.py) looks for that exact invocation in the transcript (a Bash
# tool call, or a Codex exec/shell call, whose whole command is this script, optionally behind
# `bash`/`sh`) and then never captures the session. It covers the invocation shapes the skill-name
# detection misses, such as a Codex skill chosen implicitly without `$bailiwick-purge`. A mention of
# the script (Read, grep, prose, a longer command) is not an invocation and does not count.
#
# Arguments are refused (exit 2): a command with arguments does not match the detector, so the
# caller must learn at once that the session was NOT marked. Both outcomes print the one accepted
# form, so the agent can check the command it actually ran against it: detection reads the tool
# call, and this script cannot see how it was invoked.
FORM='bash "$BAILIWICK/hooks/mark_purge_session.sh"'
if [ "$#" -gt 0 ]; then
  echo "[bailiwick] mark_purge_session.sh takes no arguments — this session is NOT marked; re-run it bare" >&2
  echo "[bailiwick] accepted form, alone as its own command (no arguments, no chaining): $FORM" >&2
  exit 2
fi
echo "[bailiwick] purge session marked: capture_session.py will not capture this session"
echo "[bailiwick] counts only if the command you ran was exactly, alone (no arguments, no chaining): $FORM"
exit 0
