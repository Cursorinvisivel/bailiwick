---
name: purge
description: Remove every reference to a client or project (`<id>`, `{org}` token, org name) from the knowledge library, captures, telemetry, and registry — re-attributing or genericizing the REUSABLE knowledge (keep how a problem was solved) while deleting only what is clearly client/project-specific. Human-gated and destructive. Use for client offboarding, a deletion request, or before sharing/publishing a library.
---

# /purge — de-identify a client or project (human-gated, destructive)

Strips a client/project's identity from the library while **preserving the operational knowledge**:
the reusable "how we solved X" stays (re-attributed or genericized), only the *linkage* is removed,
and only what is *clearly* client/project-specific is deleted. Read `$BAILIWICK/agents/memory.md`
(scopes, `clients/<id>/`, telemetry) and `$BAILIWICK/knowledge/context/org-shorthands.md` (the `<id>`
registry) first. This file holds the gates. The mechanics are in `$BAILIWICK/skills/purge/reference/`
(the **Ref** column); read each one when its step starts.

## Run card

| Step | Gate: the next step waits until this holds | Ref |
|---|---|---|
| 1.1 Sentinel | `mark_purge_session.sh` ran bare, as its own call, before anything else; the user confirmed the guardrail ask (Codex: typed `$bailiwick-purge`) | |
| 1.2 Wired? Role | the check prints `wired` (otherwise STOP and restart as in "Run location"); the role is recorded, and on `satellite` 5.3 is skipped and reported "pending central purge" | |
| 1.3–1.4 Tokens, `$W` | `$W` absent beforehand; created 0700; `tokens`, `tokens.ere`, `from` written | |
| 2 Scan | every surface counted, host state and any leftover `purge-work/` included | scan, host-state §2–3 |
| 3 Classify | ABSTRACT by default; DELETE only the clearly specific; SURFACE the rest | |
| 3a Review | `bailiwick-security-review-local` opus/high, or a labelled inline fallback | briefs §3a |
| 3b Advisor | redaction check printed `0`; `bailiwick-advisor` fable/high, or recorded skipped | briefs §3b |
| 4 PLAN / APPROVE | the user explicitly approves the full plan, target-list counts and sha256 included | execute |
| 5.1–5.6 Execute | in order; hashes re-checked; `purge_delete.sh` exit 3 = STOP; commit message, slug, branch, PR text each count `0` against `tokens.ere`; knowledge committed before any capture purge | execute |
| 5a Verify | residual + per-surface record; reviewer opus/medium or recorded skip; unexpected hit: STOP | scan, briefs §5a |
| 5b Own footprint | hook checks (1)–(3) recorded | host-state §4 |
| 5.7 Scrub | the last in-session action: logs redacted, re-scans print `0`, `$W` removed | execute |
| 6/7 Outputs | `--history` commands printed, never run; `--attest` drafts with host state and any rewrite "pending user action", tier `de-identified` | attest |
| 5b User block | printed every run, as the last output | host-state §5 |

**The final report includes this card as a filled table, `Step | done / skipped / blocked |
evidence`** (command output, count, or reason), one row per step, like the `/lead` execution table.
A step without evidence is `blocked`, never `done`.

## Paths and run location

`$BAILIWICK_HOME` (default `~/.bailiwick`) is the per-machine state root (central captures, audit
log, health shards), written `${BAILIWICK_HOME:-$HOME/.bailiwick}` in commands. `$W` is its
`purge-work/` directory; `$CC` is `${CLAUDE_CONFIG_DIR:-$HOME/.claude}`. Spell them out in every
command: shell state does not persist between tool calls.

**Run location.** Start the purge session from the Bailiwick clone with `BAILIWICK_SHADOW=1 claude`
(`BAILIWICK_SHADOW=1 codex` for Codex). That wires this one session and nothing persistent; the
signing and commit gate and the inbox location align with the clone; the hook skips the session's own
capture once the sentinel runs. Not from the client's repo: the session's project directory,
shadow-capture path, backup blob path, and retraction records would carry its name. **Not
recommended:** adding the clone to `$BAILIWICK_HOME/allowlist`, which wires every later session there,
so later `/curate` sessions (which read decrypted client captures) would be captured.

## Hard rules (do not violate)
- **Never run on agent initiative.** Purge is destructive and irreversible: it needs an explicit user
  request and an explicit approval of the plan in this session.
