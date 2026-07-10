---
id:            adr-008-purge-and-deidentification
type:          decision
status:        accepted
date:          2026-07-09
authors:       [Francisco Ferrinho]
tags:          [adr, confidentiality, purge, de-identification, deletion-request, curation, governance]
supersedes:    []
superseded_by:
scope:         generic
---

# ADR-008 — Purge & de-identification: keep the knowledge, discard the client/project linkage

---

## Context

The framework prevents client-identifying detail from entering the generic library at **promotion**
time (the Security-Review leakage check; abstract to `generic`, route client detail to `clients/<id>/`).
What it lacked was the **retroactive** counterpart: a way to remove *all* traces of a client or project
from an existing library on offboarding, on a deletion request, or before sharing the
library — **without** losing the reusable operational knowledge (how a problem was solved, what
solution fit a need). The single `<id>` threads through many surfaces (`clients/<id>/`,
`scope: client:<id>`, the `{org}` token, `distinct_projects_used` in telemetry, the `org-shorthands.md`
registry, inline mentions, and captures stamped with the client origin), so removing it is a
multi-surface operation that also touches irreversible things (captures, git history).

## Decision

Add a **human-gated `/purge`** skill and a **de-identified `/curate` mode**.

1. **`/purge <from> [--to <target>] [--history]`** — scan → plan → approve → execute, never on agent
   initiative. Its defining rule: **default is ABSTRACT, not delete** — keep the reusable knowledge and
   either **re-attribute** it to a chosen id (`--to`, default `acme`, or the operator's own org, or
   `generic`) or genericize it; **DELETE only** what is clearly client/project-specific
   (`clients/<from>/`, captures that cannot be sanitized in place); **SURFACE** ambiguous
   `scope: client:<from>` files for a per-file human decision.
2. **Captures are purged only after the sanitized knowledge is committed** (the committed-knowledge
   safety check) — never destroy the source before the clean copy exists in git.
3. **Git-history purge (`--history`) OUTPUTS the `git filter-repo` command(s) for the operator to run
   themselves** — the skill never executes the history rewrite (no `filter-repo`, no `git rm` on
   history). It is a *quick path* (ready-to-run commands + the surrounding steps), not an automation,
   because history rewrite changes every commit hash and forces satellites / open sync PRs to re-clone.
4. **De-identified `/curate` mode** (`--sanitized`, or `.bailiwick-sync.json` `curate.deidentify: true`)
   promotes with **no** client/project identifiers at all — a stronger form of the standard abstraction.
   It serves both a standing "never store client/project info" posture and the purge routine
   (re-ingest still-uncurated operational knowledge generically **before** the captures are destroyed).

## Options considered

- **A — human-gated `/purge` + de-identified `/curate` (CHOSEN).** Preserves the framework's ethos
  (drafts for review, human gate, never destructive on initiative) while closing the retroactive gap.
- **B — an automated scrub script.** Rejected: deciding delete-vs-abstract per file is judgment, and
  the operation is irreversible — automation here is a footgun.
- **C — rely on promotion-time abstraction only.** Rejected: it cannot remove residual inline ties in
  already-promoted generic knowledge, purge captures, or handle an offboarding / deletion request.

## Rationale

De-identification, not deletion, is the point: the value of the library is the accumulated "how," which
is client-agnostic once abstracted. Re-attribution (`--to`) matters because reusable knowledge usually
belongs *somewhere* (the operator's own org) rather than nowhere. The committed-knowledge safety check
encodes the one ordering that must never invert — clean copy before source destruction. Git-history
purge is an **output-only** quick path — the skill hands the operator the commands and never runs them —
because history rewrite breaks the multi-machine sync model and must be a deliberate human act.

## Consequences

### Positive
- A real de-identification / client-offboarding capability; strengthens the privacy-by-construction
  posture (see `docs/threat-model.md`).
- The library becomes shareable/publishable after a purge pass without losing operational value.
- De-identified `/curate` gives a zero-identifier posture for the cautious, reused by `/purge`.

### Negative / accepted trade-offs
- Abstraction quality is human judgment — a careless purge could over-delete or leave a residual tie;
  the plan-then-approve gate and diffs mitigate this.
- `--history` is destructive to clones/satellites; the skill only **outputs** the commands, never runs
  them — the operator executes the history rewrite deliberately.
- Captures, once purged, are gone — hence the committed-knowledge safety check.
- **Not a GDPR-grade erasure; de-identified vs. fully erased.** `/purge` covers what Bailiwick stores —
  the library, telemetry, local + central captures, and (via `capture_backup.sh purge`) the encrypted
  backup blobs in the **current** tree — and *outputs* git-history-rewrite commands for **both** the
  knowledge repo and the backup repo. By default it is **de-identified, not fully erased**: because
  `capture_backup.sh purge` is `git rm` + commit (no history rewrite), the client's **ciphertext
  persists in the backup repo's git history** until that history is rewritten on all remotes or the gpg
  key is destroyed. It also does **not** reach forks, other people's clones, remote caches, CI/build
  artefacts, or anything outside the operator's control. The docs avoid "right-to-be-forgotten" framing
  for this reason; treat it as de-identification / offboarding, not legal-grade deletion.

## References
- `skills/purge/SKILL.md` · `codex-skills/bailiwick-purge/SKILL.md`
- `skills/curate/SKILL.md` (De-identified mode) · `agents/memory.md` (scopes, `clients/<id>/`, telemetry)
- `knowledge/context/org-shorthands.md` (the `<id>` registry) · `hooks/capture_backup.sh` (`purge`)
- `adr-002-dirty-zone-backup-confidentiality.md` · `docs/threat-model.md`
