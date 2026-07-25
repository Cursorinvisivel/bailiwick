# GCP — domain context

## Scope
GCP resource lifecycle, IAM, VPC/networking, Cloud SQL, Storage, Secret Manager,
Cloud Scheduler, Workflows, service account design, resource labeling.

Not in scope: GKE workloads → kubernetes.md | Cloud Run/Functions → serverless.md | BigQuery/pipelines → data.md

## Memory Hints
Pass these tags to the Memory stage based on what the task touches:

| Sub-area | Tags to load |
|---|---|
| IAM / service accounts | gcp, iam, security, least-privilege |
| Naming | gcp, naming, conventions |
| Labels | gcp, labels, finops |
| Cloud SQL / proxy | gcp, cloud-sql, csql-proxy |
| Terraform backend | terraform, state, backend, gcs |
| SA impersonation | terraform, gcp, provider, impersonation |
| Environment scheduling | gcp, cloud-scheduler, workflows |
| Provider config | terraform, gcp, provider |

## Domain Checklist
Apply during generation and review:

- [ ] Labels: env, owner, cost-center, managed-by=terraform on every resource
- [ ] No primitive roles (owner, editor) on any workload
- [ ] No hardcoded project_id — always via variable
- [ ] Secrets in Secret Manager, never in plaintext or outputs
- [ ] `prevent_destroy = true` on Cloud SQL instances and data buckets
- [ ] Service account scoped to minimum required permissions
- [ ] `for_each` over `count` for any replicated resource
- [ ] Resource naming follows caf-naming-taxonomy.md (`{org}-{type}-{workload}-{env}-{region}-{instance}`)
