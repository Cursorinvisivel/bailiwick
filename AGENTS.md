# AGENTS.md — Bailiwick

> Cross-tool operating guide for this repository.
> Read by Codex (`AGENTS.md`), Gemini (`GEMINI.md`/`AGENTS.md`), and GitHub Copilot. The Claude Code
> twin is `CLAUDE.md` — the rules below are identical across all four tools.

## Purpose
Central repository of AI-agent tools, roles, and knowledge patterns for cloud and infrastructure-as-code work.
Single source of truth — never copy files to other repositories.
Other repositories reference this via `$BAILIWICK`.

## How orchestration works here
The **Lead** is the **orchestrator**: it plans work and dispatches the **stages** of the **Quality
Workflow** — the ordered review pass Memory → Implement → Quality (with Security Review / Docs /
Cloud Research substituted by task type). The canonical stage definitions live under `agents/`
(frontmattered Markdown); `--install-tools` installs them as **native subagents on all four
tools** — Claude Code symlinks (`~/.claude/agents/`), plus generated adapters for Gemini
(`~/.gemini/agents/`), Codex (`~/.codex/agents/`, TOML) and Copilot (`~/.copilot/agents/`).
Independent stages run concurrently, dependent stages in order; a stage that can't run as a
subagent falls back to inline role adoption. See ADR-010 (incl. Amendment 1).

