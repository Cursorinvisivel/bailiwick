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

## Amendment 2 (2026-10-22) — stage sizing (model tier + effort)

**Finding.** Every stage ran at the main session's model and default effort. A Memory index walk
cost the same as a Security Review. Verified against official docs (2026-10-22), each host offers
a different sizing surface:
- **Claude Code:** subagent frontmatter `model` (`haiku`/`sonnet`/`opus`/`inherit`/full ID) and
  `effort` (`low`…`max`). The Agent tool's per-invocation `model` and `effort` override both.
- **Codex:** agent TOML `model` and `model_reasoning_effort`. A value in the **file takes
  precedence** over explicit spawn values and `[agents]` defaults.
- **Copilot (VS Code / CLI):** `.agent.md` `model` (harness model names, string or preference
  list) and `reasoning-effort` (`low`…`max`). Subagent dispatch cannot override them.
- **Gemini CLI:** `model` (Gemini model name) and no effort field. Gemini CLI was superseded by
  **Antigravity CLI** (2026-06-18), which reads custom agents from `~/.gemini/config/agents/`
  (`subagent: true`, `model: inherit|flash|pro`). That path is not yet generated (residual below).

**Decision.**
1. Canonical `agents/*.md` carry Claude Code `model:` + `effort:` as the **Standard-task
   defaults**: Memory/Federation/freshness light, Docs/Cloud Research standard, Quality/Security
   Review deep + high. Implement is `model: inherit` + `effort: medium`, which marks it as the
   **task-sized** stage.
2. `/lead` rates the task (trivial / standard / complex-high-risk), records model tier + effort per
   stage, passes them through the host's dispatch parameters, and reports the sizing actually
   applied. A reviewer never runs below the implementer.