- **Default is ABSTRACT, not delete.** DELETE only what is clearly client/project-specific and cannot
  be meaningfully abstracted.
- **Never purge a capture until its sanitized knowledge is committed** (5.6). Captures cannot be
  sanitized in place; never destroy the source before the clean copy is in git.
- **Nothing is written or deleted without approval of the full plan.** Present diffs; wait.
- **Reviewers and the Advisor are read-only and advisory** (3a, 3b, 5a). They never write, delete, or
  execute; their output is never the approval; the main session alone executes. Briefs stay minimal
  (`briefs.md`): a brief is an identifier-bearing surface too.
- **Keep the tokens out of every guarded command line.** `hooks/guardrails.py` (`_audit`) logs each
  ask/deny/break-glass command to `$BAILIWICK_HOME/guardrail-audit.log` as submitted (whitespace
  collapsed, first 500 chars), before expansion and including any `VAR=value` in the same call
  (`D=<path>; rm -r -- "$D"` logs `<path>`). So guarded deletions read list files in `$W` written with
  the Write tool, and commits use `git commit -F <file>` with a generic message. Unguarded read-only
  commands (`grep -c`, `git grep -l`, `ls`) are not audited. Step 5.7 scrubs what slipped through.
- **One matching rule.** A token of 4 characters or fewer matches only on alphanumeric boundaries,
  case-insensitively (`adi` never hits "loading"); longer tokens match as case-insensitive substrings.
  `scripts/purge_scrub.py` implements it; every grep and count uses `grep -iE -f "$W/tokens.ere"`,
  never `grep -F -f tokens`; `purge_verify.sh residual` applies the same rule.
- **`$W` hygiene.** `$W` holds every token-bearing work file (tokens, `from`, target lists, the Advisor
  brief, the 5a copies). Create it 0700 (`umask 077`); Step 5.7 removes it. **Whenever the run ends
  early** (STOP, abort, declined plan), remove it with
  `rm -r -- "${BAILIWICK_HOME:-$HOME/.bailiwick}/purge-work"` (guarded, no token) and print that
  command in the report in case the removal was declined. A STOP that continues into a supplemental
  plan in the same session keeps `$W` until 5.7.
- **Deletions are confined.** Only through `scripts/purge_delete.sh` (`execute.md`): only the
  approved lists, only when they still hash to the approved sha256 given on its command line, only
  inside the allowed roots, never through a glob, dot or empty path component, or symlink. Anything
  else is refused and reported. Never `--apply` before the plan is approved.
- **The skill never deletes the purge session's own host state** (transcripts and the rest of `$CC`).
  It lists it and prints user-run commands (5b). The hook drops this session's capture and backup blob
  once the sentinel has run.

## Inputs
- `<from>`: a registry `<id>` (from `org-shorthands.md`, e.g. `wombat`; its `{org}` token and full org
  name are looked up so all three are detected), or a free-form identifier (repo name or project
  string) supplied literally.
- `--to <target>`: where the ABSTRACTED knowledge is re-attributed. **Default `acme`** (the own-org /
  not-client-owned placeholder); another registry `<id>` re-homes it; `generic` fully genericizes it
  (scope `generic`, no owner).
- `--history` (optional): also output the commands to purge the tokens from **git history** (Step 6).
- `--attest` (optional): draft a **purge attestation** and a non-reversible internal audit stub
  (Step 7). An engineering record, **not** a legal or compliance assurance; output-only, never sent.

## Procedure

