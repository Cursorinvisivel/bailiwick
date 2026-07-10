# CLAUDE.md — [Project / Repo Name]

## Framework
Agents and knowledge library live in $BAILIWICK.
Absolute path: /path/to/bailiwick
The MCP filesystem serves $BAILIWICK — files are directly accessible.

## The framework is the default

This framework is assumed on for every task — no trigger phrase required.

- **Knowledge + conventions are always in play.** Consult $BAILIWICK/knowledge/INDEX.md
  and load relevant topics/patterns on-demand (max 5 content files; descend domain sub-indexes under
  `indexes/` if present — index navigation doesn't count); reuse what is already in context.
- **Orchestration is proportional to the work**, not mandatory:
  - *Substantial or multi-step work* (IaC generation, design docs, reviews, anything cross-cutting)
    → route through the Lead Agent. The Lead reads the relevant domain agent(s), queries Memory for
    context, delegates to execution agents, and presents results for review.
  - *Trivial edits and direct questions* → handle inline with knowledge loaded. Do not spin up the
    full agent tree for a one-line fix or a lookup.

You no longer need to prefix tasks with `Lead:`. When you do want to force orchestration explicitly,
`Lead: [task]` still works.

## Agent Overview

All agent files are in $BAILIWICK/agents/.

**Domain agents** (Lead reads these for Memory hints + domain checklist):

| Agent | Domain |
|---|---|
| gcp.md | GCP infra: IAM, Cloud SQL, VPC, Storage, Secret Manager, Scheduler |
| kubernetes.md | GKE, Helm, operators, Gateway API, ESO, Workload Identity |
| serverless.md | Cloud Run, Cloud Functions, Eventarc |
| data.md | BigQuery, Dataflow, NiFi / NiFiKop |
| cicd.md | GitHub Actions, Atlantis, WIF for CI |

**Execution agents** (invoked by Lead after domain context is loaded):

| Agent | Role |
|---|---|
| implementer.md | Terraform, YAML, script generation |
| quality.md | Technical review |
| security-review.md | Security review with CIS mapping |
| docs.md | ADRs, HLDs, runbooks, workshops |
| memory.md | Knowledge library query and registration |
| cloud-research.md | Research from official sources with citation |
| federation.md | External/company KB consult + gated ingest (dormant until a source is enabled) |

Knowledge index: $BAILIWICK/knowledge/INDEX.md
Load patterns on-demand via INDEX.md (descend domain sub-indexes under `indexes/` if a domain is sharded) — maximum 5 content files per task; index navigation doesn't count.
Check context before loading: do not re-read files already in context this session.

Engineering defaults (always-on): before writing, **scan the repo + KB for reusable code/modules to
extend rather than recreate**; apply least privilege, CAF naming + labels, pinned versions, no
secrets, plan-before-apply, drafts for review. Full baseline:
$BAILIWICK/knowledge/context/engineering-defaults.md

## Project Context

### Identity
project_id: [unique-kebab-case-id]
# Stable identifier for this project/venture across all its repos.
# Used by Memory Agent to tag Retrieval Feedback `used` entries (@project_id).
# Feeds distinct_projects_used in .telemetry.json — determines graduation eligibility.
# If client-scoped, align with scope: client:<id> — use the same id here.
# Examples: platform-hub, trading-engine, client-acme, home-lab

### Purpose
[Brief description of what this repo contains and does]

### Stack
- IaC: Terraform >= 1.5 / provider google ~> 5.0
- GCP environment: [project IDs per environment]
- Components: [e.g. GKE, Cloud Run, Cloud SQL]

### Repo Structure
```
[relevant directory structure]
```

### Terraform Backend
Bucket: [state bucket name]
Prefix pattern: [environment]/[component]

### Environments
| Abbreviation | GCP Project ID | Purpose |
|---|---|---|
| dev | [project-id] | ... |
| stg | [project-id] | ... |
| prd | [project-id] | ... |

### Additional labels (beyond standard)
[List project-specific labels, or "none beyond standard"]

### Internal modules used
[List modules with source URL, or "none"]

### CI/CD
[Describe pipeline — trigger, validation steps, deploy]

## Practical Change Guide

> Per-repo map of the most common change types: the file(s) and the data-driven construct
> (`for_each`/map/`locals`/factory module/root-module loop) to **extend** — so you add an entry, not a
> new standalone resource. Loaded each session so agents don't re-scan the repo for routine changes.
> **Snapshot as of [commit / date] — an index to verify, not gospel: confirm the named construct still
> exists (one grep) before relying on it; if it moved, fix here and re-run `/enrich`.**

### Change IAM bindings
1. Edit `[iam.tf]` — add a key to `local.[iam_map]` (do **not** add a standalone `google_project_iam_member`)
2. Confirm the `for_each` key-uniqueness pattern (commonly `role||member`)
3. Flag any privilege expansion to the user

### Add / modify [database / Cloud SQL]
1. Edit `[sql.tf]` — add an entry to `[local.cloud_sql_instances / the instances map]`
2. [Cross-file dependency: private IP / networking / users / backups]
3. Validate with `terraform plan` before apply

### Add / modify [Domain]
1. Edit `[file]` — update `[variable / local / map]`
2. [Constraint or blast-radius note]

### Change networking / firewall
1. [Steps]
2. Flag blast radius: [what else may be affected]

## Capture & Curation
Two layers, by design:
- **Enforced capture (hooks, no human needed).** SessionEnd/Stop hooks write a raw transcript of
  any substantive session to `.bailiwick-outputs/raw/<session_id>.jsonl`. Capture cannot be forgotten — the
  harness runs it, not the model. (`.bailiwick-outputs/*.md` is only the manual channel for
  Codex/Gemini/Copilot sessions, which have no hooks.)
- **Gated curation (human-approved).** Run `/curate` (the SessionStart hook nags when captures are
  pending) to distill captures into the knowledge library. Promotion to
  $BAILIWICK/knowledge/ always requires explicit approval.

The hooks are installed once globally in `~/.claude/settings.json` and self-gate to Bailiwick
repos — no per-repo install. This complement file referencing `$BAILIWICK` is what the guard keys on.

`.bailiwick-outputs/` (and this file) are hidden via the repo's `.git/info/exclude` — written by
`bootstrap.sh`. Never add framework entries to the tracked `.gitignore`: the entry alone would
expose the framework to anyone who clones. Raw captures are unsanitised — never commit them.

## Non-Negotiable Rules
- Never terraform apply/destroy without explicit approval
- Never git commit/push without approval
- Never modify $BAILIWICK/knowledge/ without human gate (via `/curate`)
- `.bailiwick-outputs/raw/` is enforced staging only — exempt from the gate, but never committed and never promoted unsanitised
