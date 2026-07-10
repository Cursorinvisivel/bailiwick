---
id: agent-cli-hook-contracts
type: topic
tags: [claude-code, codex, gemini, hooks, guardrails, enforcement, tooling, reference]
confidence: low
last_validated: 2026-07-07
supersedes: []
scope: generic
---

# Topic: Pre-execution hook contracts — Claude Code vs Codex CLI vs Gemini CLI

> Verified against vendor source/docs 2026-07-05 (adapters implemented same day). The
> gotchas here cost real debugging time if learned the hard way.

## Contracts at a glance
| | Claude Code | Codex CLI (≥0.131) | Gemini CLI (≥0.21) |
|---|---|---|---|
| Event | `PreToolUse` | `PreToolUse` | `BeforeTool` |
| Config | `~/.claude/settings.json` hooks | `~/.codex/config.toml` `[[hooks.PreToolUse]]` (or hooks.json) | `~/.gemini/settings.json` `hooks.BeforeTool` |
| Shell tool name | `Bash` | `Bash` | `run_shell_command` |
| Payload | stdin JSON: `tool_name`, `tool_input.command`, `cwd` | same field names | same + `tool_input.dir_path` etc. |
| Decisions | `allow`/`ask`/`deny` | **deny or allow+rewrite ONLY — no ask** | `allow`/`deny`/**`ask`** (ask undocumented, source-verified) |
| Exit-2 fallback | blocks, stderr = reason | blocks IF stderr non-empty | blocks, stderr = reason |
| Failure direction | fail-open | fail-open (incl. malformed output!) | fail-open (incl. polluted stdout) |

## Gotchas (each verified)
- **Codex deny REQUIRES a non-empty `permissionDecisionReason`** — deny without it is
  invalid output → hook marked Failed → tool RUNS (fail-open). Always emit the reason.
- **Codex has no ask/confirm** on PreToolUse (`ask` is parsed and rejected). "Re-confirm
  with the user" semantics need an out-of-band override (env var allow-once) or deny+retry.
- **Codex hook trust: NO `/hooks` command** (verified codex-cli 0.142.5 — the earlier "TUI
  browser" claim was wrong). Codex prompts to trust the **first time the hook fires** in a trusted
  project, **in the `codex` CLI only — the VS Code extension does NOT surface the prompt** (so
  IDE-primary users must trust once from the CLI or the hook stays inert). Trust persists as a
  `[hooks.state."…"]` table in `~/.codex/config.toml`; **it can land inside an installer's managed
  markers, so a block-replace reinstall must preserve `[hooks.state…]`** (ours does).
- **Quoted-argument false positives (all adapters):** a destructive verb inside a *quoted*
  argument is not a command — e.g. `gcloud logging read '… methodName:"delete" …'` (read-only) must
  not match a mutation tier. Match command-token tiers against a **quote-stripped** command; keep the
  raw command only for the signature check (which reads inside the quoted message).
- **Gemini's `ask` forces the user-confirmation dialog** (PolicyDecision.ASK_USER) but only
  the scheduler source documents it — re-verify after CLI upgrades; fallback to `deny`.
- **stdout hygiene**: both tools parse stdout as JSON; any stray print → decision ignored,
  fail-open. Log to files/stderr, never stdout.
- **MCP tool naming differs**: Codex `mcp__server__tool` (double underscore) vs Gemini
  `mcp_server_tool` (single) — matchers are not portable.
- Gemini timeouts are **milliseconds** (default 60000); Codex `timeout` is **seconds**.
- Gemini exports `CLAUDE_PROJECT_DIR` as a compat alias; Codex provides only payload `cwd`.

## Applicability
- Wiring any guardrail/policy hook across multiple agent CLIs (the Bailiwick adapter:
  `hooks/guardrails.py claude|codex|gemini` + `install_adapter_hooks.py` — working example).
- Client deployments wanting enforced (not policy) command controls per tool.

## Provenance
- openai/codex source (`codex-rs/hooks/*`: schema.rs, output_parser.rs, pre_tool_use.rs) +
  developers.openai.com/codex/hooks; hooks GA 2026-05-14.
- google-gemini/gemini-cli source (`packages/core/src/hooks/types.ts`,
  `scheduler/hook-utils.ts`) + geminicli.com/docs/hooks; BeforeTool since v0.20.0.
- Verified 2026-07-05 during Bailiwick adapter work (ADR-006 tiers).

## Related
- [Claude MCP wiring](claude-mcp-wiring.md)
