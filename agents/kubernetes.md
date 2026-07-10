# Kubernetes Domain Agent

## Scope
GKE cluster config, Helm releases, Kubernetes operators, manifests, Gateway API,
Workload Identity, External Secrets Operator, multi-cluster patterns.

Not in scope: GCP IAM/networking not tied to workloads → gcp.md | Cloud Run → serverless.md

## Memory Hints
Pass these tags to Memory Agent based on what the task touches:

| Sub-area | Tags to load |
|---|---|
| Workload Identity (GKE pods) | gcp, gke, kubernetes, identity, workload-identity |
| WIF for private/on-prem clusters | gcp, wif, kubernetes, oidc, jwks, private-cluster |
| Gateway API / HTTPS | gke, gateway-api, kubernetes, httproute, tls, networking |
| External Secrets Operator | kubernetes, eso, external-secrets, secret-manager |
| Connect Gateway provider | gke, kubernetes, helm, terraform, provider, fleet, connect-gateway |
| Operators (NiFiKop, etc.) | kubernetes, nifikop, gke, operator, helm |
| Cloud SQL proxy on GKE | gcp, cloud-sql, csql-proxy, kubernetes, gke |
| Private CA + Gateway | gcp, private-ca, certificate-manager, tls, gateway-api |

## Domain Checklist
Apply during generation and review:

- [ ] Workload Identity over service account key files — no mounted JSON keys
- [ ] ESO for secrets — no plain Kubernetes secrets with sensitive values
- [ ] Resource requests and limits set on all containers
- [ ] `for_each` over `count` for node pools and HelmRelease resources
- [ ] RBAC scoped to namespace where possible — no cluster-admin without justification
- [ ] Gateway API preferred over Ingress for new GKE workloads
- [ ] Operator CRD lifecycle managed in Terraform (prevent orphaned CRDs)
