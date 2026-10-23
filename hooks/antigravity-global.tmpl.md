<!-- BEGIN bailiwick (managed block — do not edit by hand; refreshed by bootstrap.sh --install-tools) -->
# bailiwick — private operator layer (Antigravity global)

> This block lives in your personal `~/.gemini/GEMINI.md`. Antigravity (CLI `agy`, IDE, and 2.0 app)
> and legacy Gemini tools load it as the **global context file**, before any project `GEMINI.md`. A repo's own
> `GEMINI.md` or `AGENTS.md` is loaded afterwards and **takes precedence** — project constraints win over this
> personal layer. Nothing here is shared with any repository or colleague; it is local to this machine.

## Per-repository activation
Activate the framework defaults below for the current repository when **either** condition holds:
1. **Seeded:** the repo contains a file named **`.bailiwick.local.md`** — read it before substantive
   work and treat it as **private operator guidance** (project context + a pointer to the framework).
2. **Shadow — no in-repo file** (FRAMEWORK.md §7.1): the environment variable `BAILIWICK_SHADOW=1`
   is set, **or** the repository root is listed in `~/.bailiwick/allowlist` (one absolute path per
   line; `#` comments). There is no marker to read — apply the framework defaults directly; the repo
   carries no framework files by design, so do **not** create any.
The repository's own `GEMINI.md` / `AGENTS.md` remain **authoritative** for repository constraints; the
framework layer complements them, never overrides them.

> Note: Opening the marker adds repo-specific context when the agent follows this instruction.

## Framework defaults
- The framework (agents + knowledge library) lives at: `__BAILIWICK__`
- Open agent roles and knowledge files directly by path (e.g.
  `__BAILIWICK__/agents/implementer.md`); nothing is copied into the repo.
- Knowledge index: `__BAILIWICK__/knowledge/INDEX.md` — load on-demand, max 5 content
  files per task. Orchestration is proportional: route substantial/multi-step work through Lead;
  handle trivial edits inline.
- Engineering defaults (always-on): before writing, scan the repo + KB for reusable code/modules to
  extend rather than recreate; apply least privilege, CAF naming + labels, pinned versions, no
  secrets, plan-before-apply, drafts for review. Full baseline:
  `__BAILIWICK__/knowledge/context/engineering-defaults.md`

## Non-negotiables (runtime-enforced under Antigravity by PreToolUse in ~/.gemini/config/hooks.json; uphold them regardless)
- **High-impact actions never run on your initiative — and even when instructed, re-confirm in the
  moment that this specific execution is really intended**: `terraform`/`terragrunt apply`|`destroy`;
  kubectl/helm mutations; gcloud/gsutil/az/aws mutating verbs (delete/destroy/update/patch/rm);
  recursive/forced `rm`; `git merge`; repo deletion. Validation-only commands (plan/validate/fmt,
  `--dry-run`, read-only CLI) run freely.
- `git commit`/`push`/PR opening only on a clear user go-ahead — never your initiative. Never add AI
  attribution signatures (Co-Authored-By, "Generated with …", 🤖) to commit/PR messages unless
  explicitly wanted.
- Never modify `__BAILIWICK__/knowledge/` without the human gate (`/curate`, run under Claude Code).
- `.bailiwick-outputs/raw/` is unsanitised capture staging — never commit it. All outputs are drafts for review.

> Enforcement reality: under **Antigravity**, the bailiwick guardrail is wired as a `PreToolUse`
> hook in `~/.gemini/config/hooks.json` (installed by `bootstrap --install-tools`) returning
> `decision: "force_ask"` for ADR-006 tiers — always prompts, ignoring any cached "Always Allow"
> grant (plain `ask` would honour it); it self-gates to wired repos.

## Quality Workflow stages as Antigravity subagents (ADR-010)
The `bailiwick-*` stage adapters are generated into `~/.gemini/agents/` (the legacy Gemini CLI
path). Antigravity reads custom subagents from `~/.gemini/config/agents/` instead, which is not
generated yet — until it is, open the stage role files under `__BAILIWICK__/agents/` directly.
Run independent stages in parallel,
dependent stages in order; each stage's final report must carry its outputs and knowledge signals.

## Capture (Automatic under Antigravity via Stop hook)
Under Antigravity, raw transcripts are captured **automatically** upon session completion via the
`Stop` hook in `~/.gemini/config/hooks.json`. When running in an environment without active hook
support, write a manual session output file per the agent-output template to `.bailiwick-outputs/`
(seeded) or `~/.bailiwick/captures/<repo-key>/` (shadow) so the Memory stage can process it during `/curate`.
<!-- END bailiwick -->
