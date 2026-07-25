# CLAUDE.md — Bailiwick

## Purpose
Central repository of AI-agent tools, roles, and knowledge patterns for cloud and infrastructure-as-code work.
Single source of truth — never copy files to other repositories.
Other repositories reference this via $BAILIWICK.

## Orchestrator & Stages
Location: $BAILIWICK/agents/

The **Lead** is the orchestrator; the **Quality Workflow** is the ordered review pass it drives.
Each stage runs as a **native Claude Code subagent** (the Agent/Task mechanism) — concurrently
where the work is independent — or inline for small work. See ADR-010.

| Part | File | Role |
|---|---|---|
| Lead (orchestrator) | lead.md | Single entry point; dispatches stages, integrates results |
| Implement stage | implementer.md | Code and IaC generation |
| Quality stage | quality.md | Technical review |
| Security Review stage | security-review.md | Security review: IAM, network, CIS benchmark |
| Docs stage | docs.md | Documentation, templates, workshops |
| Memory stage | memory.md | Knowledge library management |
| Cloud Research stage | cloud-research.md | External research from official sources |
| Federation stage | federation.md | External/company memory: read-only consult + gated ingest |

Orchestration is proportional: route substantial or multi-step work through the Lead
(it dispatches stages by task type); handle trivial edits and direct questions inline with knowledge
loaded. No prefix is required — stating a substantial task *is* the invocation. To force the full
Quality Workflow when routing under-evaluates a task, say so ("run the full Quality Workflow" or
name the stages).

**Execution model:** the Lead is the native main session; it dispatches real native Claude Code
subagents (not role-play in one context). Independent stages run **concurrently**; dependent stages
("Memory → Implement → Quality") run in order. Because each subagent starts as a fresh context, every
stage loads the knowledge it needs itself. There are also 5 non-executing domain-context files (gcp,
kubernetes, serverless, data, cicd) the Lead reads for retrieval hints + checklists. Stage
definitions are the frontmattered `agents/*.md` files, installed globally as
`~/.claude/agents/bailiwick-*.md` symlinks by `bootstrap.sh --install-tools` (never seeded
per-repo); the same install generates adapters for Gemini/Codex/Copilot user-scope agent dirs
(ADR-010 Amendment 1 — trigger model per tool in FRAMEWORK.md §10). A stage's final report is its
only channel back — outputs and knowledge signals go in it. See lead.md, ADR-010, and
FRAMEWORK.md §3.

## Knowledge Library
Location: $BAILIWICK/knowledge/
Index: $BAILIWICK/knowledge/INDEX.md

Rules:
- Memory stage loads files on-demand via INDEX.md
- Indexes form a recursive tree: root INDEX.md is injected each session; large domains shard into `indexes/index_<domain>.md` (and deeper). Descend on-demand for the relevant domain.
- Never load the entire library in a single invocation
- Maximum 5 *content* files (topics/patterns) per task unless justified — index navigation nodes don't count, but keep the descent shallow (≤2–3 levels)
- **Engineering defaults always apply** — `context/engineering-defaults.md` (reuse-first: scan repo + KB for code to extend before creating; least privilege; CAF naming + labels; pinned versions; no secrets; plan-before-apply; drafts for review)
- Updates to the knowledge library require explicit human approval (via `/curate`)

## Capture & Curation
Enforced by Claude Code hooks ($BAILIWICK/hooks/):
- **Capture (automatic).** Stop/SessionEnd hooks write raw transcripts of substantial sessions
  to `<project>/.bailiwick-outputs/raw/`. The SessionStart hook asserts the framework defaults, injects the
  knowledge index (the map), and nags when captures are pending. The harness runs these — capture
  cannot be forgotten.
- **Curation (human-gated).** The `/curate` skill ($BAILIWICK/skills/curate/)
  distills captures into the knowledge library; promotion always requires approval.
- **Durability (optional).** With `capture_backup` enabled in `.bailiwick-sync.json`, Stop/SessionEnd
  hooks gpg-encrypt captures and push **ciphertext** to a dedicated private repo so un-curated
  dirty data survives disk loss; `/curate` decrypts, promotes, and purges. See hooks/README.md.

## Skills (global, in `~/.claude/skills/`)
- **`/curate`** — human-gated distillation of captures into the knowledge library (above).
- **`/enrich`** ($BAILIWICK/skills/enrich/) — scan a bootstrapped repo and draft
  project-context-filled instruction files for all four tools, both the committed team baselines
  (framework-agnostic) and the hidden complements (framework-aware). Drafts only; never commits.
  Run it after bootstrapping an existing project.
