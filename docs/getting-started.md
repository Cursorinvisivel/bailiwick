# Getting Started with Bailiwick

Welcome. **Bailiwick** is a personal knowledge layer for your AI coding agents (Claude Code
first-class; also Codex CLI, Gemini CLI, and GitHub Copilot): a curated, always-on knowledge
library of your conventions and hard-won context, fed by enforced session capture with human-gated
curation, and paired with runtime guardrails on high-impact commands so a knowledge-loaded agent
stays within your rules. It is **single-practitioner by design** and wires into repos with zero
footprint by default — it layers alongside a team's existing instruction files as hidden
complements, touching shared files only through explicit actions you take (see
[Intent & scope](../README.md#intent--scope)). It's plain Markdown, Python, and shell — there is no
service to run and nothing to host.

This guide walks you from a fresh clone to your first completed knowledge cycle. It's the
happy path; for day-2 operations (multi-machine sync, encrypted backup, federation) see
[operations](operations.md), and for the full architecture see [architecture](FRAMEWORK.md).

Two commands do almost everything: **`bootstrap.sh --install-tools`** (once per machine) and
**`bootstrap.sh /path/to/repo`** (once per repo). Everything below expands on those.

---

## 1. Prerequisites

Install these before you start:

- **`python3`** and **`bash`** on your `PATH` — the hooks are written in both.
- **`git`** — for the framework clone and for sync.
- A supported agent tool — **Claude Code** is the primary target; Codex CLI, Gemini CLI, and
  GitHub Copilot are also supported.

Optional, but recommended:

- **`gh` CLI** (authenticated) — lets the GitHub MCP server resolve a token lazily from your
  keychain instead of an exported PAT, and enables PR-based sync.
- **`terraform-mcp-server`** — a local binary (installed via `go install`) that serves HashiCorp
  provider/module docs to the agent. `--install-tools` installs it for you if `go` is present.
- **`github-mcp-server`** — GitHub's official local MCP binary (also `go install`) that serves
  repo/PR/issue context; its token comes from `gh` (above) or `$GITHUB_TOKEN`. `--install-tools`
  installs it too when `go` is present. Both MCP binaries need `$(go env GOPATH)/bin` on your `PATH`.
- **`gpg`** — only if you later enable encrypted dirty-zone backup (see [operations](operations.md)).

Clone the repo, then point `$BAILIWICK` at it (the docs, templates, and configs all resolve
paths through this variable):

```bash
git clone https://github.com/your-org/bailiwick.git ~/bailiwick
echo 'export BAILIWICK="$HOME/bailiwick"' >> ~/.zshrc   # or ~/.bashrc
source ~/.zshrc
```

---

## 2. Install once per machine

Run the global installer. It needs **no target repo** — it wires up your machine, not any project:

```bash
$BAILIWICK/scripts/bootstrap.sh --install-tools
```

This is idempotent (re-run it any time — e.g. after adding a new skill) and installs, when missing:

- The **capture + guardrail hooks**, merged into `~/.claude/settings.json` (existing keys are
  preserved). These fire in *every* project but self-gate — they stay inert unless the repo is
  Bailiwick-wired.
- The **global Claude Code skills** as symlinks in `~/.claude/skills/`: `/curate`, `/enrich`,
  `/learn`, `/metrics`, `/investigate`, `/purge`.
- The **Quality Workflow stages as native Claude Code subagents** — symlinks in `~/.claude/agents/`
  (`bailiwick-implement`, `bailiwick-quality`, `bailiwick-memory`, `bailiwick-security-review`,
  `bailiwick-docs`, `bailiwick-cloud-research`, `bailiwick-federation`). This is what lets the Lead
  dispatch stages as real, concurrent subagents (ADR-010); never seeded per-repo.
- The **same stages as generated adapters for the other tools** — Gemini (`~/.gemini/agents/`),
  Codex (`~/.codex/agents/`, TOML) and Copilot (`~/.copilot/agents/`), produced from the canonical
  files and refreshed on every re-run (ADR-010 Amendment 1). Files you created yourself in those
  dirs are never overwritten.
- The **Codex skill wrappers** (`$bailiwick-curate`, `$bailiwick-enrich`, `$bailiwick-learn`,
  `$bailiwick-investigate`, `$bailiwick-purge`) in `~/.codex/skills/`.
- The **Codex and Gemini operator layers** — managed blocks in `~/.codex/AGENTS.md` and
  `~/.gemini/GEMINI.md` that teach those tools to read a repo's framework marker without shadowing
  the team's own `AGENTS.md` / `GEMINI.md`.
- The **guardrail adapters** for Codex (`PreToolUse`) and Gemini CLI (`BeforeTool`).
- The **`terraform-mcp-server`** and **`github-mcp-server`** binaries, if `go` is available (each is
  installed and validated; a missing `go` skips them with a warning).

> **Codex users:** the guardrail needs a one-time hook trust. The first time the guardrail fires in
> a trusted project, the `codex` CLI prompts you to allow it; trust then persists in
> `~/.codex/config.toml`. (The VS Code extension does not surface this prompt — use the CLI once.)

Windows PowerShell has full parity — use `bootstrap.ps1 -InstallTools`.

That's the whole machine setup. You never repeat it per project.

---

## 3. Wire your first repo

Pick any repo and wire it. **Shadow mode is the default**, and for most people it's the right one.

**Shadow mode (default)** writes **zero files** into the repo. Activation lives in a per-machine
allowlist (`~/.bailiwick/allowlist`) plus user-scope MCP/instruction config; captures stage
centrally under `~/.bailiwick/captures/`. The repo stays pristine — ideal for a client clone you
must leave untouched.

```bash
$BAILIWICK/scripts/bootstrap.sh /path/to/repo
```

**Seeded mode** (`--seeded`) instead writes the wiring *into* the repo (MCP configs, hidden
complement instruction files, capture staging), hidden from version control via the repo's
`.git/info/exclude` — never the tracked `.gitignore`, whose entries alone would reveal the
framework to anyone who clones.

```bash
$BAILIWICK/scripts/bootstrap.sh --seeded /path/to/repo
```

Two more flags worth knowing up front:

- **`--with-standards`** seeds a **tracked, framework-agnostic** team baseline (`CLAUDE.md`, and
  `AGENTS.md` / `.github/copilot-instructions.md` per your tool flags) with generic engineering best
  practices and no framework references. This is the deliberate shared-team path and works in both
  modes. Existing team files are never overwritten.
- **`--init`** creates a brand-new repo (runs `git init`) and implies `--seeded`. Combine with
  `--with-standards --all-tools` for a fresh shared repo:

```bash
$BAILIWICK/scripts/bootstrap.sh --init --with-standards --all-tools /path/to/new-repo
```

Windows: `bootstrap.ps1 /path/to/repo`, `bootstrap.ps1 -Seeded /path/to/repo`, etc.

> **Onboarding an existing project?** After bootstrapping, run **`/enrich`** (Claude Code) or
> **`$bailiwick-enrich`** (Codex). It scans the repo, asks only for what it can't infer, and drafts
> filled-in instruction files for all four tools. Drafts only — it never commits. Then run
> **`/learn`** (`$bailiwick-learn`): the same scan posture aimed at the *knowledge library* — it
> distills the repo's decisions, patterns, and pitfalls into a pre-digested capture staged where
> `/curate` gathers, so a final `/curate` promotes the repo's existing knowledge under the normal
> human gate. Bootstrap → `/enrich` → `/learn` → `/curate` is the full onboarding sequence.

---

## 4. Verify it works

Open **Claude Code** in the wired repo and confirm three things (this is the fullest experience —
under Codex the guardrail *denies* with a break-glass override rather than prompting, and capture is
manual; Gemini CLI prompts like Claude Code but capture is manual):

1. **Knowledge index is injected.** On session start you should see the framework defaults asserted
   and the knowledge `INDEX.md` (the ~2k-token map) injected. That's the SessionStart hook — the
   agent can now judge which knowledge files a task needs without a blind read.

2. **The guardrail confirms high-impact commands.** Ask the agent to run something mutating, e.g.
   `terraform apply`. The guardrail forces an in-the-moment confirmation *even when you instructed
   it* — nothing destructive runs on agent initiative. Validation-only commands
   (`terraform plan/validate/fmt`, `kubectl get`, read-only cloud CLI) pass untouched.

3. **A substantive session leaves a capture.** After real work (files mutated or ≥3 tool calls),
   a raw transcript is staged. In **seeded** mode look in `<repo>/.bailiwick-outputs/raw/`; in
   **shadow** mode look under `~/.bailiwick/captures/`. Pure conversation produces no capture.

Every guardrail decision is also appended to `~/.bailiwick/guardrail-audit.log` if you want a
paper trail.

---

## 5. Your first task

There is **no command to "start a workflow."** Stating a substantial task in Claude Code *is* the
invocation. The **Lead** is the orchestrator — the native main session — and for substantial or
multi-step work it drives the **Quality Workflow**: the ordered Memory → Implement → Quality review
pass, dispatched as native subagents (concurrently where the work is independent). See ADR-010 and
`agents/lead.md`.

Try it in the wired repo:

```
Add a Cloud SQL Postgres instance with a private IP and Secret-Manager-managed
credentials to this module, with tests.
```

That's multi-step and domain-specific, so it routes through the Lead: it reads the `gcp.md` domain
context file for retrieval hints + checklist, runs the Memory stage, dispatches the Implement and
Quality stages, integrates, and closes with a Memory (Collect). Everything comes back as **drafts
for your review**.

**Proportional routing.** Trivial edits and direct questions are answered **inline** — the Lead does
*not* spin up the Quality Workflow for a one-line fix or a lookup. That's by design, not a misfire.

**Forcing the Workflow.** If the model under-evaluates a task and handles it inline when you wanted
the full rigor, say so explicitly:

```
Run the full Quality Workflow: Memory → Implement → Quality. Don't handle this inline.
```

Naming the stages is the most reliable form — it pins the steps rather than relying on the model to
expand "Lead" into the whole pass. (This is a policy directive the session follows, not a
runtime-enforced switch like the guardrails.)

**Under the other tools** the same stages are installed as native agents (ADR-010 Amendment 1) —
same names, different trigger conventions (mechanics: each tool's official subagent docs):

| Tool | Automatic? | To force a stage |
|---|---|---|
| Claude Code | ✅ on description match, proportional | name the stage / "run the full Quality Workflow" |
| Gemini CLI¹ | ✅ auto-delegation | `@bailiwick-<stage> <task>` |
| Codex (CLI + IDE ext.) | ❌ not by default — the operator layer instructs delegation for substantial work | ask by name: "use the bailiwick-quality agent to …" |
| Copilot (VS Code + CLI) | ❌ explicit selection (auto only agent-to-agent) | pick the agent in VS Code / CLI; cloud agent can't see them |

¹ CLI only for now — Gemini Code Assist agent mode (VS Code) exposes a subset of the CLI, and
subagent support there is unverified.

---

## 6. Your first knowledge cycle

The point of capture is curation. After a session or two of real work:

```
/curate
```

`/curate` walks you through the pending raw captures, distils the reusable bits (abstracted away
from any client specifics), and — **only on your explicit approval** — promotes them into the
knowledge library under `$BAILIWICK/knowledge/`. Nothing enters knowledge without a
human gate. That's the core loop: **capture is enforced, promotion is gated.**

The other global skills round out the workflow:

- **`/enrich`** — draft project-context instruction files for a bootstrapped repo (see §3).
- **`/learn`** — onboard an existing repo's knowledge at bootstrap time (see §3): scan the project
  and stage its distilled decisions, patterns, and pitfalls as a pre-digested capture that the next
  `/curate` promotes under the normal gate. Writes no knowledge itself.
- **`/metrics`** — a read-only health report on the knowledge library (retrieval, the
  load→applied→used funnel, cold/stale candidates) plus a fleet view of framework health. Writes
  nothing.
- **`/investigate`** — research a reference (URL, repo, article) or an open question and distil the
  findings into gated knowledge candidates with provenance — including "evaluated, not adopted"
  verdicts worth remembering.
- **`/purge`** — remove every reference to a client/project from the library, captures, telemetry, and
  registry, keeping the reusable knowledge (re-attributed or genericized) and deleting only what is
  clearly client/project-specific. Human-gated and destructive (scan → plan → approve → execute).
  De-identified by default (ciphertext lingers in backup history until `--history` rewrite / key
  destruction); `--attest` drafts a safety-net attestation of what was scrubbed. Pairs with
  `/curate --sanitized` (de-identified mode — stores no client/project identifiers).

Codex users get thin native wrappers: `$bailiwick-curate`, `$bailiwick-enrich`, `$bailiwick-learn`, `$bailiwick-investigate`, `$bailiwick-purge`.

---

## 7. Next steps

- **[operations](operations.md)** — day-2 operations: multi-machine sync (central + satellites),
  encrypted dirty-zone backup, federated external memory, and keeping repos current with `--update`.
- **[architecture](FRAMEWORK.md)** — the full, self-contained specification: the orchestration
  model, the four tool adapters, shadow vs. seeded wiring (§7.1), guardrail tiers, and the capture
  pipeline.
- **[CONTRIBUTING.md](../CONTRIBUTING.md)** — how to propose knowledge, patterns, and framework
  changes.

Welcome aboard — start small: wire one repo, do a little work, run `/curate`, and let your
knowledge library grow from your own practice.
