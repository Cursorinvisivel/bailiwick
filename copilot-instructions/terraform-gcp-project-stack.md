# Copilot Instructions — Terraform GCP Project Stack

> Use this template for **project/deployment repos** (environment stacks with multiple interacting resources).
> For reusable Terraform modules, use `terraform-gcp.md` instead.

## Absolute Rules (Non-Negotiable)

> **NEVER commit or push code autonomously.**
> All changes are part of an interactive workflow and must be reviewed by the user first.

> **NEVER run destructive or state-mutating commands without explicit request.**
> Do not run `terraform apply`, `terraform destroy`, `terraform import`, `terraform state rm/mv`, `terraform taint`, or any command that provisions, mutates, or deletes real resources.

> **By default, only safe Terraform operations.**
> Allowed by default: `terraform plan`, `terraform refresh`, `terraform validate`, `terraform fmt`, `terraform show`, `terraform state list`.

> **Never change backend, provider impersonation, or remote state configuration without explicit approval.**

These rules override all other guidance in this file.

---

## Framework (Bailiwick)

Agents and the knowledge library live in `$BAILIWICK`
(`/path/to/bailiwick`).
For agent roles and task delegation, see `AGENTS.md` in this repo.
Open agent/knowledge files by path from `$BAILIWICK` on demand — nothing is copied in.

---

## 1. Scope

> **Fill in:** What this repo manages, and explicitly what it does NOT manage.
> The "does NOT manage" list prevents agents from inventing resources that belong elsewhere.

This repository manages Terraform-based GCP infrastructure for [project / environment].

Manages:
- [Resource A]
- [Resource B]

Does **not** manage:
- [Resource X — lives in repo Y]
- [Resource Z — managed manually / out of scope]

Default assumption: Google Cloud, Terraform >= 1.5, primary region `europe-west1`.

---

## 2. Authoritative Files

> **Fill in:** One row per significant file. List the key `locals`, variables, and data sources each file owns.
> Agents use this map to know where to make changes without reading every file.

| File | Owns |
|---|---|
| `providers.tf` | Backend bucket and prefix, impersonation SA, provider version, `default_labels` |
| `variables.tf` | All input variable definitions and defaults |
| `data.tf` | All data sources and shared locals |
| `main.tf` / `[domain].tf` | [Domain-specific resources] |
| `iam.tf` | IAM bindings and service accounts |
| `outputs.tf` | All outputs (mark sensitive ones with `sensitive = true`) |

Key variables (use exact names — do not rename):
- `[variable_name]` — [what it controls]
- `[variable_name]` — [what it controls]

---

## 3. Existing Patterns — Use Exact Names

> **Fill in:** Resource names, local keys, module source refs, identifiers that must be preserved.
> Agents must never invent new names — they can break `for_each` keys, state references, and DNS records.

- Terraform SA: `tf-[short]@[project-id].iam.gserviceaccount.com`
- State bucket: `[bucket-name]`, prefix: `[project-id]`
- VPC/subnet names: `[names]`
- Key resource identifiers: `[names — especially immutable fields like instance keys]`
- Module source: `git::https://github.com/[org]/[repo].git?ref=[version]`
- Variable naming language: [your team's language] — maintain the existing style

---

## 4. Operational Workflow

Authentication: `gcloud auth application-default login` — the provider then impersonates the SA.
If Terraform init is required, confirm with the user first (backend access may need credentials).

Allowed commands (safe, non-destructive):
```
terraform plan
terraform refresh
terraform validate
terraform fmt
terraform show
terraform state list
```

Always show plan output to the user before any decision to apply. Never run apply autonomously.

Validation chain before finalising changes:
1. `terraform fmt -recursive`
2. `terraform init -backend=false` (provider/module validation without backend)
3. `terraform validate`
4. `terraform plan` (requires credentials — report blocker if unavailable)

---

## 5. CI/CD Footprint

> **Fill in:** List every pipeline file and whether it is authoritative for Terraform lifecycle.
> This prevents agents from inferring deployment intent from legacy or unrelated pipelines.

| File | Purpose | Authoritative for Terraform? |
|---|---|---|
| `[security-scan pipeline]` | Security scans (secret/IaC/SCA/SAST scanners) + findings import | No (scans only) |
| `[delivery pipeline]` | [Helm / other non-Terraform delivery] | **No** — not Terraform lifecycle |
| `[deploy pipeline]` | [deployment] | **No** — not Terraform lifecycle |
| `[Jenkinsfile / GitHub Actions workflow]` | [Purpose] | Yes/No |

Do not run pipeline actions (`04`, `05`, or any deploy step) autonomously.

---

## 6. Practical Change Guide

> **Fill in:** Domain-specific instructions for the most common change types.
> Each entry should name the exact file(s) to edit and flag cross-file dependencies.

### Add / modify [Domain A, e.g. Cloud SQL instance]
1. Edit `[file].tf` / `[file].auto.tfvars` — update the `[map/variable]` field
2. Preserve [cross-file dependency or naming constraint]
3. Validate with `terraform plan` and review with user before apply

### Add / modify [Domain B, e.g. IAM binding]
1. Edit `iam.tf` — update `local.[iam_map]`
2. Confirm the `role||member` key pattern for `for_each` uniqueness
3. Flag any privilege expansion for user review

### Add a new workload / namespace
1. [Step 1 — file + field]
2. [Step 2 — downstream impact]
3. [Step 3 — validation]

### Change networking / firewall
1. [Step 1]
2. Flag blast radius: [what else may be affected]

### Change secrets / certificates
1. [Step 1]
2. Verify `sensitive = true` on outputs that expose secret material

---

## 7. Language and Source of Truth

- If there is a mismatch between README and `*.tf` code: **`*.tf` is the source of truth**.
- If there is a mismatch between README and `*.auto.tfvars`: **`*.tfvars` is the source of truth for values**.
- Non-Terraform pipeline files are not authoritative for the Terraform lifecycle.
- When a structural infrastructure change is made, propose a README update in the same task.
- Variable and comment language: [your team's language] — maintain the existing style; do not mix.

---

## Security and Blast Radius Checklist

Before implementing any change, verify:
- [ ] No secrets or project IDs hardcoded in `.tf` files (use variables or data sources)
- [ ] IAM changes follow least privilege — no primitive roles on production workloads
- [ ] Resource renames or key changes in `for_each` maps will cause destroy+recreate — flag explicitly
- [ ] Immutable field changes (e.g. Cloud SQL instance tier, zone) cause replacement — flag explicitly
- [ ] Import blocks for existing resources are preserved unless user explicitly asks to refactor state
- [ ] Sensitive outputs are marked `sensitive = true`

## GCP Review Focus

- IAM scope and service account usage
- Workload Identity bindings (KSA ↔ GSA)
- VPC/subnet/firewall impact
- Cloud SQL connectivity model and DR region
- Secret Manager access patterns
- Cloud Armor policy attachment on public-facing backends
- Cost-impacting changes (node pools, SQL tiers, multi-region resources)
