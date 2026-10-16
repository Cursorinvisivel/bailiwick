---
name: lead
description: Coordinate a Bailiwick task through specialist agents, explicit stage dependencies, independent review, and an execution report. Use when the user requests the Lead, a team leader, or the full Quality Workflow for a concrete task; ordinary lookups do not need this skill.
---

# /lead — coordinate the Quality Workflow

Use the current main session as Lead. Read `$BAILIWICK/agents/lead.md` for domain routing
and stage selection; this skill adds the execution contract for an explicitly requested team.
It is shared across tools. Keep orchestration in the main session, even when a runtime permits
nested agents, so one coordinator owns dependencies, integration, and the final report.

## Resolve context and capabilities

1. Resolve the framework root from `$BAILIWICK`, the active private complement/operator guidance,
   or the physical location of this skill (resolve symlinks; the root is two directories above
   `skills/lead`). Confirm `agents/lead.md` exists. If unresolved, ask for the framework path;
   do not invent one or bootstrap the project as a side effect.
2. Read the project's authoritative instructions and its active private complement, then
   `agents/lead.md` and `knowledge/context/engineering-defaults.md`. Reuse material already in
   context. Search the repository and relevant KB index entries for existing work to extend.
3. Inspect the current runtime's actual delegation tools and available `bailiwick-*` agents.
   Do not infer capabilities from the editor's brand or an installed role file alone.

| Host | Entry and execution |
|---|---|
| Claude Code | `/lead` after global skill installation; dispatch installed stages through native subagent tools. |
| Codex | `$bailiwick-lead` wrapper; dispatch available custom agents through native subagent tools. |
| Gemini CLI / Code Assist | Follow this canonical skill directly, or use native skill discovery if configured. Dispatch stages only where the current runtime exposes delegation. |
| GitHub Copilot | Follow this file directly; use available agent delegation. Selecting one custom agent alone does not establish team execution. |
| Antigravity / other hosts | Follow this file by reference or through host-supported skill discovery. Verify native delegation; this skill does not install a host adapter. |

When native delegation is unavailable or prohibited by session policy, announce the limitation
before execution and adopt the stage definitions inline, in dependency order. Record these as
**inline fallback**, never as dispatched agents or independent review. Do not start extra CLIs,
install adapters, or change permissions to manufacture a team. If the user explicitly requires
real agents or independent review, complete safe preparation and report that requirement blocked.

## Plan the stages

State the requested outcome, acceptance criteria, and a compact stage plan before execution.
For each stage record its owner, inputs/dependencies, expected output, and execution mode
(`delegated`, `inline fallback`, or `not applicable` with reason). Include:

- **Memory Query** before execution, using domain hints and the KB loading budget from the Lead.
- **Execution** selected from the Lead's matrix: Implement for code/IaC, Docs for documents,
  Cloud Research for external evidence, or the requested review stage for review-only work.
- **Quality** after any implementation or document draft. Add Security Review when the change
  affects IAM, network exposure, secrets, or data exposure. For research-only work, have Quality
  check evidence, freshness, and applicability rather than a code checklist.
- **Memory Collect** after integration, including research-only and partially completed tasks.

Explicit invocation requires these applicable stages even for a small task; keep the scope of
each stage small. Do not silently replace delegated work with solo execution for convenience.
Stage dependencies determine order: research findings must reach implementation before decisions
that depend on them, and review must consume the completed draft. Parallelize only independent
work within runtime limits. An explicitly requested narrower scope still takes precedence;
record the omitted stages and the user's constraint.

## Dispatch and integrate

For each delegated stage, send a self-contained brief containing:

- Framework root and canonical role file (`agents/implementer.md`, `quality.md`, `memory.md`,
  `security-review.md`, `docs.md`, or `cloud-research.md` as appropriate).
- User objective, acceptance criteria, project instructions, domain hints/checklist, relevant
  knowledge facts/IDs, and upstream outputs. Do not assume the stage inherits main-session context.
- Exact file/module ownership and allowed side effects. Tell writers they share the workspace,
  must preserve others' edits, and must not revert unrelated work. Avoid concurrent ownership
  of the same files; assign a single integrator when boundaries overlap.
- Required return: findings/artifact paths, validation performed and results, unresolved issues,
  sources with dates for research, and reusable knowledge signals. Reviewers return severity
  and file/evidence references; Memory Collect returns candidates only, with no KB writes.

Wait for required outputs before starting dependent stages. Investigate conflicting findings,
integrate artifacts, and verify the acceptance criteria against the actual result. Surface
contradictions with existing knowledge as soon as found.

Keep implementation and review in separate agent contexts when delegation is available. Give
the reviewer the task, final draft/diff, and raw validation evidence; request its own assessment.
Resolve material findings, rerun affected checks, and return revised portions to review. If a
material issue cannot be resolved within the authorized scope, report the unfinished requirement
and its blocker; do not label the task complete. If delegation fails, record the failed attempt
and use the disclosed fallback above, without claiming an independent review occurred.

## Completion and evidence

Before reporting completion, confirm applicable stages returned results, review findings were
addressed or explicitly remain unresolved, and validation supports the acceptance criteria.
Include a concise execution table:

| Stage | Agent/thread or inline mode | Result / evidence | Outstanding issue |
|---|---|---|---|

Populate it with actual executions, including failures, inline fallbacks, and reasons for
omissions. Planning a stage is not evidence it ran. Distinguish completed work from blocked or
unverified requirements; retain that distinction when context is compacted or the task resumes.

Run Memory Collect on the integrated outputs and unresolved questions. Use its read-only
candidate/report operation, not its curation write/telemetry/commit steps. When Claude Code
capture hooks are active, include knowledge signals in the main conversation. On hosts without
those hooks, write a short manual session output under the project's `.bailiwick-outputs/`
(unless the user forbids it), using `knowledge/templates/agent-output-template.md`. Record
the execution table, validation, knowledge candidates, and retrieval feedback there. Respect
shadow-mode privacy: verify this staging path is ignored before writing; if it is not, keep
the report in the conversation and disclose why it was not persisted.

Invoking Lead authorizes orchestration of the requested task, not extra external actions.
Preserve existing human gates for high-impact actions, commits/pushes/PRs, and knowledge
promotion. Research that should enter the KB goes through `/investigate` or `/curate` with
its explicit approval gate; Lead and its subagents do not promote knowledge themselves.