- **`/learn`** ($BAILIWICK/skills/learn/) — onboard an existing repo's knowledge at bootstrap
  time: scan the project (decisions, IaC patterns, conventions, pitfalls) and distill the findings
  into a pre-digested capture staged exactly where `/curate` gathers (seeded: `.bailiwick-outputs/`;
  shadow: `~/.bailiwick/captures/<repo-key>/`) — promotion rides the standard capture→curate
  human gate; writes no knowledge itself. Complement to `/enrich` (instruction files vs knowledge
  candidates). Codex wrapper: `$bailiwick-learn`.
- **`/metrics`** ($BAILIWICK/skills/metrics/) — read-only health report on the
  knowledge library (retrieval, load→applied→used funnel, cold/stale candidates, telemetry↔file
  reconciliation). No gate needed; writes nothing.
- **`/investigate`** ($BAILIWICK/skills/investigate/) — research a reference
  (URL/repo/article) or an open need ("find the best patterns for X") and distill the findings
  into KB candidate(s) with provenance — including "evaluated, not adopted" verdicts worth
  remembering. Same human gate as `/curate`; ad-hoc counterpart to federation ingest. Codex
  wrapper: `$bailiwick-investigate`.
- **`/purge`** ($BAILIWICK/skills/purge/) — human-gated, destructive de-identification: remove every
  reference to a client/project (`<id>`, `{org}` token, org name) from the library, captures,
  telemetry, and registry, **keeping the reusable knowledge** (re-attributed via `--to <id>` or
  genericized) and deleting only what is clearly client/project-specific. Scan → plan → approve →
  execute; captures (enumerated by **origin**, across all machines) purged only after the sanitized
  knowledge is committed. **De-identified by default, not "fully erased"** — ciphertext persists in the
  backup repo's git history until rewritten/key-destroyed; `--history` **outputs** the rewrite commands
  for **both** the knowledge and backup repos, never executes them. `--attest` (output-only) drafts a
  safety-net attestation + non-reversible internal stub — an engineering record, never a legal assurance
  (ADR-008). Pairs with `/curate --sanitized` (de-identified mode — stores no identifiers). Codex
  wrapper: `$bailiwick-purge`.

See $BAILIWICK/hooks/README.md.

## MCP Configured
- filesystem: serves $BAILIWICK and the active project's workspaceFolder
- fetch: GCP documentation, Terraform registry, provider docs
- github: access to repos, PRs, issues
- terraform: HashiCorp provider docs and registry

### Desktop reference (optional, read-only)
Claude Desktop and ChatGPT Desktop have no hook system, so they sit **outside** the four adapters
above and outside capture/curation/guardrails entirely. `bootstrap.sh --install-tools --with-desktop`
optionally wires a single narrowly-scoped `bailiwick-knowledge` MCP filesystem server — rooted at
`knowledge/` only, never the rest of the framework — into each app's own MCP config. `bootstrap.sh`
(and `bootstrap.ps1`) auto-detects the macOS/Windows/WSL config paths and delegates the idempotent,
non-destructive merge to `hooks/install_desktop_mcp.py` (scoped to the single `bailiwick-knowledge`
server). This lets
either app **consult** the knowledge library for reference outside a coding session; it can never
write back into it. Pair it with `knowledge/templates/desktop-reference-instructions.md`, pasted into
the app's Project/custom instructions, since the retrieval discipline below isn't auto-injected there.

## Non-Negotiable Rules
These are **runtime-enforced** by the same `guardrails.py` engine under **three adapters** —
Claude Code (PreToolUse, forced confirmations), **Codex CLI** (PreToolUse, deny + break-glass
allow-once; needs a one-time hook trust — Codex prompts on first fire in the `codex` CLI, not VS Code), and **Gemini CLI** (BeforeTool, `ask` confirmations) —
installed globally by `bootstrap.sh --install-tools`, self-gating to wired repos. Nothing dangerous
runs silently or on agent initiative. **Copilot** has no hook equivalent (policy only); the Gemini
**VS Code agent's** hook support is unverified (policy there — keep YOLO mode off). **Claude Desktop /
ChatGPT Desktop** are outside all three enforcement layers (no hook system at all) — the optional
`--with-desktop` wiring above is deliberately read-only and scoped to `knowledge/` only for this reason.
- **High-impact actions re-confirm even when instructed** — terraform/terragrunt apply & destroy;
  kubectl/helm mutations (apply/delete/patch/scale/drain/rollout, install/upgrade/uninstall);
  gcloud/gsutil/az/aws mutating verbs (delete/destroy/update/patch/rm); recursive/forced `rm`;
  `git merge`; `gh repo delete` — the guardrail forces an in-the-moment re-confirmation that this
  specific action is really the intent, never agent initiative
