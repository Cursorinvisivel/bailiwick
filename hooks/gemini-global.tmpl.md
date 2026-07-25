<!-- BEGIN bailiwick (managed block — do not edit by hand; refreshed by bootstrap.sh --install-tools) -->
# bailiwick — private operator layer (Gemini global)

> This block lives in your personal `~/.gemini/GEMINI.md`. Gemini Code Assist (VS Code agent mode)
> and Gemini CLI load it as the **global context file**, before any project `GEMINI.md`. A repo's own
> `GEMINI.md` is loaded afterwards and **takes precedence** — project constraints win over this
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

> Note: the VS Code agent has no guaranteed loader for an arbitrary filename, so the framework
> defaults below are stated **here** (in the always-loaded global file) and do not depend on the agent
> choosing to open the marker. Opening the marker adds repo-specific context when the agent follows
> this instruction.

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

## Non-negotiables (runtime-enforced under Gemini CLI by the bailiwick BeforeTool guardrail hook; policy in the VS Code agent — uphold them regardless)
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

> Enforcement reality: under **Gemini CLI** the bailiwick guardrail is wired as a `BeforeTool`
> hook (`~/.gemini/settings.json`, installed by `bootstrap --install-tools`) returning
> `decision: "ask"` — the same forced confirmation as Claude Code; it self-gates to wired repos.
> The **VS Code Code Assist agent's** hook support is unverified, so there the controls are
> (1) **do not enable** `geminicodeassist.agentYoloMode` — keep the approval dialog — and (2) these
> policies. `excludeTools` is, per Google's own docs, simple string matching that "can be easily
> bypassed" and "is not a security mechanism" — a best-effort speed-bump only.

## Quality Workflow stages as Gemini subagents (ADR-010)
The `bailiwick-*` subagents in `~/.gemini/agents/` are the Bailiwick Quality Workflow stages.
Gemini may **auto-delegate** to them on description match for substantial multi-step work; the
user (or you) can **force** a stage with `@bailiwick-<stage>` (e.g. `@bailiwick-quality review
this module`). Run independent stages in parallel, dependent stages in order; each stage's final
report must carry its outputs and knowledge signals. Mechanics: see the official Gemini CLI
subagents docs.

## Capture (manual under Gemini — no session hooks)
Gemini has no Stop/SessionEnd hook in VS Code, so capture is not automatic. When you finish a
substantive session, **write a session output file** (a short markdown summary: what changed,
decisions, pitfalls, follow-ups) per the agent-output template — the Memory stage reads it during
`/curate`. Location depends on activation mode:
- **Seeded repo:** write to `.bailiwick-outputs/` in the repo.
- **Shadow repo** (repo must stay untouched; FRAMEWORK.md §7.1): write the `.md` at the **top** of a
  folder under `~/.bailiwick/captures/` — `/curate` sweeps `~/.bailiwick/captures/*/*.md`, so it must
  sit directly in the folder, **not** in a `raw/` subdir (which is scanned for `.jsonl` only). To keep
  it beside this repo's automatic Claude Code captures, drop it in the staging folder Claude Code
  already created for the repo (named `<repo>-<short-hash>/`, keyed by git remote); if none exists yet,
  any stable folder name works. Do **not** create `.bailiwick-outputs/` in the repo.
Do **not** attempt to run the Claude Code capture hook script by hand; it expects a harness payload and
cannot be invoked standalone.
<!-- END bailiwick -->
