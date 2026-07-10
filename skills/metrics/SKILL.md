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

Present the report to the user, then **interpret** the sections that call for action:

## How to read it (and what to do)
- **[retrieval]** — `ever loaded` vs `cold`. The `loaded` signal is mechanical and reliable
  (`capture_session.py` derives it from every transcript), so this is trustworthy.
- **[impact — funnel load → applied → used]** — `loaded` (mechanical read), `applied` (loaded in a
  session that shipped a mutation/commit — mechanical proxy, ADR-004), `used` (curate-judged: the
  reasoning shows the tidbit informed the output). If it warns that no `applied`/`used` signal exists
  yet, say plainly the impact column is *blind, not zero* — do not present high-load files as low-value.
- **[reach & graduation]** — `graduation-eligible` = topics at `confidence: high` used in ≥3 distinct
  projects → propose promoting `topics/ → patterns/` at the next `/curate`. `bump candidate` = ≥3
  projects but confidence still low/medium → propose a confidence bump.
- **[archival / rewrite candidates]** — `never loaded` files are archive-or-advertise candidates
  (either genuinely unused, or under-discovered because their INDEX tags/description are weak — check
  the index entry before archiving). The loaded-but-never-useful list stays OFF until a `used` signal
  exists.
- **[stale]** — `last_validated` older than ~9 months → re-validate in Periodic Curation.
- **[reconciliation]** — orphan rows / missing rows are fixed by `/curate` Step 3 reconcile.
- **[framework health — per source]** — one row per machine from the health shards
  (`~/.bailiwick/health/*.jsonl` + `health/remote/*` pulled from the encrypted backup): last
  heartbeat, errors/warns (7d) by component, backup push drift ("last push FAILED" = the machine's
  off-site copy is lagging — local data is safe; investigate connectivity/auth). A machine whose
  heartbeat has gone stale has silently stopped emitting — check it. On a satellite (or with backup
  disabled) only the local machine appears; the full fleet view lives on central after a
  `capture_backup.sh pull`.

## Scope & limits
- All actions it *suggests* (archive, graduate, bump confidence) still go through **`/curate`** under
  the human gate — `/metrics` only surfaces candidates, it changes nothing.
- It measures what telemetry records. The `applied` tier is mechanical (capture-time, ADR-004); the
  `used` tier populates only when `/curate` runs and judges the reasoning. Until captures with shipped
  work have been curated, read `[impact]` as "not yet accrued," not "zero value."
