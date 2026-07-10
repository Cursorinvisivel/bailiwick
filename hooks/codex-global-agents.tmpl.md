<!-- BEGIN bailiwick (managed block — do not edit by hand; refreshed by bootstrap.sh --install-tools) -->
# bailiwick — private operator layer (Codex global)

> This block lives in your personal `~/.codex/AGENTS.md`. Codex loads it FIRST, before any
> repository `AGENTS.md`. A repo's own `AGENTS.md` is loaded afterwards and therefore **takes
> precedence** — project constraints always win over this personal layer. Nothing here is shared
> with any repository or colleague; it is local to this machine.

## Per-repository activation (does NOT shadow the team's AGENTS.md)
Activate the framework defaults below for the current repository when **either** condition holds:
1. **Seeded:** the repo contains a file named **`.bailiwick.local.md`** — read it before beginning
   substantive work and treat it as **private operator guidance** (project context + a pointer to the
   framework).
2. **Shadow — no in-repo file** (FRAMEWORK.md §7.1): the environment variable `BAILIWICK_SHADOW=1`
   is set, **or** the repository root (the `git rev-parse --show-toplevel` path) is listed in
   `~/.bailiwick/allowlist` (one absolute path per line; `#` comments). There is no marker to read —
   apply the framework defaults directly; the repo carries no framework files by design, so do **not**
   create any.
In all cases the repository's own `AGENTS.md` remains **authoritative** for repository constraints,
build/test commands, conventions, and security — the framework layer complements it, never overrides it.

> Why a neutral marker (`.bailiwick.local.md`) and not a repo-root instruction file: Codex loads
> at most ONE instruction file per directory, so a framework file at the repo root would SUPPRESS the
> team's own `AGENTS.md`. `.bailiwick.local.md` is not a recognized Codex instruction filename, so
> it never shadows anything — it is read only because this global instruction tells you to.

## Framework defaults (apply when activated per above — seeded marker or shadow allowlist/env)
- The framework (agents + knowledge library) lives at: `__BAILIWICK__`
- Open agent roles and knowledge files directly by path from there (e.g.
  `__BAILIWICK__/agents/implementer.md`); nothing is copied into the repo.
- Knowledge index: `__BAILIWICK__/knowledge/INDEX.md` — load on-demand, max 5 content
  files per task. Orchestration is proportional: route substantial/multi-step work through Lead;
  handle trivial edits inline.
- Engineering defaults (always-on): before writing, scan the repo + KB for reusable code/modules to
  extend rather than recreate; apply least privilege, CAF naming + labels, pinned versions, no
  secrets, plan-before-apply, drafts for review. Full baseline:
  `__BAILIWICK__/knowledge/context/engineering-defaults.md`

## Non-negotiables (runtime-enforced by the bailiwick PreToolUse guardrail hook once trusted in the `codex` CLI; observe as policy regardless)
- **High-impact actions never run on your initiative — and even when instructed, re-confirm in the
  moment that this specific execution is really intended**: `terraform`/`terragrunt apply`|`destroy`;
  kubectl/helm mutations; gcloud/gsutil/az/aws mutating verbs (delete/destroy/update/patch/rm);
  recursive/forced `rm`; `git merge`; repo deletion. Validation-only commands (plan/validate/fmt,
  `--dry-run`, read-only CLI) run freely.
- `git commit`/`push`/PR opening only on a clear user go-ahead — never your initiative. Never add AI
  attribution signatures (Co-Authored-By, "Generated with …", 🤖) to commit/PR messages unless
  explicitly wanted.
- Never modify `__BAILIWICK__/knowledge/` without the human gate (`/curate`).
- `.bailiwick-outputs/raw/` is unsanitised capture staging — never commit it. All outputs are drafts for review.

> Enforcement: the bailiwick guardrail is wired as a Codex `PreToolUse` hook (managed block in
> `~/.codex/config.toml`, installed by `bootstrap --install-tools`). Codex has no confirmation
> dialog, so guarded actions are **denied** with the remedy in the reason; `BAILIWICK_BREAK_GLASS=1`
> permits once (logged). The hook runs only after a one-time trust — Codex prompts on first fire in the
> `codex` CLI (the VS Code extension does not surface it; trust persists in `~/.codex/config.toml`)
> and self-gates to bailiwick-wired repos — these rules remain your policy baseline either way.
<!-- END bailiwick -->
