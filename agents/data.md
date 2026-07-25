# Data — domain context

## Scope
BigQuery datasets, tables, views, and access control; Dataflow jobs and pipelines;
NiFi and NiFiKop operator; data ingestion and transformation patterns.

Not in scope: GKE cluster setup → kubernetes.md | GCP IAM not data-specific → gcp.md

## Memory Hints
Pass these tags to the Memory stage based on what the task touches:

| Sub-area | Tags to load |
|---|---|
| NiFiKop / NiFi on GKE | kubernetes, nifikop, gke, operator, helm, webhook |
| WIF for pod auth (NiFi private clusters) | gcp, wif, kubernetes, oidc, jwks, private-cluster |
| GCP IAM for data resources | gcp, iam, security, least-privilege |
| BigQuery / Dataflow | gcp, bigquery, dataflow (check topics; use Cloud Research if absent) |

> Load topics selectively as the knowledge library grows for this domain.
> Do not pre-load all data topics at once. Load only what the specific task requires.

## Domain Checklist
Apply during generation and review:

- [ ] BigQuery: dataset location explicit, no default to US unless intentional
- [ ] BigQuery: `default_encryption_configuration` set for sensitive datasets
- [ ] BigQuery: access entries via IAM bindings — no legacy ACLs
- [ ] No SA key files for pipeline auth — Workload Identity or WIF preferred
- [ ] Operators (NiFiKop, etc.): review Terraform-owned CRD ordering + webhook readiness before any operator or CRD changes
- [ ] Dataflow: pipeline options externalised as variables, not hardcoded
- [ ] Data at rest: CMEK configured for regulated datasets
