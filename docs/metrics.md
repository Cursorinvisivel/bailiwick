# Reading the metrics report

`/metrics` is a read-only health report on the knowledge library. It answers one question: is the
stored knowledge being used, and is it useful? It also flags machines that have gone quiet. It
writes nothing; every action it suggests (archive, graduate, bump confidence) still goes through
`/curate` under the human gate.

```bash
python3 $BAILIWICK/skills/metrics/report.py            # human-readable
python3 $BAILIWICK/skills/metrics/report.py --json     # per-file rows, for trend tracking
```

This page walks through a real report, section by section, and is candid about what its numbers
do and do not show yet.

## The example

The figures below come from the maintainer's own private instance on 2026-10-29: one engineer
on three machines. The totals are real. File IDs and machine names are replaced with seed-library
IDs and placeholders, because the real ones would identify private projects. The per-file lists
are shortened.

```text
=== bailiwick knowledge metrics ===

[library]
  content files (topics/patterns/context/clients) 278
    topics                                     263
    patterns                                   9
    contexts                                   6

[retrieval]
  ever loaded                                  54/278
  total load events                            89
  cold (never loaded)                          224/278
  caveat: 7 of 9 reachable captures predate subagent read capture (capture_schema < 2);
  subagent-aware since 2026-10-28. Files read only by stage agents look cold, so do not
  archive for coldness until that spans 60 days.

[impact — funnel: load → applied → used]
  loaded (read)                                54/278
  applied (loaded + session shipped: mutation/commit) 41/278
  used (curate-judged: informed the output)    25/278

[reach & graduation]
  used in >=3 distinct projects                6
  graduation-eligible (topic, high, >=3 projects) 1
    → agent-cli-hook-contracts  (promote topics/ → patterns/)

[top 10 by loads]
    9 loads · 7 proj · engineering-defaults
    5 loads · 5 proj · code-review-rubric
    5 loads · 4 proj · caf-naming-taxonomy
    4 loads · 2 proj · acme-project-map
    3 loads · 3 proj · agent-cli-hook-contracts
    3 loads · 1 proj · claude-mcp-wiring
    3 loads · 3 proj · gcp-iam-conventions
    3 loads · 3 proj · terraform-variable-conventions
    2 loads · 2 proj · gcp-labels-required
    2 loads · 2 proj · gcp-gke-workload-identity

[archival / rewrite candidates]
  never loaded (224) — NOT archive candidates yet (see [retrieval] caveat);
  advertise better or wait for subagent-aware captures:
    · gcp-backend-gcs-pattern
    · llm-context-token-optimization
    · powershell-utf8-bom-parsing
    · … 221 more

[framework health — per source]
  workstation-b   last event 23 days ago · errors 7d: 0 · warns 7d: 0
  laptop-c        last event today       · errors 7d: 1 · warns 7d: 0
                  backup last push ok: today
                    1× capture_backup — last: push failed (capture/laptop-c; 1 unpushed
                    commit(s); ciphertext safe in local mirror)
  laptop-a        last event today       · errors 7d: 0 · warns 7d: 0
                  backup last push ok: today
```

## Section by section

### [library]

