---
name: learn
description: Onboard an existing repository's knowledge at bootstrap time — scan the repo (decisions, IaC patterns, conventions, pitfalls) and distill the findings into a pre-digested capture staged exactly where /curate gathers, so promotion rides the standard capture→curate human-gated pipeline. Writes NO knowledge itself. Use once after bootstrapping an existing project, alongside /enrich (which drafts instruction files; /learn drafts knowledge candidates).
---

# /learn — project onboarding → knowledge candidates

Onboard what an **existing repository already knows** into the Bailiwick pipeline. Where the
capture hooks learn a repo *organically* (session by session, over weeks), `/learn` front-loads
that: one deliberate scan at bootstrap time, distilled into a **pre-digested capture** that
`/curate` then promotes under the normal human gate.

It is the third leg of onboarding an existing project:

| Step | Tool | Output |
|---|---|---|
| Wire | `bootstrap.sh <repo>` | MCP + complements + capture staging |
| Instruct | `/enrich` | instruction files (CLAUDE.md baselines + hidden complements) |
| **Learn** | **`/learn`** | **knowledge candidates, staged as a capture** |
| Promote | `/curate` | gated writes to `$BAILIWICK/knowledge/` |

`/learn` and `/enrich` share the scan posture but target opposite sides of the boundary: `/enrich`
writes **instruction files into the repo**; `/learn` writes **one capture file into the dirty
zone** for the library. Neither touches `knowledge/`.

## Hard rules (do not violate)
- **Never write to `$BAILIWICK/knowledge/`.** `/learn` has no promotion path of its own — its only
  output is a capture in enforced staging. The human gate lives in `/curate`, and `/learn` must not
  duplicate or bypass it.
- **Never commit or push.** The capture staging is gitignored/central by design; there is nothing
  to commit.
- **The capture is dirty-zone data.** Client-identifying detail (project IDs, org names, real
  buckets) is *allowed* in it — abstraction and `clients/<id>/` routing happen at `/curate`, same
  as for any raw capture. Never promote it unsanitised; never commit it.
