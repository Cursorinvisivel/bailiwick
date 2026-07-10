# Knowledge Index

> Managed by Memory Agent. Do not edit manually without updating tags.
>
> All telemetry-tracked content files — `topics/`, `patterns/`, `context/`, and `clients/` — carry
> YAML frontmatter with: `id`, `type`, `tags`, `confidence` (low|medium|high), `last_validated`,
> `supersedes`, `scope` (generic|client:\<id\>). Counters (`source_sessions`, `load_count`,
> `useful_count`, `open_contradictions`, `distinct_projects_used`) live in `.telemetry.json`, joined
> by `id` — **every such `id`-bearing content file must have a telemetry row** (curate reconciles each
> run). Memory Agent maintains these counters. Graduation gate (topics→patterns only):
> `confidence: high` + `distinct_projects_used >= 3` → eligible for `patterns/`.
> (The framework's own **ADRs** live outside this library in `docs/decisions/` — status-tracked
> design records about the framework itself, not telemetry-tracked knowledge.)

> **This root index is injected into every wired session** (SessionStart hook), so it is kept lean —
> it is the **map of maps**. Indexes form a recursive **tree**: when any node grows past the shard
> threshold (> 15 topics) its topics move into a deeper node under `indexes/` (e.g.
> `indexes/index_<domain>.md`, which may itself split into `indexes/index_<domain>_<subdomain>.md`),
> leaving a **shard-pointer row** behind (see `## Topic shards`). Only root is injected; deeper nodes
> load on-demand as you descend. Index nodes are navigation — they don't count toward the max-5
> content budget (keep the descent ≤2–3 levels). Health & sharding rules: `agents/memory.md`.

## agents

### Orchestration
| File | Role | When to invoke |
|---|---|---|
| lead.md | Orchestration | Single entry point for any complex task |

### Domain agents (read by Lead to extract Memory hints + domain checklist)
| File | Domain | Triggers |
|---|---|---|
| gcp.md | GCP infra | IAM, Cloud SQL, VPC, Storage, Secret Manager, Scheduler, labels |
| kubernetes.md | Kubernetes / GKE | GKE, Helm, operators, manifests, Gateway API, ESO, WIF for pods |
| serverless.md | Serverless | Cloud Run, Cloud Functions, Eventarc, Pub/Sub triggers |
| data.md | Data platform | BigQuery, Dataflow, NiFi, NiFiKop, data pipelines |
| cicd.md | CI/CD | GitHub Actions, Atlantis, Terraform pipelines, WIF for CI |

### Execution agents
| File | Role | When to invoke |
|---|---|---|
| implementer.md | IaC/code generation | Terraform, YAML, scripts generation |
| quality.md | General review | Technical review of code and documentation |
| security-review.md | Security review | Security-focused review: IAM, network, CIS benchmark |
| docs.md | Documentation | ADRs, HLDs, runbooks, workshops, proposals |
| memory.md | Knowledge library management | Pattern query and registration |
| cloud-research.md | External research | Validate current practices from official sources |
| federation.md | External memory listener | Consult external/company KB (read-only) + gated ingest into our library |

## hooks & skills

> Enforcement + capture layer. Hooks live in `hooks/`, skills in `skills/`.
> The guardrail runs under three adapters (Claude Code, Codex, Gemini CLI); capture is Claude Code.
> See `hooks/README.md`.

