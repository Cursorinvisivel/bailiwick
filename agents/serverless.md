# Serverless — domain context

## Scope
Cloud Run services and jobs, Cloud Functions gen1/gen2, Eventarc, Pub/Sub-driven pipelines,
event-driven patterns.

Not in scope: GKE workloads → kubernetes.md | Data processing at scale → data.md

## Memory Hints
Pass these tags to the Memory stage based on what the task touches:

| Sub-area | Tags to load |
|---|---|
| Cloud Run / serverless general | gcp, serverless, cloud-run (check topics first) |
| WIF for CI triggering | gcp, wif, github-actions, oidc |
| IAM invoker patterns | gcp, iam, security, least-privilege |
| Naming / labels | gcp, naming, conventions, labels, finops |

> Few topics exist yet for this domain. If no topic file is found, signal the Cloud Research stage
> to fetch current best practices before the Implement stage generates code.

## Domain Checklist
Apply during generation and review:

- [ ] VPC connector or Direct VPC egress configured for private resource access
- [ ] No unauthenticated (`allUsers`) invoker without explicit justification and review
- [ ] Secrets via Secret Manager references — not environment variable literals
- [ ] Concurrency and CPU allocation explicitly set (no implicit Cloud Run defaults)
- [ ] Minimum and maximum instances defined for cost and cold-start control
- [ ] Cloud Functions: runtime pinned to a non-deprecated version
- [ ] Eventarc triggers scoped to minimum event types required
