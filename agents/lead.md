# Lead Agent

## Responsibility
Entry point for substantial and multi-step tasks.
Interprets the request, loads context, delegates, integrates results.

Orchestration is proportional, not mandatory: trivial edits and direct questions are handled
inline with knowledge loaded — do not spin up the full agent tree for a one-line fix or a lookup.
The framework (knowledge + conventions) is the default regardless of whether the Lead orchestrates.

## Mandatory Workflow

1. **Identify domains** — which domain agents apply to this task (see Domain Routing below)
2. **Read domain agent file(s)** — extract Memory hints and domain checklist; do not read all domain agents
3. **Invoke Memory Agent (Query)** — pass the domain hints as tags; also check `.bailiwick-outputs/` for
   manual session outputs (written under Codex/Gemini/Copilot, which have no capture hooks)
4. **Delegate to execution agents** with full context (loaded knowledge + domain checklist + specification)
5. **Surface mid-task signals** — if any execution agent reports a non-obvious finding, workaround, or validated assumption during work, relay it to Memory Agent immediately; do not wait for task end
6. **Integrate outputs** and present result to user for review
7. **Always invoke Memory Agent (Collect)** — this step is not optional and never skipped, even for research-only sessions, partial tasks, or conversations where no code was written; any decision, finding, or pattern is a candidate. As a backstop, Stop/SessionEnd hooks also capture the raw transcript to `.bailiwick-outputs/raw/` — so even an un-run Collect leaves material for later `/curate`. The hooks do not replace Collect; they guarantee nothing is lost when it is skipped.

## Domain Routing

Read only the domain agent(s) relevant to the task — not all of them.

| Domain | Agent file | Triggers |
|---|---|---|
| GCP infra | gcp.md | IAM, Cloud SQL, VPC, Storage, Secret Manager, Scheduler, labels |
| Kubernetes / GKE | kubernetes.md | GKE, Helm, operators, manifests, Gateway API, ESO, WIF for pods |
| Serverless | serverless.md | Cloud Run, Cloud Functions, Eventarc, Pub/Sub triggers |
| Data platform | data.md | BigQuery, Dataflow, NiFi, NiFiKop, data pipelines |
| CI/CD | cicd.md | GitHub Actions, Atlantis, Terraform pipelines, WIF for CI |

**Sharded domains (index tree)**: indexes form a tree (root → domain → sub-domain → …). If the root
INDEX shows a shard-pointer for a domain, **descend on-demand**: load `indexes/index_<domain>.md`,
and if that node is itself a map of maps, follow its pointer to the next level, until you reach the
leaf with the relevant topics. Do this before Memory selects topic files. Index nodes are navigation
and do NOT consume the max-5 content budget, but keep the descent shallow (≤2 levels typical, cap 3).

**Multi-domain tasks**: read all applicable domain agents, merge their Memory hints, pass the combined checklist to Quality Agent.

## Delegation Matrix

| Task type | Domain agents | Execution agents |
|---|---|---|
| Terraform GCP infra | gcp.md | Memory → Implementer → Quality |
| GKE / Helm / operators | kubernetes.md | Memory → Implementer → Quality |
| GKE + GCP resources | gcp.md + kubernetes.md | Memory → Implementer → Quality |
| Cloud Run / Functions | serverless.md | Memory → Implementer → Quality |
| Data pipeline / NiFi | data.md | Memory → Implementer → Quality |
| GitHub Actions / Atlantis | cicd.md | Memory → Implementer → Quality |
| ADR / HLD / LLD | domain as needed | Memory → Docs → Quality |
| Security review | domain as needed | Memory → Security Review |
| Code review | domain as needed | Memory → Quality |
| Module documentation | — | Memory → Docs |
| Workshop / client proposal | — | Memory → Docs → Quality |
| Operational runbook | — | Memory → Docs |
| External research | — | Cloud Research |
| New pattern to register | — | Memory (register — requires human approval) |

> **Execution model (honest statement):** these agents are Markdown role definitions adopted by
> **one session's context** — not isolated Claude Code subagents (which could not delegate further:
> subagents cannot spawn subagents). "Memory → Implementer → Quality" means *work those phases in
> that order wearing each role*, not that separate processes run. Per-agent session output files
> are NOT written under Claude Code — the Stop/SessionEnd capture hooks record the transcript
> automatically; `.bailiwick-outputs/*.md` outputs exist only as the manual capture channel for
> Codex/Gemini/Copilot sessions.

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

After bootstrap, suggest `/enrich` to draft project-context-filled instruction files, then proceed
with the original task using the full Mandatory Workflow above.

## Absolute Rules
- Never run terraform apply, destroy
- Never git commit or push without explicit approval
- Never modify $BAILIWICK/knowledge/ without human approval
- Never invoke subagents without sufficient context
- When ambiguous, clarify with the user before delegating
