---
id: gcp-gke-workload-identity
type: pattern
tags: [gcp, gke, kubernetes, identity, workload-identity]
confidence: high
last_validated: 2026-06-04
supersedes: []
scope: generic
---

# Pattern: GKE Workload Identity

## Concept
Workload Identity maps Kubernetes Service Accounts (KSA) to Google Service Accounts (GSA),
eliminating the need for service account keys in pods.

## Prerequisites
- GKE cluster with Workload Identity enabled: `workload_pool = "${var.project_id}.svc.id.goog"`
- Kubernetes namespace created

## Implementation steps (Terraform)

```hcl
# 1. Google Service Account
resource "google_service_account" "workload" {
  account_id   = "${var.environment}-${var.region_short}-sa-${var.app_name}"
  display_name = "${var.app_name} workload identity SA"
  project      = var.project_id
}

# 2. IAM binding: KSA can impersonate GSA
resource "google_service_account_iam_member" "workload_identity" {
  service_account_id = google_service_account.workload.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${var.k8s_namespace}/${var.k8s_service_account}]"
}

# 3. Kubernetes Service Account with annotation
resource "kubernetes_service_account" "workload" {
  metadata {
    name      = var.k8s_service_account
    namespace = var.k8s_namespace
    annotations = {
      "iam.gke.io/gcp-service-account" = google_service_account.workload.email
    }
  }
}
```

## Verification
```bash
curl -H "Metadata-Flavor: Google" \
  http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email
```

## Rules
- Never mount service account keys in GKE pods
- One KSA per application — do not share across distinct workloads
- GSA with minimum roles for the specific workload

## Related
- [GCP IAM conventions](gcp-iam-conventions.md)
- [Terraform module structure](terraform-module-structure.md)
