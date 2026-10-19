#!/usr/bin/env bash
# Live end-to-end check of the /curate freshness fetch guard — run after installing or upgrading
# Claude Code. Starts ONE real headless session (costs a model call; never run it in CI) that
# dispatches the INSTALLED bailiwick-cloud-research-freshness agent to fetch an off-registry URL,
# then reads the audit log to see which guard layers refused it:
#   fetch-deny:scoped  the agent's own frontmatter hook (independent of the hook payload)
#   fetch-deny:global  the settings.json hook — proves Claude Code still sends `agent_type`
# doctor.sh proves the installed commands and policy offline; only this proves the harness wiring.
#
# Usage: scripts/smoke_fetch_guard.sh        Exit 0: both layers refused; 1: a layer did not.
set -u

AGENT="bailiwick-cloud-research-freshness"
BW_HOME="${BAILIWICK_HOME:-$HOME/.bailiwick}"
LOG="$BW_HOME/guardrail-audit.log"
OFF="https://example.com/"

command -v claude >/dev/null 2>&1 || { echo "✗ claude CLI not found"; exit 1; }
[ -e "$HOME/.claude/agents/$AGENT.md" ] || {
  echo "✗ $AGENT is not installed in ~/.claude/agents — run scripts/bootstrap.sh --install-tools"; exit 1; }

before=0; [ -f "$LOG" ] && before="$(wc -l < "$LOG")"
TIMEOUT=""; command -v timeout >/dev/null 2>&1 && TIMEOUT="timeout 300"  # absent on stock macOS
echo "Claude Code $(claude --version 2>/dev/null | head -1) — dispatching $AGENT (one live session)…"
prompt="Dispatch the $AGENT subagent with exactly this task: 'Guard smoke test. Fetch $OFF with WebFetch once and report whether it was denied, quoting the reason. Do not retry or try other URLs.' Do not fetch anything yourself. Then relay its report in one line."
work="$(mktemp -d)"
reply="$(cd "$work" && printf '%s\n' "$prompt" | $TIMEOUT claude -p --allowedTools "Agent,WebFetch" 2>&1)"
rm -rf "$work"
echo "  agent: $(printf '%s' "$reply" | tr '\n' ' ' | cut -c1-300)"

fresh="$(tail -n +"$((before + 1))" "$LOG" 2>/dev/null | grep -F "$AGENT")"
new="$(printf '%s\n' "$fresh" | grep -F "https://example.com sha256:")"
rc=0
for layer in scoped global; do
  if printf '%s\n' "$new" | grep -q "fetch-deny:$layer"; then
    echo "✓ $layer layer refused the off-registry fetch"
  else
    echo "✗ $layer layer did not record a refusal"; rc=1
  fi
done
if [ "$rc" -ne 0 ]; then
  [ -z "$fresh" ] && echo "  no refusal at all: the session may not have dispatched the agent — check the reply above."
  printf '%s\n' "$fresh" | grep -q "fetch-deny-launcher:scoped" \
    && echo "  scoped layer denied via its launcher, which could not run the guard — re-run bootstrap.sh --install-tools."
  echo "  scoped missing: the agent's frontmatter hook or its launcher is not wired (doctor.sh)."
  echo "  global missing: settings.json hook absent, or this Claude Code no longer sends agent_type."
fi
exit "$rc"
