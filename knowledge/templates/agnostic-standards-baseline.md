# [Project / Repo Name]

> Baseline engineering guidance for this repository, **shared with the team**. Applies to AI coding
> assistants (Claude Code, Gemini, Codex, GitHub Copilot) and humans alike. Self-contained and tool-agnostic —
> edit freely. (This is the team's standard file; any private/framework wiring lives elsewhere.)
>
> **"Agnostic" here means tool/org-agnostic** — framework-neutral, portable across AI assistants and
> teams — **not cloud-agnostic.** The example standards below are Terraform/GCP-oriented; swap in
> your own stack's conventions.
>
> **Public-safe:** this file is committed and may be public. Keep it to **generic standards + only
> non-identifying context**. Do NOT put personal names, employer/client names, concrete cloud
> project/account IDs, state-bucket names, or internal hostnames here — those belong in the private,
> un-pushed complement, not a shared/public repo.

## Project context
- **Purpose:** [what this repo contains / does]
- **Stack:** [e.g. Terraform >= 1.5, provider google ~> 6; GKE / Cloud Run / Cloud SQL]
- **Environments:** [dev / stg / prd — identifiers]
- **State / backend:** [remote state location + layout]

## Working intelligence — before writing anything
- **Reuse before you create — work down this decision ladder and stop at the first rung that fits.**
  A brand-new standalone resource is the *last* resort, not the first move. For the concern at hand
  (e.g. an IAM grant, a database, a bucket, a service account, a firewall rule):
  1. **Does this need to exist at all?** Challenge the requirement (YAGNI): already satisfied by an
     existing resource/behaviour, or speculative ("might need it later")? If speculative — don't
     build it; say so.
  2. **An existing iteration construct that already creates this kind of thing** — a `for_each` /
     `count` / `dynamic` block, or the `map` / `list` / `locals` / `*.tfvars` collection that drives
     one (e.g. an IAM bindings map keyed by `role||member`, an instances map). If it exists, **add an
     entry to that collection** — do not write a standalone resource alongside it.
  3. **A module that wraps this concern** — a local module, a registry/published module the repo
     already uses, or one in a sibling repo — call or extend it rather than re-implementing.
  4. **A provider-native feature or established root-module loop/convention** for this resource
     type — use it; don't hand-roll what the provider or an existing convention gives you.
  5. **Only then: author the minimum new resource that fully solves the task** — and say so
     explicitly: name what you searched for (the map/module/loop) and why nothing could absorb it.
- **Minimal never means below the completeness baseline** — the ladder trims *scope*, not standards:
  required labels, typed+validated variables, documented outputs, pinned versions, least-privilege
  IAM, and `lifecycle` protection on stateful resources are never "boilerplate" to skip.
- **Read before you write.** Match the surrounding structure, naming, and idioms.
- **Proportional effort.** Smallest change that fully solves it; don't reinvent or gold-plate.

## Cloud infrastructure
- Least privilege by default — explicit, scoped IAM; no broad/primitive roles.
- Consistent resource naming + labels/tags (owner, environment, cost-centre) on every resource.
- Remote state, per-environment isolation; environments parameterised, never hardcoded.
- Prefer keyless / workload-identity auth over long-lived credentials.

## Terraform
- Clear module structure; typed variables, documented outputs.
- Pin provider and module versions; no floating `latest`.
- No secrets in code, variables, or state inputs — source them from a secrets manager.
- `plan` before `apply`; `apply`/`destroy` are deliberate, reviewed actions — never automatic.
- Reuse existing/published modules over bespoke ones; extend, don't fork-and-drift.

## Code quality
- Readable and consistent with the surrounding code; clarity over cleverness.
- Small, focused changes; one concern at a time.
- DRY — factor duplication into shared modules/locals/helpers.
- Validate: format + lint + the project's tests (for Terraform: `fmt`, `validate`, then `plan`).
- Comment only the non-obvious; no dead or commented-out code.

## Security
- Never commit secrets, credentials, or identifying data — keep them out of code, inputs, and logs (rotate if exposed).
- Least privilege everywhere; restrict network egress; follow CIS-style hardening.
- No side-effecting commands (cloud mutations, `apply`/`destroy`, `git push`) without explicit human approval.
- Treat generated changes as **drafts for human review**.
