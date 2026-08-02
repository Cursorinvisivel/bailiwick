# Bailiwick — Framework Reference

> The complete, self-contained design reference for **Bailiwick**: what it is, how it works, its
> goals, and its honest strengths and limitations. One document, readable cold. This is the deep
> reference — for the overview start with the [README](../README.md), to install and wire a repo see
> [getting-started](getting-started.md), and for day-2 operations see [operations](operations.md).
> §14 (*Strengths & limitations*) is the honest "what's good and what's not" summary.
>
> Canonical path: `$BAILIWICK` · Single source of truth — target repos reference it, never copy
> from it. Single-user by design (one owner, one primary machine); §13 states the scope and non-goals
> ([ROADMAP.md](../ROADMAP.md) covers what a team version would require). Other docs and the code
> cross-reference this file's section numbers (e.g. §7.1).

---

## 1. Essence

Bailiwick is a **prompt-and-convention framework** that gives an AI coding agent — Claude Code
(most fully), Codex, Gemini, and GitHub Copilot — a persistent, curated **memory**, runtime
**guardrails**, and a **proportional orchestration model**. The machinery is **domain-neutral**:
knowledge files, agent roles, guardrail patterns, and the capture→curate loop assume nothing about
your stack. What ships in the box is a small **seed** library that leans toward cloud and
infrastructure-as-code work — it grew up doing GCP + Terraform — but that is the seed's example
domain, not what the tool *is*. It is plain Markdown + JSON + shell — no runtime service. Three ideas
hold it together:

1. **Knowledge is always on, loaded on-demand.** A curated library of topics/patterns/context is
   indexed by a recursive map (`INDEX.md`) injected every session; the agent loads only the few
   files relevant to the task.
2. **Capture is enforced; promotion is human-gated.** Under **Claude Code**, harness hooks stage raw
   transcripts of substantial sessions *automatically* (Codex/Gemini/Copilot capture is a manual
   step — §10, §14); a human-gated `/curate` step distils them into the library. Nothing enters the
   knowledge base without review.
3. **The framework is the single source of truth, never copied.** By default (**shadow mode**, §7.1)
   target repos carry *no files at all* — activation lives in global/user-scope config and the repo
   is left completely untouched; with `--seeded`, thin hidden pointer files are written into the
   repo instead. Either way the agent reads the framework live over an MCP filesystem root; updates
   propagate without redistribution.

### Design principles
- Simplicity over machinery; Markdown over services.
- Security and least privilege by default; drafts for human review, never auto-applied.
- Repetition implies standardisation (promote the third occurrence).
- Proportional effort — don't spin the full agent tree for a one-line fix.
- Provenance and scope are always explicit (whose knowledge is this, for whom).

---

## 2. Architecture at a glance

```
                        ┌─────────────────────────────────────────────┐
                        │  $BAILIWICK  (single source of truth)      │
                        │                                               │
  SessionStart hook ───▶│  agents/      orchestration + domain + exec   │
  (inject INDEX,        │  knowledge/   topics·patterns·context·clients │
   defaults, ff-pull)   │  hooks/       capture + session-start         │
                        │  skills/      /curate (gated promotion)        │
  Stop/SessionEnd ─────▶│  scripts/     bootstrap (onboarding)          │
  hook (capture raw)    │  prompts/, copilot-instructions/, vscode/      │
                        └───────────────┬───────────────────────────────┘
                                        │  MCP filesystem (read)
                       ┌────────────────┴───────────────┐
   hidden complements   │  target repo (client/project)  │  .bailiwick-outputs/raw/ (local capture)
   CLAUDE.local.md ─────│  .mcp.json · .vscode/mcp.json  │  wiring hidden via .git/info/exclude
   .bailiwick.local.md└───────────────────────────────┘   (team CLAUDE.md/AGENTS.md untouched)
                                        ▲                        ▲
                      inbound ff-pull   │   outbound /curate     │  consult (read-only)
                      ──────────────────┘   sync_knowledge.sh    │  + gated ingest
                       multi-machine sync (central/satellite)    │
                                                        federated external "brains"
                                                        (.bailiwick-sources.json)
```

Six layers:

| Layer | What it is | Files |
|---|---|---|
| **Enforcement** | Hooks the harness runs unconditionally | `hooks/` |
| **Orchestration & roles** | Agent role definitions (Markdown read on-demand) | `agents/` |
| **Memory** | Curated knowledge library + telemetry sidecar | `knowledge/` |
| **Curation** | Human-gated promotion skill | `skills/curate/` plus Codex wrapper `codex-skills/bailiwick-curate/` |
| **Onboarding & sync** | Bootstrap + cross-machine propagation | `scripts/`, `hooks/sync_knowledge.sh` |
| **Federation** | Read-only bridge to external brains | `agents/federation.md`, `.bailiwick-sources.json` |

---

## 3. Orchestration model (Lead + Quality Workflow)

The **Lead** is the **orchestrator**: the native Claude Code main session that plans work and
dispatches **real native subagents** (the Agent/Task mechanism), running them **concurrently where
the work is independent**. The Lead is not itself a subagent — native subagents cannot spawn further
subagents, so orchestration lives in the main session. The ordered review pass it drives is the
**Quality Workflow**; each step is a **stage** that runs as a dispatched subagent or inline for small
work. "Agent" / "subagent" means the native mechanism; the framework's own executable parts are
stages. Stage definitions are the frontmattered `agents/*.md` files, installed globally as
`~/.claude/agents/bailiwick-*.md` symlinks by `bootstrap.sh --install-tools` (never seeded per-repo
— shadow stays zero-footprint). The same install generates **multi-tool stage adapters** from the
canonical files — Gemini `~/.gemini/agents/*.md`, Codex `~/.codex/agents/*.toml`, Copilot
`~/.copilot/agents/*.agent.md` — so all four tools can dispatch the stages natively (ADR-010
Amendment 1; trigger model per tool in §10). A stage's **final report** is its only channel back
and the only part the capture hooks record, so outputs and knowledge signals go in it. See
ADR-010. 13 files in three tiers.

### Tiers
- **Orchestrator (1):** `lead.md` — entry point for substantial/multi-step work; drives the Quality
  Workflow.
- **Domain context (5, non-executing):** `gcp.md`, `kubernetes.md`, `serverless.md`, `data.md`,
  `cicd.md`. The Lead *reads* these to extract (a) Memory tags and (b) a generation/review checklist.
  They never execute; they encode domain best practice and "what to load".
- **Stages (7):** `implementer.md` (code/IaC drafts), `quality.md` (technical review),
  `security-review.md` (security + CIS mapping), `docs.md` (ADR/HLD/runbook/workshop),
  `memory.md` (library query + collect), `cloud-research.md` (authoritative external research),
  `federation.md` (external-brain consult + gated ingest).

### Flow
1. A task arrives. **Proportional routing:** trivial edits / direct questions are answered inline
   with knowledge loaded; substantial work routes through the **Lead**. Stating a substantial task
   *is* the invocation; explicit phrasing forces the full Quality Workflow when routing
   under-evaluates a task.
2. Lead identifies relevant **domain context file(s)**, reads them for Memory tags + checklist.
3. Lead dispatches the **Memory stage (Query)** with those tags — it descends the `INDEX.md` tree
   on-demand, loads ≤5 content files, checks `.bailiwick-outputs/` for prior session outputs.
   Because each subagent starts as a fresh context, the stage loads this knowledge itself. If
   federation is enabled, the **Federation stage** also consults external indexes read-only (≤2
   files, tagged `[external:<id>]`; resolve conflicts by the source-authority precedence, §11 — a
   tidbit never overrides a project decision or an authoritative doc).
