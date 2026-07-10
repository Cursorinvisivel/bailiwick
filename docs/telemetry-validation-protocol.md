# 20-Session Measurement Protocol

> Run after the first ~20 real working sessions across at least two genuinely distinct projects.
> Purpose: determine whether the telemetry schema is generating trustworthy data before
> letting it drive any automated promotion decisions.

---

## Per-Session (light, ~2 min after each Collect)

**Spot-check one `used` entry per session.**
Pick one file from `Retrieval Feedback.used` and ask: did this file actually shape the output,
or was it loaded and ignored? Record the answer as `honest` or `inflated` next to the entry
in the session output file. No action required — just a running tally.

**Note any `missed` entries.**
These are the highest-signal inputs to the library. Capture them even if you don't promote
immediately — they tell you where retrieval is failing under real load.

---

## After 20 Sessions — Three Questions

### 1. Are `used` self-reports honest?

Open `.telemetry.json`. For the 5 files with the highest `useful_count`, cross-reference
with your session output spot-checks.

| Signal | Interpretation |
|---|---|
| `useful_count` matches spot-check tally | Self-reporting is trustworthy — allow it to drive archival flags |
| `useful_count` consistently higher than spot-check | Inflation — agents are marking `used` without discrimination; add a stricter definition to agent-output-template.md before trusting graduation |
| `useful_count` consistently lower | Agents are under-reporting; graduation will be too slow but won't promote incorrectly |

**Decision gate**: do not let `distinct_projects_used` drive promotion until spot-checks confirm
`used` entries are honest. Treat as human-review flags until then.

---

### 2. Has any file accumulated the archival signature?

Query `.telemetry.json` for entries matching all three conditions:
- `load_count >= 5`
- `useful_count <= 1`
- `last_useful` is null or older than 6 months

```
# Quick read — paste into a session and ask Memory Agent to evaluate:
"Read .telemetry.json. List any entry where load_count >= 5,
 useful_count <= 1, and last_useful is null or old. These are archival candidates."
```

| Signal | Interpretation |
|---|---|
| Entries found | Archival mechanism is working — surface to Periodic Curation for rewrite or removal |
| No entries found | Either the library is young and healthy, or `useful_count` is inflated (see Q1) |
| Files loaded 0 times | These are either too new to have been needed, or their tags aren't matching real tasks — check INDEX.md tag coverage |

---

### 3. Is `distinct_projects_used` crediting the right files?

For each file with `distinct_projects_used.length >= 1`, read the list and ask:
are these genuinely independent contexts, or the same venture under different repo names?

**Inflation check**: if any `project_id` appears that corresponds to repos you know are
part of the same engagement or venture, those were not properly normalised — update the
relevant CLAUDE.md `project_id` fields and re-evaluate.

**Undercounting check**: if a file you know was used heavily in a client engagement shows
`distinct_projects_used: []`, the `@project_id` tag was likely omitted from session outputs —
add a reminder to agent-output-template.md or tighten the instruction in memory.md.

| Signal | Interpretation |
|---|---|
| `distinct_projects_used` lists independent projects | Signal is clean — allow confidence proposals when length >= 3 |
| Same venture counted multiple times | Normalisation missed — fix `project_id` values, consider adding a known-projects registry to CLAUDE.md |
| Lists are empty despite real usage | Tagging is not happening — strengthen the instruction in agent-output-template.md |

---

## Staleness Window Calibration

After 20 sessions, check `last_validated` on any file that was loaded but produced a `missed`
entry (i.e. it was close enough to load, but not close enough to help). These are candidates
for content gaps, not staleness — distinguish the two:

- `missed` + file is recent → content gap, not staleness → EXPAND candidate
- `missed` + file is old → possible staleness → flag for re-validation

If no file has crossed the 9-month threshold yet, the staleness window cannot be calibrated
from this run. Note the oldest `last_validated` date and schedule a re-check at month 9.

---

## Decision After the Run

| Finding | Action |
|---|---|
| `used` self-reports honest | Unlock `distinct_projects_used` to drive confidence proposals |
| Archival signatures present and credible | Run first Periodic Curation Session |
| `distinct_projects_used` inflated | Fix `project_id` normalisation before any graduation |
| `missed` entries accumulating in one domain | That domain needs new topic files — prioritise in next sessions |
| Library still under 30 files after 20 sessions | Collect is under-triggering — check whether Lead is always invoking it |
| No file near graduation gate | Either too few projects, or `used` inflation — determine which before adding more design |

---

## Index growth — response ladder

Growth is handled in two stages. Do not jump to embeddings.

### Tier 1.5 — hierarchical sharding (built-in; do this first)
Implemented in the framework (see `agents/memory.md` → Index Health & Sharding). The
root `INDEX.md` is injected every session, so keep it lean: when a domain exceeds **15 topics** — or
root `INDEX.md` exceeds ~**20 KB**, which the SessionStart hook nags about — shard that domain into
`indexes/index_<domain>.md` and leave a shard-pointer row in root. Sub-indexes load on-demand, never
injected. Sharding is **recursive** — a sub-index that itself grows past threshold splits again into
deeper nodes, forming an **index tree**; only root is injected, each level loads on the descent. This
absorbs most growth at near-zero complexity cost: no embeddings, no new infra.

### Tier 2 — semantic retrieval (embeddings)
Only build Tier 2 if, **after** sharding, you still observe at least one of:
- Tag / sub-index retrieval produces demonstrably wrong files in 3+ sessions (wrong file loaded, right file missed, gap confirmed by a `missed` entry)
- The lean root INDEX + the relevant sub-index together still consume a noticeable share of context (> ~15% on inspection)
- A single domain crosses ~60 files and tag matching no longer discriminates within it

Until then, the data doesn't support the complexity cost. Sharding is the pressure valve; embeddings
are the last resort.
