---
name: metrics
description: Read-only report on how well the knowledge library is earning its place — retrieval (loads, reach), the load-vs-useful gap, cold/stale/archival candidates, graduation-eligible tidbits, telemetry↔file reconciliation — plus the per-source framework-health fleet view (component failures, backup push drift, machine heartbeats). Use to review knowledge health, check for failing framework processes, before a Periodic Curation, or to decide what to archive/graduate. Reads only; writes nothing; needs no gate.
---

# /metrics — knowledge library health report

Turns the telemetry sidecar (`knowledge/.telemetry.json`) + file frontmatter into a
repeatable view of whether the stored knowledge is used and useful. **Read-only** — it never writes,
so no human gate applies (unlike `/curate`).

## Run it
```
python3 $BAILIWICK/skills/metrics/report.py [--top N] [--json]
```
- default: human-readable report over Bailiwick's own knowledge dir.
- `--json`: machine-readable (per-id rows + orphans/missing) for dashboards or trend tracking.
- `--top N`: length of the "top by loads" and reach lists (default 10).

## Present it (fixed structure — keep runs comparable)

The script's output is deterministic; the presentation must be too, so consecutive runs can be
compared at a glance. Always answer in exactly this shape, nothing more:

1. **Raw report** — the script's output verbatim in one fenced code block. Never reformat it,
   reorder its sections, or convert it into markdown tables/prose — its section layout IS the
   stable interface.
2. **`## Interpretation`** — one bullet group per report section that calls for action, in the
   report's own order, labelled with the report's bracket names in bold (**[impact]**,
   **[reach & graduation]**, **[archival]**, **[stale]**, **[reconciliation]**,
   **[framework health]**). Omit sections that are empty or need nothing. Each action candidate
   is a single bullet: `<id> — <proposed action> (<evidence>)`.
3. **`## Bottom line`** — 2–3 sentences: is the library earning its place, and the single most
   useful next step (e.g. "run /curate to reconcile", "archive these 4 cold files").

No other headings, no summary tables, no re-derived statistics — interpretation content comes
from the section guide below.

## How to read it (and what to do)
- **[retrieval]** — `ever loaded` vs `cold`. The `loaded` signal is mechanical (`capture_session.py`
  derives it from every transcript), but captures before `capture_schema: 2` never saw subagent
  reads, so a file only stage agents read looks cold. When the report prints a `caveat:` line,
  relay it: cold counts are inflated until subagent-aware captures span 60 days.
- **[impact — funnel load → applied → used]** — `loaded` (mechanical read), `applied` (loaded in a
  session that shipped a mutation/commit — mechanical proxy, ADR-004), `used` (curate-judged: the
  reasoning shows the tidbit informed the output). If it warns that no `applied`/`used` signal exists
  yet, say plainly the impact column is *blind, not zero* — do not present high-load files as low-value.
- **[reach & graduation]** — reach is **load-based** (credited when a session loads the file), not
  curate-judged use. `graduation-eligible` =
  topics at `confidence: high` reached in ≥3 distinct projects. Eligibility is necessary, not
  sufficient: the curate flow proposes graduation on reach plus no open contradictions, with no
  `used` check. Advise the human approver to look at the topic's `useful_count` in the report
  (it prints `used=` next to each eligible topic) before approving `topics/ → patterns/`;
  deferring on thin `used` is a reasonable approver call, not a rule. `bump candidate` = ≥3
  projects but confidence still low/medium → propose the next step whose criteria it meets
  (`low → medium` also needs `useful_count >= 2`, shown as `used=`).
- **[archival / rewrite candidates]** — while the `caveat:` line shows, `never loaded` files are
  **not** archive candidates: older captures in the window miss subagent reads. Recommend nothing
  be archived for coldness until it clears. Otherwise, `never loaded` files are archive-or-advertise candidates
  (either genuinely unused, or under-discovered because their INDEX tags/description are weak — check
  the index entry before archiving). The loaded-but-never-useful list stays OFF until a `used` signal
  exists.
- **[stale]** — `last_validated` older than ~9 months → re-validate in Periodic Curation.
- **[reconciliation]** — orphan rows / missing rows are fixed by `/curate` Step 3 reconcile.
- **[framework health — per source]** — one row per machine from the health shards
  (`~/.bailiwick/health/*.jsonl` + `health/remote/*` pulled from the encrypted backup): last
  heartbeat, errors/warns (7d) by component, backup push drift. State vs history: `⚠ last push
  FAILED` is current state; `errors 7d` (all components) and the `N× component — last: …` line
  (most recent *error*, unpushed count as of that failure) are rolling-window history. Decide:
  - `⚠` shown (newest backup error newer than newest push ok, or no push ever succeeded) → off-site
    copy lagging, local data safe; triage per docs/operations.md "When backup pushes fail".
  - `capture_backup` errors, no `⚠` → a later push succeeded; watch, `scripts/doctor.sh` if they
    keep accruing. No `⚠` also appears if no push has run since the last success: on that machine,
    compare `backup last push ok` with the newest capture in `.bailiwick-outputs/raw/` or
    `~/.bailiwick/captures/<key>/raw/` (a gap under `throttle_minutes` is normal). `last push ok` older than `last event` is normal.
  - errors from any other component (e.g. sync_knowledge, guardrails, capture_session,
    session_start, metrics) → read the detail and triage on its own terms.
  - stale `last event` → run `scripts/doctor.sh` on that machine, unless retired.
  - Other machines' rows on central lag by one push (the uploaded shard predates the push that
    carried it), so a recovered machine can still show `⚠`: confirm on the machine itself (local
    `/metrics` or doctor) before triaging.

  On a satellite (or with backup disabled) only the local machine appears; the full fleet view
  lives on central after a `capture_backup.sh pull`.

## Scope & limits
- All actions it *suggests* (archive, graduate, bump confidence) still go through **`/curate`** under
  the human gate — `/metrics` only surfaces candidates, it changes nothing.
- It measures what telemetry records. The `applied` tier is mechanical (capture-time, ADR-004); the
  `used` tier populates only when `/curate` runs and judges the reasoning. Until captures with shipped
  work have been curated, read `[impact]` as "not yet accrued," not "zero value."