1. **Mark, check wiring, resolve the tokens.**
   1. **First action, before any scan:** run `bash "$BAILIWICK/hooks/mark_purge_session.sh"` as its own
      Bash call, exactly as written (no arguments, nothing chained). The capture hook detects this
      sentinel and excludes the session from capture and backup however `/purge` was reached in Claude
      Code: typed, model-invoked, via `/lead`, or followed inline (on Codex it is denied; see below). It counts
      only once it has **run successfully** (the user confirmed the ask and the script printed
      `[bailiwick] purge session marked: …`); a declined ask leaves the session captured. Without it,
      only a user-typed `/purge` or `$bailiwick-purge` excludes the session: a model-invoked skill
      alone only holds the capture local (`purge_detection: error`, health `skill (unconfirmed)`), so
      the sentinel is never optional. Because it
      disables capture and deletes this session's earlier captures, **the guardrail asks the user to
      confirm it**: tell the user that confirmation is expected and what it does. It counts only in the
      main session (a subagent running it is ignored). **Codex** has no ask, so the guardrail denies it:
      that is fine when the user typed `$bailiwick-purge` (the hook detects the typed name). If the
      skill was chosen implicitly, STOP and ask the user to restart the session with `$bailiwick-purge`
      typed; do not relaunch with `BAILIWICK_BREAK_GLASS=1`, which lifts every guardrail for the
      whole destructive session. The skip's health line names only the detector (`slash command`,
      `sentinel`, `config`, plus any `… (unconfirmed)` ones).
   2. Check wiring:
      `python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import bw_common as b; print("wired" if b.is_bailiwick_repo(sys.argv[2]) or b.is_shadow_repo(sys.argv[2]) else "NOT wired")' "$BAILIWICK/hooks" "$PWD"`.
      On `NOT wired`, STOP (no guardrail confirmations, no capture exclusion): tell the user to end the
      session and restart it from the clone with `BAILIWICK_SHADOW=1 claude`.
      **Role.** `.telemetry.json` is central-owned: a satellite must never produce a telemetry delta
      (`scripts/doctor.sh`, `hooks/sync_knowledge.sh`). Read the role (absent file = `satellite`):
      `python3 -I -c 'import json,os,sys; p=sys.argv[1]; print((json.load(open(p)) if os.path.isfile(p) else {}).get("role") or "satellite")' "$BAILIWICK/.bailiwick-sync.json"`.
      On `central`, run every step. On `satellite`, **skip 5.3** (telemetry scrub and the confidence
      downgrades it drives) and report telemetry as **"pending central purge"**: the user re-runs
      `/purge <from>` on the central machine after this run's sync PR is merged, and there only 5.3
      (plus the 5a residual over `.telemetry.json`) has work left. 5a records telemetry as `not
      checked — pending central purge`, so no tier is derived on a satellite. Knowledge, `INDEX.md`,
      `## Related` and registry edits are fine on a satellite: they are ordinary knowledge commits and
      reach `main` through the `sync/<machine>` PR (`sync_knowledge.sh`); the PR title, body and branch
      follow the 5.5 identifier check.
   3. **Resolve the tokens.** Registry `<from>`: the `<id>`, the `{org}` token (it may differ, e.g.
      `wombat`→`wmb`), and the organisation name. Free-form: the literal identifier(s) the user gives.
   4. **Create `$W`.** If `${BAILIWICK_HOME:-$HOME/.bailiwick}/purge-work` already exists, STOP: an
      earlier purge never reached 5.7 and it may hold another client's tokens. Report its file count
      (`find … -type f | wc -l`), never its names, and let the user finish that run or remove it (print
      the command). Otherwise:
      `(umask 077 && mkdir -p "${BAILIWICK_HOME:-$HOME/.bailiwick}/purge-work/deleted")`. With the Write
      tool, not Bash, write `$W/tokens` (one per line; append the variants 3a finds) and `$W/from` (the
      `<from>` directory name). Generate the patterns, and regenerate after every append:
      `python3 -I "$BAILIWICK/scripts/purge_scrub.py" ere --tokens "$W/tokens" --out "$W/tokens.ere"`.

