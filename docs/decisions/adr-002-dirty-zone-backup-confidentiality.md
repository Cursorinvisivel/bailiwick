---
id:            adr-002-dirty-zone-backup-confidentiality
type:          decision
status:        accepted
date:          2026-06-26
authors:       [Francisco Ferrinho]
tags:          [adr, confidentiality, data-classification, backup, governance]
supersedes:    []
superseded_by:
scope:         generic
---

# ADR-002 — Confidentiality basis for encrypted off-machine backup of the dirty zone

---

## Context

The encrypted dirty-zone backup (`capture_backup.sh`; see `hooks/README.md` → Encrypted
dirty-zone backup) pushes **un-curated** captures off-machine for durability. Those captures are raw
transcripts that can contain sensitive material, and the backup may run on machines used for
confidential engagements, not only the operator's own. Enabling it for **all** captures (including
sensitive ones) is a judgment call that must be made deliberately per machine, and the reasoning
recorded here so the basis for `confidentiality_ack: true` is durable and re-examinable — not buried
in chat.

This ADR is written as a **decision template**: the specific classification below is the reference
example that ships; each operator re-runs the same reasoning for their own engagements and terms.

Reference data classification (the example this decision is calibrated against):
- The engagement is bound by a **confidentiality obligation** (e.g. an NDA or equivalent).
- No access to **business data** or **production/customer data**.
- What is seen — and what could be inadvertently captured — is **platform configuration, access
  details, and resource names/identifiers** (infrastructure metadata), bound by nothing beyond that
  obligation.

This complements ADR-001 (which keeps the framework single-user and agent-first) by governing how dirty
data may be backed up across machines.

## Decision

Enable the encrypted off-machine backup for **all** captures, including sensitive ones
(`capture_backup.enabled: true`, `confidentiality_ack: true`), on the combined basis of the **data
classification above** and the **technical controls** below:

- Only **ciphertext** ever leaves a machine (gpg-encrypted to the owner's key before push).
- The **private key never leaves** the curating machine; backup machines hold only the public key.
- Backups go to a **dedicated private repo** (`bailiwick-holding`), never the framework or a work repo.
- `confidentiality_ack` is a per-machine affirmation that the engagement's terms permit it.

The classification and terms differ per operator and per engagement, so `confidentiality_ack` is a
**per-machine** switch: where the terms do not permit an off-machine copy, it stays `false` and
captures remain local.

## Options Considered

### Option A — Encrypted backup of all captures incl. sensitive ones (CHOSEN)
**Pros:** Maximum durability — no un-curated capture is lost to disk failure, on any machine.
**Cons:** Sensitive data (config/resource-level) leaves the environment it originated in, even if only
as ciphertext; relies on the confidentiality terms as the governing instrument and on the encryption
controls holding.

### Option B — Own-work captures only; sensitive captures stay local
**Pros:** No sensitive data leaves its environment at all — lowest governance risk.
**Cons:** Captures on transient/confidential machines get **no** durability; disk loss = lost
knowledge, which is the exact gap this feature exists to close.

### Option C — No off-machine backup (status quo before this work)
**Pros:** Simplest; zero exfiltration.
**Cons:** No durability for any dirty data — the problem this ADR's feature solves.

## Rationale

For the reference classification, the captured material is **infrastructure metadata** (platform
config, access details, resource names/identifiers), not business or production data, and is covered
only by the engagement's confidentiality terms. Combined with ciphertext-only transport and a private
key that never leaves the curating machine, the residual exposure is bounded and proportionate to the
durability gained. Option B was rejected because it leaves durability — the primary goal — unmet on
exactly the machines most likely to be transient. Where an operator's classification or terms differ,
the same reasoning yields a different setting via the per-machine `confidentiality_ack`.

## Consequences

### Positive
- Un-curated captures survive disk loss on every machine where the terms permit the backup.
- The confidentiality judgment is now an explicit, dated, re-examinable record (this ADR + the
  `confidentiality_ack` gate), not a silent default.

### Negative / Accepted trade-offs
- Sensitive (config/resource-level) data leaves its origin environment as ciphertext — accepted only
  under permitting terms + the encryption controls.
- Security now depends on gpg key hygiene and the backup repo staying private.

### Risks and mitigation
| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Backup repo accidentally made public/shared | Low | High | Dedicated private repo; ciphertext-only (unreadable without the private key); periodic access review |
| Data classification changes (business/production data enters scope) | Medium | High | This ADR's basis no longer holds — set `confidentiality_ack: false` for that machine; re-evaluate before re-enabling |
| gpg private key compromised | Low | High | Key lives only on the curating machine; rotate key + re-key the backup if suspected; passphrase-protected |
| A specific engagement's terms forbid any off-machine copy | Medium | High | `confidentiality_ack` is per-machine — leave it false on that machine (captures stay local) |

## References
- `hooks/capture_backup.sh` and `hooks/README.md` → Encrypted dirty-zone backup
- `.bailiwick-sync.json` → `capture_backup` (`confidentiality_ack`)
- `adr-001-kb-tooling-and-team-brain.md`
- `docs/FRAMEWORK.md` §5 (hooks), §6 (capture lifecycle)
