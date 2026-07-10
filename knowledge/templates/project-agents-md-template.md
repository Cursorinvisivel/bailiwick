# .bailiwick.local.md — private operator marker — [Project / Repo Name]

> **Private, untracked, never shared.** This file is the framework's per-repository Codex marker. It
> is read **only** because your global `~/.codex/AGENTS.md` (installed by `bootstrap.sh --install-tools`)
> instructs Codex to load it when present. It is deliberately **not** a repo-root instruction file:
> that would suppress the team's `AGENTS.md` (Codex loads one instruction file per directory).
> This marker shadows nothing — **the repository's own `AGENTS.md` remains authoritative** for project
> constraints; this file only adds your private operator layer on top. The Claude Code twin is
> `CLAUDE.local.md`; the framework rules are identical across tools.

## Framework
Agents and the knowledge library live in the Bailiwick repo (`$BAILIWICK`).
Absolute path: /path/to/bailiwick

These tools read files by path, not via MCP. When a task needs an agent role or a
knowledge file, open it directly from the absolute path above
(e.g. `$BAILIWICK/agents/implementer.md`). Nothing from the framework is
copied into this repo — it is referenced in place.

## Agents and Delegation

Agents live in `$BAILIWICK/agents/`. Open the specific file and adopt it
as instructions for the task (delegation is prompt-driven; agents share context).

The framework is the default — no trigger phrase required. Orchestration is proportional: route
substantial or multi-step work through the Lead agent; handle trivial edits and direct questions
inline with knowledge loaded.

| Task | Agents to invoke |
|---|---|
| Terraform module / IaC | Memory → Implementer → Quality |
| ADR / HLD / LLD | Memory → Docs → Quality |
| Security review | Memory → Security Review |
| Code review | Memory → Quality |
| Module documentation | Memory → Docs |
| Workshop / client proposal | Memory → Docs → Quality |
| Operational runbook | Memory → Docs |
| New pattern to register | Memory (register — requires human approval) |
| External research / validation | Cloud Research |

Knowledge index: `$BAILIWICK/knowledge/INDEX.md`
Load patterns on-demand via INDEX.md — start with `topics/`, then `patterns/` (descend domain
sub-indexes under `indexes/` if a domain is sharded), maximum 5 content files per task (index
navigation doesn't count). Do not re-read files already in context this session.

Engineering defaults (always-on): before writing, **scan the repo + KB for reusable code/modules to
extend rather than recreate**; apply least privilege, CAF naming + labels, pinned versions, no
secrets, plan-before-apply, drafts for review. Full baseline:
`$BAILIWICK/knowledge/context/engineering-defaults.md`

## Project Context

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
[List modules with source URL and ref, or "none"]

### CI/CD
[Describe pipeline — trigger, validation steps, deploy]

## CI/CD Footprint

> List every pipeline file in the repo and declare whether it is authoritative for the
> Terraform lifecycle. This prevents tools from misreading legacy files as current intent.

| File | Purpose | Authoritative for Terraform? |
|---|---|---|
| `[pipeline file]` | [e.g. security scans — secret/IaC/SCA scanners] | No (scans only) |
| `[pipeline file]` | [e.g. Legacy Helm delivery] | **No** — not Terraform lifecycle |
| `[pipeline file]` | [e.g. Atlantis plan/apply trigger] | Yes |

Do not run deploy or delivery pipeline steps autonomously.

## Practical Change Guide

> Per-repo map of the most common change types: the file(s) and the data-driven construct
> (`for_each`/map/`locals`/factory module/root-module loop) to **extend** — so you add an entry, not a
> new standalone resource. Loaded each session so agents don't re-scan the repo for routine changes.
> Name the exact file(s) and flag cross-file dependencies. **Snapshot as of [commit / date] — an index
> to verify, not gospel: confirm the named construct still exists before relying on it; re-run `/enrich`
> if the layout drifted.**

### Add / modify [Domain A]
1. Edit `[file]` — update `[variable/local/map]`
2. [Cross-file dependency to preserve]
3. Validate with `terraform plan` before apply

### Add / modify [Domain B]
1. Edit `[file]`
2. [Constraint or blast-radius note]

### Change IAM bindings
1. Edit `iam.tf` — add a key to the relevant `local.[iam_map]` (do **not** add a standalone `google_project_iam_member`)
2. Confirm the `for_each` key-uniqueness pattern (commonly `role||member`)
3. Flag any privilege expansion to the user

### Change networking / firewall
1. [Steps]
2. Flag blast radius: [what else may be affected]

## Capture & Curation
- **Capture.** Under **Claude Code**, Stop/SessionEnd hooks auto-write raw transcripts of
  substantial sessions to `.bailiwick-outputs/raw/`. **Codex, Gemini (VS Code agent), and Copilot do not run
  those hooks** — under those tools, when you finish a substantive session write a short session
  output to `.bailiwick-outputs/` manually (per the agent-output template): what changed, decisions,
  pitfalls, follow-ups. Do **not** try to run the Claude Code capture hook script by hand — it expects
  a harness payload. Memory Agent reads these during Collect.
- **Curation (human-gated).** Run `/curate` (Claude Code) — or the Memory agent Collect flow by
  hand (Gemini/Codex/Copilot) — to distill captures into the knowledge library. Promotion to
  `$BAILIWICK/knowledge/` always requires explicit approval.

`.bailiwick-outputs/` (and this file) are hidden via the repo's `.git/info/exclude` — written by
`bootstrap.sh`. Never add framework entries to the tracked `.gitignore`: the entry alone would
expose the framework to anyone who clones. Raw captures are unsanitised — never commit them.

## Non-Negotiable Rules
- Never terraform apply/destroy without explicit approval
- Never git commit/push without approval
- Never modify `$BAILIWICK/knowledge/` without a human gate (via `/curate`)
- `.bailiwick-outputs/raw/` is enforced staging only — never committed, never promoted unsanitised

---

## Optional: Copilot Agent Registry

> Add this section when the repo has custom `.github/agents/` agent files for Copilot
> workspace agents. Remove if not applicable.

### [Agent Name]
- **File**: [`.github/agents/agent-name.md`]
- **Purpose**: [What this agent does]
- **Tools available**: [e.g. `read`, `edit`, `search`] — no terminal access
- **Auto-invoked when**: [Trigger phrases or file types]

### [Agent Name]
- **File**: [`.github/agents/agent-name.md`]
- **Purpose**: [What this agent does]
- **Tools available**: [e.g. `web`] — no code generation
- **Auto-invoked when**: [Trigger phrases]

**Tool restrictions are intentional.** Agents that generate code must not have web access
(prevents hallucinated APIs). Agents that do research must not have terminal access
(prevents accidental `terraform apply`).
