---
name: curate
description: Distill pending raw session captures (.bailiwick-outputs/raw/) and agent outputs (.bailiwick-outputs/) into the Bailiwick knowledge library under a human gate. Use when the SessionStart hook reports pending captures, or to run the Periodic Curation Session (every 6-8 weeks).
---

# /curate — gated knowledge curation

This skill runs the **Memory stage Collect flow** on demand. It is the human-gated
review step that turns enforced raw capture into curated knowledge. Read
`$BAILIWICK/agents/memory.md` first — it is the source of truth for
the Collect, dedup, approval-routing, and Periodic Curation logic. Follow it exactly.

**Paths:** `$BAILIWICK_HOME` (default `~/.bailiwick`) is the per-machine state root — central captures, audit
logs, health shards. Every path below is spelled under it; resolve the variable, never the literal.

**Runnable from any wired repo.** It reaches the dirty pool (via `capture_backup.sh pull`) and the
knowledge library by **absolute path**, so one invocation processes the whole centralized encrypted
pool — captures from *all* machines/repos — plus the current repo's own local `.bailiwick-outputs/`. The
active repo is not special; it only adds its local captures. Decrypting the cross-repo pool needs the
gpg private key, so full centralized curation runs on the machine that holds it.

## Hard rules (do not violate)
- **Delegated stages never write and never gate.** Steps 2a and 5a subagents only return candidates or findings; every knowledge write, the approval batch, and retirement stay in the main session. No dispatch happens before Step 0 passes.
- **No web-capable or shell-capable stage runs while `.bailiwick-inbox/` holds plaintext.** Restored captures are decrypted there (Step 1). Only the Step 2a distillers (`bailiwick-memory`: Read/Grep/Glob, no web, no shell) may read the inbox; the main session deletes the decrypted copies right after candidate extraction and **before any Step 5a dispatch** (see the inbox cleanup under Step 2a), and Periodic-mode freshness research is collected before the restore (Step 1). Step 8 then only retires the originals.
- **`bailiwick-quality` keeps Bash, and plaintext captures stay readable by it.** Captures in `.bailiwick-outputs/` and `$BAILIWICK_HOME/captures/` are not hidden from it by any tool restriction; the control is the brief (supporting excerpts only, no reads of capture paths), which is a policy control, not a tool restriction.
- **Never** write to `$BAILIWICK/knowledge/` content files without explicit user approval in this session. The library is human-gated.
- `.telemetry.json` is the ONLY knowledge file written without approval (commit with `telemetry:` prefix).
- Never duplicate: check INDEX.md tags AND read candidate files before any write (NEW / EXPAND / IMPROVE / SKIP).
- Raw captures in `.bailiwick-outputs/raw/` are unsanitised and may contain client IAM, project IDs, or secrets. Abstract to generic before promoting; route client-identifying detail to `clients/<id>/`. Never commit raw captures.
- **Step 0 is mandatory and comes before everything else** (ADR-009): run `bash $BAILIWICK/hooks/public_origin.sh check`. **Exit 3 = contribute-only clone — ABORT immediately**, before gathering or extracting anything. Report the reason to the user and stop; captures stay staged and curate normally once the instance is private (see [staying-private.md](../../docs/staying-private.md)). Do not work around this by writing knowledge files directly — the block exists because `knowledge/` is tracked, so promoting here would publish it.

## Procedure

0. **Public-origin gate (ADR-009) — run this first, always**
   - `bash $BAILIWICK/hooks/public_origin.sh check`
   - Exit 0: proceed. Exit 3: **STOP.** Show the printed reason, tell the user their captures remain
     staged and nothing was extracted, and end the session. Never fall through to Step 1.

