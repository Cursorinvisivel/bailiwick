---
name: curate
description: Distill pending raw session captures (.bailiwick-outputs/raw/) and agent outputs (.bailiwick-outputs/) into the Bailiwick knowledge library under a human gate. Use when the SessionStart hook reports pending captures, or to run the Periodic Curation Session (every 6-8 weeks).
---

# /curate — gated knowledge curation

This skill runs the **Memory Agent Collect flow** on demand. It is the human-gated
review step that turns enforced raw capture into curated knowledge. Read
`$BAILIWICK/agents/memory.md` first — it is the source of truth for
the Collect, dedup, approval-routing, and Periodic Curation logic. Follow it exactly.

**Runnable from any wired repo.** It reaches the dirty pool (via `capture_backup.sh pull`) and the
knowledge library by **absolute path**, so one invocation processes the whole centralized encrypted
pool — captures from *all* machines/repos — plus the current repo's own local `.bailiwick-outputs/`. The
active repo is not special; it only adds its local captures. Decrypting the cross-repo pool needs the
gpg private key, so full centralized curation runs on the machine that holds it.

## Hard rules (do not violate)
- **Never** write to `$BAILIWICK/knowledge/` content files without explicit user approval in this session. The library is human-gated.
- `.telemetry.json` is the ONLY knowledge file written without approval (commit with `telemetry:` prefix).
- Never duplicate: check INDEX.md tags AND read candidate files before any write (NEW / EXPAND / IMPROVE / SKIP).
- Raw captures in `.bailiwick-outputs/raw/` are unsanitised and may contain client IAM, project IDs, or secrets. Abstract to generic before promoting; route client-identifying detail to `clients/<id>/`. Never commit raw captures.

## Procedure

1. **Gather inputs**
   - List `.bailiwick-outputs/raw/*.jsonl` (enforced transcript captures) and their `.md` headers.
   - **Shadow-mode captures** (FRAMEWORK.md §7.1): also list `~/.bailiwick/captures/*/raw/*.jsonl`
     (auto Claude Code captures) **and** `~/.bailiwick/captures/*/*.md` (manual Codex/Gemini session
     outputs) — use `$BAILIWICK_HOME/captures/` if that env var is set. Repos wired in shadow mode
     stage centrally, keyed by origin repo, not in any `.bailiwick-outputs/`. The auto-capture `.md` headers
     carry `mode: shadow` + `origin_remote` — use those to judge scope (`generic` vs `client:<id>`)
     since the repo path is not self-identifying. Include them in the candidate gather exactly like
     in-repo captures.
   - List `.bailiwick-outputs/*.md` (agent session outputs, if any — including `learn-*.md`
     onboarding captures staged by `/learn`, which arrive pre-digested with a
     `## Candidates for Promotion` section and dedup hints).
   - **Restore off-machine captures** (if `capture_backup` is enabled in `.bailiwick-sync.json`): run
     `bash $BAILIWICK/hooks/capture_backup.sh pull` — decrypts every backed-up blob
     (from any machine) into `$BAILIWICK/.bailiwick-inbox/raw/<machine>/<repo>/…` (needs the gpg private
     key + passphrase). Include these in the candidate gather. `.bailiwick-inbox/` is gitignored — never commit it.
   - Read `$BAILIWICK/knowledge/INDEX.md`.
   - If there is nothing pending, say so and stop.

2. **Extract candidates** — from each capture, pull decisions, non-obvious patterns, validated assumptions, pitfalls, and Retrieval Feedback (loaded / used / missed). Research-only and conversation-only sessions still count. **Federation ingest:** external knowledge consulted from a `.bailiwick-sources.json` source is also an ingest candidate — follow `agents/federation.md` (abstract, never transclude; add `source:` + `## Provenance` + `scope: external:<id>`; route through this same approval batch; never write back to the source).

