---
name: purge
description: Remove every reference to a client or project (`<id>`, `{org}` token, org name) from the knowledge library, captures, telemetry, and registry — re-attributing or genericizing the REUSABLE knowledge (keep how a problem was solved) while deleting only what is clearly client/project-specific. Human-gated and destructive. Use for client offboarding, a deletion request, or before sharing/publishing a library.
---

# /purge — de-identify a client or project (human-gated, destructive)

Retroactively strips a client/project's identity from the library while **preserving the operational
knowledge** — the reverse of the promotion-time leakage check. The reusable "how we solved X" stays
(re-attributed or genericized); only the *linkage* to the specific client/project is removed, and only
what is *clearly* client/project-specific is deleted. Read `$BAILIWICK/agents/memory.md` (scopes,
`clients/<id>/`, telemetry) and `$BAILIWICK/knowledge/context/org-shorthands.md` (the `<id>` registry)
first.

**Runnable from any wired repo** — reaches the library, captures, and encrypted pool by absolute path.

## Hard rules (do not violate)
- **Never run on agent initiative.** Purge is destructive and irreversible; it requires an explicit
  user request and an explicit approval of the plan in this session.
- **Default is ABSTRACT, not delete.** Keep the reusable knowledge; DELETE only artifacts that are
  clearly client/project-specific and cannot be meaningfully abstracted.
- **Never purge a capture until its sanitized knowledge is committed.** Captures cannot be sanitized
  in place, so they are deleted — but only after the abstracted knowledge is safely in git (the
  committed-knowledge safety check, Step 5). Never destroy the source before the clean copy exists.
- **Nothing is written or deleted without approval of the full plan.** Present diffs; wait.

## Inputs
- `<from>` — the client/project to purge. Either a registry `<id>` (from `org-shorthands.md`, e.g.
  `wombat`) — in which case its `{org}` token and full org name are looked up so all three are
  detected — or a free-form identifier (repo name / project string) you supply literally.