1. **Gather inputs**
   - List `.bailiwick-outputs/raw/*.jsonl` (enforced transcript captures) and their `.md` headers.
   - **Shadow-mode captures** (FRAMEWORK.md §7.1): also list `$BAILIWICK_HOME/captures/*/raw/*.jsonl`
     (auto Claude Code captures) **and** `$BAILIWICK_HOME/captures/*/*.md` (manual Codex/Gemini session
     outputs) — `$BAILIWICK_HOME` is the staging root. Repos wired in shadow mode
     stage centrally, keyed by origin repo, not in any `.bailiwick-outputs/`. The auto-capture `.md` headers
     carry `mode: shadow` + `origin_remote` — use those to judge scope (`generic` vs `client:<id>`)
     since the repo path is not self-identifying. Include them in the candidate gather exactly like
     in-repo captures.
   - List `.bailiwick-outputs/*.md` (agent session outputs, if any — including `learn-*.md`
     onboarding captures staged by `/learn`, which arrive pre-digested with a
     `## Candidates for Promotion` section and dedup hints).
   - Also snapshot completed GCP freshness reports from `$BAILIWICK/.bailiwick-outputs/gcp-freshness-*.md`
     in the **framework root**, even when invoked from a client repo. Include only `status: completed`;
     exclude `running`, `partial`, and `failed` reports from extraction and retirement. Take this
     snapshot **before** dispatching new research, so this run's report waits for a later curation.
     Apply this status filter to freshness reports encountered through **any** gather path,
     including the generic agent-output glob, and deduplicate resolved paths.
   - **Periodic mode only — dispatch freshness research first.** After the public-origin gate
     and the snapshot above, launch the
     [GCP freshness check](references/gcp-freshness.md) **before** restoring off-machine captures.
     Its procedure selects notes from the KB index before dispatch. Only the tool-restricted
     `bailiwick-cloud-research-freshness` agent under Claude Code may overlap the restore and other
     capture processing (native asynchronous delegation). Never fall back to the general Cloud
     Research stage without the user's explicit go-ahead for this run (see the procedure). With any
     agent that can read files — that fallback, or a generated Gemini/Codex/Copilot adapter — **collect the freshness result
     before running the restore**, so no file-reading agent with web access runs while decrypted
     plaintext lands in `.bailiwick-inbox/`. Disclose sequential/inline fallback.
   - **Restore off-machine captures** (if `capture_backup` is enabled in `.bailiwick-sync.json`): run
     `bash $BAILIWICK/hooks/capture_backup.sh pull` — decrypts every backed-up blob
     (from any machine) into `$BAILIWICK/.bailiwick-inbox/raw/<machine>/<repo>/…` (needs the gpg private
     key + passphrase). Include these in the candidate gather. `.bailiwick-inbox/` is gitignored — never commit it.
   - **Held captures.** A capture whose `.md` header has `- purge_detection: error` is one the
     capture hook could not classify (it could not tell whether the session was a `/purge`); it is
     held local and never backed up. List these **separately** from the ordinary gather and ask the
     user, per capture, before any extraction or subagent brief: **delete** it, **curate it in
     de-identified mode**, or **curate normally** once the user confirms it was not a purge session.
     Never read, extract from, or brief a held capture silently, and never fold it into the gather.
   - Read `$BAILIWICK/knowledge/INDEX.md`.
   - If there is nothing pending, say so. Stop for ordinary curation; **periodic mode continues**
     (freshness research was already dispatched above).

2. **Extract candidates** — from each capture, pull decisions, non-obvious patterns, validated assumptions, pitfalls, and Retrieval Feedback (loaded / used / missed). Research-only and conversation-only sessions still count. **Federation ingest:** external knowledge consulted from a `.bailiwick-sources.json` source is also an ingest candidate — follow `agents/federation.md` (abstract, never transclude; add `source:` + `## Provenance` + `scope: external:<id>`; route through this same approval batch; never write back to the source).

   Distinguish freshness-maintenance reads from project reuse before applying feedback. The
   capture hook can mechanically credit any KB read; exclude freshness-only IDs from reuse
   credits per Memory's freshness exception, retaining independently evidenced project usage.

