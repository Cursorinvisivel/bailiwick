---
id: gcp-backend-gcs-pattern
type: pattern
tags: [terraform, state, backend, gcs]
confidence: high
last_validated: 2026-06-04
supersedes: []
scope: generic
---

# Pattern: GCS Backend for Terraform

## Base configuration

```hcl
terraform {
  backend "gcs" {
    bucket = "example-terraform-state"
    prefix = "{environment}/{component}"
  }
}
```

## Prefix convention
`{environment}/{component}`

Examples:
- `prd/gke-platform`
- `stg/networking`
- `shr/iam`
- `dev/cloud-run-api`

## State bucket — requirements
- Versioning enabled
- Uniform bucket level access
- Public access prevention enforced
- Version retention: minimum 30 days
- IAM: access restricted to CI/CD service accounts and authorised operators

## Workspaces
Do not use Terraform workspaces for environment separation.
Use distinct prefixes per environment in the same bucket.

## Initialisation
```bash
terraform init \
  -backend-config="bucket=example-terraform-state" \
  -backend-config="prefix=prd/component"
```

## Related
- [Terraform module structure](terraform-module-structure.md)
- [Terraform variable conventions](terraform-variable-conventions.md)
- [Environments](../context/environments.md)
