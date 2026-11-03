---
name: lead
description: Default way of working for substantial tasks in a Bailiwick-wired repository (framework defaults are active in the session, a CLAUDE.local.md/.bailiwick.local.md complement references the framework, the repo is in ~/.bailiwick/allowlist, BAILIWICK_SHADOW=1 is set, or it is the framework repo itself) — more than one file beyond typos/formatting/mechanical renames, any other IaC change, any IAM/network/secrets/security-control change, a single-file change adding behaviour beyond a small fix, a new module/document/test suite or substantive doc rewrite, a design decision, or a requested review or researched recommendation. Coordinates specialist stage agents with explicit dependencies, independent review, and an execution report; use it without being asked. Skip it for questions, lookups, explanations, typos/formatting/mechanical renames, and small single-file fixes, which the main session handles inline. Outside wired repositories, use it only when the user invokes /lead.
---

# /lead — coordinate the Quality Workflow

Use the current main session as Lead. Read `$BAILIWICK/agents/lead.md` for domain routing
and its stage matrix; this skill adds the execution contract for substantial work, including
the stages it adds to that matrix (see "Plan the stages").
It is shared across tools. Keep orchestration in the main session, even when a runtime permits
nested agents, so one coordinator owns dependencies, integration, and the final report.

## When to lead

Loading this skill does not make a task led. Decide first, with these rules; if the task stays
inline, say so in one line and continue in the main session without stages or an execution table.

1. **Wired repository?** The default applies only where Bailiwick is wired: framework defaults
   are active in the session, a `CLAUDE.local.md`/`.bailiwick.local.md` complement references the
   framework, the repo is listed in `~/.bailiwick/allowlist`, `BAILIWICK_SHADOW=1` is set, or it
   is the framework repo itself.
   Elsewhere, lead only when the user invokes `/lead`.
2. **Apply the rule.** This one line is canonical; the session-start banner and the host
   templates copy it verbatim:

   > Lead it: more than one file (beyond typos, comments, formatting, mechanical renames); any other IaC change; any IAM, network, secrets, or security-control change in any file; a single-file change that adds behaviour beyond a small fix; a new module, document or test suite, or a substantive doc rewrite; a design decision; a requested review or researched recommendation. Inline: questions, lookups, explanations, those mechanical edits, and small single-file fixes.

   Precedence: typos, comments, formatting, and mechanical renames stay inline even when they span
   files, touch IaC, or ship. Otherwise any *Lead it* trigger wins over the inline list. "Explain
   this code" or "what does X do" is inline; "review this module/PR" or "what's the best way to do
   X on GCP" is a requested review or researched recommendation, so it is led.
