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
   - `$BAILIWICK/skills/purge/SKILL.md`, and each `$BAILIWICK/skills/purge/reference/*.md` file when
     the run card names it for the current step
   - `$BAILIWICK/agents/memory.md` (scopes, `clients/<id>/`, telemetry)
   - `$BAILIWICK/knowledge/context/org-shorthands.md` (the `<id>` registry)
3. Follow the canonical `/purge` procedure exactly:
   - **Run card.** Work through the canonical run card in order: 1.1 sentinel → 1.2 wired? → 1.3–1.4
     tokens and `$W` → 2 scan → 3 classify → 3a review → 3b Advisor → 4 PLAN/APPROVE → 5.1–5.6 execute → 5a verify → 5b
     own-footprint checks → 5.7 scrub → 6/7 outputs → 5b user block. The final report includes it as a
     filled table, `Step | done / skipped / blocked | evidence`; a step without evidence is `blocked`.
   - **Run location.** Start Codex from the Bailiwick clone with `BAILIWICK_SHADOW=1 codex`, which
     wires this one session and nothing persistent. Not from the client's repo (its name would land in
     the session's paths and records). Adding the clone to the allowlist is not recommended: it would
     capture later `/curate` sessions that read decrypted client captures.
   - **First action, before any scan:** run `bash "$BAILIWICK/hooks/mark_purge_session.sh"` as its own
     command, exactly as written. It disables capture and deletes this session's captures, so the
     guardrail gates it; Codex has no ask, so it is **denied**. That is expected when the user typed
     `$bailiwick-purge`: the capture hook detects that typed name (Codex name detection matches only
     the `bailiwick-<name>` form) and excludes the session. If Codex chose the skill implicitly (no
     typed `$bailiwick-purge`), STOP and ask the user to restart the session with `$bailiwick-purge`
     typed; never relaunch with `BAILIWICK_BREAK_GLASS=1`, which lifts every guardrail for the whole
     destructive session. Then confirm the session is wired (canonical Step 1.2); if not, stop and ask
     the user to restart with `BAILIWICK_SHADOW=1 codex`.
   - **Role (canonical Step 1.2).** Read `role` from `$BAILIWICK/.bailiwick-sync.json` (absent =
     `satellite`). `.telemetry.json` is central-owned: on a satellite skip the telemetry scrub (5.3)
     and report telemetry as "pending central purge" (re-run that step on the central machine after the
     sync PR merges; 5a records telemetry `not checked`, so no tier is derived). Knowledge, `INDEX.md`
     and registry edits are fine on a satellite: they reach `main` through the `sync/<machine>` PR.
   - **`$W` hygiene.** Create `$BAILIWICK_HOME/purge-work/` mode 0700 (`umask 077`); stop if it
     already exists (a leftover of an unfinished run). It holds every token-bearing work file and is
     removed at Step 5.7. Whenever the run ends early (stop, abort, declined plan), remove it and print
     the `rm -r` command in the report.
   - **One matching rule.** Tokens of 4 characters or fewer match only on alphanumeric boundaries;
     `scripts/purge_scrub.py` implements it (`ere` for grep patterns, `scrub` for the logs; `scrub` is
     a dry run unless `--apply`, accepts only the audit log and `health/` shards, refuses symlinks, and
     refuses tokens under 3 characters unless `--allow-short`).
   - Inputs: `<from>` (the client/project to purge) and `--to <target>` (re-attribution target for the
     abstracted knowledge; default `acme`, or another registry `<id>`, or `generic`). `--history`
     optionally offers to purge git history (knowledge **and** backup repos). `--attest` optionally
     drafts a purge attestation + non-reversible internal stub (safety-net engineering record, never a
     legal assurance; output-only).
   - SCAN every surface, CLASSIFY each hit (ABSTRACT by default / DELETE only clearly client-specific /
     SURFACE for user decision), present the full plan as diffs, and **wait for explicit approval**.
   - Execute in the canonical order; run the **committed-knowledge safety check** before purging any
     capture; `--history` is opt-in: output the commands only; never run them.
   - Independent review brackets the run, using `bailiwick-security-review-local` (Read, Grep, Glob
     only; the main session runs the git and list commands and passes their output):
     - Step 3a (opus, high): the scan, classification, and draft plan.
     - Step 3b: an Advisor consult on a **redacted** plan. Before dispatch, `grep -ciE -f` the
       `tokens.ere` patterns file over the brief; it must print 0. Then
       `python3 -I "$BAILIWICK/scripts/purge_scrub.py" check --tokens <tokens-file> <brief>` must exit 0
       (`total: 0`): read-only, counts only, it also catches separator and URL/HTML/base64/hex-encoded
       variants.
     - Step 5a (opus, medium): the `purge_verify.sh residual` output after execution, with each
       surface recorded as `tool`, `manual`, or `not checked`. No tier is derived while any surface is
       `not checked`.

     Briefs stay minimal. Where Codex cannot delegate, run the review inline and label it "inline
     fallback — no independent review occurred"; record the Advisor as skipped. Reviewer output is
     never the approval.
   - Keep the tokens out of guarded command lines (the audit log records them verbatim):
     - Deletions go only through `scripts/purge_delete.sh` (dry run by default; `--apply` only after
       approval), reading a list file. The plan shows each list's count, sha256, and dry run. The
       approved sha256 (from `purge_delete.sh --print-sha`, which binds the list and `$W/from`; canonical
       `reference/execute.md`) is passed on the command line, and on a mismatch the script deletes
       nothing (exit 1). **Exit 3 (a FAILED line): STOP — do not commit, delete captures or purge
       backup blobs; see `execute.md`.**
       It acts only inside the allowed roots (`clients/<from>/`, `definitions/clients/<from>/`, a
       tracked surfaced `knowledge/` file whose frontmatter scope is `client:<from>`, capture
       `.jsonl`/`.md` files directly inside one of the 8 `/curate` gather or retire dirs — local
       `<repo>/.bailiwick-outputs/`, `.bailiwick-outputs/raw/`, `.bailiwick-outputs/.curated/`,
       `.bailiwick-outputs/raw/.curated/`, and central `$BAILIWICK_HOME/captures/<repo-key>/`,
       `<repo-key>/raw/`, `<repo-key>/.curated/`, `<repo-key>/raw/.curated/` (`<repo-key>` one path
       component; no deeper nesting) — and `.bailiwick-inbox/` files), with literal git pathspecs. It refuses empty or
       relative lines, `..`/`.`/`//` components, glob characters, symlinks, and anything else.
     - `purge_verify.sh residual --tokens-file` reads every token and 3a variant from the tokens file.
     - Commit messages and `/sign` slugs never name the client. Mandatory check before the commit:
       `grep -ciE -f "${BAILIWICK_HOME:-$HOME/.bailiwick}/purge-work/tokens.ere" <msg-file>` on the commit
       message file (`.git/COMMIT_MSG_<slug>` under `$bailiwick-sign`; the `-F <file>` otherwise) prints `0`, and
       `python3 -I "$BAILIWICK/scripts/purge_scrub.py" check --tokens "${BAILIWICK_HOME:-$HOME/.bailiwick}/purge-work/tokens" <msg-file>`
       exits 0; the
       same for the branch name, the slug, and any PR title and body (each written to a file in `$W`
       first). Any non-zero count or exit: reword, never commit, push, or open the PR.
     - The machine-local logs (audit log, health shards) are redacted in place, last (Step 5.7), with
       `purge_scrub.py scrub --apply` after a dry run; Codex denies the `--apply` (no ask), so the user
       runs that one command out-of-band, then the re-scan continues here.
   - Verify the hook dropped the session's capture and backup blob, and that the pending-retraction
     ledger and its spool files (`backup-retract.pending*`) are empty.
   - **User-run block, every run:** print canonical `reference/host-state.md` §5 as the last output,
     always including `bash "$BAILIWICK/hooks/capture_backup.sh" retract` and the per-blob
     `purge <machine>/<repo-key>/<sid>.{jsonl,md}.gpg` (both idempotent), plus the host-state deletion.
     The user runs it after the session ends, from a plain shell; never delete host state from inside
     the session. Codex's local session store location is not verified by the framework, so ask the
     user where it is.
   - The `--history` commands follow `docs/history-purge.md` §1: two passes (contents and messages,
     then token-named paths), ending with message, path, and ref checks.

## Guardrails

- Never run on agent initiative. Present the plan; execute only on explicit approval.
- Default is ABSTRACT — keep the reusable knowledge; delete only what is clearly client/project-specific.
- Never purge a capture until its sanitized knowledge is committed.
- Reviewers and the Advisor are read-only and advisory; only the user's explicit approval opens the gate.
- `--history` **outputs** the git-history-rewrite commands (`git filter-repo`, etc.) for **both** the
  knowledge and backup repos for the user to run themselves; the skill never executes them — history
  rewrite breaks satellites/clones.
- Erasure is **de-identified by default, not "fully erased"**: ciphertext persists in the backup repo's
  git history until it is rewritten or the gpg key is destroyed. `--attest` must report only the tier
  it can verify, and never assert legal sufficiency. In the purge session, host state and any history
  rewrite are "pending user action" and the tier stays `de-identified`. An upgrade takes a fresh
  `--attest` session (sentinel first; canonical `reference/attest.md` §5).
