---
id: terraform-module-structure
type: pattern
tags: [terraform, module, structure, iac]
confidence: high
last_validated: 2026-06-28
supersedes: []
scope: generic
---

# Pattern: Terraform Module Structure

## Mandatory structure

```
modules/[module-name]/
├── main.tf          # primary resources
├── variables.tf     # all input variables
├── outputs.tf       # all relevant outputs
├── versions.tf      # terraform and provider version constraints
├── locals.tf        # local values and transformations
└── README.md        # generated via docs agent
```

## versions.tf — template

```hcl
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"   # track the current provider major; pin per module
    }
  }
}
```

## variables.tf — conventions
- All variables with description
- Validation blocks for critical inputs
- Never `default = null` on required variables — omit the default
- Sensitive variables with `sensitive = true`

## outputs.tf — conventions
- Export IDs and names of all primary resources
- Export `self_link` when available
- Description on all outputs

## locals.tf — conventions
- Use for combined label construction
- Use for naming transformations
- Do not use for complex business logic

## Related
- [Terraform variable conventions](terraform-variable-conventions.md)
- [GCS Terraform backend](gcp-backend-gcs-pattern.md)
- [GKE Workload Identity](gcp-gke-workload-identity.md)