| Component | Event / trigger | Role |
|---|---|---|
| hooks/guardrails.py | Claude Code PreToolUse · Codex PreToolUse · Gemini CLI BeforeTool | Runtime guardrail (ADR-006 tiers), one engine three adapters: forced re-confirmation of high-impact actions even when instructed; go-ahead confirmation on commit/push/PR + AI-signature check; capture plumbing exempt; ADR-005 tiered failure |
| hooks/install_adapter_hooks.py | helper (`bootstrap.sh --install-tools`) | Wires the guardrail into Codex (`~/.codex/config.toml`) + Gemini CLI (`~/.gemini/settings.json`) |
| hooks/health_common.sh | sourced helper | Per-machine framework-health logging; aggregated into the `/metrics` fleet view |
| hooks/session_start.sh | SessionStart | Assert framework defaults (knowledge on, orchestration proportional) + inject this index (the map) + nag on pending captures |
| hooks/capture_session.py | Stop, SessionEnd | Enforced raw transcript capture of substantial sessions to `.bailiwick-outputs/raw/` |
| hooks/capture_backup.sh | Stop, SessionEnd (push); `/curate` (pull/purge) | Optional encrypted off-machine backup of the dirty zone (gpg ciphertext → dedicated private repo); see `.bailiwick-sync.json` `capture_backup` |
| hooks/sync_knowledge.sh | `/curate` or manual | Outbound knowledge sync: central pushes `main`; satellite branch + PR |
| hooks/install_hooks.py | helper (`bootstrap.sh --install-tools`) | Idempotent safe-merge of the hooks block into `~/.claude/settings.json` (substitutes the real Bailiwick path; migrates stale installs) |
| hooks/install_global_layer.sh | helper (`bootstrap.sh --install-tools`) | Installs the global Codex/Gemini operator layers (managed blocks in `~/.codex/AGENTS.md`, `~/.gemini/GEMINI.md`) |
| hooks/settings.template.json | — | Hooks block to merge into `~/.claude/settings.json` (installed once, global) |
| skills/curate | `/curate` | Human-gated distillation of captures into the library (runs Memory Collect) |
| skills/enrich | `/enrich` | Draft project-context-filled instruction files for all four tools after bootstrapping (drafts only) |
| skills/metrics | `/metrics` | Read-only knowledge-health report (retrieval, impact funnel, reconciliation) + per-source framework-health fleet view; no gate |
| skills/investigate | `/investigate` | Research a reference or an open need and distil into gated KB candidates with provenance |
| skills/purge | `/purge` | Human-gated de-identification: remove a client/project (`<id>`/`{org}`/name) from the library, captures, telemetry, registry — keep the reusable knowledge (re-attribute/genericize), delete only what's clearly client-specific (ADR-008) |

## patterns

| File | Tags | When to load |
|---|---|---|
| terraform-module-structure.md | terraform, module, structure, iac | Generating or reviewing a Terraform module |
| caf-naming-taxonomy.md | naming, conventions, caf, taxonomy, finops | Naming ANY resource (folder, project, SA, infra) — `{org}-{type}-{workload}-{env}-{region}-{instance}` |
| gcp-naming-conventions.md | gcp, naming, superseded | ⤳ superseded by caf-naming-taxonomy.md |
| gcp-iam-conventions.md | gcp, iam, security, least-privilege | IAM bindings, service accounts, roles |
| gcp-labels-required.md | gcp, labels, tags, finops | Creating any GCP resource with labels |
| gcp-backend-gcs-pattern.md | terraform, state, backend, gcs | Configuring Terraform backend |
| gcp-gke-workload-identity.md | gcp, gke, kubernetes, identity, workload-identity | GKE resources or workload identity |
| terraform-variable-conventions.md | terraform, variables, inputs, outputs | Defining variables and outputs |
| code-review-rubric.md | review, terraform, gcp, blast-radius, security | Any code or PR review |

## topics

> Maintained by Memory Agent. Created incrementally from project work.
> Load topics/ before patterns/ — they are pre-digested and context-specific.

| File | Tags | When to load |
|---|---|---|
| claude-mcp-wiring.md | claude-code, codex, mcp, tooling, bootstrap, capture, hooks, skills | Bootstrapping/updating mixed-tool repos so Claude Code/Codex MCP, skills, and capture hooks are wired correctly |
| llm-context-token-optimization.md | llm, context, tokens, optimization, agents, tooling, reference | Reducing token spend / extending session length in agent setups — framework tuning, client agent deployments, MCP schema overhead (~55k-token trap), or evaluating minimal-codegen rulesets |
| agent-cli-hook-contracts.md | claude-code, codex, gemini, hooks, guardrails, enforcement, tooling | Wiring pre-execution guardrail/policy hooks across Claude Code / Codex / Gemini CLI — decision contracts, fail-open gotchas, no-ask-on-Codex, trust (first-fire CLI prompt, not VS Code), quoted-arg false positives |
| powershell-utf8-bom-parsing.md | powershell, windows, bootstrap, cross-platform, scripting, encoding, pitfall | Why a BOM-less UTF-8 `.ps1` fails to parse on Windows PowerShell 5.1 (non-ASCII → ANSI misread) while pwsh 7 is fine — add a UTF-8 BOM |