- **git commit / push / PR opening need a clear user go-ahead** — never agent initiative; the
  guardrail forces a confirmation. An AI attribution signature in a commit/PR message
  (Co-Authored-By, "Generated with … Claude", 🤖) triggers its own confirmation — strip it unless
  the user explicitly wants it
- **Exempt:** dirty-zone capture plumbing (`capture_backup.sh`, capture-mirror) is never blocked —
  capture prevents data loss. Validation-only commands (terraform plan/validate/fmt, kubectl
  get/--dry-run, read-only cloud CLI) run untouched
- Never modify /knowledge/ without explicit human gate (via `/curate`)
- `.bailiwick-outputs/raw/` is enforced capture staging — never committed, never promoted unsanitised
- All outputs are drafts for human review

## Usage in Other Repositories
DO NOT copy files to target repos. **Bootstrap them** instead:
`$BAILIWICK/scripts/bootstrap.sh [--seeded|--init] [--all-tools] <repo>` (Windows: `bootstrap.ps1`).
**Shadow mode is the default** (FRAMEWORK.md §7.1): zero files in the repo — activation via the
`~/.bailiwick/allowlist` + user-scope MCP/instruction config; captures stage centrally under
`~/.bailiwick/captures/`. `--with-standards` is the intentional team path (tracked,
framework-agnostic baselines) and works in both modes. With **`--seeded`** (implied by
`--visible`/`--init`) the repo instead gets only HIDDEN framework files (the team's own
CLAUDE.md/AGENTS.md/copilot-instructions.md are NEVER touched):
1. Framework guidance as **complement files** the tool loads alongside the team's (four adapters of
   differing completeness — see FRAMEWORK.md §10):
   `CLAUDE.local.md` (Claude Code, merges after CLAUDE.md) + optional `.bailiwick.local.md` (Codex
   private marker, read via the global `~/.codex/AGENTS.md` layer — never shadows the team `AGENTS.md`) +
   `.github/instructions/bailiwick.instructions.md` (Copilot, `applyTo:"**"`, **local VS Code only** —
   the hosted Copilot cloud agent cannot see untracked files) + the shared `.bailiwick.local.md`
   marker (Gemini, read via the global `~/.gemini/GEMINI.md` layer; never shadows a team `GEMINI.md`)
2. `.mcp.json` (Claude Code), `.vscode/mcp.json` (VS Code), `.codex/config.toml` (Codex MCP, with
   `--with-agents`), and `.gemini/settings.json` (Gemini MCP, with `--with-gemini`) serving
   workspaceFolder + $BAILIWICK
3. `.bailiwick-outputs/` capture staging
The wiring is **hidden** via the repo's `.git/info/exclude` (never the tracked `.gitignore`), so the
framework is never shared with colleagues/clients — yet each tool still loads its complement
(instruction files are discovered by filesystem, regardless of git tracking). Re-run `bootstrap.sh --update <repo>` after a
framework change to refresh the managed MCP configs without clobbering hand-edited files.
Capture/curation hooks are installed ONCE globally in ~/.claude/settings.json and self-gate to
Bailiwick-wired repos — there is no per-repo hook setup. The `/curate` skill is global too.
See: $BAILIWICK/scripts/bootstrap.sh (and bootstrap.ps1) — scripted, update-safe onboarding
See: $BAILIWICK/docs/getting-started.md and docs/operations.md → Multi-machine sync
See: $BAILIWICK/hooks/settings.template.json (hooks block — install once in ~/.claude/settings.json)

## Multi-Machine Sync
The framework is cloned per machine; `.bailiwick-sync.json` (gitignored) sets each machine's role
(`central` | `satellite`, default satellite). **Inbound:** the SessionStart hook fast-forwards the
Bailiwick clone from `origin/main`. **Outbound:** after an approved `/curate`,
`hooks/sync_knowledge.sh` propagates — central pushes `main`; a satellite pushes a
`sync/<machine>` branch and opens a PR. `.telemetry.json` is **central-owned** (satellites skip it).
Full model: docs/operations.md → Multi-machine sync.