- **Distill, don't transcribe.** A candidate is reusable knowledge — a decision *with its
  rationale*, a non-obvious pattern, a pitfall and its workaround. Restating what the repo's own
  docs/READMEs already record is not a candidate (the KB rule: don't store what the repo stores);
  *reference* repo docs in provenance instead.

## Procedure

1. **Preflight.**
   - Confirm the repo is Bailiwick-wired: a complement referencing `$BAILIWICK`
     (`CLAUDE.local.md` / `.bailiwick.local.md` / `.github/instructions/bailiwick.instructions.md`)
     ⇒ **seeded**; else `BAILIWICK_SHADOW=1` or the repo root listed in `~/.bailiwick/allowlist`
     ⇒ **shadow**. If neither, tell the user to run `bootstrap.sh <repo>` first and stop.
   - Resolve the staging dir — the same split `capture_session.py` uses (seeded wins if both):
     - **seeded** → `<repo>/.bailiwick-outputs/`
     - **shadow** → `~/.bailiwick/captures/<repo-key>/` (`$BAILIWICK_HOME` if set). Compute
       `<repo-key>` from the single source of truth, exactly like `session_start.sh` does:
       `PYTHONPATH="$BAILIWICK/hooks" python3 -c 'import sys, capture_session; sys.stdout.write(capture_session.repo_key(sys.argv[1]))' <repo>`
   - **Check for a prior learn capture** (`learn-*.md` in the staging dir, its `.curated/`, or the
     shadow equivalents). If one exists, this is a re-run: scan only for what changed since its
     `commit:` stamp and say so — never stack a second full capture of the same repo for `/curate`
     to dedup twice.

2. **Load the map.** Read `$BAILIWICK/knowledge/INDEX.md` (usually already injected at
   SessionStart; descend into a domain sub-index only if clearly relevant). This is a **pre-dedup
   hint, not the dedup** — the mandatory dedup stays in `/curate` Step 4. Use it to mark each
   candidate: likely **NEW**, likely **EXPAND** of an existing id, **validates** an existing topic
   (retrieval evidence, not a new file), or **contradicts** one (high-value — flag it explicitly).

3. **Scan the repo (autonomous, scaled to its size).** Use the domain context files
   (`gcp.md` / `kubernetes.md` / `serverless.md` / `data.md` / `cicd.md`) as the "what to look
   for" checklist — same posture as `/enrich` Step 2, but hunting **reusable knowledge**, not
   project profile.

   **Inventory first, then batch — never one global pass over a large repo.** Start with a cheap
   inventory (directory tree, file counts, where the knowledge-dense files live: ADRs/docs,
   `*.tf`, pipeline files, long-lived modules). Then pick the scan shape:
   - **Small repo** (roughly ≤ 20–30 knowledge-relevant files): a single scan pass is fine.
   - **Larger repo:** partition the inventory into **bounded batches** — by directory or domain,
     ~10–15 files each — and scan one batch at a time (one Explore delegation per batch works
     well; a knowledge-dense file, e.g. a large ADR set, can be a batch of one). After **each**
     batch, immediately distill its findings (Step 4 filter applied) and **append them to a
     working notes file outside the repo** (the session scratchpad). The batch's raw reading is
     then disposable — nothing depends on it staying in context. Long-context recall over a
     30-file read loses early findings to compression/truncation; the working file is the memory,
     not the context window. The final capture (Step 5) is authored **from the working notes**,
     merging duplicates across batches — never from memory of the scan.

   Look for, at minimum:
   - **Decisions with rationale:** ADRs, design docs, "why we did X" in READMEs/comments/PR-style
     commit messages — the rationale is the candidate, not the decision alone.
   - **IaC patterns in evidence:** module composition and reuse constructs, state/backend layout,
     naming + labelling schemes, per-environment wiring — anything another project could copy.
   - **Pitfalls & workarounds:** `# HACK`/`# WORKAROUND`/`NOTE:` comments, pinned-version
     explanations, retry/timeout tuning, provider quirks worked around.
   - **Undocumented engineering — read the code itself, not just its annotations.** Interpret the
     code like a reviewer hunting for things worth stealing: an unusual or elegant solution to a
     hard problem, a non-obvious technique or construct, a data structure or composition trick
     that no comment or doc explains. These are often the highest-value candidates precisely
     *because* nobody wrote them down. Three rules for these: (a) judge whether it is deliberate
     technique or an accident/anti-pattern — when unsure, still record it but say so; (b)
     code-derived candidates have **inferred intent**, so mark their provenance `inferred from
     code` (vs a documented source) — the `/curate` reviewer then knows to validate the
     interpretation, not just the wording; (c) **quote the evidence, sanitized at extraction**:
     include in the candidate the minimal code excerpt that grounds the inference, with
     identifying values swapped for common placeholders — org/client names → `acme`, project/env
     identifiers → generic (`project`, `dev`/`prd`), resource names → the resource *type* itself
     (`load-balancer`, `bucket`, `service-account`) — while keeping the structure and logic
     intact (the technique is the point, not the identifiers). The reviewer then sees exactly
     what the conclusion rests on without opening the repo, and the excerpt is already in
     promotable, generic form. Provenance keeps the *real* path/SHA — sanitize the quote, never
     the pointer.
   - **CI/CD lifecycle patterns:** how plan/apply is gated, promotion between environments,
     drift handling.
   - **Conventions in evidence** not written down anywhere (structure, naming, commit style) —
     candidates for `context/` or a client project-map.
   - **History signals (cheap pass):** notable fix/revert commits whose messages explain a
     non-obvious failure mode.

4. **Distill candidates.** In batched mode this step runs **per batch** (into the working notes
   file), plus a final merge pass over the notes; in a single-pass scan it runs once. For each
   finding worth keeping, apply the filter (Hard rules →
   distill, don't transcribe; skip what any repo would show) and record: a title, proposed type
   (`topics/` | `patterns/` | `context/` | `clients/<id>/`), tentative `scope` (`generic` vs
   `client:<id>`), suggested tags, the dedup hint from Step 2, the distilled insight itself
   (a few paragraphs max), and **provenance** (file paths / commit SHAs). Quality over volume —
   a handful of real candidates beats an inventory.

5. **Write the capture.** One markdown file, `learn-<UTC yyyymmdd-HHMMSS>.md`, in the Step 1
   staging dir — authored from the Step 3/4 working notes when the scan was batched (then discard
   the notes file; the capture supersedes it) — the **manual session-output channel** `/curate` Step 1 already gathers
   (`.bailiwick-outputs/*.md`, or `~/.bailiwick/captures/<repo-key>/*.md` in shadow mode). No new
   pipeline, no gate needed for this write (it is enforced dirty-zone staging). Format — header
   mirrors the auto-capture headers; the `## Candidates for Promotion` heading is load-bearing
   (it is what memory.md Step 1 extracts):

   ```markdown
   # Learn capture — <repo name>

   - captured: <ISO timestamp>
   - skill: learn
   - mode: seeded | shadow
   - project_dir: <path>
   - origin_remote: <git remote or (none)>
   - project: <project_id — CLAUDE.md identity if present, else repo name>
   - commit: <git rev-parse --short HEAD>

   ## Candidates for Promotion

   ### <title>
   - proposed_type: topics | patterns | context | clients/<id>
   - proposed_scope: generic | client:<id>
   - tags: [...]
   - dedup_hint: NEW | EXPAND <id> | validates <id> | contradicts <id>
   - provenance: <paths / SHAs; append `(inferred from code)` for code-derived candidates>

   <the distilled insight>

   <for a code-derived candidate, a fenced `evidence` block: the minimal sanitized excerpt
   (acme / resource-type names) that grounds the inference — see Step 3>

   ## Retrieval Feedback
   - project: <project_id>
   - missed: [<KB ids or short descriptions of knowledge that would have helped this scan>]

   Pending curation. Run `/curate` to review and promote (human-gated).
   ```

   Present the candidate list (titles + types + scopes) to the user as a summary of what was
   staged.

6. **Hand off to `/curate`.** Tell the user to run `/curate` — typically immediately, completing
   the onboarding sequence. Two properties of the flow worth stating:
   - **Safety net:** this session's own Stop/SessionEnd raw capture records the full scan
     transcript, and its pending-`jsonl` nag is what reminds about curation — the learn `.md` is
     the pre-digested primary input, the raw capture the fallback.
   - **Durability:** like all manual-channel session outputs, the learn `.md` is *not* in the
     encrypted off-machine backup (`capture_backup.sh` pushes `raw/` only) — one more reason to
     curate promptly rather than let it sit.

## Notes
- **`/learn` vs `/investigate`:** `/investigate` researches *external* references/needs and
  proposes KB candidates directly under its own gate; `/learn` reads *this repo* and stages
  through the capture pipeline — the user's chosen flow, so onboarding knowledge is reviewed
  exactly like organically captured knowledge.
- **`/learn` vs `/enrich`:** run both on an existing project; they are complementary, not
  alternatives. `/enrich` may surface candidates too ("genuinely reusable patterns discovered
  here should still be promoted via /curate") — `/learn` is the systematic version of that note.
- Codex wrapper: `$bailiwick-learn` (`codex-skills/bailiwick-learn/`).