2a. **Distill in fresh contexts (large inputs only)** — keeps long raw transcripts out of the main
   session. **Threshold:** use 2a when there are more than 2 raw captures, or any capture over ~200 KB;
   otherwise extract inline as in Step 2. When it applies, dispatch `bailiwick-memory` in its **Collect** operation,
   one dispatch per capture batch (group small captures, give an oversized one its own), all
   concurrently, each at **sonnet, low** ("Size the stages" in
   [skills/lead/SKILL.md](../lead/SKILL.md) is the sizing source of truth; pass model and effort as
   dispatch parameters). Brief each with the capture path(s), the Step 2 extraction targets
   (including Retrieval Feedback), the dedup hints from the Step 1 INDEX read, and the active mode
   (below). It returns **candidates only**: type, draft, source capture, provenance, confidence,
   plus its Retrieval Feedback lines. It does no KB reads beyond the supplied hints and writes
   nothing. The main session still owns Federation ingest candidates, telemetry (Step 3), dedup
   (Step 4), and routing (Step 5); treat returned drafts as unverified input, never as approved.
   - **De-identified mode:** the brief instructs the subagent to abstract at extraction and return
     no client/project identifiers (no org names, `<id>`/`{org}` tokens, project IDs); if it cannot
     abstract a candidate it returns `needs-main-review` with a pointer, never a verbatim quote.
     The subagent still *reads* the raw capture, so its transcript (a local file under the host's
     per-session store, e.g. `~/.claude/projects/`) holds the identifiers — the same exposure as
     the main session reading them, but in an extra file `/purge` does not enumerate. Disclose this
     in the report; for a `/purge` routine, treat those host transcripts as residual surface.
   - **Fallback:** where delegation is unavailable (host or Codex wrapper cannot spawn), extract
     inline per Step 2 and record "inline fallback" in the curation report.
   - **Inbox cleanup (both the inline and the 2a path; Hard rules).** Once every candidate is
     extracted and the 2a subagents have returned, first list each restored blob as
     `<machine>/<repo>/<file>.gpg` (Step 8 needs it to purge the blob), then delete this run's
     decrypted copies under `$BAILIWICK/.bailiwick-inbox/` (the guardrail re-confirms a recursive
     `rm`). Nothing after this point reads the inbox: candidate drafts and the exact supporting
     excerpts stay in the main context for Steps 4–7 and the Step 5a briefs, and the ciphertext
     stays in the backup repo until Step 8, so no unreviewed input is lost. If a later step needs
     more of a source, re-run `capture_backup.sh pull` for it rather than keeping plaintext around.