3. Adapters translate **effort only**. `model:` is never translated, because tier names do not map
   across vendors and pinned names rot. Codex gets `model_reasoning_effort` except on task-sized
   stages (the file would block the Lead's spawn value). Copilot gets `reasoning-effort`. Gemini
   gets nothing.

**Accepted residuals:** on Codex/Copilot/Gemini the model tier is the session's. Copilot and the
fixed Codex stages cannot be resized per task. No Antigravity `~/.gemini/config/agents/` adapter
exists yet.

## Amendment 3 (2026-11-03) — the Lead skill is the default for substantial work

**Finding.** Decision 4 kept routing proportional, and the stricter `/lead` contract (required
stages, explicit sizing, execution table) ran only when the user remembered to invoke it. Measured
on captures since 2026-10-25: 2 explicit `/lead` invocations against 102 stage dispatches. Most
substantial work ran under the lighter `agents/lead.md` routing, so docs and runbooks went
unreviewed and sizing was left to frontmatter defaults. The skill's own description ("Use only
when the user explicitly invokes /lead") actively blocked description-matched invocation.

**Decision.**
1. In a Bailiwick-wired repository, substantial work runs under the Lead skill **by default**.
   The skill's description and the session-start defaults instruct the session to invoke it
   unasked. Outside wired repositories the globally installed skill stays opt-in, so it does not
   self-invoke in unrelated projects.
2. The line is defined once, as a canonical one-line rule in the skill's **"When to lead"**
   section, which the session-start banner and the Codex/Antigravity templates copy verbatim (a
   test keeps them in sync). Led: more than one file beyond typos, comments, formatting, and
   mechanical renames; any other IaC change; any IAM, network, secrets, or security-control
   change in any file; a single-file change that adds behaviour beyond a small fix; a new module,
   document, or test suite, or a substantive doc rewrite; a design decision; a requested review or
   researched recommendation.
   Inline: questions, lookups, explanations, those mechanical edits, and small single-file fixes.
   The mechanical edits stay inline even across files or in IaC; otherwise any led trigger wins.
3. Loading the skill does not make a task led: the session applies the rule first and, for inline
   work, says so in one line and continues without stages. When unsure, it states its choice in
   one line and proceeds without waiting.
4. The user's words override the rule both ways (force: `/lead`, "lead it", "run the full Quality
   Workflow", naming the stages; keep inline: "just do it", "inline"). They change routing only and
   never satisfy a human gate. A task that outgrows the inline rules mid-way switches to the Lead.
5. This amends Decision 4 (where the line sits and which contract applies above it) and narrows
   Decision 2: small work is handled inline with no stages, and a led stage runs inline only as the
   skill's disclosed fallback when delegation is unavailable.

**Accepted residuals:** led tasks gain Memory Query, Quality, and Memory Collect stages, so a
small led task costs more than it did under matrix routing. The Trivial sizing row lowers effort,
but Quality stays deep, so every led task pays at least one deep review. Invocation is policy, not
a runtime switch: a session can still misjudge the line, which is why it states its choice when
unsure. Copilot and the seeded instruction files get the rule only indirectly (via
`agents/lead.md`) until the Copilot instructions, project CLAUDE.md, and project AGENTS.md templates
in `knowledge/templates/` are updated through `/curate`; those still offer the old `Lead:` prefix.

**Trial rollout.** This ships to the private framework clones first (merged into
`bailiwick-private` main) and is judged with `scripts/stage_cost.py` before the public merge. If the
trial is undone with `git revert -m 1 <merge>`, git still records the commits as merged, so a later
pull of the same commits from public `main` silently brings nothing back. Before re-merging, revert
the revert commit. Check that the change is really present with
`grep -q '^## When to lead' skills/lead/SKILL.md`.

## Amendment 4 (2026-11-03) — tier economy and the Advisor grade

**Finding.** Measured on captures since 2026-10-25 (satellite): reviewers (Quality, Security Review)
processed about 2.6–2.9M tokens per run at opus/high, the most expensive stage per run; Implement
about 0.9M. Amendment 2's table had no tier between "everything deep" and light for reviewers, so
a Trivial or Standard change still paid a deep, high-effort review. It also had no reach signal: a
change to framework instructions (stage files, skills, hooks, guardrails) was rated Standard by edit
size although its blast radius is every later session. A first fix rated all framework-instruction
changes Complex, which made almost every change in this repo Complex (opus/high Implement for a
one-rule markdown change) and gave client repos no trigger. And it had no slot for the most capable
model on genuinely novel or irreversible work.

**Decision.**
1. `/lead` sizes each dispatch from this table (Claude Code model, effort), using the cheapest tier
   that fits (light=haiku, standard=sonnet, deep=opus, advisor=fable):

   | Rating | Signals | Implement | Docs / Cloud Research | Quality / Security Review | Advisor |
   |---|---|---|---|---|---|
   | Trivial | one file, no IAM/network/state impact, pattern in KB | sonnet, low | sonnet, low | sonnet, medium | — |
   | Standard | default; module or document, bounded blast radius | sonnet, medium | sonnet, medium | opus, medium | on demand |
   | Complex / high-risk | multi-module, IAM, networking, state moves, prod, unfamiliar API | opus, high | sonnet, high | opus, high | on demand |
   | Edge | Complex, plus any of: no precedent in the KB, the repo, or the vendor's documented patterns; a novel design or architecture choice; an irreversible or high-blast step | opus, high | sonnet, high | opus, high | fable, high (plan before Implement + final diff) |

   The SKILL.md table is canonical; this is the as-adopted copy.

   Memory Query, Federation, and freshness run haiku + low; Memory Collect runs sonnet + low. A
   reviewer never runs below the implementer.
2. **Shared reach is a reviewer signal.** Canonical definition: `skills/lead/SKILL.md` "Size the
   stages". Shared reach means the change is consumed by many downstream units: shared Terraform
   modules, CI templates, org policies, landing-zone/host projects; in the framework repo, stage
   instructions, skills, hooks and guardrails. Shared reach raises Quality and Security Review to
   the Complex row; Implement and Docs / Cloud Research stay at the rating the edit itself earns. This replaces the
   framework-only "framework-wide reach" wording.
3. **Lead model.** The Lead is the main session and sizes every dispatch (prompts, tasks, reach).
   Recommended model: opus; fable for Edge-dominated sessions. This is the user's choice, not
   enforced.
4. **Advisor stage.** New `agents/advisor.md`: `bailiwick-advisor`, model fable, effort high, tools
   Read/Grep/Glob (read-only, never edits). It gets a compact brief and returns a second opinion.
   It runs on Edge work (reviewing the plan before Implement and the final diff) and on demand at
   any rating when the Lead cannot settle a decision. It is installed by bootstrap like every
   frontmattered `agents/*.md`. Rules:
   - "Reviewers disagreeing" is not an Edge signal (it can only appear after review); it stays an
     on-demand Advisor trigger.
   - A task promoted to Edge mid-way consults the Advisor on the final diff only.
   - The final-diff consult receives the diff file, the reviewers' findings, and the plan decision,
     and asks "does the result realise the decision, and which edge risks remain" — not a third
     line-by-line review.
   - The brief is about 2k tokens excluding the diff, which is passed as a file.
5. **Frontmatter defaults.** `quality.md` and `security-review.md` change from opus + high to opus +
   medium. Frontmatter holds the Standard defaults, as Amendment 2 decision 1 intended. The Lead
   raises effort for Complex and Edge. This amends the reviewer default in Amendment 2 decision 1.
6. **Host effort.** New frontmatter key `fixed_host_effort` (quality, security-review: high; docs,
   cloud-research: medium) is the effort for hosts that cannot be sized per dispatch. Codex adapters
   for rated stages (Implement, Quality, Security Review, Docs, Cloud Research) omit
   `model_reasoning_effort`, so the Lead passes effort at spawn. Copilot cannot size per dispatch and
   uses `fixed_host_effort`, so reviewers stay at high there: quality over cost where sizing is
   impossible. Read-only adapter detection also catches NotebookEdit and MCP write tools.

**Accepted residuals:** Standard reviews at medium effort may catch less than at high, so review
findings and post-merge defects need watching (`scripts/stage_cost.py` for cost). Round-1
search/edit discipline and the effort change ship together, so `stage_cost.py` cannot attribute
savings between them; watch review yield (findings per review vs post-merge defects) as the quality
signal. Fable is the most expensive tier, so the Advisor is gated to Edge or explicit on-demand use.
The advisor tier is Claude-Code-only: `model:` is still not translated, so on other hosts the
Advisor runs on the session model. On Copilot, reviewers run at `fixed_host_effort` (high), costing
more than Claude Code Standard reviews. The Lead model is a recommendation the user may ignore.

## Amendment 5 (2026-11-03) — skills dispatch stages; restricted local reviewer; inbox plaintext rule

1. **Skills dispatch stages outside `/lead`.** `/curate` (Step 2a Collect, Step 5a review) and
   `/purge` (3a, 3b, 5a) dispatch native stage subagents themselves, sized per the
   `skills/lead/SKILL.md` tiers. Delegated stages never write or gate; the skill keeps the human gate.
   Unavailable delegation is an inline fallback, disclosed.
2. **Restricted `security-review-local`.** New `agents/security-review-local.md`
   (`bailiwick-security-review-local`, Read/Grep/Glob only: no shell, no web). A variant of Security
   Review, not a stage; used when the input is sensitive (purge plans, security-tagged curate
   candidates). Agent files: 16 (8 stages, 5 domain, lead, 2 restricted variants).
3. **Inbox plaintext rule.** While the `/curate` inbox holds decrypted plaintext, no web- or
   shell-capable stage receives decrypted content. Decrypted copies are deleted after extraction,
   before any reviewer runs.
