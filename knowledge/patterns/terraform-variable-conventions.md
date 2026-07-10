---
id: terraform-variable-conventions
type: pattern
tags: [terraform, variables, inputs, outputs]
confidence: high
last_validated: 2026-06-04
supersedes: []
scope: generic
---

# Pattern: Terraform Variable Conventions

## variables.tf

### Required on all variables
- `description` — clear, in English
- `type` — explicit, never omitted

### Validation blocks — use when
- Environment values (dev/stg/prd)
- Region names
- Inputs that affect security

```hcl
variable "environment" {
  description = "Deployment environment"
  type        = string

  validation {
    condition     = contains(["dev", "stg", "prd", "shr"], var.environment)
    error_message = "Environment must be dev, stg, prd, or shr."
  }
}
```

### Required variables without default
```hcl
variable "project_id" {
  description = "GCP Project ID"
  type        = string
  # no default — required
}
```

### Sensitive variables
```hcl
variable "db_password" {
  description = "Database password"
  type        = string
  sensitive   = true
}
```

## outputs.tf

### Required
- `description` on all outputs
- Export ID and name of primary resources
- Export `self_link` when available

```hcl
output "service_account_email" {
  description = "Service account email address"
  value       = google_service_account.main.email
}
```

## Related
- [Terraform module structure](terraform-module-structure.md)
- [GCS Terraform backend](gcp-backend-gcs-pattern.md)
- [Environments](../context/environments.md)
