# Copilot Instructions — Terraform GCP + GKE

## Includes all patterns from $BAILIWICK/copilot-instructions/terraform-gcp.md

## GKE — Additional Patterns

### Workload Identity (mandatory in GKE)
Never mount service account keys in pods.
Use Workload Identity to map KSA → GSA.

```hcl
workload_identity_config {
  workload_pool = "${var.project_id}.svc.id.goog"
}
```

### Node Pools
- Use dedicated node pools per workload type
- Shielded nodes enabled in production
- Auto-upgrade and auto-repair always active

### Networking
- Private cluster in production (nodes without public IPs)
- Authorized networks for control plane
- VPC-native (alias IP ranges)

### RBAC
- Do not use cluster-admin for workloads
- Kubernetes RBAC aligned with GCP IAM via Workload Identity

## Additional Prohibitions (GKE)
- Never service account keys in pods
- Never cluster-admin for applications
- Never nodes with public IPs in production without justification
