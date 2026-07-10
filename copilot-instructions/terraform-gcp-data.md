# Copilot Instructions — Terraform GCP Data Platform

## Includes all patterns from $BAILIWICK/copilot-instructions/terraform-gcp.md

## Data Platform — Additional Patterns

### BigQuery
- Datasets with explicit location (EU by default)
- Expiration defined for temporary tables
- IAM at dataset level, not table level (unless justified exception)
- Required labels including `data-classification`

### Cloud Storage (data)
- Buckets with versioning enabled for critical data
- Lifecycle rules for cost management
- Uniform bucket level access always
- Minimum retention defined for regulated data

### Secret Manager
- Use for all data access credentials
- Automatic rotation where supported by the service
- Audit logs enabled for secret access

## Data Classification Labels
```hcl
data-classification = "public" | "internal" | "confidential" | "restricted"
```
