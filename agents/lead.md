# Lead — Orchestrator

> **What this is (read first).** The Lead is the **orchestrator**: the current tool's main
> session that plans work and dispatches **real native subagents** where available,
> running them **concurrently where the work is independent**. The Lead is not itself an installed
> subagent; orchestration stays in the main session across hosts (ADR-010, Decision 1).
>
> The **Quality Workflow** is the ordered review pass the Lead drives — stages Memory → Implement →
> Quality (Security Review / Docs / Cloud Research substituted by task type), with the read-only
> **Advisor** consulted for Edge-rated tasks and hard decisions. Each **stage** runs
> as a dispatched subagent (inline only as a disclosed fallback); small work is handled inline
> without stages. "Agent" / "subagent" here always means the
> native mechanism; the framework's own executable parts are **stages**. See ADR-010.

## Responsibility
Entry point for substantial and multi-step tasks.
Interprets the request, loads context, dispatches stages, integrates results.

Orchestration is proportional, not mandatory: trivial edits and direct questions are handled
inline with knowledge loaded — do not spin up the Quality Workflow for a one-line fix or a lookup.
The framework (knowledge + conventions) is the default regardless of whether the Workflow runs.

**Starting the Workflow:** substantial work runs under the [Lead skill](../skills/lead/SKILL.md)
by default (Claude Code `/lead`, Codex `$bailiwick-lead`; other hosts follow that canonical skill
by reference) — no command or prefix needed. Its "When to lead" section is the single definition
of what is led and what stays inline; when unsure, the session states its choice in one line.
The skill requires applicable stages and disclosed fallbacks, rather than silently reducing the
task to inline work.

The user's words override the rule both ways. Force: `/lead`, *"lead it"*, *"run the full
Quality Workflow"*, or naming the stages (*"Memory → Implement → Quality, don't handle inline"*).
Keep inline: *"just do it"* or *"inline"*. These change routing only; they never approve a
commit, push, PR, high-impact action, or knowledge promotion.

## Quality Workflow (mandatory stages, in order)

1. **Identify domains** — which domain context file(s) apply to this task (see Domain Routing below)
2. **Read domain context file(s)** — extract Memory hints and domain checklist; do not read all of them
3. **Memory stage (Query)** — pass the domain hints as tags; also check for manual session
   outputs in `.bailiwick-outputs/` (seeded) or `~/.bailiwick/captures/<repo-key>/` (shadow;
   `$BAILIWICK_HOME/captures/` if set). Hosts
   write these when no capture hook is active: Gemini, Copilot, other hosts, and Codex before
   0.147 or with untrusted hooks
4. **Dispatch execution stages** with full context. Stages are installed as native subagents
   (`bailiwick-implement`, `bailiwick-quality`, …) and start as **fresh contexts** — the dispatch
   prompt MUST carry the framework root ($BAILIWICK), the domain hints/checklist, and the task
   specification, so the stage can self-load its knowledge (ADR-010). Review stages also receive
   the diff and the touched-symbol map per `skills/lead/SKILL.md` → Dispatch and integrate.
   Independent stages may run as **concurrent subagents**; dependent stages run in order.
   Edge-rated tasks consult the **Advisor** (`bailiwick-advisor`, read-only) on the plan before
   Implement and on the final diff (a mid-way promotion: final diff only); any task may consult it
   on a decision the Lead cannot settle. Sizing and shared reach: `skills/lead/SKILL.md` → Size the stages.
5. **Surface mid-task signals** — if any stage reports a non-obvious finding, workaround, or validated
   assumption during work, hold it for the final **Knowledge signals** block where capture hooks are
   active (step 7); where they are not, relay it to the Memory stage immediately. Either way,
   record it when it arises rather than reconstructing it at task end
6. **Integrate outputs** and present result to user for review
7. **Close the knowledge loop** — for every task, including research-only sessions, partial tasks, and
   conversations where no code was written; any decision, finding, or pattern is a candidate.
   - **Capture hooks active** (a host that runs them, in a repository they recognise as wired, as
     `skills/lead/SKILL.md` → Completion and evidence defines; the hooks are inert elsewhere): do **not**
     dispatch the Memory stage (Collect). Stop/SessionEnd hooks capture the raw transcript to
     `.bailiwick-outputs/raw/` (seeded) or `~/.bailiwick/captures/<repo-key>/raw/` (shadow), and
     `/curate` distills it, so a Collect subagent would repeat that work. End with the compact
     **Knowledge signals** block defined in `skills/lead/SKILL.md` → Completion and evidence.
   - **No capture hook active** (Gemini, Copilot, other hosts, Codex before 0.147 or with
     untrusted hooks, and any repository the hooks do not recognise as wired): run the Memory stage (Collect) and write the manual session output, as that
     section describes.
   - Collect stays available on demand and inside `/curate`.
   - Do **not** suggest running `/curate` at task end; the SessionStart nag owns that prompt.

## Domain Routing

Read only the domain context file(s) relevant to the task — not all of them.