4. Lead dispatches the **execution stages** via the Stage Matrix (commonly
   Memory → Implement → Quality; Security Review / Docs / Cloud Research substituted by task type).
   Independent stages run **concurrently**; dependent stages run in order. Each surfaces knowledge
   signals back to the Lead in real time — under Claude Code the capture hooks record the transcript;
   `.bailiwick-outputs/*.md` is the manual channel for Codex/Gemini/Copilot.
5. Lead integrates, presents **drafts for human review**, and always closes with the **Memory stage
   (Collect)**. Stop/SessionEnd hooks capture the raw transcript as a backstop.

### Non-negotiables across agents — policy, guardrail, enforcement
The rules below are stated as **policy** (instructions the agent follows) and, under **Claude Code**,
the dangerous subset is additionally **enforced** at runtime by a PreToolUse guardrail hook
(`guardrails.py`, §5) — a real control, not advice:

| Rule | Claude Code | Codex CLI / Gemini CLI | Copilot |
|---|---|---|---|
| **High-impact actions** — terraform/terragrunt `apply`/`destroy`; kubectl/helm mutations; gcloud/gsutil/az `delete`/`destroy`/`update`/`patch`/`rm`; aws `delete-`/`terminate-`/`remove-`/`update-` verbs + `s3 rm`/`rb`/`mv`; recursive/forced `rm`; `git merge`; `gh repo delete` | **Enforced — forced re-confirmation**, even when user-instructed (ADR-006) | **Enforced** — Gemini: `ask` (same dialog); Codex: **deny** (no ask exists; `BAILIWICK_BREAK_GLASS=1` = allow-once, logged) | Policy |
| `git commit` / `push` / PR opening without a clear user go-ahead; AI attribution signatures in commit/PR messages | **Enforced — forced confirmation** (signatures get their own) | **Enforced** — same mapping as above | Policy |
| Dirty-zone capture plumbing (`capture_backup.sh`, capture-mirror) never blocked; validation-only commands (plan/validate/fmt, `--dry-run`, read-only CLI) pass untouched | Exempt by design | Exempt by design | — |
| Never modify `knowledge/` without the human gate; `.bailiwick-outputs/raw/` never committed; outputs are drafts | Policy (gated by `/curate`) | Policy | Policy |

Terminology used throughout: **policy** = the agent is instructed; **guardrail** = the runtime
detects and forces a confirmation; **enforcement** = the runtime blocks the action regardless of
agent judgement. The **same guardrail engine runs under three adapters** (`guardrails.py claude|codex|gemini`,
installed globally by `bootstrap.sh --install-tools` via `install_adapter_hooks.py`; all self-gate to
wired/shadow repos): Claude Code (PreToolUse, ask tiers), **Codex CLI** (PreToolUse — deny with
actionable reasons, since Codex has no ask; requires a **one-time interactive trust** via the TUI
a first-fire prompt in the `codex` CLI, not VS Code, before hooks run), and **Gemini CLI** (BeforeTool — `ask` tiers, mirroring Claude Code;
`ask` is source-verified but undocumented, so re-verify on CLI upgrades). **Copilot** has no hook
equivalent — policy only; the Gemini Code Assist **VS Code agent's** hook support is unverified, so
treat it as policy there too (see §10). Security Review additionally
runs a **knowledge-promotion leakage check**: client-identifying specifics are abstracted before
promotion, and a client's accepted risk never becomes a generic pattern that would suppress findings
for another client.

---

## 4. Knowledge library

Location: `knowledge/`. Plain Markdown content + a JSON telemetry sidecar.

### Structure
```
knowledge/
  INDEX.md            recursive map, injected every session (the "map of maps")
  .telemetry.json     usage counters, joined to content by `id` (telemetry: commits, ungated)
  topics/    (4)      seed working knowledge (framework meta + generic examples)
  patterns/  (9)      canonical, stable references with full examples
  context/   (4)      org/team context (environments, team-conventions, org-shorthands,
                      engineering-defaults)
  clients/   (0)      per-client subdirs — none ship; where `client:<id>` knowledge would live
  templates/ (15)     ADR/HLD/LLD/runbook/module-readme/workshop/topic/index/agent-output +
                      complement & agnostic-baseline blueprints (CLAUDE.local/bailiwick.local/copilot/standards)
  indexes/ (0)       deeper index-tree nodes (empty until a domain grows past the shard threshold)
  runbooks/ workshops/   present for generated artifacts (empty until produced)
  # (Framework ADRs are NOT here — they live in docs/decisions/ as status-tracked design records.)
```

### Frontmatter schema (every `id`-bearing content file — topics, patterns, context, clients)
```yaml
id:            kebab-case, matches filename
type:          topic | pattern | context
tags:          [list]
confidence:    low | medium | high     # human-curated; agent proposes, human approves
last_validated: YYYY-MM-DD
supersedes:    [ids]                    # forward chain when replacing
scope:         generic | client:<id> | external:<id>
# optional: superseded_by: <id>  (deprecated files);  source: <id> (federation-ingested)
```

The framework's own **ADRs live outside this library** in `docs/decisions/` (they record why the
*framework* is built as it is — design records, not curated domain knowledge). They use a
**status-based** frontmatter — `id`, `type: decision`, `status`
(proposed|accepted|deprecated|superseded), `date`, `authors`, `tags`, `supersedes`/`superseded_by`,
`scope` — and are **outside the telemetry and graduation model** (records, not gradable knowledge).

### The always-on baseline (`context/engineering-defaults.md`)
One context file is **not** load-on-demand: `engineering-defaults.md` (scope `generic`, `confidence:
high`) is the framework's operating baseline that applies to **every** task across all four tools.
Each tool's complement (or its global operator layer) points at it, so the reuse-first intelligence (scan repo + KB for code
to extend before creating), least privilege, CAF naming + required labels, pinned versions, no
secrets, plan-before-apply, and drafts-for-review are in play before any code is written. It cites —
but does not restate — the canonical patterns/agents (load those on-demand). It is the *internal*
twin of the agnostic `--with-standards` baseline (§7): same defaults, but framework-aware and
private, where the baseline template is generic and committed for the team.

### Scopes (provenance, always explicit)
- `generic` — reusable, ours, not client-specific.
- `client:<id>` — work for a specific client (e.g. `client:acme`); client-identifying detail
  lives only under `clients/<id>/`.
- `external:<id>` — **ingested from an external/company brain** via federation (e.g.
  `external:globex`); carries a `source:` field + a `## Provenance` note.
- `<id>` tokens are governed by `context/org-shorthands.md` (one shorthand per org; never invent).

### De-identification (ADR-008)
Two controls keep client/project identity out of the shared library — a forward one and a retroactive
one:
- **De-identified `/curate`** (`--sanitized`, or `.bailiwick-sync.json` `curate.deidentify: true`)
  promotes with **no** identifiers at all: scope forced `generic`, no `clients/<id>/` files, org names
  / `<id>` / `{org}` / project associations stripped at ingest — keeping only the reusable "how it was
  solved". A stronger form of the standard abstraction (which merely routes client detail to `clients/<id>/`).
