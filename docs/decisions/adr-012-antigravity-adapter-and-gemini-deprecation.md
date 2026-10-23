---
id:            adr-012-antigravity-adapter-and-gemini-deprecation
type:          decision
status:        accepted
date:          2026-10-22
authors:       [Francisco Ferrinho]
tags:          [adr, antigravity, gemini, hooks, guardrails, capture, multi-tool]
supersedes:    []
superseded_by:
scope:         generic
---

# ADR-012 — Antigravity adapter and Gemini CLI deprecation

> Status is **accepted** (2026-10-22): Gemini CLI and Code Assist were sunset by Google on
> June 18, 2026, replaced by Google Antigravity (`agy`, Antigravity 2.0, Antigravity IDE).
> Bailiwick introduces the Antigravity adapter, upgrades capture to automatic via `Stop` hooks,
> routes `--with-gemini` to `--with-antigravity` with a deprecation warning, and schedules
> removal in April 2027.

## Context

Google officially deprecated and sunsetted the standalone Gemini CLI and personal Gemini Code Assist
IDE extensions on June 18, 2026. The platform was replaced by **Google Antigravity**, an AI-first
development platform providing:
1. `agy` (Antigravity CLI v1.4+)
2. Antigravity 2.0 (Desktop workspace application)
3. Antigravity IDE (VS Code-based development environment)

In Bailiwick, Gemini support previously suffered from significant integration limitations:
- **Manual capture:** Gemini CLI lacked lifecycle hooks for session termination, requiring manual
  session output markdown writing for `/curate`.
- **Advisory tools:** Gemini Code Assist in VS Code lacked verified hook support.
- **Undocumented hooks:** `BeforeTool` with `decision: "ask"` was verified in scheduler source but
  undocumented.

Antigravity resolves these deficiencies with a standardized lifecycle hook system:
- **`PreToolUse`:** Replaces `BeforeTool`, matching `run_command` with payload `toolCall: {name, args: {CommandLine}}`.
  Decisions include `ask` and `force_ask`; the adapter emits **`force_ask`**, because plain `ask`
  honours a cached "Always Allow" and would skip ADR-006's in-the-moment re-confirmation.
- **`Stop`:** Emits `conversationId`, `transcriptPath`, and `workspacePaths` on session completion,
  allowing **enforced automatic capture** (`capture_session.py`).
- **`hooks.json`:** Structured hook specification in `~/.gemini/config/hooks.json` or `.agents/hooks.json`.
- **MCP:** Standardized on `mcp_config.json` (`~/.gemini/config/mcp_config.json` or `.agents/mcp_config.json`).
- **Rules & Subagents:** Discovers rules in `GEMINI.md` / `AGENTS.md` and subagents in `~/.gemini/agents/`.

## Decision

1. **Adopt Antigravity as the primary Google adapter:**
   - Pre-tool guardrails wired in `~/.gemini/config/hooks.json` targeting `run_command`.
   - Automatic raw session capture wired to the `Stop` event in `~/.gemini/config/hooks.json`.
   - MCP configurations mapped to `mcp_config.json`.
2. **Deprecate `--with-gemini`:**
   - `--with-antigravity` is the new primary flag for `bootstrap.sh` and `bootstrap.ps1`.
   - `--with-gemini` is retained as an alias routing to `--with-antigravity`, issuing a console
     warning noting deprecation and scheduled removal in April 2027 (in 6 months).
   - `--all-tools` activates Claude Code, Codex, and Antigravity.
3. **Prune legacy Gemini hooks:**
   - `install_adapter_hooks.py` and `bootstrap.sh` remove the obsolete `BeforeTool` hook from
     `~/.gemini/settings.json` automatically, issuing an informative notice.
4. **Upgrade Capture Status:**
   - The Google adapter is promoted in the compatibility matrix from **Manual** to **Automatic** capture.

## Consequences

- Antigravity sessions now enjoy parity with Claude Code and Codex CLI: enforced runtime guardrails
  and automatic background capture.
- Target repositories can remain completely untouched in shadow mode, reading the global operator
  layer and global MCP.
- The Antigravity transcript JSONL schema is undocumented: the raw transcript is always captured,
  but `capture_session.py`'s derived signals (tool names, mutating count, knowledge loads) are a
  best-effort guess until validated against a real `agy` transcript.
- Backward compatibility is maintained for 6 months for any scripts or habits invoking `--with-gemini`.
