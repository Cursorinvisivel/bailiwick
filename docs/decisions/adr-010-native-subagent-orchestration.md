---
id:            adr-010-native-subagent-orchestration
type:          decision
status:        accepted
date:          2026-07-24
authors:       [Francisco Ferrinho]
tags:          [adr, orchestration, subagents, vocabulary, quality-workflow, claude-code]
supersedes:    []
superseded_by:
scope:         generic
---

# ADR-010 — Native subagent orchestration; rename the sequential pass to "Quality Workflow"

> Status is **accepted** (2026-07-24): all three implementation forks in §Consequences are
> resolved and the mechanism is implemented — frontmattered stage definitions in `agents/*.md`,
> installed globally as `~/.claude/agents/bailiwick-*.md` symlinks by
> `bootstrap.sh --install-tools` / `bootstrap.ps1 -InstallTools`.

## Context

The framework's agents (`agents/*.md`) were, until now, **Markdown role definitions adopted by one
session's context** — not native Claude Code subagents. "Delegation" meant *working the phases in
order wearing each role*, sequentially, in a single process.

The vocabulary chosen for that model actively collides with native Claude Code semantics. A Claude
Code user brings a fully-formed mental model: native subagents are defined as `.claude/agents/*.md`,
launched via the Agent/Task tool, run **concurrently**, **delegate**, and **report back**. The
framework's surface hit every trigger for that model and meant the opposite:

- files live in an `agents/` directory, named "Lead Agent" / "Implementer Agent" / "Quality Agent";
- the prose used "orchestration", "delegates to execution agents", "Delegation Matrix";
- `lead.md` even said "Never invoke **subagents** without sufficient context" — the *native term*
  for a mechanism that was not the native one.

Honest disclaimers existed ("not isolated Claude Code subagents…") but appeared as asides against a
wall of native-sounding nouns, and were undercut by casual reuse of "subagents" elsewhere. The
result: users reasonably expected concurrent multi-agent orchestration and got sequential role-play,
with no documentation of how to even start it.

## Decision

1. **Adopt real native subagent orchestration.** The **Lead** is redefined as the **orchestrator**:
   the native Claude Code main session, which uses the Agent/Task tool to spawn genuine subagents,
   **concurrently where the work is independent**. The Lead is not itself a subagent (native
   subagents cannot spawn further subagents).

2. **Rename the sequential review pass to the "Quality Workflow."** The ordered
   Memory → Implement → Quality pass (with Security Review / Docs / Cloud Research substituted by
   task type) is the **Quality Workflow**. It is a sequence of **stages**; each stage runs either
   inline (small work) or as a dispatched **subagent** (native mechanism).

3. **Reserve "agent" / "subagent" for the native mechanism.** The framework's executable parts are
   **stages** (or **roles**) within the Quality Workflow — "Implement stage", "Quality stage",
   "Memory stage". "Subagent" now means, accurately, the native process that executes a stage. The
   five non-executing domain files (gcp, kubernetes, serverless, data, cicd) remain **context
   files** the orchestrator reads for retrieval hints + checklists.