3. **Update telemetry + reconcile (no gate)** — **central machine only; on a satellite (`.bailiwick-sync.json` role ≠ `central`) skip this entire step — telemetry is central-owned (see docs/operations.md → Multi-machine sync).** Apply `Retrieval Feedback` to `.telemetry.json` per memory.md Step 2, then **reconcile**: every `id`-bearing content file (`topics/`, `patterns/`, `context/`, `clients/`) must have a telemetry row — seed a zero-row for any missing id, and flag orphan rows (a row whose id has no file) for removal. This is the only unattended write. (The framework's own ADRs live outside the library in `docs/decisions/` — status-tracked, not part of this reconcile.)

4. **Dedup (mandatory)** — for each candidate, search the index by tag/scope (descend into the relevant domain sub-index under `indexes/` if that domain is sharded), READ any overlapping file, and decide NEW / EXPAND / IMPROVE / SKIP. Never create a second file for an existing topic.

5. **Route by confidence (memory.md Step 4)**
   - NEW file → surface for approval now.
   - IMPROVE that contradicts existing content → surface for approval now.
   - EXPAND / non-contradicting IMPROVE → hold for the digest (mention count, do not block).
   - SKIP → silent.

6. **Present a single approval batch** — for blocking candidates, show the proposed file path, type, frontmatter (`id`, `tags`, `confidence: low`, `last_validated`, `scope`), and body. Wait for explicit approval. Use the topic template at `$BAILIWICK/knowledge/templates/topic-file-template.md`.

7. **Write on approval only** — write approved files, update `last_validated`, **author/refresh each written file's `## Related` section** (1–5 peer notes as relative markdown links, not `[[wikilinks]]` — see memory.md Step 6; grows the visual knowledge graph as a curation byproduct; at the 5-link cap, replace the weakest edge rather than skipping a stronger new tie), and update the relevant index node (root `INDEX.md`, or the domain sub-index if sharded) for new files. **Seed a `.telemetry.json` row for every new `id`-bearing content file** (Step 3 reconciliation catches any miss). If adding entries pushes a node over its shard threshold (> 15 topics), surface a shard proposal (memory.md → Index Health & Sharding). Stage knowledge changes for a commit with the `knowledge:` prefix (separate from project code; the telemetry row is a separate `telemetry:` commit). Do not commit without approval.

8. **Retire processed inputs** — after an input's candidates are handled (promoted, held, or rejected), retire it so it is not re-processed: move raw captures (`.jsonl` + `.md`) to `.bailiwick-outputs/raw/.curated/` (stops the SessionStart nag) — or, for a **shadow-mode capture**, an auto `.jsonl` to `~/.bailiwick/captures/<repo-key>/raw/.curated/` and a manual Codex/Gemini `.md` to `~/.bailiwick/captures/<repo-key>/.curated/` (same effect for its central nag; `<repo-key>` is the `<repo>-<hash>` staging folder) — and move any processed agent-output candidate (`.bailiwick-outputs/*.md`) to `.bailiwick-outputs/.curated/` (drops it from the Step 1 gather). For an input restored from the encrypted backup, also **purge its blob**: `bash $BAILIWICK/hooks/capture_backup.sh purge <machine>/<repo>/<file>.gpg` (relevant content is now in the clean zone; the blob is ciphertext, so this is hygiene, not a security-critical erase). Delete the decrypted copy from `.bailiwick-inbox/`. Never delete unreviewed inputs.

9. **Propagate (after the approved commit)** — run `$BAILIWICK/hooks/sync_knowledge.sh`. On the **central** machine it pushes the commit to `origin/main`. On a **satellite** it parks the new commits on `sync/<machine>`, pushes (`--force-with-lease`), and opens/refreshes a PR to `main` — keeping local `main` a clean fast-forward mirror; telemetry is excluded (central reconciles rows when the PR merges). Inbound currency is automatic via the SessionStart hook's ff-only pull. See docs/operations.md → Multi-machine sync.

## Periodic Curation mode
If the user invokes `/curate periodic` (or asks for the periodic session), additionally run memory.md's Periodic Curation Session: proactive staleness scan (all `last_validated` > 9 months), apply the held EXPAND/IMPROVE digest, surface archival candidates (high `load_count`, low `useful_count`), and propose confidence graduations (`distinct_projects_used >= 3`, `open_contradictions == 0`).

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
telemetry reconcile, `## Related` links) are unchanged.