This is how much has been promoted through `/curate`. It tells you nothing about value: it is the
intake side of the funnel. Almost everything is a `topic`, which is expected. A topic becomes a
`pattern` only after it has proven itself across projects (see [reach & graduation](#reach-graduation)).

### [retrieval]

**Loaded** means a session actually read the file. Hooks derive it from transcripts, so it is
mechanical, not self-reported. **Cold** means the file has never been read.

The `caveat:` line matters more than the numbers next to it. Until 2026-10-28, captures recorded
only what the main session read, not what stage subagents read. Narrow gotcha files are exactly
what stage agents load, so cold counts are inflated. The report holds off on calling anything
cold-and-unused until subagent-aware captures cover 60 days (here, around 2026-12-27).

### [impact — funnel: load → applied → used]

There are three tiers, each stricter than the last ([ADR-004](decisions/adr-004-tiered-usefulness-signal.md)):

| Tier | Meaning | How it is measured |
|---|---|---|
| loaded | the file was read | mechanical, from the transcript |
| applied | read in a session that shipped a change or commit | mechanical proxy |
| used | the reasoning shows it informed the output | judged by a human during `/curate` |

`used` is the only tier that says the knowledge mattered. It fills in only as captures are curated,
so it always lags (see [below](#what-one-curate-run-changes)). A fresh install shows it empty. That
means not measured yet, not zero.

### [reach & graduation]

Reach counts distinct projects, not loads: a file read ten times in one project has reach 1. A
topic **graduates** to `patterns/` when it is at `confidence: high` and used in 3 or more projects
([FRAMEWORK.md §4](FRAMEWORK.md#confidence-graduation)). The report names it with the action to
take. Graduating means rewriting the topic as a pattern, with full examples, at the next `/curate`.
A file with reach ≥3 that is still at low or medium confidence is a candidate for a confidence
bump instead.

**[top 10 by loads]** shows where retrieval concentrates. Here it is mostly the always-on
baseline (`engineering-defaults`, 7 projects) and cross-cutting conventions (review rubric, naming,
IAM, variables). A project map loaded in only one or two projects is expected: it is specific to
that project by design.

### [archival / rewrite candidates]

Never-loaded files are either unused or hard to find (weak index tags or description). Check the
index entry before archiving anything. While the retrieval caveat is showing, the report lists them
but proposes nothing. Topics promoted today are cold simply because they are new.

### [framework health — per source]

There is one row per machine: last heartbeat, errors and warnings over 7 days, and the last
successful backup push. Read the rows like this:

- **`laptop-a`** is healthy: a heartbeat today, and its backup push matches its last event.
- **`laptop-c`** shows one error: a backup push failed. The report notes the encrypted capture is
  safe in the local mirror, and a later push succeeded the same day, so it needs action only if it
  repeats.
- **`workstation-b`** has a heartbeat 23 days old and no backup line. That is the quiet failure to
  watch for, because a machine that stops reporting stops backing up its captures. Here it is
  expected, since the machine was retired and replaced by `laptop-a`. Otherwise, run
  `scripts/doctor.sh` on it.

## Are these numbers good?

Partly. Taken stage by stage:

| Step | Ratio | Rate |
|---|---|---|
| intake → loaded | 54 / 278 | 19% |
| loaded → applied | 41 / 54 | 76% |
| applied → used | 25 / 41 | 61% |
| loaded → used | 25 / 54 | 46% |
| **intake → used** | **25 / 278** | **9%** |

**The encouraging part is precision.** When the agent does pull a file in, it informs the output
almost half the time. Retrieval loads at most a handful of files per task, so this is the ratio
that shows whether the index points at the right knowledge. It does.

**The weak part is coverage.** About 91% of what has been curated has not yet shown up as used.
Some of that is expected. A library of narrow gotchas has a long tail: a Cloud SQL failover pitfall
is worth keeping even if it is needed twice a year. Some of it is measurement: the retrieval caveat
applies, and `used` only counts sessions that have been through `/curate`, so it lags. But neither
explains all of it. It may also mean intake has been too permissive: knowledge promoted because it
was true, not because it was likely to be needed again.

### What one `/curate` run changes

The same instance, reported twice on the same day, before and after one `/curate` session:

| | Before | After |
|---|---|---|
| content files | 272 | 278 |
| loaded | 41 | 54 |
| applied | 28 | 41 |
| used | 19 | 25 |
| reach ≥3 projects | 2 | 6 |
| graduation-eligible | 0 | 1 |
| intake → used | 7% | 9% |

The library grew by 6 files, but measured use grew faster, so coverage improved even as intake
rose. That supports the measurement-lag explanation: part of the gap is sessions not yet curated.
One run is not a trend, though. It shows the direction, not where the ratio settles.

### When this becomes decidable

After the 60-day window clears, re-run the report and read the cold count (now 81%):

- If cold files fall well below that once subagent reads are counted, the gap was mostly
  measurement.
- If they stay around three quarters or more, intake is too loose. Tighten the bar in `/curate`
  ("will this be needed again?", not only "is this correct?"). Then use the archival list to merge
  or retire what has never been read.

Until then the report supports one claim and no more: the knowledge that is reached is useful, and
measured use is rising faster than intake. It does not yet show that the library as a whole is
earning its size.

## Related

- [skills/metrics/SKILL.md](../skills/metrics/SKILL.md): the report's fixed presentation format
  and per-section guidance
- [ADR-004](decisions/adr-004-tiered-usefulness-signal.md): why usefulness is tiered
- [FRAMEWORK.md §4](FRAMEWORK.md): the knowledge model, confidence and graduation
- [operations.md](operations.md): multi-machine sync and capture backup, behind the health section
- [Traffic metrics](traffic-metrics.md): repository adoption signals, which are a separate thing
