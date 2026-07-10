---
id: gcp-iam-conventions
type: pattern
tags: [gcp, iam, security, least-privilege]
confidence: high
last_validated: 2026-06-28
supersedes: []
scope: generic
---

# Pattern: GCP IAM Conventions

## Fundamental Rules

### Never use
- `roles/owner` on workloads or application service accounts
- `roles/editor` on any production resource
- Bindings to individual users on production resources (use groups)

### Always prefer
- Specific predefined roles over primitive roles
- Bindings at the lowest necessary level (resource > project > organisation)
- IAM conditions when access should be temporary or context-restricted

## Resource Manager role boundaries (non-obvious)
- `roles/resourcemanager.folderAdmin` covers the full **folder** lifecycle (create/delete/update/move/
  setIamPolicy) but does **NOT** include `projects.create` or `projects.delete`. A minimal
  "build and tear down a subtree" SA grant is therefore
  `folderAdmin` + `resourcemanager.projectCreator` + `resourcemanager.projectDeleter` +
  `resourcemanager.projectIamAdmin` (each is a separate role; `projectDeleter` exists only on its own).
- **IAM is additive/union** — a binding whose condition never matches simply grants nothing and does
  **not** error. So a misdesigned "exclude this resource" condition fails *silently*.
- **IAM allow-policy conditions ignore `resource.name` for Resource Manager** (projects are documented
  as unsupported; folders are absent from the supported tables). You cannot protect a folder from its
  managing SA with a condition (Resource Manager ignores `resource.name` in allow-conditions, so an anchor-folder structural pattern is needed instead).

## Billing delegation
- To **grant** `roles/billing.user` to a Terraform/bootstrap SA, the human running the bootstrap needs
  `roles/billing.admin` on the billing account — `billing.user` alone cannot set billing-account IAM.
- Grant `billing.user` on the **billing account itself**, not at the org node.

## Service Accounts

### Creation
- One service account per workload/application — never share
- Name follows convention: `{env}-{region}-sa-{purpose}`
- Description mandatory

### Authentication
- GKE: Workload Identity always — never key files in pods
- Cloud Run: dedicated service account per service
- CI/CD: Workload Identity Federation — never long-lived service account keys

### Keys
- Avoid service account keys whenever possible
- If unavoidable: mandatory rotation, Secret Manager, never in code

## Terraform Bindings

### Reuse the repo's binding pattern first
Most repos already grant IAM through a **data-driven collection**, not one resource per binding —
typically a `for_each` over a `map`/`locals` keyed for uniqueness (commonly `role||member`), or a
`*.tfvars` list. **Before adding a binding, find that collection and add an entry to it**; author a
standalone resource only when the repo has no such pattern. Adding a key is additive — Terraform
creates just the new binding and touches none of the existing ones (zero blast radius).
```hcl
# Established factory — add a key, don't add a resource.
locals {
  iam_bindings = {
    "roles/run.invoker||serviceAccount:${google_service_account.app.email}" = {
      role   = "roles/run.invoker"
      member = "serviceAccount:${google_service_account.app.email}"
    }
    # ← new grants go here
  }
}

resource "google_project_iam_member" "bindings" {
  for_each = local.iam_bindings
  project  = var.project_id
  role     = each.value.role
  member   = each.value.member
}
```

### Standalone member — only when no collection exists (still additive)
```hcl
resource "google_project_iam_member" "example" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.app.email}"
}
```

### Avoid (authoritative — replaces existing bindings)
```hcl
# Use only when full binding management is intentional
resource "google_project_iam_binding" "example" { ... }
```

## Auditing
- Enable audit logs for Admin Activity and Data Access in production
- Alerts for privileged role bindings

## Related
- [GKE Workload Identity](gcp-gke-workload-identity.md)
- [Code review rubric](code-review-rubric.md)
- [CAF naming taxonomy](caf-naming-taxonomy.md)
- [Engineering defaults](../context/engineering-defaults.md)
