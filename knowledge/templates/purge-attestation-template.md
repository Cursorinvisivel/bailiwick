<!--
Purge attestation template (used by /purge --attest, Step 7). TWO artifacts, TWO homes:
  A. Client-facing attestation — handed to the client, NOT retained (it re-identifies them).
  B. Internal audit stub       — retained at ~/.bailiwick/purge-audit/, non-reversible (no client name).
This is an ENGINEERING RECORD of what was mechanically done — NOT a legal or compliance assurance.
Never assert legal sufficiency. Fill every <placeholder>; delete guidance comments before signing.
-->

# A. Purge attestation — <client / project name>

**For:** <client name / recipient>
**Request reference:** <ticket / email / contract clause> · **Date of request:** <YYYY-MM-DD>
**Performed by:** <operator name / role> · **Date performed:** <YYYY-MM-DD> · **Method version:** <purge vX / commit>

## What was removed / de-identified

De-identification of every reference to <client> across the Bailiwick knowledge instance, keeping only
reusable, generic engineering know-how (re-attributed or genericized). Per surface:

| Surface | Action | Count |
|---|---|---|
| `clients/<id>/` files | deleted | <n> |
| `scope: client:<id>` files (outside subtree) | abstracted / deleted | <n> / <n> |
| Inline references (topics/patterns/context, INDEX, `## Related`) | abstracted | <n> |
| Telemetry associations (`distinct_projects_used[]`) | scrubbed | <n> |
| `confidence:` downgrades (evidence dropped below graduation) | applied | <n> |
| Local + central captures | deleted | <n> |
| Encrypted backup blobs (current tree, all machines) | purged | <n> |
| `org-shorthands.md` registry row | removed | 1 |

**Method:** clearly client-specific artifacts were deleted; reusable knowledge was abstracted (identity
stripped) and retained as generic patterns. The retention of generic know-how is stated here as a
factual description of what remains — **its permissibility is for your legal review; this document
makes no legal claim.**

## Verification

Post-purge re-scan for [`<id>`, `<org-token>`, `<org name>`] across the library, index, `## Related`,
telemetry, local + central captures, and the backup branch (decrypted):

> **Residual hits: 0** across all surfaces. <or: list any non-zero surface — do NOT attest if non-zero.>

## Erasure tier and honest caveats  *(non-negotiable — do not soften)*

- **Tier: <de-identified | fully erased>** — derived from verified state, not asserted.
  - *De-identified* means working trees and the current backup tree are clean, **but ciphertext may
    persist in the backup repository's git history** (the encryption key never left the curating
    machine). True erasure of that history requires a git-history rewrite on all remotes and/or
    destruction of the key.
  - *Fully erased* is claimed only where that history rewrite and/or key destruction has been verified.
- **Scope boundary:** this covers the Bailiwick instance under our control only. It does **not** reach
  forks, other parties' clones, remote caches, CI/build artefacts, or any third-party system.
- **Not legal advice.** This is an engineering record of actions taken, provided for your accountability;
  it is not a determination of legal or regulatory sufficiency.

**Signature:** ______________________  **Name / role:** __________________  **Date:** __________

<!-- Hand this to the client. Do NOT store it in knowledge/ or the captures — it re-identifies them. -->

---

<!--
# B. Internal audit stub  →  write to ~/.bailiwick/purge-audit/<timestamp>-<hash8>.md
# Retained for accountability; MUST NOT re-identify. No client name, no removed content.
-->

```yaml
purge_id:        <salted-hash-of-client-token>      # salt stored SEPARATELY from this file
performed_utc:   <YYYY-MM-DDTHH:MM:SSZ>
knowledge_commit: <sha of the knowledge: cleanup commit>
tier:            <de-identified | fully erased>
method_version:  <purge vX / commit>
counts:          { clients_files: <n>, abstracted: <n>, telemetry: <n>, confidence_downgrades: <n>, captures: <n>, backup_blobs: <n> }
residual_hits:   0
# NO client name, NO org tokens, NO removed content — this stub proves a purge ran, nothing more.
```