2. **Scan: enumerate every trace, count per surface, list-only** (`scan.md` has each surface's detail):
   `clients/<from>/`; `definitions/clients/<from>/` (count files, do not grep binaries); `scope:
   client:<from>`/`external:<from>` files; telemetry `distinct_projects_used[]`; inline mentions in
   `knowledge/`, `INDEX.md`, `## Related`; captures **by origin stamp, not path** (local raw, central,
   and the backup across every machine via `capture_backup.sh pull`, recording each matched blob
   rel-path); unstamped captures (content pass); the registry row; the audit log and health shards
   (local and `health/remote/`); `.bailiwick-inbox/`; a leftover `purge-work/`; host state under `$CC`
   (`host-state.md` §2, and §3 for this session's `<proj>`/`<sid>`); with `--history`, commits and ref
   names. Never print matched lines or `projects/` names.

3. **Classify each hit:**
   - **ABSTRACT (default)**: reusable knowledge with an inline client tie. Propose a rewrite that KEEPS
     the solution and re-attributes per `--to`: genericize (`for wombat's landing zone` → `for a
     landing zone`) or re-home (`… for <target-org>'s landing zone`). Retag `scope:` to `--to` or
     `generic`.
   - **DELETE**: the `clients/<from>/` files; the whole `definitions/clients/<from>/` subtree (build
     specs are never abstracted: surface a reusable rule inside one as a `knowledge/` candidate
     instead of keeping the file); all captures for this
     origin (they cannot be sanitized in place).
   - **SURFACE FOR DECISION**: `scope: client:<from>` files *outside* `clients/<from>/` (abstract and
     keep, or delete), and each **unstamped capture** (delete, or run `/curate` in de-identified mode
     first and then delete; see "Re-ingesting sanitized knowledge").

3a. **Independent plan review, before the plan is presented.** Dispatch
   `bailiwick-security-review-local` (Read, Grep, Glob only) at **opus, high** ("Size the stages" →
   *Edge* and *Shared reach* in `$BAILIWICK/skills/lead/SKILL.md`; pass model and effort as dispatch
   parameters) over the scan, the classification, and the draft plan with its order (`briefs.md` §3a).
   Fold each finding in as "added by review" or keep it as an open finding. The main session edits
   the plan; the reviewer does not.

3b. **Advisor on the plan, before approval.** Dispatch `bailiwick-advisor` (**fable, high**; read-only,
   never executes) with the **redacted** brief (`briefs.md` §3b). **Gate:** the brief is written to
   `$W/advisor-brief.md` and `grep -ciE -f "$W/tokens.ere"` over it prints `0`; dispatch exactly that
   text. Revise the plan once for its answer. If the revision is material (a new surface, or a
   DELETE/ABSTRACT flip), re-run 3a over the changed items only. Show unresolved disagreement to the
   human rather than iterating.

4. **Present the plan (single approval batch).** Every ABSTRACT rewrite as a diff; every DELETE; the
   telemetry scrub **and any resulting `confidence:` downgrades** (5.3); the registry-row removal;
   INDEX and `## Related` fixes; the capture purges; the 5.7 log scrub; with `--history`, the Step 6
   commands. Write `$W/targets` and `$W/targets-captures`, show each list's count and sha256 and the
   `purge_delete.sh` dry run (`execute.md`), and resolve every dry-run `skip` in the plan; the approval
   covers exactly those hashes. Add the **review record**: the 3a findings, the
   3b verdict, per stage its model/effort and mode (`delegated`, `inline fallback`, or `skipped`), and
   the user-run host-state surface (5b). **Fallback:** without delegation, run 3a inline, labelled
   "inline fallback — no independent review occurred", and record "Advisor: skipped (delegation
   unavailable)"; the human sees it and decides. **Wait for explicit approval.** Nothing has changed.

5. **Execute on approval, in this order:**
   1. **Abstractions**: rewrite files, retag `scope:` to `--to`/`generic`, and fix the `## Related`
      links and INDEX rows that pointed at abstracted or deleted notes.
   2. **Delete** the clearly client-specific files: `purge_delete.sh --apply` over `$W/targets` with
      the approved sha256 (computed with `purge_delete.sh --print-sha`, which binds the list and
      `$W/from`; `execute.md` defines both). On a hash mismatch it deletes nothing and exits 1: STOP.
      **Exit 3 (a FAILED line): STOP — do not commit, delete captures or purge backup blobs; see
      `execute.md`.** Report every `skip` line.
   3. **Scrub telemetry, then re-evaluate confidence** (**central only**; on a satellite skip this
      step and report "pending central purge", see 1.2). Remove the id from every
      `distinct_projects_used[]`. For each touched id, re-check the remaining projects against the
      graduation evidence (medium = used in ≥1 project; high = stable across 3+ distinct projects) and
      **downgrade frontmatter `confidence:` where it no longer holds** (a `high` under 3 → `medium`).
      These downgrades were in the plan, never applied silently.
   4. **Remove the `org-shorthands.md` registry row LAST** (it was needed for detection).
   5. **Commit** the knowledge and definitions changes (`knowledge:` prefix; needs approval). **The
      message never names the identifier** (no id, org name, token, or token-bearing path): use
      generic wording such as `knowledge: de-identify a client (purge)`, also for a `--to`
      re-attribution. Commit with `git commit -F <file>`; in a signing repo use `/sign` with a generic
      slug (e.g. `purge`). **Mandatory identifier check before the commit runs:**
      `grep -ciE -f "${BAILIWICK_HOME:-$HOME/.bailiwick}/purge-work/tokens.ere" <msg-file>` on the
      commit message file (`.git/COMMIT_MSG_<slug>` under `/sign`; the `-F <file>` otherwise) must
      print `0`. Check the branch name, the slug, and any PR title and body the same way before
      use (write each to a file in `$W` with the Write tool and grep it; `printf … | grep` would put
      a candidate identifier on the command line). Any non-zero count: reword and re-check; never
      commit, push, or open a PR on a non-zero count.
   6. **Committed-knowledge safety check, then purge captures.** Verify the commit exists and
      `git status` is clean for the touched files. If not, STOP and report: never purge the source
      first. Then delete `$W/targets-captures` the same way (its own approved sha256), and purge every
      backup blob matched in Step 2 by its rel-path, sweeping every `<machine>/` subtree (`execute.md`).
      This clears the current backup tree, **not the backup repo's git history** (Step 6 tiers).
   7. **Scrub the machine-local logs: the LAST in-session action**, run **after 5a and the 5b
      checks** and before the Step 6/7 output (every guarded command adds an audit line, so an earlier
      scrub leaves lines behind). No other Bailiwick session may run meanwhile. Preview with
      `purge_scrub.py scrub` (a dry run by default), then redact the audit log and health shards in
      place with `purge_scrub.py scrub --apply` (the guardrail asks; the script refuses any target but
      `$BAILIWICK_HOME/guardrail-audit.log` and `$BAILIWICK_HOME/health/**`, and any symlink),
      re-scan (each count prints `0`), then
      remove `$W` (`execute.md`). **No guarded command after this step.** If one runs anyway (a 5a
      supplemental fix, a further commit), recreate `$W` (1.4), re-run scrub and re-scan, remove `$W`.

5a. **Verify, then independently confirm** (after 5.6, before 5.7).
   1. Run `bash $BAILIWICK/scripts/purge_verify.sh residual --tokens-file "${BAILIWICK_HOME:-$HOME/.bailiwick}/purge-work/tokens"
      [--backup-path <machine>/<repo-key>/]...` (one per matched subtree). The file carries every
      token and every 3a variant, so none is on the command line. Cover what it cannot see
      (`scan.md`, last section). **Record each Step 2 surface** as `tool`, `manual` (name the search),
      or `not checked`. A surface with a later clearing step keeps its count and names it (audit log,
      health, inbox: 5.7; host state: pending user action, 5b). Derive the tier **only when no surface
      is `not checked`**; otherwise report "tier not derivable — <surfaces> not checked".
   2. Dispatch `bailiwick-security-review-local` at **opus, medium** (mechanical input; `briefs.md`
      §5a). **Skip it only if** the residual is clean beyond what the tier expects **and** no DELETE
      removed a content file; record the skip and both reasons.
   3. Residual hits expected for the tier (git history, backup history, `refs/pull` without
      `--history`) are reported as such. **Anything else, or reusable knowledge lost: STOP and
      report.** Fixes go through a supplemental plan and the same approval gate; reviewer findings
      never trigger edits. Lost tracked files are recoverable from git; deleted captures are not, which
      is why 3a runs before the captures are purged. If the run ends here, remove `$W`.
   Fallback as in Step 4: inline, labelled "inline fallback — no independent review occurred".

5b. **The purge session's own footprint.** This session holds the identifiers verbatim (plan diffs,
   briefs, reviewer and Advisor reports).
   - **Capture and backup blob: the hook handles them.** Verify, do not assume: run and record checks
     (1)–(3) of `host-state.md` §4.
   - **User-run block, unconditional:** print `host-state.md` §5 **every run**, as the last output, with
     the tokens, `<proj>`, `<sid>`, `<machine>`, and `<repo-key>` substituted. It always includes
     `bash "$BAILIWICK/hooks/capture_backup.sh" retract` and the per-blob
     `purge <machine>/<repo-key>/<sid>.{jsonl,md}.gpg` (both idempotent), plus the host-state listing,
     deletion, and `history.jsonl` redaction. The user runs it after this session ends, from a plain
     shell. Host state is reported as **pending user action**, never as clean.

