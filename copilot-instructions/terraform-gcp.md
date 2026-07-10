# Copilot Instructions — Terraform GCP

## Absolute Rules (Non-Negotiable)

> **NEVER commit or push code autonomously.**
> All changes are part of an interactive workflow and must be reviewed by the user first.

> **NEVER run destructive or state-mutating commands without explicit request.**
> Do not run `terraform apply`, `terraform destroy`, or any command that provisions, mutates, or deletes real resources.

> **By default, only safe Terraform operations.**
> Allowed by default: `terraform init`, `terraform fmt`, `terraform validate`, `terraform plan`, `terraform show`, `terraform state list`.

---

## Framework (Bailiwick)
- Agents and the knowledge library live in `$BAILIWICK`
  (`/path/to/bailiwick`).
- For agent roles and task delegation, see `AGENTS.md` in this repo.
- Open agent/knowledge files by path from `$BAILIWICK` on demand — nothing is copied in.

## Context and Baseline
- This repository manages infrastructure as code with Terraform for GCP.
- Identify relevant modules/files before editing; prefer minimal, targeted changes.
- Preserve existing patterns unless the user asks to change them.

## Naming and Conventions
- Format: `{env}-{region}-{service}-{purpose}`
- Environments: dev, stg, prd, shr
- Regions: euw1 (europe-west1), euw4 (europe-west4), use1 (us-east1)
- Separator: hyphen. Never underscore in GCP resource names.
- Do not invent naming conventions — if ambiguous, clarify before implementing.

## Provider and Versions
- Keep Terraform and provider versions explicitly constrained.
- Do not add/update providers without pinned versions and a clear reason.

## GCP Labels (mandatory on all resources)
```hcl
labels = {
  env         = var.environment
  owner       = var.owner
  cost-center = var.cost_center
  managed-by  = "terraform"
}
```

## IAM
- Use `google_project_iam_member` (additive) — never `iam_binding` without justification
- No primitive roles (owner, editor) on workloads
- One service account per workload

## Backend GCS
```hcl
terraform {
  backend "gcs" {
    bucket = "example-terraform-state"
    prefix = "{environment}/{component}"
  }
}
```

## Variables
- All with `description` and `type`
- Validation blocks for environment and region
- `sensitive = true` for secrets
- Never hardcode project_id — use a variable

## Validation Workflow
Before finalising changes, run when possible:
1. `terraform fmt -recursive`
2. `terraform init -backend=false`
3. `terraform validate`
4. `tflint`
5. `tfsec` or `checkov`

If commands are blocked (credentials/backend), report the blocker and the exact next commands.

## State, Plan, and Blast Radius Safety
- Do not change backend/state location without explicit approval.
- Do not run manual state operations unless explicitly requested.
- Never remove/rename resources without flagging dependency impact and blast radius.
- Summarise plan by create/update/delete/replace counts.
- Explicitly highlight replacements and their likely causes (immutable field changes).
- Request confirmation before high-impact or potentially destructive paths.

## Security, Drift, and Cost
- Flag least-privilege deviations and risky public exposure.
- Highlight broad IAM grants and open network exposure.
- Flag changes with likely cost impact and ask for cost vs. resilience preference when relevant.

## Cloud-Specific Review Focus — GCP
- IAM bindings and org policy
- VPC/firewall exposure
- Service account usage
- GKE workload identity
- Secret Manager access patterns

## Communication Expectations
- Explain what changed, why, and expected infrastructure impact.
- Separate confirmed facts from assumptions.
- Ask concise clarifying questions when uncertainty affects safety.
- Keep outputs actionable and ready to execute.

## Absolute Prohibitions
- Never hardcode project_id or credentials in code
- Never terraform apply or destroy without explicit approval
- Never primitive roles on production workloads

## Project-Specific Context (fill in)
- Environments:
- Module layout:
- Naming standards (exceptions to pattern):
- CI/CD validation steps:
- Ownership:
