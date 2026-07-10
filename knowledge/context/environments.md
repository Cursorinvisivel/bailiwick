---
id: environments
type: context
tags: [environments, terraform, workspaces]
confidence: low
last_validated: 2026-06-25
supersedes: []
scope: generic
---

# Environments and Backends

## Standard environments

| Abbreviation | Name | Purpose |
|---|---|---|
| dev | Development | Development and local testing |
| stg | Staging | Pre-production validation |
| prd | Production | Production |
| shr | Shared | Shared resources (networking, base IAM) |

## GCS Backend — standard

Bucket: `example-terraform-state`

Prefix by environment and component: `{environment}/{component}`

Examples:
- `dev/gke-platform`
- `stg/networking`
- `prd/cloud-run-api`
- `shr/iam`

## Environment separation

Each environment lives in a separate GCP project.
Do not use Terraform workspaces for environment separation.
Use distinct prefixes per environment in the same state bucket.

## Environment promotion

dev → stg → prd via CI/CD pipeline.
Never promote state — redeploy with the target environment's tfvars.

## Related
- [CAF naming taxonomy](../patterns/caf-naming-taxonomy.md)
- [GCS Terraform backend](../patterns/gcp-backend-gcs-pattern.md)
- [Terraform variable conventions](../patterns/terraform-variable-conventions.md)
