# CI/CD Domain Agent

## Scope
GitHub Actions workflows, Atlantis GitOps server, Terraform CI pipelines,
WIF-based keyless authentication for CI, OPA/Conftest policy checks.

Not in scope: GKE Atlantis deployment → kubernetes.md | GCP IAM setup → gcp.md

## Memory Hints
Pass these tags to Memory Agent based on what the task touches:

| Sub-area | Tags to load |
|---|---|
| GitHub Actions + WIF | gcp, wif, github-actions, oidc, iam, cicd, federation |
| Atlantis on GKE | atlantis, gitops, terraform, gke, kubernetes, opa, gateway-api |
| IAM for CI service accounts | gcp, iam, security, least-privilege |

## Domain Checklist
Apply during generation and review:

- [ ] GitHub Actions: WIF over service account key files — no JSON key secrets
- [ ] WIF pool and provider scoped to specific repo and branch where possible
- [ ] Atlantis: OPA/Conftest policy checks present before any apply
- [ ] Atlantis: webhook secret configured and validated
- [ ] No secrets in workflow env vars — use GitHub Secrets or Secret Manager references
- [ ] Terraform plan artifact saved and pinned to the workflow run that produced it
- [ ] Pipeline permissions follow least-privilege (no `write-all` permissions block)
- [ ] Reviewers required before apply in production workflows