3. **Unsure?** Pick one, state it in one line ("leading this: touches IAM" / "handling inline:
   one-line typo fix"), then proceed. Do not block on a reply; the user can redirect.

The user's words override the rule both ways. Force: `/lead`, "lead it", "run the full Quality Workflow", or naming the stages. Keep inline: "just do it" or "inline".
These phrases change routing only. They never approve a commit, push, PR, high-impact action, or
knowledge promotion. A task that grows past the inline rules mid-way (a second file, an IAM
change) switches to this contract at that point; say so and plan the remaining stages.

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
deliberate: this contract is stricter than the matrix alone, so rows that omit Memory Query or
Quality (for example Module documentation, Operational runbook, External research) gain them
here.

- **Memory Query** before execution, using domain hints and the KB loading budget from the Lead.
  Alongside it, run the **Federation** consult (`agents/federation.md`, read-only) when
  `.bailiwick-sources.json` has an enabled source; the Lead dispatches it, because a Memory
  subagent cannot spawn further agents.
- **Execution** selected from the Lead's matrix: Implement for code/IaC, Docs for documents,
  Cloud Research for external evidence, or the requested review stage for review-only work.
- **Quality** after any implementation or document draft. Add Security Review when the change
  affects IAM, network exposure, secrets, or data exposure. Research-only work also requires
  Quality, scoped to evidence, freshness, and applicability rather than a code checklist.
- **Advisor** (`agents/advisor.md`, read-only): required for Edge-rated tasks, on the plan
  before Implement and on the final diff; otherwise on demand (see "Size the stages").
- **Memory Collect** after integration, including research-only and partially completed tasks.

Once you decide to lead a task, these applicable stages are required even when it turns out
small; keep the scope of each stage small (rate it Trivial in "Size the stages" when its signals
fit). **Split large Implement work into slices.** Give each module or file-ownership
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

| Task rating | Signals | Implement | Docs / Cloud Research | Quality / Security Review | Advisor |
|---|---|---|---|---|---|
| **Trivial** | One file, no IAM/network/state impact, pattern already in KB | sonnet, low | sonnet, low | sonnet, medium | — |
| **Standard** | Default; a module or document, bounded blast radius | sonnet, medium | sonnet, medium | opus, medium | on demand |
| **Complex / high-risk** | Multi-module, IAM, networking, state moves, prod, unfamiliar API | opus, high | sonnet, high | opus, high | on demand |
| **Edge** | Complex, plus any of: no precedent in the KB, the repo, or the vendor's documented patterns; a novel design or architecture choice; an irreversible or high-blast step | opus, high | sonnet, high | opus, high | fable, high: on the plan before Implement and on the final diff |

**Shared reach** — the change is consumed by many downstream units: shared Terraform modules, CI
templates, org policies, landing-zone/host projects; in the framework repo, stage instructions,
skills, hooks and guardrails. Shared reach raises Quality and Security Review to the Complex row;
Implement and Docs / Cloud Research stay at the rating the edit itself earns.

Tiers: light = `haiku`, standard = `sonnet`, deep = `opus`, advisor = `fable`. Use the cheapest
tier that fits the rating; do not default to `opus`. Memory Query, Federation, and freshness
checks run **haiku, low** regardless of rating; they navigate and read. Memory Collect runs
**sonnet, low**, because it judges what is reusable. A reviewer never runs below the
implementer's tier or effort. The canonical frontmatter (`model:`/`effort:` in `agents/*.md`)
holds the Standard defaults. A stage with `model: inherit` (Implement) is task-sized and must
always be sized explicitly. Memory Query (haiku, low) differs from `memory.md`'s frontmatter
(sonnet, low = Memory Collect), so pass its sizing explicitly at dispatch.

The Lead is the main session and sizes every dispatch, brief, and scope, so it is where a deep
model pays across the whole task: run it on `opus` (`fable` for sessions dominated by Edge work).
The Lead's model is the user's session choice; record it as a `Lead (main session)` row in the execution table.

Consult the **Advisor** on demand at any rating when the Lead cannot settle a decision on its
own: conflicting material findings, a design choice with no precedent in the KB, the repo, or the vendor's documented patterns, or an irreversible or
high-blast step. Brief it compactly with the question, the options, the constraints, and the
evidence (about 2k tokens excluding the diff; pass a diff as a file path), never with the whole
task history. It never edits. The final-diff consult: give it the diff file, the reviewers'
findings and the plan decision; ask whether the result realises the decision and which edge
risks remain unaddressed, not a line-by-line review. A task promoted to Edge mid-way consults
the Advisor on the final diff only.

Tiers map per host. Honour what the current runtime actually exposes, and record anything it
cannot express:

| Host | Light / standard / deep / advisor | Effort | Per-dispatch override |
|---|---|---|---|
| Claude Code | `haiku` / `sonnet` / `opus` / `fable` (`inherit` = session model) | `low`/`medium`/`high` | Agent tool `model` and `effort` override frontmatter |
| Codex | Not mapped; the session model is used unless the user names one | `model_reasoning_effort` | Spawn values apply only where the agent file sets none. The rated stages (Implement, Quality, Security Review, Docs, Cloud Research) have no effort in their adapter, so pass effort at spawn; other stages' file values are fixed |
| GitHub Copilot | Not mapped; uses the selected model | `reasoning-effort` in the adapter | None; adapter values are fixed. Rated stages use their `fixed_host_effort` (frontmatter: the effort for hosts that cannot size per dispatch; reviewers high, Docs/Research medium). Record sizing as "file default" |
| Gemini CLI / Antigravity | Not mapped; inherits the session model | No field | None; record sizing as "host default" |

Never invent another vendor's model names to fill a tier; record "inherit" instead (the advisor
tier is not mapped outside Claude Code). Do not
raise or lower sizing to save time once the plan is stated. If a stage proves harder than
rated (failed validation, material review findings), re-dispatch it one level up and record
the change.