- **`/purge <from> [--to <target>] [--history] [--attest]`** retroactively removes an existing
  client/project — its `<id>`, `{org}` token, and org name — from the library, captures, telemetry, and
  the registry, on offboarding, de-identification, or a deletion request. It **re-attributes or
  genericizes the reusable knowledge** (`--to`: default `acme`, another `<id>`, or `generic`) and
  **deletes only** what is clearly client/project-specific. Captures are enumerated by **origin stamp**
  (not path — repo basenames can be shared) across **every machine**, and purged only after the
  abstracted knowledge is committed. After a telemetry scrub it **re-evaluates `confidence:`** (a note
  that loses its 3rd distinct project drops from `high`). Human-gated throughout.
  - **Erasure is de-identified by default, not "fully erased."** Purge clears the working trees and the
    *current* backup tree, but `capture_backup.sh purge` is `git rm` + commit — so the client's
    **ciphertext persists in the backup repo's git history** until that history is rewritten or the gpg
    key is destroyed. `--history` **outputs** (never runs) `git filter-repo` commands for **both** the
    knowledge repo and the backup repo; only then, or after key destruction, is a **"fully erased"** tier
    truthful. See ADR-008 and the threat model.
  - **`--attest`** (optional, output-only) runs a verification re-scan (→ 0 residual hits, else stop) and
    drafts a **purge attestation** — a client-facing record + a non-reversible internal audit stub
    (salted-hash id, no client name) at `~/.bailiwick/purge-audit/`. A *safety-net engineering record of
    what was mechanically done*, with the derived erasure tier — **never a legal or compliance assurance**
    (`knowledge/templates/purge-attestation-template.md`).

### Telemetry sidecar (`.telemetry.json`)
- `entries` keyed by `id`. 1:1 with telemetry-tracked content files (`topics`/`patterns`/`context`/`clients`).
- Per entry: `load_count`, `applied_count`, `useful_count`, `source_sessions`, `last_loaded`,
  `last_applied`, `last_useful`, `open_contradictions`, `distinct_projects_used[]`.
- **Tiered usefulness (ADR-004):** `loaded` (read) → `applied` (loaded in a session that shipped a
  mutation and/or commit — mechanical, derived by `capture_session.py`) → `used` (curate-judged from
  the reasoning that the tidbit informed the output). `applied` is coarse (every co-loaded id in a
  shipping session is credited); the human-gated `used` tier disambiguates. Surfaced by `/metrics`.
- Written by the Memory stage during Collect; committed with a `telemetry:` prefix **without** a
  human gate. **Documented single-writer assumption** — concurrent writers lose increments (this is
  the central constraint a team version must redesign; see §10).
- `/curate` reconciles: every telemetry-tracked `id`-bearing file (topics/patterns/context/clients) must have a row (seed missing; flag orphans).

### The recursive index tree
`INDEX.md` is **injected into every session** by the SessionStart hook, so it is kept lean — a
"map of maps". When any node exceeds ~15 topics it shards into `indexes/index_<domain>.md` (which
may shard further). Only root is injected; deeper nodes load on-demand during descent (target ≤2
levels, hard cap 3). Index nodes don't count toward the ≤5 content-file budget.

Retrieval here is **lexical and curation-driven** — the injected map plus tags and frontmatter, not
semantic similarity. This is deliberate: it stays cheap, legible, and diff-reviewable, and it is
excellent at small-to-mid scale. It is also the model's main scaling limit — a hand-curated map is
labour-intensive as the library grows (§14). An **optional local vector index** over the same
Markdown (embeddings as an accelerator alongside — not replacing — the curated map) is a plausible
enhancement that would not change this substrate; it is a roadmap possibility, not a dependency
([ROADMAP.md](../ROADMAP.md)).

### Confidence & graduation
`low` (first capture) → `medium` (used in ≥1 project, no open contradictions) → `high` (stable
across **3+ distinct projects**, no open contradictions). `topics/` graduate to `patterns/` after
reaching `high`, rewritten with full examples. Confidence is human-approved; the agent only
proposes.

---

## 5. Enforcement hooks

Installed **once globally** in `~/.claude/settings.json` (template:
`hooks/settings.template.json`); they fire in every project but **self-gate** — they
no-op unless the repo carries a framework **complement** file (`.bailiwick.local.md`,
`CLAUDE.local.md`, or the Copilot instructions) referencing `$BAILIWICK`. The team's shared files
are never touched or relied on for this. In **shadow mode** (§7.1) the same gate also passes with **no in-repo file** — via a
`~/.bailiwick/allowlist` match on `cwd` (or `BAILIWICK_SHADOW=1`); enforcement and capture then
apply exactly as they would in a seeded repo. Capture/session hooks are **Claude Code** hooks; the
**guardrail** additionally runs under Codex CLI (PreToolUse) and Gemini CLI (BeforeTool) via
`install_adapter_hooks.py` (§3, §10). Copilot runs none.