3. **Update telemetry + reconcile (no gate)** — **central machine only; on a satellite (`.bailiwick-sync.json` role ≠ `central`) skip this entire step — telemetry is central-owned (see docs/operations.md → Multi-machine sync).** Apply `Retrieval Feedback` to `.telemetry.json` per memory.md Step 2, then **reconcile**: every `id`-bearing content file (`topics/`, `patterns/`, `context/`, `clients/`) must have a telemetry row — seed a zero-row for any missing id, and flag orphan rows (a row whose id has no file) for removal. This is the only unattended write. (The framework's own ADRs live outside the library in `docs/decisions/` — status-tracked, not part of this reconcile.)

4. **Dedup (mandatory)** — for each candidate, search the index by tag/scope (descend into the relevant domain sub-index under `indexes/` if that domain is sharded), READ any overlapping file, and decide NEW / EXPAND / IMPROVE / SKIP. Never create a second file for an existing topic.

5. **Route by confidence (memory.md Step 4)**
   - NEW file → surface for approval now.
   - IMPROVE that contradicts existing content → surface for approval now.
   - EXPAND / non-contradicting IMPROVE → hold for the digest (mention count, do not block).
   - SKIP → silent.

5a. **Independent review of the candidate set (before the batch)** — promotion has shared reach
   (every later session loads it), so the candidates written in this run get an independent
   review. **Scope:** only the candidates that will be written in this run, meaning the blocking
   ones from Step 5; in Periodic mode also the held EXPAND/IMPROVE digest batch. SKIP and held
   non-periodic candidates are not reviewed. **Skip 5a when nothing blocking survives** (and no
   digest batch is applied) and record "5a: skipped — no blocking candidates" in the curation
   report. Dispatch only after the inbox cleanup (Hard rules).
   - **Sizing** ("Size the stages" tiers in [skills/lead/SKILL.md](../lead/SKILL.md); pass model and
     effort as dispatch parameters, one choice for the whole set, driven by its riskiest member):
     **sonnet, medium** for one or two generic NEW/IMPROVE candidates with no security tags;
     **opus, medium** by default; **opus, high** when any candidate is client-scoped, contradicts
     existing content, is security-tagged, or is a new `patterns/` or `context/` file.
   - **Reviewers.** Dispatch `bailiwick-quality` over the set: accuracy against the source
     capture, duplicate/conflict with existing KB, client identifiers or secrets that sanitisation
     missed, overclaimed confidence. When any candidate concerns IAM, network exposure, secrets,
     or data exposure, add the no-network, no-shell **`bailiwick-security-review-local`**
     (Read/Grep/Glob only; same sizing, concurrently), never the general `bailiwick-security-review`.
     `bailiwick-quality` has Bash (no web): brief it with excerpts only and tell it not to run
     commands that read capture paths (`.bailiwick-outputs/`, `$BAILIWICK_HOME/captures/`, the inbox).
   - **Brief requirements.** Give each candidate an id (`c1`, `c2`, ...) and pass the candidate
     drafts, the exact source excerpts that support each (not whole captures), and the Step 4
     overlapping-file ids. Each reviewer returns, besides prose, one line per flagged candidate:
     `FLAG <candidate-id> leak|secret|duplicate|accuracy|confidence: <reason>`, so findings can be
     counted later. Reviewers are read-only and never write; their findings are shown to the
     human **alongside** the Step 6 batch, per candidate, and are advisory: nothing auto-drops or
     auto-edits, the human decides.
   - **De-identified mode:** excerpts in the brief must be abstracted too (identifiers redacted
     to placeholders), so the reviewer cannot echo identifiers into its report or transcript;
     accuracy is then judged against the redacted excerpt and the report says so. Do not
     pass raw captures to reviewers in this mode.
   - **Standard mode:** excerpts may carry client detail destined for `clients/<id>/`; keep them
     minimal and exclude secrets (redact credential values before briefing).
   - **Fallback:** where delegation is unavailable, perform the same checks inline and label the
     batch "inline self-review — not independent". Never present a review that did not run
     independently as one; the curation report's execution record lists each stage as
     `delegated`, `inline fallback`, or `skipped`.

6. **Present a single approval batch** — include the Step 5a findings per candidate (or the
   fallback or skip label). For blocking candidates, show the proposed file path, type, frontmatter (`id`, `tags`, `confidence: low`, `last_validated`, `scope`), and body. Wait for explicit approval. Use the topic template at `$BAILIWICK/knowledge/templates/topic-file-template.md`.

7. **Write on approval only** — write approved files, update `last_validated`, **author/refresh each written file's `## Related` section** (1–5 peer notes as relative markdown links, not `[[wikilinks]]` — see memory.md Step 6; grows the visual knowledge graph as a curation byproduct; at the 5-link cap, replace the weakest edge rather than skipping a stronger new tie), and update the relevant index node (root `INDEX.md`, or the domain sub-index if sharded) for new files. **Seed a `.telemetry.json` row for every new `id`-bearing content file** (Step 3 reconciliation catches any miss). If adding entries pushes a node over its shard threshold (> 15 topics), surface a shard proposal (memory.md → Index Health & Sharding). Stage knowledge changes for a commit with the `knowledge:` prefix (separate from project code; the telemetry row is a separate `telemetry:` commit). Do not commit without approval.

8. **Retire processed inputs** — after an input's candidates are handled (promoted, held, or rejected), retire it so it is not re-processed: move raw captures (`.jsonl` + `.md`) to `.bailiwick-outputs/raw/.curated/` (stops the SessionStart nag) — or, for a **shadow-mode capture**, an auto `.jsonl` to `$BAILIWICK_HOME/captures/<repo-key>/raw/.curated/` and a manual Codex/Gemini `.md` to `$BAILIWICK_HOME/captures/<repo-key>/.curated/` (same effect for its central nag; `<repo-key>` is the `<repo>-<hash>` staging folder) — and move any processed agent-output candidate (`.bailiwick-outputs/*.md`) to `.bailiwick-outputs/.curated/` (drops it from the Step 1 gather). For an input restored from the encrypted backup, also **purge its blob**: `bash $BAILIWICK/hooks/capture_backup.sh purge <machine>/<repo>/<file>.gpg` (relevant content is now in the clean zone; the blob is ciphertext, so this is hygiene, not a security-critical erase). The decrypted copies were already deleted after extraction (Step 2a inbox cleanup); use that manifest for the blob purge and confirm none of this run's files remain in `.bailiwick-inbox/`. Never delete unreviewed inputs. For freshness reports, retire only completed reports in the Step 1 snapshot after their candidates are handled; never retire running, partial, failed, or newly dispatched reports.

9. **Propagate (after the approved commit)** — run `$BAILIWICK/hooks/sync_knowledge.sh`. On the **central** machine it pushes the commit to `origin/main`. On a **satellite** it parks the new commits on `sync/<machine>`, pushes (`--force-with-lease`), and opens/refreshes a PR to `main` — keeping local `main` a clean fast-forward mirror; telemetry is excluded (central reconciles rows when the PR merges). Inbound currency is automatic via the SessionStart hook's ff-only pull. See docs/operations.md → Multi-machine sync.

## Periodic Curation mode
If the user invokes `/curate periodic` (or asks for the periodic session), additionally run memory.md's Periodic Curation Session: proactive staleness scan (all `last_validated` > 9 months), apply the held EXPAND/IMPROVE digest, surface archival candidates (high `load_count`, low `useful_count`), and propose confidence graduations (`distinct_projects_used >= 3`, `open_contradictions == 0`).

Periodic mode also runs a bounded, report-only **GCP knowledge freshness check**, even with no
pending captures. Follow [the detailed procedure](references/gcp-freshness.md): existing Cloud
Research stage, indexed official-source allowlist, at most 5 generic notes / 10 distinct URLs /
15 minutes total. Collect and persist its result before ending the session, or explicitly record
an incomplete run. No durable scheduler is installed. The new report is input to a **later**
curation; research never changes knowledge, `last_validated`, confidence, or telemetry.

## De-identified mode
Invoked by `/curate --sanitized` (a.k.a. de-identified mode), or forced always-on when
`.bailiwick-sync.json` sets `"curate": { "deidentify": true }`. In this mode, promotions carry **no
client/project identifiers at all**: every candidate is written with `scope: generic`, **no
`clients/<id>/` files are created**, and all org names, `<id>`/`{org}` tokens, project IDs, and
`distinct_projects_used` associations are stripped or abstracted at ingest — keeping only the reusable
"how it was solved." It is a stronger form of the standard abstraction step (which merely routes
client detail to `clients/<id>/`): here nothing identifying is stored, ever.

Use it (a) as a standing default for anyone who never wants client/project information in the library,
or (b) during a **`/purge`** routine — run de-identified `/curate` first to preserve any still-uncurated
operational knowledge generically **before** the identifying captures are purged (see
`skills/purge/SKILL.md` → Re-ingesting sanitized knowledge). All other rules (dedup, human gate,
telemetry reconcile, `## Related` links) are unchanged. Delegated stages (Steps 2a, 5a) carry the
mode in their briefs and receive only abstracted material where noted there; their host-side
transcripts are the one surface this mode cannot scrub.