- `--to <target>` — where the ABSTRACTED knowledge is re-attributed. **Default `acme`** (the own-org /
  not-client-owned placeholder). Pass another registry `<id>` to re-home it under a different entity
  (e.g. your own company's id), or `generic` to fully genericize (scope `generic`, no owner).
- `--history` (optional) — also offer to purge the tokens from **git history** (see Step 6; guarded).
- `--attest` (optional) — after the purge, run a verification re-scan and draft a **purge attestation**
  (client-facing) plus a non-reversible internal audit stub (see Step 7). A *safety net* for "we may
  need to scrub and show we did" — an engineering record, **not** a legal/compliance assurance.
  Output-only: drafts for human review, never sent.

## Procedure

1. **Resolve the target's tokens.** If `<from>` is in `org-shorthands.md`, collect all three strings
   to detect: the `<id>`, the `{org}` token (may differ, e.g. `wombat`→`wmb`), and the organisation
   name. If free-form, use the literal identifier(s) the user gives. These tokens drive detection.

2. **Scan — enumerate every trace** (report counts per surface):
   - `clients/<from>/` subtree.
   - Files carrying `scope: client:<from>` (or `external:<from>`).
   - `.telemetry.json` `distinct_projects_used[]` entries containing the id.
   - **Inline mentions** of any token across `knowledge/` (topics/patterns/context), `INDEX.md`, and
     `## Related` links.
   - Captures for this origin — enumerated by **origin stamp, not path** (a repo basename can be
     shared by two clients, so a path prefix over/under-matches): local `.bailiwick-outputs/raw/`;
     central `~/.bailiwick/captures/*/` (match each capture `.md` header's `origin_remote`); and the
     encrypted backup branch **across every machine** — run `bash $BAILIWICK/hooks/capture_backup.sh
     pull`, then match each decrypted capture's `origin_remote`. Record the matched backup blob
     rel-paths (`<machine>/<repo-key>/<file>.gpg`) for Step 5; blobs are per-machine, so a client used
     on more than one machine has blobs under several `<machine>/` subtrees.
   - The `org-shorthands.md` registry row.
   - (with `--history`) commits whose message or diff contains a token.

3. **Classify each hit:**
   - **ABSTRACT (default)** — reusable knowledge with an inline client tie. Propose a de-identified
     rewrite that KEEPS the solution and re-attributes per `--to`: genericize
     (`for wombat's landing zone` → `for a landing zone`) or re-home
     (`… for <target-org>'s landing zone`). Retag `scope:` to `--to` (or `generic`).
   - **DELETE** — clearly client/project-specific and not abstractable: the `clients/<from>/` files;
     all captures for this origin (cannot be sanitized in place).
   - **SURFACE FOR DECISION** — `scope: client:<from>` files *outside* `clients/<from>/`: show each and
     let the user choose abstract-and-keep vs delete (reusable-but-mis-scoped vs purely client).

4. **Present the plan (single approval batch).** Every ABSTRACT rewrite as a diff; every DELETE; the
   telemetry scrub **and any resulting `confidence:` downgrades** (a note that loses its 3rd distinct
   project no longer meets the `high` bar — see Step 5.3); the registry-row removal; INDEX + `## Related`
   fixes; the capture purges; and (with `--history`) the exact `git filter-repo` invocations. **Wait for
   explicit approval.** Nothing has been changed yet.

5. **Execute on approval, in this order:**
   1. Apply approved **abstractions** — rewrite files, retag `scope:` to `--to`/`generic`, fix any
      `## Related` links and INDEX rows that pointed at now-abstracted or deleted notes.
   2. **Delete** the clearly-client-specific files (`clients/<from>/`, and any surfaced files the user
      chose to delete).
   3. **Scrub telemetry, then re-evaluate confidence.** Remove the id from every
      `distinct_projects_used[]`. Removing a client's project can drop a note below its graduation
      evidence (medium = used in ≥1 project; high = stable across 3+ distinct projects), so for each
      touched id re-check the remaining `distinct_projects_used[]` against those thresholds and
      **downgrade the frontmatter `confidence:` where the evidence no longer supports it** (a `high` now
      under 3 distinct projects → `medium`, etc.). These downgrades were surfaced for approval in Step 4,
      not applied silently.
   4. **Remove the `org-shorthands.md` registry row LAST** (it was needed for detection during the run).
   5. **Commit** the knowledge changes (`knowledge:` prefix) — requires approval. The clean, abstracted
      library is now in git.
   6. **Committed-knowledge safety check → purge captures.** Verify the abstracted knowledge is
      committed (`git status` clean for the touched files / the commit exists). ONLY then delete the
      captures: local raw, central `~/.bailiwick/captures/<repo-key>/`, and every backup blob matched
      by origin in Step 2 — `bash $BAILIWICK/hooks/capture_backup.sh purge <machine>/<repo-key>/<file>.gpg`
      per blob, **sweeping every `<machine>/` subtree** (per-machine blobs). Purge by the matched
      rel-paths, never by guessing a path. **Note — this removes blobs from the current backup tree but
      NOT from the backup repo's git history: the ciphertext persists in history until it is rewritten
      (`--history`, below) or the gpg key is destroyed** (see the erasure-tier note in Step 6). If the
      knowledge is not yet committed, STOP and report — never purge the source first.

6. **(`--history`, optional) Purge git history — OUTPUT the commands; never run them.** Rewriting
   history is **brutally destructive**: it changes every commit hash, and satellites / open sync PRs
   must **re-clone** (their `main` diverges). The skill's only job here is to **generate the exact
   commands for the user to run themselves** — it does NOT execute the history rewrite, `git rm`, or
   `filter-repo`. Print a ready-to-run block:
   - **Knowledge repo:** the `git filter-repo` invocation(s), e.g.
     `git filter-repo --replace-text <(printf '%s==><redacted>\n' <id> <org-token> "<org name>")`
     (or `--path clients/<from>/ --invert-paths` to drop the client subtree from history).
   - **Backup repo (the ciphertext) — do NOT skip if erasure matters.** The knowledge-repo rewrite does
     not touch the encrypted capture-backup repo, where the client's ciphertext still lives in history
     after Step 5's purge. Output the equivalent per matched subtree from Step 2:
     `git filter-repo --path <machine>/<repo-key>/ --invert-paths` (repeat per `<machine>/`), then
     force-push the backup branch and have every machine re-fetch its mirror. The **only** other
     true-erasure lever is **destroying the gpg key** (which renders all ciphertext undecryptable).
   - The steps to run around them: back up each repo first, force-push afterward, and have every clone /
     satellite / backup mirror re-fetch (histories diverge).
   The user runs the commands deliberately, outside the skill.

   **Erasure tiers — never over-claim.** Report only the tier that matches what was *actually run*:
   - **De-identified** (Steps 1–5, no `--history`): working trees are clean and the current backup tree
     no longer holds the blobs, **but ciphertext persists in the backup repo's git history** (the gpg
     key never leaves the curating machine). This is the default, honest claim.
   - **Fully erased**: only after the backup-repo history is rewritten on **all** remotes **and/or** the
     gpg key is destroyed. Derive this tier from verifiable state — never from an operator assertion.

7. **(`--attest`, optional) Purge attestation — draft only, never sent.** Produce a record that a scrub
   happened, *without re-creating the identity you just removed*. This is an **engineering record of
   what was mechanically done — not a legal or compliance assurance**; it must never assert legal
   sufficiency. Run it only after the purge (and any Step 6 history rewrite) so the tier reflects reality.
   1. **Verification re-scan.** Re-run the Step-2 token scan across **every** surface — library, `INDEX`,
      `## Related`, telemetry, local + central captures, and the backup branch (decrypt + grep). Record
      residual hits per surface. A credible attestation shows **0 residual hits** for every token; if any
      surface is non-zero, **STOP and report — do not attest**.
   2. **Derive the erasure tier from verified state (Step 6 tiers) — never assert it.** `de-identified`
      when working trees + current backup tree are clean but the backup repo's **history** still holds
      the client's blobs; `fully erased` only when the backup-history rewrite has been run on all remotes
      and/or the gpg key is destroyed. Check what you can; default to the conservative tier.
   3. **(A) Client-facing attestation** — a Markdown **draft** from
      `knowledge/templates/purge-attestation-template.md`: the client (named — it's for them), request
      reference + date, operator, per-surface scope + counts, the abstract-vs-delete method and what
      generic know-how was retained (**stated as fact, flagged for the client's legal review, never
      asserted as lawful**), the honest caveats (the derived tier; ciphertext-in-history unless erased;
      scope boundary — this fleet only; **not legal advice**), and the verification re-scan result
      (→ 0 residual hits). Treat it like a capture: **hand it over, do not retain it** — it re-identifies
      the client.
   4. **(B) Internal audit stub** — a retained, **non-reversible** record that *a* purge ran without
      being a client dossier: a **salted hash** of the client token (store the salt separately from the
      stub), timestamp, the knowledge-cleanup commit SHA, per-surface counts, the derived tier, and the
      method version — **no client name, no removed content**. Write it to `~/.bailiwick/purge-audit/`,
      **outside** the telemetry-tracked library, never in the shared brain.
   Output-only, like `--history`: draft (A) for human review + signature and write (B); the skill never
   sends anything.

## Re-ingesting sanitized knowledge
If useful operational knowledge is still only in the captures (not yet promoted) when you purge, run
**`/curate` in de-identified mode first** (see `skills/curate/SKILL.md` → De-identified mode): it
promotes the knowledge with **no** client/project identifiers, so the reusable content is preserved
generically before the identifying captures are destroyed.

## Guardrails
- Human-gated; destructive; never agent-initiative. Present diffs; approve; then execute.
- Keep the solution, discard the linkage. Delete only what is clearly client/project-specific.
- Captures are purged only after the sanitized knowledge is committed.
- `--history` **outputs** the git-history-rewrite commands for the user to run; the skill never
  executes them (no `filter-repo`, no `git rm` on history).
- **Scope boundary — not GDPR-grade erasure.** Purge covers what Bailiwick stores (library, telemetry,
  local + central captures, current backup tree) and *outputs* the history-rewrite commands for both
  the knowledge repo and the backup repo. By default it is **de-identified, not fully erased**:
  ciphertext persists in the **backup repo's git history** until that history is rewritten or the gpg
  key is destroyed (Step 6 tiers). It also does NOT reach forks, others' clones, remote caches, or
  CI/build artefacts. Say so — frame it as de-identification / offboarding, not legal-grade deletion.