| Hook | Event | Role |
|---|---|---|
| `guardrails.py` | **PreToolUse** (`Bash`) | **Runtime guardrail (ADR-006).** Three tiers, each resolving to an in-the-moment gate — a **forced confirmation** under Claude Code and Gemini CLI, a **hard deny with break-glass** under Codex (no confirm dialog; §10) — so nothing dangerous runs silently or on agent initiative: **EXEMPT** (dirty-zone capture plumbing always passes — data-loss prevention); **ASK-IMPACT** (real-world impact re-confirms *even when user-instructed*: terraform/terragrunt `apply`/`destroy`, kubectl/helm mutations, gcloud/gsutil/az/aws mutating verbs incl. `update`/`patch`/`rm`, recursive/forced `rm`, `git merge`, `gh repo delete`); **ASK-GO-AHEAD** (`git commit`/`push`, `gh pr create`/`merge`/`close` need a clear user go-ahead; AI attribution signatures in the message get their own confirmation). Validation-only commands (plan/validate/fmt, `--dry-run`, read-only CLI) pass untouched; line-continuations folded before matching. Self-gated. **Tiered failure mode (ADR-005):** on evaluation error it fails **closed** (deny) for commands that trip a destructive pre-filter, else fails **open**; `BAILIWICK_BREAK_GLASS=1` downgrades that error-path deny to ask. **Direct-command patterns only — not a complete security boundary** (misses `make apply`, wrapper scripts, aliases, Terraform-MCP actions). Every decision is logged to `~/.bailiwick/guardrail-audit.log`. |
| `session_start.sh` | SessionStart | Assert framework defaults; **inject `INDEX.md`**; **inbound ff-pull** of the Bailiwick clone (throttled, clean-`main`-only, non-fatal); nag on pending captures; nag on framework-health **errors in the last ~24h** (this machine's shard); warn loudly if `python3` is missing (guardrail+capture inactive); nag if INDEX > ~20 KB (shard). |
| `capture_session.py` | Stop, SessionEnd | Copy the transcript to `<project>/.bailiwick-outputs/raw/<id>.jsonl` when the session did substantive work (mutations or ≥3 tool calls). No intelligence, no promotion. |
| `capture_backup.sh` | Stop, SessionEnd (push); `/curate` (pull/purge) | **Optional** durable backup: gpg-encrypts new captures and pushes **ciphertext** to a per-machine branch of a dedicated private repo (`capture_backup` in `.bailiwick-sync.json`; off + `confidentiality_ack: false` by default). `pull` decrypts to `.bailiwick-inbox/raw/` for curate (runnable from any wired repo); `purge` drops a blob from the **current tree** (not history — ciphertext persists in git history until rewritten/key-destroyed). Blobs are keyed by the collision-resistant `repo_key` (origin-based), so same-basename repos never commingle. Private key never leaves the curating machine. **Best-effort / fail-open**, local-mirror-first — a failed push lags the remote copy but never loses the capture; push success/failure (with unpushed-commit count) is logged to the framework-health shard, surfaced by `/metrics` and the SessionStart error nag. Also transports each machine's **health shard** (encrypted) on `push` and refreshes the fleet's shards into `~/.bailiwick/health/remote/` on `pull`. |

Helpers (not hook events): `sync_knowledge.sh` (outbound knowledge sync — §8), `install_hooks.py`
(idempotent safe-merge of the hooks block into `~/.claude/settings.json`, matcher-preserving;
**rewrites the baked canonical Bailiwick path to the machine's real Bailiwick root** and migrates stale
installs — satellites need no manual path edits), `install_global_layer.sh`
(+ `codex-global-agents.tmpl.md`, `gemini-global.tmpl.md`) — installs the global Codex / Gemini
operator layers into `~/.codex/AGENTS.md` and `~/.gemini/GEMINI.md` (§10), and `health_common.sh` —
**framework-health logging**: every component appends failures (best-effort, never blocking) to the
per-machine shard `~/.bailiwick/health/<machine>.jsonl`; shards travel encrypted on the
`capture_backup` branches and `/metrics` renders the per-source fleet view (heartbeats, errors by
component, backup push drift). All used by `bootstrap.sh --install-tools`.

Guarantees (precise): capture is automatic for **Claude Code** sessions where the hooks run (Codex/
Copilot need the manual flow); raw captures are **never added to the target repo** by the framework
(`.bailiwick-outputs/raw/` is git-ignored) — but they are **local plaintext on disk** until curated or, if
enabled, encrypted by `capture_backup.sh`; `.git/info/exclude` prevents git tracking, it does not
secure local files. No spam (only substantive sessions); self-gating keeps unrelated repos silent.

**Backup key recovery (a decision, not an implementation detail):** with `capture_backup` enabled,
the gpg private key lives only on the curating machine. The owner must keep an **offline recovery
copy** of that key, or accept **permanent loss** of the encrypted captures if the curating machine
is lost. Recorded in `docs/decisions/adr-002-dirty-zone-backup-confidentiality.md`.

---

## 6. Capture → Curate → Promote lifecycle

1. **Capture (automatic).** Hooks stage raw transcripts to `<repo>/.bailiwick-outputs/raw/` (seeded mode)
   or, in **shadow mode** (§7.1), to a central `~/.bailiwick/captures/<repo-key>/raw/` keyed by
   origin repo (git remote, else root-path hash) with origin + scope stamped — leaving the repo tree
   untouched. Both feed the same dirty-zone backup → `/curate` pipeline; central staging concentrates
   dirty data, so ADR-002's encryption/key-recovery posture matters more there, not less.
2. **`/curate` (human-gated skill).** Procedure: gather raw + agent-output candidates → extract
   (decisions, patterns, pitfalls, Retrieval Feedback, federation-ingest candidates) → update +
   reconcile telemetry (**central machine only**) → dedup against INDEX (NEW/EXPAND/IMPROVE/SKIP) →
   route by confidence (NEW and contradicting-IMPROVE block for approval; additive EXPAND held for
   the periodic digest) → **single approval batch** → write on approval (+ seed telemetry, update
   INDEX, stage a `knowledge:` commit) → retire processed inputs to `.curated/`.
3. **Periodic Curation** (every 6–8 weeks): staleness scan, apply held digest, archival candidates,
   confidence graduations, index-tree rebalancing.

Hard rule: knowledge content files are **never** written without explicit approval in-session;
`.telemetry.json` is the only ungated write.

---

## 7. Onboarding (bootstrap scripts)

`scripts/bootstrap.sh` (+ `bootstrap.ps1`) wire a repo to the framework — on any machine, for a
fresh repo (`--init`) or an existing clone. **Shadow mode is the default** (§7.1): a no-flag run
writes zero files into the repo. `--seeded` selects the in-repo hidden wiring described by the
properties below; `--visible` and `--init` imply seeded (they write repo files by design);
`--with-standards` (the intentional team-baseline path) works in both modes. Key properties of the
seeded variant:

- **Generates** `.mcp.json` (Claude Code) + `.vscode/mcp.json` (VS Code) + `.codex/config.toml`
  (Codex MCP draft/reference, with `--with-agents`; current Codex CLI loads active MCP from
  `~/.codex/config.toml`) + `.gemini/settings.json` (Gemini MCP, with `--with-gemini`; a
  team-tracked one is left untouched) and **seeds hidden
  complement files** — `CLAUDE.local.md` (+ optional `.bailiwick.local.md` Codex marker,
  `.github/instructions/bailiwick.instructions.md`) from templates, substituting the real Bailiwick
  path and repo name. The team's own `CLAUDE.md`/`AGENTS.md`/`copilot-instructions.md` are **never
  touched or shadowed** — each tool loads its complement alongside them (filesystem discovery, so
  gitignored complements still load). See §10 for why Codex uses a marker + global layer rather than
  a repo-root instruction file.
- **Hidden wiring (the privacy property):** framework files are excluded via the repo's
  **`.git/info/exclude`** — *not* the tracked `.gitignore` — so a colleague/client who clones sees
  **no trace** of the framework. `.bailiwick-outputs/` is always local. `--visible` opts into tracked files
  for a shared-team repo.
- **Update-safe:** two file classes — **managed** (MCP configs: regenerated on `--update`) vs
  **seeded** (complement files: preserved; only a drifted Bailiwick path is corrected). `--force`
  overwrites everything; a plain re-run skips existing files. Idempotent. `--update`/`--clobber`
  reconcile the framework's own block in `.git/info/exclude` — only lines **after the framework
  marker**, never a user's own exclude rules.
- **Tracked-file guard:** a seeded file that the target repo *already tracks* (a real project
  `AGENTS.md`/`copilot-instructions.md`) is **never seeded, overwritten, or excluded** (even with
  `--force`) — the hidden-wiring model cannot hide a tracked file, and overwriting would clobber
  project content. Such files must be merged deliberately and are shared. Only untracked files are
  seeded + hidden.
- **Managed-config safety (`.mcp.json`, `.vscode/mcp.json`, `.codex/config.toml`, `.gemini/settings.json`,
  and the global `~/.claude/settings.json` / `~/.codex/AGENTS.md` / `~/.gemini/GEMINI.md`). The rule
  across every generated config:
  1. **A team-authored config is never clobbered.** Where a tool treats its config as committable
     (notably `.gemini/settings.json`), a repo-**tracked** one is **left untouched** — skip + warn,
     merge the framework MCP by hand — **even with `--force`**. Bailiwick's *own* generated managed
     files (`.mcp.json`, `.vscode/mcp.json`, the `.codex/config.toml` draft) are hidden via
     `.git/info/exclude` in seeded mode (so never tracked) and simply regenerated on `--update`; they
     are tracked only under `--visible`, where sharing them is the intent.
  2. In shared **global** files, Bailiwick edits **only its own marker-delimited managed block**
     (`# BEGIN bailiwick …` / `<!-- BEGIN bailiwick … -->`); hand-written content around it is preserved
     (safe-merge — `install_hooks.py`, `install_adapter_hooks.py`, `install_global_layer.sh`), and
     `--uninstall` removes only those blocks.
  3. **Fail closed on ambiguity** — if an existing `settings.json` is not valid JSON (or a `hooks`
     value has the wrong shape), the installer **refuses to modify it** and prints manual instructions
     rather than guessing.
- **Destructive reset (`--clobber`, requires `--force`):** the deliberate escape hatch from the two
  guards above. The two-flag combo (inert with `--clobber` alone) overwrites repo-tracked complement
  files *and* existing `--with-standards` baseline files, resetting a repo to the generic baseline
  for whatever reason. Tracked files are recoverable via `git checkout`; untracked overwrites are
  not. Everything else stays update-safe — this is the only path that crosses the tracked-file guard.
- **Agnostic baselines (`--with-standards`):** optionally seeds **tracked, shared** standard files
  (`CLAUDE.md`, and `AGENTS.md`/`copilot-instructions.md` per the tool flags) with self-contained
  generic best practices (cloud/Terraform/quality/security + reuse-first intelligence) and **no
  framework/org references** — written only when absent, never clobbered, never excluded.
  This is the *team's* committed baseline; the hidden complements layer the private framework on top.
- **Global prerequisites (`--install-tools`):** installs the once-per-machine pieces when missing —
  terraform-mcp-server (`go install`), the capture/curation **+ guardrail** hooks
  (`~/.claude/settings.json`), the global **Claude Code skill symlinks** (`~/.claude/skills/`:
  `/curate`, `/enrich`, `/learn`, `/metrics`, `/investigate`, `/purge`), the global **Codex skill symlinks** (`~/.codex/skills/`: `$bailiwick-curate`,
  `$bailiwick-enrich`, `$bailiwick-learn`, `$bailiwick-investigate`, `$bailiwick-purge`), and the global **Codex + Gemini operator layers** (managed blocks in
  `~/.codex/AGENTS.md` and `~/.gemini/GEMINI.md` that activate per-repo on the
  `.bailiwick.local.md` marker). Without it,
  every run *validates* these and prints ✓/✗ in the Next steps. (Skills and operator layers are
  global, not per-repo.) Optionally, `--with-desktop` also wires the knowledge-scoped Desktop
  reference MCP for Claude/ChatGPT Desktop (§10).
- **Enrich after bootstrap (`/enrich` in Claude Code, `$bailiwick-enrich` in Codex):** scans the
  bootstrapped repo (Terraform backend/providers/modules, GCP project IDs, environments, CI/CD,
  structure), asks only for gaps it couldn't infer, and **drafts project-context-filled instruction
  files for all four tools** — both the committed team baselines (kept framework-agnostic, via a
  mandatory leakage guard) and the hidden complements (framework-aware). Drafts only; never commits.
  Best run right after bootstrapping an existing project. See `skills/enrich/SKILL.md`
  and `codex-skills/bailiwick-enrich/SKILL.md`.
- **Learn after bootstrap (`/learn` in Claude Code, `$bailiwick-learn` in Codex):** the knowledge-side
  complement to `/enrich` — scans the bootstrapped repo for **reusable knowledge** (decisions with
  rationale, IaC patterns, pitfalls/workarounds, conventions in evidence) and distills it into one
  pre-digested capture staged exactly where `/curate` gathers (seeded: `.bailiwick-outputs/`; shadow:
  `~/.bailiwick/captures/<repo-key>/` — the manual session-output channel). Promotion rides the
  standard capture→curate human gate; `/learn` itself writes no knowledge. Bootstrap → `/enrich` →
  `/learn` → `/curate` is the full existing-project onboarding sequence. See `skills/learn/SKILL.md`
  and `codex-skills/bailiwick-learn/SKILL.md`.
- **Federation wiring:** injects each enabled external source's path as an extra MCP filesystem
  root (see §9).

### 7.1 Shadow mode — zero-footprint activation (the DEFAULT; ADR-003)

> Status: implemented for **Claude Code** (gate in `session_start.sh`/`guardrails.py`/`capture_session.py`,
> `bootstrap.sh --shadow`, central captures + `capture_backup.sh`, `/curate` gather) and **Codex/Gemini**
> (operator layers activate on `~/.bailiwick/allowlist` or `BAILIWICK_SHADOW`, refreshed via
> `--install-tools`) — ADR-003. Global Codex/Gemini MCP is injected by `--shadow --with-agents` /
> `--with-gemini` (bailiwick-* servers into `~/.codex/config.toml` / `~/.gemini/settings.json`, **including
> account-aware `bailiwick-github`** when a usable gh account resolves — override > `github_account_map` >
> access probe, same rules as the per-repo flow; skipped with `--no-gh-auth`). Remaining: **Copilot**
> user-scope instruction auto-injection is
> build-dependent (VS Code #304101). ADR-003 is accepted in `docs/decisions/`; ADR-007 made shadow the default.

**Shadow mode is the default** (since 2026-07; previously seeded was): a no-mode-flag bootstrap
leaves the repo **completely untouched** — the motivating case is a **client clone**, but it is now
the standard wiring for every repo. It writes **zero files** into the target repo;
activation moves entirely to **global/user-scope** config, selected per repo by a
`~/.bailiwick/allowlist` (or `BAILIWICK_SHADOW=1`). **Seeded** mode (`--seeded`; implied by
`--visible`/`--init`) is the in-repo variant: hidden complement + MCP files, excluded via
`.git/info/exclude`. The knowledge library is already central, so
only two things relocate: **activation** (repo file → global config) and **captures** (in-repo →
central staging). All global-scope mechanisms below were verified against each tool's official docs.

| Tool | Global instructions (no repo file) | Global MCP (no repo file) | Shadow status |
|---|---|---|---|
| **Claude Code** | SessionStart hook injection (already the vehicle; gate widened to the allowlist) — no global `CLAUDE.md`, so activation stays selective | `claude mcp add --scope user` (`~/.claude.json`) or `permissions.additionalDirectories` (`~/.claude/settings.json`) | ✅ full — incl. enforcement + capture |
| **Codex CLI** | `~/.codex/AGENTS.md` (loads regardless of project trust) | `[mcp_servers.*]` in `~/.codex/config.toml` (loads regardless of trust) | ✅ full |
| **Gemini CLI / Code Assist** | `~/.gemini/GEMINI.md` (every session; repo file supplements) | `mcpServers` in `~/.gemini/settings.json` | ✅ full |
| **Copilot (VS Code, local)** | user `*.instructions.md` (New Instructions (User)) — **empirically verify**: VS Code #304101 may not auto-inject `applyTo:"**"` user files | user `mcp.json` ("MCP: Open User Configuration") | ⚠️ MCP solid; instructions build-dependent |

- **Activation gate.** The Claude Code hooks' `is_bailiwick_repo` and the three tools' global operator
  layers pass when `cwd` is on the allowlist (or the env var is set) — no in-repo marker. Current
  Codex CLI loads the global instruction layer and user-scope MCP from `~/.codex/`; project trust
  remains relevant to normal Codex workspace operation, but not to a repo-local `.codex/config.toml`
  MCP path in this environment. The hosted **Copilot cloud agent stays out of scope** (it sees only
  the pushed repo — as in seeded mode).
- **Central captures (Option A).** `capture_session.py` writes plaintext to
  `~/.bailiwick/captures/<repo-key>/raw/` instead of `<repo>/.bailiwick-outputs/raw/`, stamping origin +
  scope; `capture_backup.sh` sources from there (unchanged gpg/ciphertext posture); `/curate` and the
  pending-capture nag read the central dir. This reuses the existing dirty-zone → curate pipeline,
  which already keys captures by origin repo. See §6 and ADR-003 for the confidentiality trade-off
  (central aggregation concentrates dirty data — a governance point, not a footnote).
- **Setup.** `bootstrap.sh <repo>` (no mode flag — shadow is the default; `--shadow` remains an
  explicit alias) registers the Claude Code global MCP root + allowlist entry
  (and the global tool layers via `--install-tools`) **instead of** seeding repo files; adding
  `--with-agents` / `--with-gemini` also injects `bailiwick-*` MCP servers into `~/.codex/config.toml` /
  `~/.gemini/settings.json` globally (idempotent, existing config preserved). Everything else
  (knowledge, agents, curation, sync) is identical to seeded mode.

---

## 8. Multi-machine sync

The framework is cloned per machine; `.bailiwick-sync.json` (gitignored) sets each machine's role.

- **central** — the primary machine. **Owns `.telemetry.json`.** `/curate` pushes approved commits
  straight to `origin/main`.
- **satellite** — every other machine (default if absent). **Skips the telemetry step entirely.**
  `/curate`'s `sync_knowledge.sh` parks commits on `sync/<machine>`, force-with-lease pushes, and
  opens/refreshes a PR to `main`; local `main` stays a clean fast-forward mirror.

**Inbound** currency is automatic (SessionStart ff-pull). **Outbound** is branch-per-machine + PR
(a single central merge authority — avoids the append-heavy conflict class on `INDEX.md` /
`.telemetry.json`). Telemetry being central-owned removes its conflict class entirely; central
seeds rows for satellite-PR files on its next reconcile.

**Public-origin instances are contribute-only (ADR-009).** A clone whose `origin` is the public OSS
repo is a place to *contribute from*, never to *ingest into*: the documented default is a private
downstream (`origin` → your own private repo, `upstream` → the public OSS with its push URL disabled)
so a `/curate` push can never land private knowledge in public. See `staying-private.md` and
threat-model **T9**.
> **Status:** implemented. Detection lives in `hooks/public_origin.sh` (canonical-slug match, host-
> and protocol-agnostic; optional `gh` visibility check to catch public forks; `allow_public_push`
> override in the gitignored `.bailiwick-sync.json`). `sync_knowledge.sh` refuses to propagate and
> exits 1 with the commits left local, `/curate` aborts at Step 0 before extracting anything,
> `session_start.sh` injects a contribute-only notice, and `bootstrap.sh`/`.ps1 --install-tools`
> warn without failing. Raw `git push` by hand remains outside the framework's control, and without
> an authenticated `gh` the fork check degrades to the canonical-slug match.

---

## 9. Federated memory (connecting to other "brains")

The bridge to knowledge bases we don't own — a company/central brain, another team's library.
**Policy-read-only outward** (enforced by the Federation Agent's rules, **not** by the transport — the
MCP filesystem server is read-write on all roots; see the ⚠️ below and §14): by rule, external sources
are never written to, and our KB never flows out. A transport-enforced read-only source is a roadmap
item (ROADMAP.md).

- **Registry:** `.bailiwick-sources.json` (gitignored; template `.bailiwick-sources.example.json`). Each
  source: `id`, `enabled`, `kind` (`filesystem` implemented; `git`/`mcp`/`http` reserved),
  `location`, `index`, `scope` (e.g. `external:globex`), `trust` (`reference`/`untrusted`),
  `mode` (`consult`/`consult+ingest`). Empty/all-disabled = inactive.
- **Access:** `bootstrap.sh --update` adds each enabled `location` as an extra MCP filesystem root.
  ⚠️ The MCP filesystem server is read-write on all roots — **read-only is enforced by the
  Federation Agent's rules, not the server.**
- **Consult** (during Memory Query): read the source's index, load ≤2 external files, tag every
  fact `[external:<id>]`; resolve conflicts by the source-authority precedence (§11) — external/local
  reference never overrides project decisions or authoritative docs.
- **Ingest** (inside `/curate`, gated): abstract (don't transclude), stamp `source:` +
  `## Provenance` + `scope: external:<id>`, dedup, approve. Never automatic, never written back.

This is the primitive that lets a single-user framework act as a **consumer of, or contributor to,
a larger brain** — see §10.

---

## 10. MCP & multi-tool (four adapters, not one uniform integration)

The same Markdown agents/knowledge serve four tools, but **the tools do not share an integration
model** — each has its own instruction-discovery and MCP mechanism. The framework is best understood
as **four adapters of differing completeness**, all reading the framework live (nothing copied):

| Adapter | Instruction delivery | Global private layer | MCP config | Capture | Dangerous-command control |
|---|---|---|---|---|---|
| **Claude Code** (full) | `CLAUDE.local.md` — native personal memory, **merges** after `CLAUDE.md` | `~/.claude/CLAUDE.md` | `.mcp.json` | **Automatic** (Stop/SessionEnd hooks) | **Enforced** — PreToolUse `guardrails.py` (§5) |
| **Gemini** (VS Code agent) | global `~/.gemini/GEMINI.md` layer + `.bailiwick.local.md` marker (best-effort read) | `~/.gemini/GEMINI.md` (loaded first → repo `GEMINI.md` keeps precedence) | **`.gemini/settings.json`** (`mcpServers`, generated by `--with-gemini`) | **Manual** (no hooks) — agent writes to `.bailiwick-outputs/` | **Enforced (Gemini CLI)** — `BeforeTool` hook wired to the guardrail (`ask` tiers, mirrors Claude Code; `install_adapter_hooks.py`). VS Code Code Assist agent hook support **unverified** → policy there; `excludeTools` stays advisory; still don't enable YOLO |
| **Codex** (global-layer + marker) | global `~/.codex/AGENTS.md` layer + `.bailiwick.local.md` marker; native workflow skills in `~/.codex/skills/` | `~/.codex/AGENTS.md` (loaded first → repo `AGENTS.md` keeps precedence) | **`~/.codex/config.toml`** for active MCP; `.codex/config.toml` is a repo-local draft/reference generated by `--with-agents` | **Manual** (capture hooks not wired) | **Enforced** — `PreToolUse` hook wired to the guardrail (**deny** + `BAILIWICK_BREAK_GLASS=1` allow-once; one-time trust prompted on first fire in the `codex` CLI, persisted in config) |
| **Copilot** (local VS Code only) | `.github/instructions/bailiwick.instructions.md` (`applyTo:"**"`) | VS Code user instruction dirs | `.vscode/mcp.json` (local); cloud uses hosted config | Manual | Policy |

All instruction/config files are **filesystem-discovered** (an untracked/gitignored complement still
loads locally) — **except** the GitHub-hosted **Copilot cloud agent**, which only sees the pushed
repo, so the hidden complement never reaches it.

**Stage subagents across the adapters (ADR-010 Amendment 1).** All four tools now dispatch the
Quality Workflow stages natively: canonical `agents/*.md` → Claude Code symlinks
(`~/.claude/agents/`), generated Gemini Markdown (`~/.gemini/agents/`), generated Codex TOML
(`~/.codex/agents/`; read-only toolsets map to `sandbox_mode = "read-only"`), generated Copilot
`*.agent.md` (`~/.copilot/agents/`). All user-scope — never seeded into a repo. **Triggering:**
Claude Code and Gemini auto-delegate on description match (force by naming the stage /
`@bailiwick-<stage>`); Codex does **not** auto-delegate — the global operator layer carries the
delegation rule, and the user forces by asking for an agent by name; Copilot is explicit selection
(auto only agent-to-agent; the hosted cloud agent never sees user-scope agents). **Surfaces:**
Codex subagents span the CLI **and the IDE extension** (same `~/.codex/agents/`); Gemini is
**CLI-verified only** — Code Assist agent mode exposes a subset of the CLI and subagent support
there is unverified; Copilot's covered surfaces are VS Code + CLI. Guardrail-hook coverage inside
Codex/Gemini subagent threads is **unverified** — policy posture applies there. Mechanics: each
tool's official subagent docs.

Key consequences (the four tools do not share one uniform integration):
- **Codex framework guidance goes in a global layer, not a repo-root file.** Codex loads at most one
  instruction file per directory, so a framework file at the repo root would **suppress** the team's
  `AGENTS.md`. The framework instead installs a personal **global** `~/.codex/AGENTS.md` layer
  (`bootstrap.sh --install-tools`) that conditionally reads the untracked `.bailiwick.local.md`
  marker — preserving the team file's authority.
- **Codex MCP lives in `config.toml`,** not `.mcp.json`. Codex **documents** project-scoped
  `.codex/config.toml` MCP (`[mcp_servers.*]`, **trusted projects only**) alongside user-scope
  `~/.codex/config.toml`. In our validation (codex-cli ~0.142) the repo-local file did **not** load as
  active MCP even after trusting the project — a version/environment discrepancy, **not** a Codex
  platform limitation. Until that resolves, `bootstrap.sh --with-agents` keeps generating
  `.codex/config.toml` only as a hidden draft/reference with the four intended servers
  (filesystem, fetch, github, terraform). For working Codex MCP today, use `bootstrap.sh --shadow
  --with-agents`, which injects an idempotent user-scope `bailiwick-*` MCP block into
  `~/.codex/config.toml`. The github server resolves its token via a spawn shell (gh-auth or
  `$GITHUB_TOKEN`), independent of Codex env expansion.
- **Codex skills mirror the Claude Code skills.** `codex-skills/bailiwick-curate`,
  `codex-skills/bailiwick-enrich`, `codex-skills/bailiwick-learn`, `codex-skills/bailiwick-investigate`,
  and `codex-skills/bailiwick-purge` are Codex-native wrappers installed into `~/.codex/skills/` by
  `--install-tools`. They intentionally point back to the canonical `skills/*/SKILL.md` files, so the
  procedure stays single-source while Codex gets a native `$bailiwick-curate` / `$bailiwick-enrich` /
  `$bailiwick-learn` / `$bailiwick-investigate` / `$bailiwick-purge` trigger instead of a copied prompt.
- **Gemini gets a global layer + shared marker, and (CLI) a wired guardrail.** `--install-tools` installs a
  managed block in `~/.gemini/GEMINI.md` (loaded first, so a repo `GEMINI.md` keeps precedence; the
  framework defaults are stated *in* the global file since the VS Code agent has no guaranteed loader
  for an arbitrary marker filename). `--with-gemini` generates a hidden **`.gemini/settings.json`**
  (`mcpServers`, same servers as `.mcp.json`) — the **one file** both Gemini CLI and the Code Assist
  VS Code agent read; a **team-tracked** `.gemini/settings.json` is left untouched. Its `excludeTools`
  entries are **advisory only** — Google's docs call command-specific shell restriction *"simple
  string matching,"* *"easily bypassed,"* *"not a security mechanism."* The real control under
  **Gemini CLI** is now the wired **`BeforeTool` guardrail hook** (`~/.gemini/settings.json` `hooks`
  block installed by `install_adapter_hooks.py`): the shared engine returns `decision: "ask"` for the
  ADR-006 tiers — the same forced confirmation as Claude Code (`ask` is source-verified in
  gemini-cli's scheduler but undocumented; re-verify on upgrades). The **Code Assist VS Code agent's**
  hook support is **unverified** — there, keep **`geminicodeassist.agentYoloMode` disabled** (the
  approval dialog) as the control. Capture is
  **manual** (no session hooks): the agent writes a `.bailiwick-outputs/` session output, same as Codex/Copilot.
- **The Copilot adapter is local-VS-Code-only.** The hidden, gitignored complement is filesystem-
  discovered in the IDE, but the GitHub-hosted **Copilot cloud agent cannot see untracked files**, so
  the framework does **not** reach it (that would require committing a shared instruction file).
- **MCP servers** (Claude Code `.mcp.json` / VS Code `.vscode/mcp.json`): `filesystem` (roots =
  workspace + `$BAILIWICK` + any enabled federation sources), `fetch`, `github`, `terraform`
  (`terraform-mcp-server stdio` — local binary, Docker-free for locked-down machines).
- **Shadow mode (§7.1)** relocates every one of these per-repo instruction/MCP files to its tool's
  **global/user scope** (`~/.claude.json`·`~/.claude/settings.json`, `~/.codex/config.toml`,
  `~/.gemini/settings.json`, VS Code user `mcp.json`/instructions), leaving the repo untouched —
  verified per adapter in §7.1. Only local Copilot instruction auto-injection is build-dependent
  (VS Code #304101); its user-scope MCP is unaffected.
- **Desktop reference (knowledge-scoped, outside the four adapters).** Claude Desktop and ChatGPT
  Desktop have no hook system, so they sit outside capture/curation/guardrails entirely.
  `bootstrap.sh --install-tools --with-desktop` (and `bootstrap.ps1 -InstallTools -WithDesktop`)
  optionally wires a single `bailiwick-knowledge` MCP filesystem server — rooted at `knowledge/`
  **only**, never the rest of the framework. Least privilege here applies to the **root, not the
  verbs**: the server is read-**write** within `knowledge/` and Desktop has no gates, so treat it
  as reference-by-convention (see CLAUDE.md) — into each app's own MCP config
  (`hooks/install_desktop_mcp.py`, idempotent, path auto-detected for macOS/Windows/WSL). It lets
  either app *consult* the library outside a coding session; pair it with
  `knowledge/templates/desktop-reference-instructions.md`. Deliberately **not** a fifth adapter — a
  reference channel with no enforcement and no capture.

---

## 11. Conventions & rules (quick reference)

- **Naming (CAF taxonomy):** `{org}-{type}-{workload}-{env}-{region}-{instance}` (see
  `patterns/caf-naming-taxonomy.md`). `{org}` from `org-shorthands.md`.
- **Commits:** `type(scope): description` — `feat|fix|docs|refactor|chore|knowledge|telemetry`.
  Knowledge commits are always separate from code (`knowledge:` / `telemetry:` prefixes).
- **Scopes:** `generic | client:<id> | external:<id>` (§4).
- **Source-authority precedence (conflict resolution).** When sources disagree, resolve **top-down**.
  The Bailiwick knowledge library wins for *workflow/method*, but it does **not** automatically override
  project reality or authoritative constraints:
  1. Explicit **legal, contractual, security, and client** constraints.
  2. **Accepted project decisions** and current repository state.
  3. **Official vendor documentation** and authoritative standards.
  4. Mandatory **team/company engineering controls**.
  5. **Bailiwick** operating method, reusable patterns, and templates.
  6. **External/federated** reference material (lower trust).

  So a federated or local tidbit never overrides a project decision or an authoritative doc; it wins
  only over same-or-lower tiers. (Applies to Memory Query, Federation consult, and Lead synthesis.)
- **Non-negotiables:** high-impact actions (apply/destroy, cluster & cloud mutations, recursive rm,
  git merge) re-confirm even when instructed; commit/push/PR only on a clear user go-ahead (AI
  attribution signatures get their own confirmation); capture plumbing exempt; validation-only
  commands free; no knowledge writes without the human gate; `.bailiwick-outputs/raw/` never committed;
  all outputs are drafts. Under **Claude Code, Codex CLI, and Gemini CLI** the supported direct-command
  subset is **runtime-guarded** by `guardrails.py` through each tool's hook system (Claude/Codex
  PreToolUse, Gemini CLI BeforeTool); under **Copilot** and the **Gemini Code Assist VS Code agent** it
  is **policy only** (§3, §5, §10).

---

## 12. Repository layout

```
bailiwick/
  README.md  CLAUDE.md  AGENTS.md           # entry + operating docs
  .bailiwick-sync.example.json                   # per-machine sync role template
  .bailiwick-sources.example.json                # per-machine federation registry template
  ROADMAP.md                                # non-goals & possibilities (team version, radar)
  scripts/        bootstrap.sh  bootstrap.ps1
  knowledge/      INDEX.md  .telemetry.json  topics/ patterns/ context/ clients/ templates/ …
  agents/         lead + 5 domain + 7 execution (13 files)
  hooks/          session_start.sh  capture_session.py  capture_backup.sh  sync_knowledge.sh
                  guardrails.py  install_hooks.py  settings.template.json  health_common.sh
                  install_global_layer.sh  install_adapter_hooks.py  install_desktop_mcp.py
                  codex-global-agents.tmpl.md  gemini-global.tmpl.md
  skills/         curate/  enrich/  learn/  metrics/{SKILL.md,report.py}  investigate/  purge/   (each a SKILL.md)
  codex-skills/   bailiwick-curate/  bailiwick-enrich/  bailiwick-learn/  bailiwick-investigate/  bailiwick-purge/  (SKILL.md wrappers)
  copilot-instructions/   terraform-gcp(.gke/.data/.project-stack).md
  prompts/        iam-review · pr-review · module-docs · cost-estimate · security-pr-report
  vscode/         mcp.json (template) · terraform.code-snippets
  docs/           FRAMEWORK.md (this file) · threat-model.md · telemetry-validation-protocol.md
                  getting-started.md · operations.md · README.md · decisions/ (framework ADRs, adr-001…009)
```
Hidden per-machine in **wired target repos** (via `.git/info/exclude`, never shared): `.bailiwick-outputs/`,
`.mcp.json`, `.vscode/mcp.json`, `.codex/config.toml`, `.gemini/settings.json`, `CLAUDE.local.md`,
`.bailiwick.local.md`, the Copilot instructions. Gitignored in the **Bailiwick repo**:
`.bailiwick-sync.json`, `.bailiwick-sources.json`. In **shadow mode** (§7.1) none of the per-repo files exist;
their role moves to per-machine global state under `~/.bailiwick/` (`allowlist` + `captures/` +
`health/` + `guardrail-audit.log`) plus
each tool's user-scope config.

---

## 13. Scope & non-goals (single-user by design)

Bailiwick is deliberately **single-user** — one owner, one primary machine. That is a design choice,
not an oversight, and it keeps the substrate simple (plain git + Markdown + JSON, no service).
A shared, governed, multi-contributor **team brain** is explicitly **out of scope for now**. The main
reasons it is not a team tool today:

- **Telemetry is single-writer** (`.telemetry.json` loses concurrent increments; the central/satellite
  split is a workaround, §4/§8) — this is the #1 structural blocker.
- **Curation is single-human-gated** — no governance roles, approval workflow, or promotion audit trail.
- **No identity/attribution** — frontmatter has no contributor field; graduation counts projects, not people.
- **Scope confidentiality is convention, not enforcement** — and federation read-only is agent policy,
  not transport-enforced.

Much of the design already points toward a team version (federation as the brain-to-brain connector,
explicit `generic`/`client:<id>`/`external:<id>` scopes, the Security-Review leakage check, tool-neutrality).
The full honest analysis of what a team version would require — what generalises, the hard parts, a
possible tiered project→team→company topology, and the open questions — lives in
[**ROADMAP.md**](../ROADMAP.md) so it does not clutter this reference. Adopt Bailiwick where the
single-user scope fits (a single practitioner or a small trusted team); treat the team version as a
separate future effort.

---

## 14. Strengths & limitations (what's good, what's not)

An honest self-assessment. Adopt it where the strengths matter to you and the limitations don't bite.

### Where it's strong
- **Context economy.** The injected index + on-demand loading + a hard content-file budget keep
  per-session token cost bounded as the library grows — the injected map grows far more slowly than
  the content it indexes (sharding keeps it lean), so cost tracks the index, never the library —
  the vendor-endorsed "progressive disclosure" pattern, applied throughout.
- **Enforcement is real, not advice.** The guardrail is a runtime PreToolUse hook across three tools
  (Claude Code, Codex, Gemini CLI), not a prompt the model can ignore — high-impact actions require
  an in-the-moment confirmation, and nothing dangerous runs on agent initiative.
- **Capture can't be forgotten — under Claude Code.** There, session capture is a harness hook, not a
  discipline; knowledge is never lost even when you skip curation. Codex, Gemini, and Copilot use
  **manual** capture until their lifecycle-capture adapters are wired (§10) — the guarantee is
  Claude-Code-specific, not universal.
- **Private by default.** Shadow mode writes zero files into a target repo; seeded mode hides
  via `.git/info/exclude`, never a tracked `.gitignore`. The framework stays invisible in
  client/colleague repos — that invisibility is structural, but overall privacy still depends on
  what your captures hold and how you curate them (see [threat-model.md](threat-model.md)).
- **Provenance and scope are explicit — and reversible.** Every knowledge item is `generic` /
  `client:<id>` / `external:<id>`; a leakage check keeps client specifics from becoming generic
  patterns; a de-identified `/curate` mode can store zero identifiers; and `/purge` retroactively
  removes a client/project (offboarding / de-identification / deletion request) while keeping the reusable knowledge (§4, ADR-008).
- **Simple substrate.** Plain Markdown + Python + shell. No service, no database, no build step —
  easy to read, fork, and trust.

### Where it's weak (known limitations)
- **The guardrail is not a sandbox.** It matches *direct commands* only — bypassed by `make apply`,
  wrapper scripts, shell aliases/functions, and MCP tool calls. It is a high-value productivity rail,
  not a security boundary. See `docs/threat-model.md`.
- **Single-writer telemetry.** `.telemetry.json` loses concurrent increments by design; the
  central/satellite split is a workaround, not multi-writer support (§13; [ROADMAP.md](../ROADMAP.md)).
- **Curation is manual and human-gated.** Deliberate for trust, but it is real ongoing effort; the
  library is only as good as the curation behind it.
- **Retrieval is a hand-curated map.** Excellent at small scale, labour-intensive at large scale —
  no semantic/vector recall yet ([ROADMAP.md](../ROADMAP.md)).
- **Federation read-only is policy, not transport-enforced.** The MCP filesystem server is read-write
  on all roots; read-only depends on agent discipline ([ROADMAP.md](../ROADMAP.md)).
- **Adapter completeness varies.** Full under Claude Code; Codex/Gemini get the guardrail but capture
  is manual; Copilot is policy-only and local-VS-Code-only (§10). Codex hooks need a one-time trust.
- **The seed content is GCP/Terraform-shaped.** The *machinery* is domain-neutral, but the knowledge
  tiers, domain context files, templates, and conventions that ship in the box assume cloud/IaC work and
  lean GCP + Terraform. Point it at another domain and you grow a different library, but the box
  starts where the framework grew up.

### Non-goals
Sandboxing the agent; protecting local plaintext at rest; enforced multi-tenant isolation; being a
general-purpose knowledge base (the seed library targets cloud/IaC work). See the threat model for the
security non-goals specifically.

---

## 15. Glossary
- **brain** — a knowledge base an agent reads from (Bailiwick is one; a team/company KB is another).
- **central / satellite** — sync roles; central owns telemetry and pushes `main` directly.
- **consult / ingest** — federation modes: read external knowledge for a task / pull it into our KB (gated).
- **curate** — the human-gated promotion of captures into the library.
- **federation** — the **policy-read-only** consult bridge to external brains (`.bailiwick-sources.json`); read-only by Federation-Agent rule, not transport-enforced.
- **INDEX tree** — the recursive, on-demand map of the knowledge library; root injected each session.
- **scope** — provenance of a knowledge item: `generic` | `client:<id>` | `external:<id>`.
- **seeded vs managed** — bootstrap file classes: hand-editable (preserved) vs generated (refreshed).
- **seeded mode vs shadow mode** — activation models: *shadow* (§7.1, **the default**) writes
  nothing to the repo and activates from per-machine global state (`~/.bailiwick/allowlist` +
  each tool's user-scope config); *seeded* (`--seeded`) writes hidden complement/MCP files into the
  repo (excluded via `.git/info/exclude`).