4. **Proportional routing is unchanged.** Trivial edits and direct questions are still handled
   inline; only substantial or multi-step work invokes the Quality Workflow. Stating a substantial
   task *is* the invocation — no command, no prefix. Explicit phrasing ("run the full Quality
   Workflow", naming the stages) forces it when proportional routing under-evaluates a task.

## Consequences

**Positive:** the vocabulary matches the mechanism; "start a workflow" has a real, documentable
answer; independent stages can run concurrently.

**Resolved forks (decided 2026-07-24):**

1. **Subagent file discovery vs. zero-footprint (§7.1). — DECIDED: global install.** Native subagents
   must exist as `.claude/agents/*.md`. Shadow mode writes zero files into a repo, so the subagent
   definitions install **globally** into `~/.claude/agents/` via `bootstrap.sh --install-tools`,
   consistent with how global hooks and skills already install; they are never seeded into a repo.

2. **Knowledge propagation to subagents. — DECIDED: each stage self-loads.** The SessionStart hook
   injects the knowledge index into one session; native subagents start as fresh contexts and do not
   inherit it. Each subagent stage therefore loads the index (and ≤5 domain/topic files) itself, per
   its role definition — the orchestrator passes the relevant domain hints in the dispatch prompt.

3. **Capture of subagent work. — DECIDED: signals-in-report (verified 2026-07-24).** Evidence:
   `capture_session.py` copies the hook payload's `transcript_path` — the **main session
   transcript** — into raw staging. That transcript contains every Task dispatch prompt and every
   subagent's **final report**, but not subagent-internal turns (those live in separate sidechain
   transcripts that are not copied). Resolution: every stage definition mandates that the **final
   report is the only channel back** — outputs AND knowledge signals must be in it, never only in
   intermediate turns (the rule is embedded in each stage file's context preamble). Everything
   curate-worthy therefore transits the captured main transcript by construction; no new capture
   machinery. Accepted residual: a stage's intermediate reasoning is not captured — the
   signals-in-report rule is the compensating control. Optional future hardening: a `SubagentStop`
   hook staging full stage transcripts, if the residual ever proves lossy in practice.

**Migration:** vocabulary sweep across `agents/`, `CLAUDE.md`, `FRAMEWORK.md`, `getting-started.md`,
and the SessionStart banner. `knowledge/` files change only through `/curate` (human gate). Historical
ADRs are **not** rewritten; this ADR supersedes their vocabulary going forward.

---

## Amendment 1 (2026-07-24) — multi-tool stage installation

**Finding.** The original decision assumed native subagents were Claude-Code-only, with stages
running inline under the other adapters. Verified against official docs (2026-07-24): all three
other tools have since shipped native subagent/custom-agent mechanisms — **Codex CLI** (custom
agents as TOML in `~/.codex/agents/`; GA ~2026-03), **Gemini CLI** (Markdown + YAML frontmatter in
`~/.gemini/agents/`; since v0.38.1), **Copilot** (`*.agent.md` in `.github/agents/`, user-scope
`~/.copilot/agents`, VS Code also reads `.claude/agents`).

**Decision.**
1. **The canonical stage definitions remain `agents/*.md`** (Claude Code format) — single source of
   truth, symlinked for Claude Code as decided above.
2. **Other tools get generated adapter files at user scope**, produced by
   `bootstrap.sh --install-tools` / `bootstrap.ps1 -InstallTools` from the canonical files and
   marked `GENERATED by bailiwick` (regenerated each run; a same-name file without the marker is
   never overwritten):
   - **Gemini:** `~/.gemini/agents/bailiwick-*.md` — `name`/`description` + body copied; the
     Claude-specific `tools:` field is dropped (Gemini tool names differ; its defaults apply).
   - **Codex:** `~/.codex/agents/bailiwick-*.toml` — `name`/`description` copied, body becomes
     `developer_instructions`; a canonical toolset without Edit/Write maps to
     `sandbox_mode = "read-only"`, so least-privilege propagates to Codex's transport.
   - **Copilot:** `~/.copilot/agents/bailiwick-*.agent.md` — same treatment as Gemini,
     `.agent.md` extension. In-repo `.github/agents/` is NOT seeded (visible-file leak; the
     hidden-wiring rule from ADR-007 applies).
3. **Trigger model is per-tool and documented, not normalized:** Claude Code and Gemini
   auto-delegate on description match (force: name the stages / `@bailiwick-<stage>`); **Codex does
   not auto-delegate by default** — delegation is requested explicitly or granted by AGENTS.md/skill
   rules, so the global Codex operator layer carries the delegation rule; Copilot uses explicit
   agent selection (auto only agent-to-agent via the `agents` property). Mechanism details live in
   each tool's official docs, not ours.

**Accepted residuals:** guardrail-hook coverage *inside* subagent threads is verified for Claude
Code (PreToolUse) but **unverified for Codex/Gemini** — until verified, their stage adapters rely on
the same policy + user-approval posture as those tools' main sessions; the Copilot cloud agent
ignores user-scope agents entirely (sees only the pushed repo — unchanged from the base decision).
**Surface coverage (verified 2026-07-24):** Codex subagents span CLI **and** IDE extension (official
docs: subagent activity appears in the ChatGPT desktop app, CLI, and IDE extension; same
`~/.codex/agents/`); Gemini is **CLI-verified only** — Code Assist agent mode is powered by
Gemini CLI but exposes a subset of its functionality, and subagents are not in the documented
subset (unverified there); Copilot's covered surfaces are VS Code + CLI (`~/.copilot/agents` is a
documented VS Code user-profile agents location).
