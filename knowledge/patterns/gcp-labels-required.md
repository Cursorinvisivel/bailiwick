---
id: gcp-labels-required
type: pattern
tags: [gcp, labels, tags, finops]
confidence: high
last_validated: 2026-06-04
supersedes: []
scope: generic
---

# Pattern: Required GCP Labels

## Mandatory labels on all resources

| Label | Accepted values | Example |
|---|---|---|
| env | dev, stg, prd, shr | prd |
| owner | team or project identifier | platform-team |
| cost-center | cost centre code | cc-001 |
| managed-by | terraform (always) | terraform |

## Recommended labels

| Label | Purpose | Example |
|---|---|---|
| component | platform component | gke, storage, network |
| application | specific application | api-gateway |
| version | application version | v1-2-0 |

## Terraform implementation — locals.tf

```hcl
locals {
  common_labels = {
    env         = var.environment
    owner       = var.owner
    cost-center = var.cost_center
    managed-by  = "terraform"
  }
}
```

## Rules
- Lowercase, hyphens allowed, no spaces
- Keys and values maximum 63 characters
- Never sensitive information in labels
- Labels applied to root resource and child resources where supported

## Related
- [CAF naming taxonomy](caf-naming-taxonomy.md)
- [Engineering defaults](../context/engineering-defaults.md)
