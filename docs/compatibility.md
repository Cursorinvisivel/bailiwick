# Compatibility matrix

The adapter layer (guardrail hooks, MCP wiring, capture) rides on **fast-moving** CLIs whose hook and
config surfaces change between releases. This matrix records what Bailiwick has been **verified
against** and the status of each adapter. Treat versions as a floor, not a guarantee — **re-verify on
upgrades**, especially the items flagged below.

> Fill in the exact versions you test against for your own fleet; the notes below record what the
> framework's own validation observed. Anything marked *experimental* is source-verified but
> undocumented and can regress silently on a CLI bump.

| Tool | Verified against | Status | Capture | Guardrail | Notes |
|---|---|---|---|---|---|
| **Claude Code** | current stable | **supported** (anchor) | Automatic (Stop/SessionEnd hooks) | **Enforced** — PreToolUse, `ask` tiers | The fullest, most credible adapter; documented hook API. |
| **Codex CLI** | 0.147 (own validation) | **supported** | **Automatic** — `Stop`/`SessionEnd` (>= 0.147), after the one-time trust | **Enforced** — PreToolUse, **deny** + break-glass; one-time hook trust (first fire in the `codex` CLI, not VS Code) | Repo-local `.codex/config.toml` MCP did **not** load as active in ~0.142 even after trusting the project — use `--shadow --with-agents` (user-scope `~/.codex/config.toml`). Re-check on upgrades. |
| **Gemini CLI** | current | **experimental** | Manual | **Enforced** — `BeforeTool`, `decision: "ask"` | `ask` is source-verified in gemini-cli's scheduler but **undocumented** — revalidate the ask/blocking behaviour on every CLI bump. |
| **Gemini Code Assist (VS Code agent)** | current | **advisory** | Manual | **Policy only** — hook support unverified | Keep `geminicodeassist.agentYoloMode` **disabled** (the approval dialog is the control). |
| **GitHub Copilot (VS Code, local)** | current | **advisory** | Manual | **Policy only** — no hook equivalent | User-scope MCP solid; user-scope instruction auto-injection is build-dependent (VS Code microsoft/vscode#304101). |
| **GitHub Copilot (hosted cloud agent)** | — | **out of scope** | — | — | Cannot see untracked local files, so the framework does not reach it. |

**Prerequisites** (any adapter): `python3`, `bash`, `git`. Optional: `gh` (lazy GitHub token),
`terraform-mcp-server` + `github-mcp-server` (local Go binaries via `go install`), `gpg` (encrypted
backup). See [getting-started.md](getting-started.md) §1.

**How to revalidate after a CLI upgrade:** run `bootstrap.sh --install-tools` (idempotent — refreshes
the hook/MCP wiring), then confirm the guardrail still fires: ask the agent to run `terraform apply`
in a wired repo and check it is intercepted (Claude/Gemini CLI prompt; Codex denies with a
break-glass hint). The guardrail contract is also covered by `tests/test_guardrails.py`.