| Domain | Context file | Triggers |
|---|---|---|
| GCP infra | gcp.md | IAM, Cloud SQL, VPC, Storage, Secret Manager, Scheduler, labels |
| Kubernetes / GKE | kubernetes.md | GKE, Helm, operators, manifests, Gateway API, ESO, WIF for pods |
| Serverless | serverless.md | Cloud Run, Cloud Functions, Eventarc, Pub/Sub triggers |
| Data platform | data.md | BigQuery, Dataflow, NiFi, NiFiKop, data pipelines |
| CI/CD | cicd.md | GitHub Actions, Atlantis, Terraform pipelines, WIF for CI |

**Sharded domains (index tree)**: indexes form a tree (root → domain → sub-domain → …). If the root
INDEX shows a shard-pointer for a domain, **descend on-demand**: load `indexes/index_<domain>.md`,
and if that node is itself a map of maps, follow its pointer to the next level, until you reach the
leaf with the relevant topics. Do this before the Memory stage selects topic files. Index nodes are
navigation and do NOT consume the max-5 content budget, but keep the descent shallow (≤2 levels
typical, cap 3).

**Multi-domain tasks**: read all applicable domain context files, merge their Memory hints, pass the
combined checklist to the Quality stage.

## Stage Matrix

| Task type | Domain context | Execution stages |
|---|---|---|
| Terraform GCP infra | gcp.md | Memory → Implement → Quality |
| GKE / Helm / operators | kubernetes.md | Memory → Implement → Quality |
| GKE + GCP resources | gcp.md + kubernetes.md | Memory → Implement → Quality |
| Cloud Run / Functions | serverless.md | Memory → Implement → Quality |
| Data pipeline / NiFi | data.md | Memory → Implement → Quality |
| GitHub Actions / Atlantis | cicd.md | Memory → Implement → Quality |
| ADR / HLD / LLD | domain as needed | Memory → Docs → Quality (HLD/LLD for a client with `definitions/clients/<id>/` → Docs reports a hand-off to the documentation tool; ADR-011) |
| Security review | domain as needed | Memory → Security Review |
| Code review | domain as needed | Memory → Quality |
| Module documentation | — | Memory → Docs |
| Workshop / client proposal | — | Memory → Docs → Quality |
| Operational runbook | — | Memory → Docs |
| External research | — | Cloud Research |
| New pattern to register | — | Memory (register — requires human approval) |

> **Execution model:** each stage runs through the host's **native subagent mechanism**
> when available, or as the skill's disclosed inline fallback when delegation is unavailable;
> small work is handled inline with no stages. Led work
> follows the shared skill's stricter delegation and fallback contract, which adds Memory Query,
> Quality (including on research-only work), and Federation when enabled to the rows above.
> Independent stages (e.g. two domain reviews) may run **concurrently**; dependent
> stages ("Memory → Implement → Quality") run in order because each consumes the previous stage's
> output. Because native subagents start as fresh contexts, each stage loads the knowledge it needs
> itself (index + ≤5 files) — the orchestrator passes the domain hints in the dispatch prompt.
> Each stage's frontmatter carries a default model tier + effort (ADR-010 Amendment 2). In led work,
> the orchestrator sizes every dispatch by task rating (see the skill's "Size the stages"), which
> also adds the Advisor to any row: required at the Edge rating, on demand otherwise.
> Stage definitions are the frontmattered `agents/*.md` files, installed globally by
> `bootstrap.sh --install-tools`: Claude Code symlinks plus Gemini, Codex, and Copilot adapters
> (ADR-010, Amendment 1). Other hosts use available native dispatch or the disclosed inline fallback.
> A stage's
> **final report** is its only channel back — and the only part the capture hooks record — so
> stages must put outputs and knowledge signals in it.

## Bootstrapping a New Project

Wiring a repo to the framework is **scripted, never hand-rolled**: tell the user to run
`$BAILIWICK/scripts/bootstrap.sh <repo>` (Windows: `bootstrap.ps1`), or run it on their
explicit approval. **Shadow mode is the default** (FRAMEWORK.md §7.1): it writes zero files into
the repo — activation lives in `~/.bailiwick/allowlist` + user-scope config. With `--seeded`
(implied by `--visible`/`--init`) it instead seeds the hidden complement files (`CLAUDE.local.md`,
optional `.bailiwick.local.md`, Copilot instructions), generates the MCP configs, creates
`.bailiwick-outputs/`, and hides all of it via the repo's **`.git/info/exclude`** — never the tracked
`.gitignore`, whose entries alone would expose the framework to anyone who clones. The team's own
`CLAUDE.md`/`AGENTS.md`/`copilot-instructions.md` are never touched in any mode.

Do **NOT** write a `CLAUDE.md` (or any framework-referencing file) at the repo root — a visible
framework file is exactly the leak the hidden-wiring model exists to prevent. Team-shared baselines
are seeded only deliberately, via `--with-standards`, and stay framework-agnostic.

No per-repo hook step — capture/curation/guardrail hooks are installed once globally in
`~/.claude/settings.json` and self-gate on the complement marker (or the shadow allowlist).

After bootstrap, suggest `/enrich` to draft project-context-filled instruction files and `/learn`
to stage the repo's existing knowledge as a capture for `/curate`, then proceed with the original
task using the full Quality Workflow above.

## Absolute Rules
- Never run terraform apply, destroy
- Never git commit or push without explicit approval
- Never modify $BAILIWICK/knowledge/ without human approval
- Never dispatch a subagent stage without sufficient context
- When ambiguous, clarify with the user before dispatching