## Dispatch and integrate

Pass each stage's planned sizing through the host's dispatch parameters (for example, the
Agent tool's `model` and `effort`, or Codex spawn values), not as prose in the brief. A
model cannot change its own size. For each delegated stage, send a self-contained brief
containing:

- Framework root and canonical role file (`agents/implementer.md`, `quality.md`, `memory.md`,
  `security-review.md`, `docs.md`, `cloud-research.md`, `federation.md`, or `advisor.md` as
  appropriate).
- User objective, acceptance criteria, project instructions, domain hints/checklist, relevant
  knowledge facts/IDs, and upstream outputs. Do not assume the stage inherits main-session context.
- The evidence you already hold, so the stage does not rediscover it: file paths with line
  ranges, and the excerpts that matter. A stage's reads stay in its context for every later
  turn, so supplied evidence is cheaper than re-reads. Supplying it does not limit the stage:
  reviewers still verify independently and read whatever they judge necessary.
- **Reviewer briefs carry the diff itself (required, checked at completion).** Build it from
  `git status --porcelain` plus `git diff HEAD`, and add the contents of new untracked files,
  which `git diff` omits. For committed branch work plus uncommitted changes use
  `git diff $(git merge-base <base> HEAD)` instead of `git diff HEAD`. Small change (rough guide:
  up to ~400 diff lines): paste it inline. Larger: write it to a scratch file OUTSIDE the repo
  (session scratchpad) with ONE shell redirect (bash / Git Bash), scoping untracked files to the
  task's paths:
  `{ git status --porcelain; git diff HEAD; git ls-files -o --exclude-standard -z -- <paths> | xargs -0 -r -n1 git diff --no-index -- /dev/null; } > <file>`
  Skip binaries, secrets (.tfvars, .env, key JSON) and large generated files. Exit 123 is expected
  (`diff --no-index` returns 1 when files differ); sanity-check with `grep -c '^diff --git' <file>`.
  It is an exact byte copy that costs no generated tokens; give the reviewer the path and line
  count. Never hand over "run git diff": that sends the reviewer fetching file by file. The cap
  exists because a pasted diff is the Lead's own output: it is paid once per reviewer (twice with
  Quality and Security Review in parallel), stays in the Lead's context and the capture
  transcripts, and a long hand copy can silently alter lines. If the supplied diff and the working
  tree disagree, the tree wins; flag the mismatch. Include the implementer's touched-symbol map
  (symbol → file:line → references) when one exists.
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
the reviewer the task, the final diff (inline or as a diff file, per the brief requirement
above), the touched-symbol map, and raw validation evidence; request its own assessment.
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
`host default`), not the planned one. For each review stage, state the diff delivery in its
Result / evidence cell: `diff inline`, `diff file: <path> (<n> lines)`, or
`not inline: <reason>`. Planning a stage is not evidence it ran. Distinguish completed work from
blocked or unverified requirements; retain that distinction when context is compacted or the
task resumes.

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

Leading a task, whether invoked or by default, authorizes orchestration of that task only, not
extra external actions.
Preserve existing human gates for high-impact actions, commits/pushes/PRs, and knowledge
promotion. Research that should enter the KB goes through `/investigate` or `/curate` with
its explicit approval gate; Lead and its subagents do not promote knowledge themselves.
