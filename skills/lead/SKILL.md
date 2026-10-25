---
name: lead
description: Coordinate a Bailiwick task through specialist agents, explicit stage dependencies, independent review, and an execution report. Use only when the user explicitly invokes /lead or asks for the Bailiwick Lead by name; proportional routing and ordinary lookups do not need this skill.
---

# /lead — coordinate the Quality Workflow

Use the current main session as Lead. Read `$BAILIWICK/agents/lead.md` for domain routing
and its stage matrix; this skill adds the execution contract for an explicitly requested team,
including the stages it adds to that matrix (see "Plan the stages").
It is shared across tools. Keep orchestration in the main session, even when a runtime permits
nested agents, so one coordinator owns dependencies, integration, and the final report.

## Resolve context and capabilities

1. Resolve the framework root from `$BAILIWICK`, the active private complement/operator guidance,
   or the physical location of this skill (resolve symlinks; the root is the parent of
   `skills/`). Confirm `agents/lead.md` exists. If unresolved, ask for the framework path;
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
For each stage record its owner, inputs/dependencies, expected output, sizing (model tier and
effort, see "Size the stages"), and execution mode (`delegated`, `inline fallback`, or
`not applicable` with reason). Include:

Start from the Lead's matrix row for the task type, then apply these additions. They are
deliberate: explicit invocation is stricter than proportional routing, so rows that omit Memory
Query or Quality (for example Module documentation, Operational runbook, External research)
gain them here.

- **Memory Query** before execution, using domain hints and the KB loading budget from the Lead.
  Alongside it, run the **Federation** consult (`agents/federation.md`, read-only) when
  `.bailiwick-sources.json` has an enabled source; the Lead dispatches it, because a Memory
  subagent cannot spawn further agents.
- **Execution** selected from the Lead's matrix: Implement for code/IaC, Docs for documents,
  Cloud Research for external evidence, or the requested review stage for review-only work.
- **Quality** after any implementation or document draft. Add Security Review when the change
  affects IAM, network exposure, secrets, or data exposure. Research-only work also requires
  Quality, scoped to evidence, freshness, and applicability rather than a code checklist.
- **Memory Collect** after integration, including research-only and partially completed tasks.

Explicit invocation requires these applicable stages even for a small task; keep the scope of
each stage small. **Split large Implement work into slices.** Give each module or file-ownership
boundary its own Implement dispatch, each starting fresh, rather than one long run. A stage
re-reads its whole context on every turn, so one long run costs far more than the same work done
in fresh slices. Run independent slices concurrently and dependent ones in order. Review the
integrated result: Quality and Security Review see all slices together, so no cross-slice issue
escapes review. Do not silently replace delegated work with solo execution for convenience.
Stage dependencies determine order: research findings must reach implementation before decisions
that depend on them, and review must consume the completed draft. Parallelize only independent
work within runtime limits. An explicitly requested narrower scope still takes precedence;
record the omitted stages and the user's constraint.

## Size the stages

Rate the task before dispatch and add model tier and effort to each stage's plan entry. This
skill explicitly instructs per-dispatch sizing: pass both on every delegated stage where the
host accepts them, never leaving them to the session default by omission.

| Task rating | Signals | Implement | Docs / Cloud Research | Quality / Security Review |
|---|---|---|---|---|
| **Trivial** | One file, no IAM/network/state impact, pattern already in KB | standard, low | standard, low | deep, medium |
| **Standard** | Default; a module or document, bounded blast radius | session model, medium | standard, medium | deep, high |
| **Complex / high-risk** | Multi-module, IAM, networking, state moves, prod, unfamiliar API | deep, high | standard, high | deep, high |

Memory, Federation, and freshness checks stay **light, low** regardless of rating; they navigate
and read. A reviewer never runs below the implementer's tier or effort. The canonical frontmatter
(`model:`/`effort:` in `agents/*.md`) holds the Standard defaults. A stage with `model: inherit`
(Implement) is task-sized and must always be sized explicitly.

