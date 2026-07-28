# Traffic metrics

How the repository's usage metrics work, and where to read the ones that don't earn a badge.

## What exists

| Metric | Where | Source |
|---|---|---|
| CI status | README badge | shields.io reading the `ci.yml` workflow status |
| All-time views | README badge | accumulated ledger (below) |
| Unique cloners (~) | README badge | accumulated ledger (below) |
| Top referrers & top content | [traffic report](https://github.com/Cursorinvisivel/bailiwick/blob/traffic-data/traffic-report.md) | daily snapshots (below) |

GitHub's traffic API (and the Insights → Traffic page) only keeps a **rolling 14-day window**, so
anything "all-time" has to be accumulated externally. The
[Traffic counter workflow](../.github/workflows/traffic-counter.yml) runs
[scripts/traffic_counter.py](../scripts/traffic_counter.py) daily (03:17 UTC):

- **Views/clones** are merged into a per-day ledger (`traffic-data.json`); re-snapshotting a day
  overwrites it, so partial "today" counts self-correct. A missed run loses nothing while the gap
  stays under 14 days.
- **Top referrers and top content** have no per-day breakdown — each snapshot is a whole
  overlapping 14-day top-10 — so they are stored raw by date (`referrers-data.json`) and rendered
  into [traffic-report.md](https://github.com/Cursorinvisivel/bailiwick/blob/traffic-data/traffic-report.md).
  They are deliberately **not** badges: interesting for the maintainer, noise for the README.

Everything is published on the data-only **`traffic-data`** branch — a single force-pushed orphan
commit, so it never accumulates history; continuity lives in the ledger files themselves. The
README badges read the badge JSON there through the shields.io endpoint. Until the first
successful snapshot, grey "collecting…" placeholders are published instead of an error badge.

## Caveats

- **"~" on unique cloners:** GitHub dedupes uniques only within each reported day, so the
  accumulated figure is a sum of per-day uniques — an upper bound, not true all-time uniques.
- Raw clone counts inflate easily (CI, mirrors, your own machines); unique cloners is the more
  honest adoption signal, which is why it gets the badge instead of raw clones.

## Setup (once per repository)

The Actions-issued `GITHUB_TOKEN` cannot read the traffic API. Create a fine-grained PAT —
resource owner = the account/org that owns the repo, only this repository selected, permission
**Administration: read-only** (or a classic PAT with `repo` scope) — and store it as the Actions
secret `TRAFFIC_PAT`. The workflow also runs on pushes that touch it or its script, so the first
push after setup seeds the branch immediately instead of waiting for the next cron slot.