**When stages trigger** (mechanics: each tool's official subagent docs):
- **Claude Code / Gemini** — auto-delegation on description match for substantial work; **force**
  by naming the stage ("run the full Quality Workflow", `@bailiwick-<stage>` under Gemini).
  Gemini: CLI only for now — Code Assist agent mode (VS Code) exposes a subset of the CLI and its
  subagent support is unverified.
- **Codex** — **not automatic**: the global operator layer instructs delegation for substantial
  work; **force** by asking ("use the bailiwick-quality agent to review this"). Covers the CLI
  **and** the IDE extension (same `~/.codex/agents/`).
- **Copilot** — explicit selection (agent picker in VS Code / CLI); auto only agent-to-agent. The
  hosted cloud agent never sees user-scope agents.

| Role / stage | File | Purpose |
|---|---|---|
| Lead (orchestrator) | agents/lead.md | Single entry point, dispatches stages |
| Implement | agents/implementer.md | Code and IaC generation |
| Quality | agents/quality.md | Technical review |
| Security Review | agents/security-review.md | Security review: IAM, network, CIS benchmark |
| Docs | agents/docs.md | Documentation, templates, workshops |
| Memory | agents/memory.md | Knowledge library management |
| Cloud Research | agents/cloud-research.md | External research from official sources |
| Federation | agents/federation.md | External/company memory: read-only consult + gated ingest (dormant until a `.bailiwick-sources.json` source is enabled) |

Orchestration is proportional, not mandatory: route substantial or multi-step work through the
Lead (the orchestrator dispatches stages by task type); handle trivial edits and direct questions
inline with knowledge loaded. The framework is the default — no trigger phrase required.

## Knowledge Library
Index: `knowledge/INDEX.md`

Rules:
- Load files on-demand via INDEX.md — start with `topics/`, then `patterns/`.
- Indexes form a recursive tree: root `INDEX.md` is the always-loaded map; large domains shard into `indexes/index_<domain>.md` (and deeper). Descend on-demand for the relevant domain.
- Never load the entire library in a single task.
- Maximum 5 *content* files (topics/patterns) per task unless justified — index navigation nodes don't count; keep the descent shallow (≤2–3 levels).
- **Engineering defaults always apply** — `knowledge/context/engineering-defaults.md` (reuse-first: scan repo + KB for code to extend before creating; least privilege; CAF naming + labels; pinned versions; no secrets; plan-before-apply; drafts for review).
- Updates to the knowledge library require explicit human approval (via `/curate`).

## Capture & Curation
- **Capture (automatic, Claude Code only).** Claude Code hooks
  (`hooks/`) write raw transcripts of substantial sessions to
  `<project>/.bailiwick-outputs/raw/` and nag when captures are pending. Gemini, Codex, and Copilot do not
  run those hooks — under those tools, write session outputs to `.bailiwick-outputs/` manually per the relevant role definition.
- **Curation (human-gated).** The `/curate` Claude Code skill distills captures into the
  knowledge library; promotion always requires approval. Under Codex, use the `$bailiwick-curate` Codex
  skill wrapper from `codex-skills/bailiwick-curate/`, which reads the same canonical workflow. Under
  Gemini/Copilot, run the Memory stage Collect flow (`agents/memory.md`) by hand.
- **Cross-machine sync.** The framework is cloned per machine and kept in sync via git: the
  Claude Code SessionStart hook ff-pulls `origin/main`, and approved curations propagate out via
  `hooks/sync_knowledge.sh` (central → `main`; satellite → `sync/<machine>` PR).
  `.telemetry.json` is central-owned. Detail: `docs/operations.md` → Multi-machine sync. Repos are wired
  with `scripts/bootstrap.sh` (hidden via `.git/info/exclude`).

## Non-Negotiable Rules
- **High-impact actions only with an in-the-moment re-confirmation, even when instructed** —
  terraform/terragrunt `apply`/`destroy`; kubectl/helm mutations; gcloud/gsutil/az/aws mutating
  verbs (delete/destroy/update/patch/rm); recursive/forced `rm`; `git merge`; `gh repo delete`.
  Never on agent initiative.
- **`git commit` / `push` / PR opening only on a clear user go-ahead** — never agent initiative.
  Never add AI attribution signatures (Co-Authored-By, "Generated with …", 🤖) to commit/PR
  messages unless the user explicitly wants them.
- Validation-only commands (terraform plan/validate/fmt, `--dry-run`, read-only cloud CLI) run
  freely; dirty-zone capture plumbing (`capture_backup.sh`) is never blocked.
- Never modify `knowledge/` without an explicit human gate (via `/curate`).
- `.bailiwick-outputs/raw/` is enforced capture staging — never committed, never promoted unsanitised.
- All outputs are drafts for human review.

## Tool Notes (four adapters of differing completeness — see FRAMEWORK.md §10)
- **Codex** — Codex loads at most ONE instruction file per directory
  (a repo-root instruction file wins over fallbacks), so putting framework guidance there would **shadow** a team
  `AGENTS.md`. The framework therefore puts its guidance in a personal **global** `~/.codex/AGENTS.md`
  layer (installed by `bootstrap.sh --install-tools`) that conditionally reads an untracked
  `.bailiwick.local.md` marker — the team file stays authoritative. Codex MCP is configured in
  `config.toml` (not `.mcp.json`); current Codex CLI reports active MCP from `~/.codex/config.toml`,
  while `bootstrap.sh --with-agents` generates `.codex/config.toml` only as a hidden draft/reference
  and `bootstrap.sh --shadow --with-agents` injects working user-scope `bailiwick-*` MCP. Codex does not run the Claude Code *capture* hooks, but the
  non-negotiables ARE **runtime-enforced** under Codex CLI: `bootstrap.sh --install-tools` wires the
  Bailiwick guardrail as a `PreToolUse` hook (managed block in `~/.codex/config.toml`; **deny**
  with actionable reasons — Codex has no ask — and `BAILIWICK_BREAK_GLASS=1` as logged
  allow-once). Requires a **one-time trust**: Codex prompts the first time the hook fires in a trusted
  project (in the `codex` CLI — the VS Code extension does NOT surface the prompt); trust then persists
  in `~/.codex/config.toml` and the installer preserves it across reinstalls.
- **Gemini** (Code Assist VS Code agent / Gemini CLI) — the framework lives in a personal **global**
  `~/.gemini/GEMINI.md` layer (installed by `bootstrap.sh --install-tools`) that conditionally reads the
  untracked `.bailiwick.local.md` marker; the repo's own `GEMINI.md` stays authoritative. MCP is
  `.gemini/settings.json` (`mcpServers`, generated by `--with-gemini`; a team-tracked one is left
  untouched). Under **Gemini CLI** the non-negotiables are **runtime-enforced**: `--install-tools`
  wires the Bailiwick guardrail as a `BeforeTool` hook (`~/.gemini/settings.json`), returning
  `decision: "ask"` for the ADR-006 tiers — the same forced confirmation as Claude Code. The
  **VS Code Code Assist agent's** hook support is unverified — policy there; keep the approval
  dialog (don't enable `geminicodeassist.agentYoloMode`). `excludeTools` remains — per Google —
  weak string-matching, not a guardrail. Capture is manual (write to `.bailiwick-outputs/`).
- **GitHub Copilot** — repo-wide instructions live in `.github/copilot-instructions.md`; the framework
  complement is `.github/instructions/bailiwick.instructions.md` (`applyTo:"**"`), discovered in
  **local VS Code only**. The GitHub-hosted Copilot **cloud agent cannot see untracked files**, so the
  hidden complement does not reach it.
- **Claude Code** — see `CLAUDE.md`; agents/knowledge are reachable read-only via the MCP filesystem
  second root, and the non-negotiables are **runtime-enforced** by the `guardrails.py` PreToolUse hook.
