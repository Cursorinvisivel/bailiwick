---
id: engineering-defaults
type: context
tags: [best-practices, defaults, terraform, cloud, gcp, security, code-quality, reuse, intelligence]
confidence: high
last_validated: 2026-07-05
supersedes: []
scope: generic
---

# Engineering Defaults

> The framework's always-on operating baseline for **every** task, across all tools (Claude Code,
> Codex, Copilot). Each tool loads this via its complement (CLAUDE.local.md / .bailiwick.local.md / the Copilot
> instructions). Authored standard — points to canonical depth rather than restating
> it; load the referenced patterns/agents for full detail.

## 0. Working intelligence — the decision ladder (BEFORE writing anything)
The most valuable habit: **understand and reuse before you create.** Work down this ladder for the
concern at hand (an IAM grant, a database, a bucket, a service account, a firewall rule, …) and
**stop at the first rung that fits** — a new standalone resource is the last resort, not the first move:

1. **Does this need to exist at all?** Challenge the requirement (YAGNI): already satisfied by an
   existing resource/behaviour, or speculative ("might need it later")? If speculative — don't
   build it; say so.
2. **An existing iteration construct that already creates this kind of thing** — a `for_each`/
   `count`/`dynamic` block, or the `map`/`list`/`locals`/`*.tfvars` collection driving one (e.g. an
   IAM bindings map keyed by `role||member`, an instances map). **Add an entry to it** — never a
   standalone resource alongside it.
3. **A module that wraps the concern** — your org's own published/shared modules first, then
   local/registry modules the repo already references, or a sibling repo's — call or extend,
   don't re-implement.
4. **A provider-native feature or established root-module loop/convention** for this resource
   type — use it; don't hand-roll what the provider or an existing convention gives you.
5. **Only then: author the minimum new resource/module that fully solves the task** — and say so
   explicitly, naming what you searched (the map/module/loop) and why nothing could absorb it.

**Minimal never means below the completeness baseline** — the ladder trims *scope*, not standards:
required labels, typed+validated variables, documented outputs, pinned versions, least-privilege
IAM, and `lifecycle` protection on stateful resources are never "boilerplate" to skip (§1–§4).

Always, at every rung:
- **Consult the knowledge library.** Read `INDEX.md`, descend the relevant domain sub-index, and load
  the matching topics/patterns before generating. Don't re-derive what the KB already knows.
- **Match the surroundings.** Read neighbouring files and mirror their naming, structure, and idioms —
  new code should read like the code already there.
- **Proportional effort.** Smallest change that fully solves the task; don't gold-plate, don't reinvent.

## 1. Cloud infrastructure
- **Least privilege by default** — explicit, scoped IAM; no broad/primitive roles (`patterns/gcp-iam-conventions.md`).
- **Naming + labels** — CAF taxonomy `{org}-{type}-{workload}-{env}-{region}-{instance}`
  (`patterns/caf-naming-taxonomy.md`); required labels on every resource (`patterns/gcp-labels-required.md`).
- **State + environments** — remote state, per-environment isolation, no shared mutable state
  (`patterns/gcp-backend-gcs-pattern.md`); environments parameterised, never hardcoded.
- **Identity** — prefer workload identity / keyless over service-account keys (`patterns/gcp-gke-workload-identity.md`).

## 2. Terraform
- **Structure + interface** — follow `patterns/terraform-module-structure.md` and
  `patterns/terraform-variable-conventions.md`; clear typed variables, documented outputs.
- **Pin versions** — provider and module versions pinned; no floating `latest`.
- **No secrets in code or state inputs** — source from Secret Manager / ESO, never literals.
- **Verify a file is actually ignored before trusting it** — never rely on an in-file "this is
  gitignored" header comment. Stock Terraform `.gitignore`s often ship the `*.tfvars` rule **commented
  out**, so a `terraform.tfvars` with real org/billing/project IDs gets tracked and pushed. Before
  committing, confirm with `git ls-files --error-unmatch <file>` (tracked?) and
  `git cat-file -e origin/main:<file>` (already published?); if exposed, rotate + scrub history.
- **Plan before apply; never auto-apply/destroy** — those are human-gated, out-of-band actions.
- **Reuse modules** — prefer an existing published/shared module over a bespoke one; extend it, don't fork-and-drift.

## 3. Code quality
- **Readable + consistent** — match the surrounding style; clarity over cleverness.
- **Small, focused changes** — one concern per change; easy to review and revert.
- **DRY** — reuse before adding; factor duplication into a shared module/local/helper.
- **Validate** — `terraform fmt` + `validate`, then `plan`; run the project's linters/tests where they exist.
- **Comment only the non-obvious** — no narration of obvious code, no dead/commented-out code.

## 4. Security
- **No secrets anywhere** — not in code, variables, logs, or commits; rotate if exposed.
- **Least privilege + CIS** — minimal IAM, network egress controls; align with the Security Review
  agent's CIS checklist (`agents/security-review.md`).
- **No side-effecting commands** — no `terraform apply`/`destroy`, no mutating cloud CLI, no
  `git commit`/`push` without explicit approval.
- **Sensitive data** — never commit secrets, credentials, or identifying data; keep them out of code,
  inputs, and logs (rotate if exposed). All outputs are **drafts for human review**.

## References (canonical depth — do not restate, load on demand)
- Agents: `agents/lead.md`, `implementer.md`, `quality.md`, `security-review.md`, domain agents (`gcp.md`, `kubernetes.md`, …)
- Patterns: `caf-naming-taxonomy`, `gcp-iam-conventions`, `gcp-labels-required`, `terraform-module-structure`, `terraform-variable-conventions`, `gcp-backend-gcs-pattern`, `gcp-gke-workload-identity`, `code-review-rubric`

## Related
- [CAF naming taxonomy](../patterns/caf-naming-taxonomy.md)
- [Required GCP labels](../patterns/gcp-labels-required.md)
- [GCP IAM conventions](../patterns/gcp-iam-conventions.md)
- [Code review rubric](../patterns/code-review-rubric.md)
- [Terraform module structure](../patterns/terraform-module-structure.md)