> The seed library is small (4 topics), well under the shard threshold (15). As topics accumulate,
> a domain that grows past the threshold moves into `indexes/index_<domain>.md`, leaving a
> shard-pointer under `## Topic shards` (memory.md → Index Health & Sharding).

## Topic shards

> Top-level domain sub-indexes under `indexes/` (each may itself be a tree). A row appears here when a
> domain exceeds the shard threshold and its topics move out of the section above. Descend on-demand
> for tasks in that domain; index nodes don't count toward the max-5 content budget.

_None yet — the seed library is small enough to live entirely in this root index. When a domain
grows past the shard threshold, its sub-index appears here (see `indexes/README.md`)._

## templates

| File | Tags | When to load |
|---|---|---|
| adr-template.md | adr, decision, architecture | Generating an ADR |
| hld-template.md | hld, architecture, design | Generating an HLD |
| lld-template.md | lld, implementation, design | Generating an LLD |
| runbook-template.md | runbook, ops, operations | Generating a runbook |
| module-readme-template.md | terraform, module, readme, documentation | Documenting a Terraform module |
| workshop-structure-template.md | workshop, client, agenda | Workshop structure |
| workshop-proposal-template.md | workshop, client, proposal, infrastructure | Infrastructure proposal for client |
| discovery-questions-infra.md | workshop, client, discovery, questions | Preparing a discovery session |
| project-claude-md-template.md | claude-md, project, setup, reference | Bootstrap seeds this as the hidden `CLAUDE.local.md` complement (Claude Code) — project context + framework pointer |
| project-agents-md-template.md | agents-md, codex, copilot, project, setup, cross-tool | Codex complement template; used with the global `~/.codex/AGENTS.md` + `.bailiwick.local.md` so repo `AGENTS.md` stays authoritative |
| copilot-bailiwick-instructions-template.md | copilot, instructions, applyto, complement, setup | Bootstrap seeds this as the hidden `.github/instructions/bailiwick.instructions.md` complement (Copilot, `applyTo:"**"`) |
| agnostic-standards-baseline.md | baseline, standards, best-practices, agnostic, shared, setup | Bootstrap `--with-standards` seeds this as TRACKED `CLAUDE.md`/`AGENTS.md`/`copilot-instructions.md` — self-contained generic best practices, no framework/org refs |
| agent-output-template.md | session, output, memory | Writing agent session output files |
| topic-file-template.md | topic, memory, knowledge | Creating a new topic file |
| domain-index-template.md | index, shard, domain, memory | Creating a domain sub-index when sharding a large domain |

## clients

> Client-scoped knowledge lives under `clients/<id>/` with `scope: client:<id>` (see
> `context/org-shorthands.md`). **None ships in the public release** — this is where your own
> client-specific files would accumulate, kept out of anything shared.
## context

| File | Tags | When to load |
|---|---|---|
| engineering-defaults.md | best-practices, defaults, terraform, cloud, security, code-quality, reuse, intelligence | Always-on baseline for any task — reuse-first working intelligence + cloud/Terraform/quality/security defaults (each tool's complement references it) |
| environments.md | environments, terraform, workspaces | Configuring environments or backends |
| team-conventions.md | conventions, team, patterns, commits, git | Any task involving pattern or convention decisions |
| org-shorthands.md | org, client, shorthand, scope, naming, registry | Resolving an `{org}` token, a `clients/<id>/` folder, or a `scope: client:<id>` value |

## Framework decisions (ADRs) — outside this library

> The framework's own design-decision records live in [`docs/decisions/`](../docs/decisions/)
> (adr-001 … adr-008), **not** in this knowledge library — they record what was chosen, rejected, and
> why about the *framework itself* (guardrail tiers, shadow mode, capture/backup, telemetry model).
> Status-tracked, not telemetry-tracked. Consult them when a task touches the framework's design.
