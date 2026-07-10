---
name: bailiwick-purge
description: Remove every reference to a client or project from the Bailiwick knowledge library, captures, telemetry, and registry — keeping the reusable operational knowledge (re-attributed or genericized) and deleting only what is clearly client/project-specific. Human-gated and destructive. Use when the user asks Codex to purge, offboard, or de-identify a client/project, or to run a de-identification / deletion-request pass before sharing a library.
---

# Bailiwick Purge

## Overview

Run the Bailiwick de-identification (`/purge`) workflow from Codex. This is a thin Codex wrapper; the
canonical procedure and guardrails live in Bailiwick's `skills/purge/SKILL.md`.

## Workflow

1. Resolve the Bailiwick root:
   - Prefer `$BAILIWICK`.
   - If unset and this skill is symlinked from the framework, infer the repo root two directories above this skill.
   - Fallback to `/path/to/bailiwick` if it exists.
2. Read the canonical instructions completely:
   - `$BAILIWICK/skills/purge/SKILL.md`
   - `$BAILIWICK/agents/memory.md` (scopes, `clients/<id>/`, telemetry)
   - `$BAILIWICK/knowledge/context/org-shorthands.md` (the `<id>` registry)
3. Follow the canonical `/purge` procedure exactly:
   - Inputs: `<from>` (the client/project to purge) and `--to <target>` (re-attribution target for the
     abstracted knowledge; default `acme`, or another registry `<id>`, or `generic`). `--history`
     optionally offers to purge git history (knowledge **and** backup repos). `--attest` optionally
     drafts a purge attestation + non-reversible internal stub (safety-net engineering record, never a
     legal assurance; output-only).
   - SCAN every surface, CLASSIFY each hit (ABSTRACT by default / DELETE only clearly client-specific /
     SURFACE for user decision), present the full plan as diffs, and **wait for explicit approval**.
   - Execute in the canonical order; run the **committed-knowledge safety check** before purging any
     capture; treat `--history` as opt-in, double-confirmed, and prefer generating the command.

## Guardrails

- Never run on agent initiative. Present the plan; execute only on explicit approval.
- Default is ABSTRACT — keep the reusable knowledge; delete only what is clearly client/project-specific.
- Never purge a capture until its sanitized knowledge is committed.
- `--history` **outputs** the git-history-rewrite commands (`git filter-repo`, etc.) for **both** the
  knowledge and backup repos for the user to run themselves; the skill never executes them — history
  rewrite breaks satellites/clones.
- Erasure is **de-identified by default, not "fully erased"**: ciphertext persists in the backup repo's
  git history until it is rewritten or the gpg key is destroyed. `--attest` must report only the tier
  it can verify, and never assert legal sufficiency.