Tiers map per host. Honour what the current runtime actually exposes, and record anything it
cannot express:

| Host | Light / standard / deep | Effort | Per-dispatch override |
|---|---|---|---|
| Claude Code | `haiku` / `sonnet` / `opus` (`inherit` = session model) | `low`/`medium`/`high` | Agent tool `model` and `effort` override frontmatter |
| Codex | Not mapped; the session model is used unless the user names one | `model_reasoning_effort` | Spawn values apply only where the agent file sets none; Implement's adapter omits it, so pass effort at spawn. Other stages' file values are fixed |
| GitHub Copilot | Not mapped; uses the selected model | `reasoning-effort` in the adapter | None; adapter values are fixed. Record Implement as "file default" |
| Gemini CLI / Antigravity | Not mapped; inherits the session model | No field | None; record sizing as "host default" |

Never invent another vendor's model names to fill a tier; record "inherit" instead. Do not
raise or lower sizing to save time once the plan is stated. If a stage proves harder than
rated (failed validation, material review findings), re-dispatch it one level up and record
the change.

## Dispatch and integrate

Pass each stage's planned sizing through the host's dispatch parameters (for example, the
Agent tool's `model` and `effort`, or Codex spawn values), not as prose in the brief. A
model cannot change its own size. For each delegated stage, send a self-contained brief
containing:

- Framework root and canonical role file (`agents/implementer.md`, `quality.md`, `memory.md`,
  `security-review.md`, `docs.md`, `cloud-research.md`, or `federation.md` as appropriate).
- User objective, acceptance criteria, project instructions, domain hints/checklist, relevant
  knowledge facts/IDs, and upstream outputs. Do not assume the stage inherits main-session context.
- The evidence you already hold, so the stage does not rediscover it: file paths with line
  ranges, and the excerpts that matter. A reviewer gets the full diff to review, inline. A
  stage's reads stay in its context for every later turn, so supplied evidence is cheaper than
  re-reads. Supplying it does not limit the stage: reviewers still verify independently and
  read whatever they judge necessary.
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

| Stage | Agent/thread or inline mode | Model / effort | Result / evidence | Outstanding issue |
|---|---|---|---|---|

Populate it with actual executions, including failures, inline fallbacks, and reasons for
omissions. Record the sizing actually applied (`opus / high`, `inherit / file default`,
`host default`), not the planned one. Planning a stage is not evidence it ran. Distinguish completed work from blocked or
unverified requirements; retain that distinction when context is compacted or the task resumes.

Run Memory Collect on the integrated outputs and unresolved questions. Use its read-only
candidate/report operation, not its curation write/telemetry/commit steps. When the host's
capture hooks are active (Claude Code; Codex CLI 0.147+ once its hooks are trusted), include
knowledge signals in the main conversation. Otherwise write a short manual session output
(unless the user forbids it), using `knowledge/templates/agent-output-template.md`, and record
the execution table, validation, knowledge candidates, and retrieval feedback there. Stage it
where `/curate` gathers, using the same seeded/shadow split as `/learn` (seeded wins if both):

- **seeded** → the project's `.bailiwick-outputs/`. Verify the path is git-ignored first; if it
  is not, keep the report in the conversation and disclose why it was not persisted.
- **shadow** → `~/.bailiwick/captures/<repo-key>/` (`$BAILIWICK_HOME/captures/` if set), with
  `<repo-key>` computed by `capture_session.repo_key` as `/learn` does. Nothing is written into
  the repository.

Invoking Lead authorizes orchestration of the requested task, not extra external actions.
Preserve existing human gates for high-impact actions, commits/pushes/PRs, and knowledge
promotion. Research that should enter the KB goes through `/investigate` or `/curate` with
its explicit approval gate; Lead and its subagents do not promote knowledge themselves.
