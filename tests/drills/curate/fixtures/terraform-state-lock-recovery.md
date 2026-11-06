---
id: terraform-state-lock-recovery
type: topic
tags: [terraform, state, gcs, lock, pitfall]
confidence: medium
last_validated: 2026-09-15
supersedes: []
scope: generic
---

# Terraform state lock recovery (GCS backend)

## Problem
An interrupted `terraform apply` (CI runner killed, laptop asleep) leaves the GCS backend's lock
object (`<prefix>/default.tflock`) behind; every later plan fails with "Error acquiring the state lock".

## Fix
1. Confirm no apply is still running (CI job list, `gcloud storage ls -l gs://<bucket>/<prefix>/`).
2. Run `terraform force-unlock <LOCK_ID>` with the ID from the error message.
3. Never delete the `.tflock` object by hand while a run might still be live.

## Related
- [GCS backend pattern](../patterns/gcp-backend-gcs-pattern.md)