6. **(`--history`) Purge git history: OUTPUT the commands, never run them.** A rewrite is **brutally
   destructive**: every commit hash changes, and satellites and open sync PRs must **re-clone**. The
   skill never executes the rewrite, `git rm` on history, or `filter-repo`. Point the user to
   `docs/history-purge.md` and print a ready-to-run block (plain shell, history off) that:
   - **starts with the preflight gate**, `bash scripts/purge_verify.sh preflight`: deep removal never
     destroys un-curated captures, so it blocks while any machine's staging or `capture/*` backup branch
     holds pending blobs, or a `purge-work/` is left over. If it lists this session's capture, the 5b
     user block runs first;
   - covers the **knowledge repo** per §0 (token files) and §1 (Path A: two passes in a fresh clone,
     contents and messages, then token-named paths; or Path B, the orphan squash), ending with the §1
     post-rewrite checks (messages, paths, ref names), each printing `0`, and `residual`;
   - covers the **backup repo**: do NOT skip it if erasure matters. Prefer **crypto-erasure** (§2),
     which reaches copies a rewrite cannot chase. Key destruction erases contents only: blob paths
     stay plaintext and name the repo. If the repo key carries a token, the §2 rewrite is required too;
   - wraps them: back up each repo first, force-push afterwards, every clone and mirror re-clones; and
     the **host-side residuals** note (§3): objects stay fetchable by SHA until server GC, and
     `refs/pull/*` pins them permanently; guaranteed removal needs a host support request.

   **Erasure tiers: never over-claim**; report only what was *actually run*.
   - **De-identified** (Steps 1–5, no `--history`): working trees are clean and the current backup tree
     no longer holds the blobs, **but ciphertext persists in the backup repo's git history**. The
     default, honest claim, and the ceiling while any 5b host-state item remains or any surface is
     `not checked`.
   - **Fully erased**: only after the backup-repo history is rewritten on **all** remotes **and/or** the
     gpg key is destroyed (a token in the repo key needs the rewrite regardless). Derived from
     verifiable state, never an operator assertion: `residual … --backup-path …` clean, the
     post-rewrite checks at `0`, and no 5b host-state item left. If `refs/pull` is still counted, the
     claim stays "removed from all refs we control".

7. **(`--attest`) Purge attestation: draft only, never sent** (`attest.md`). An **engineering record,
   not a legal or compliance assurance**. Recreate `$W` (1.4) and re-scan **every** Step 2 surface
   with `tokens.ere`, count-only; the backup is scanned by streaming decryption, never by `pull`
   (which would refill `health/remote/` and the inbox). Any non-zero surface: STOP, do not attest. A
   `not checked` surface is named, never reported clean, and blocks the tier. **In this session**, the
   5b user block and any Step 6 commands cannot have run yet: the attestation records them as
   **"pending user action (printed below)"** and the tier stays **`de-identified`**. Upgrading it later
   takes a **fresh `/purge --attest` session** (sentinel first) in which the user confirms those ran
   and the re-scan, `$CC` included, reads `0` (`attest.md` §5). Derive the tier, never assert it.
   Draft (A) the client-facing attestation (handed over, not retained) and write (B) the salted-hash
   internal stub to `$BAILIWICK_HOME/purge-audit/` (no client name, no content).

## Re-ingesting sanitized knowledge
If useful operational knowledge is still only in the captures (not yet promoted) when you purge, run
**`/curate` in de-identified mode first** (see `skills/curate/SKILL.md` → De-identified mode): it
promotes the knowledge with **no** client/project identifiers, so the reusable content is preserved
generically before the identifying captures are destroyed.

## Guardrails
The hard rules and the run-card gates are the guardrails: keep the solution, discard the linkage;
review is disclosed, never silent, and never the approval; `--history` and `--attest` only output.
- **Scope boundary: not GDPR-grade erasure.** Purge covers what Bailiwick stores (library, telemetry,
  local and central captures, current backup tree) and *outputs* the history-rewrite commands for the
  knowledge and backup repos. By default it is **de-identified, not fully erased**: ciphertext persists
  in the backup repo's git history until it is rewritten or the gpg key is destroyed. It does NOT reach
  forks, others' clones, remote caches, or CI/build artefacts. Frame it as de-identification /
  offboarding, not legal-grade deletion.
