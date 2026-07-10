---
id:            adr-004-tiered-usefulness-signal
type:          decision
status:        accepted
date:          2026-07-01
authors:       [Francisco Ferrinho]
tags:          [adr, telemetry, metrics, usefulness, capture, curation, impact]
supersedes:    []
superseded_by:
scope:         generic
---

# ADR-004 — Tiered usefulness signal: load → applied → used

---

## Context

The knowledge library tracks retrieval well but **impact not at all**. In practice `useful_count`
sits at 0 for **every** tracked file while loads are recorded fine — the `/metrics` report makes this
plain. The framework measures *what gets read*, not *what actually helped*.

The cause is structural. Two signals were designed (`memory.md`):
- **`loaded`** — mechanical, enforced: `capture_session.py` derives from every transcript which
  knowledge files were read during substantive work. Reliable and working.
- **`used`** — the stronger "this informed the output" signal, which required an agent to hand-write
  `used: id@project` into a `.bailiwick-outputs/*.md` session file. That path effectively never fires, so
  usefulness reads as universally zero — a blind spot, not a finding.

Meanwhile the raw capture already contains everything needed to do better: the transcript is copied
verbatim, including `thinking` blocks (reasoning), `Edit`/`Write` (mutations), and `Bash` (so a
`git commit` is visible). The evidence for "did the agent use this, and did the work ship" is already
captured — it is simply not read for that purpose.

## Decision

Replace the binary load/used model with a **three-tier usefulness signal**, each tier a strictly
stronger claim than the one below it:

1. **loaded** *(unchanged, mechanical)* — the file was read in substantive work. → `load_count`.
2. **applied** *(new, mechanical, capture-time)* — loaded **and** the same session produced a
   mutation (`Edit`/`Write`) and/or a `git commit`. Derived purely from the transcript by
   `capture_session.py`. → `applied_count` + `last_applied`.
3. **used** *(new, semantic, curate-time)* — the reasoning shows the tidbit actually **informed** the
   output. Judged by the Memory Agent reading the `thinking` blocks during `/curate` (human-gated). →
   `useful_count` + `last_useful` (repurposed from the dead self-report path).

`applied` is intentionally **coarse**: if five files were loaded in a committed session, all five get
applied credit. It answers "was this knowledge in play when real work shipped" without any
self-report. The **used** tier disambiguates *which* one actually mattered, at curate time, from the
reasoning. Both are kept — the report shows the funnel **load → applied → used**.

## Options Considered

### Option A — Three-tier load/applied/used (CHOSEN)
**Pros:** Non-zero impact signal immediately (mechanical `applied`), with a precise semantic tier
(`used`) layered on under the existing human gate. No new capture data required — reads what's already
collected. Degrades gracefully (if curate never judges `used`, `applied` still measures shipped-with).
**Cons:** `applied` over-credits co-loaded files; two impact fields to maintain; `used` still depends
on curate being run.

### Option B — Mechanical `used` only (infer "informed" by regex over reasoning/diff)
**Pros:** Fully automatic, no curate dependency.
**Cons:** "Did this knowledge inform the output" is a semantic judgment; regex over reasoning/diff is
brittle and would manufacture false precision. Rejected — better to be coarse-but-honest (`applied`)
than precise-but-wrong.

### Option C — Keep the agent-written `used: id@project` self-report (status quo)
**Pros:** No change.
**Cons:** It does not fire — `useful_count` stays 0. Rejected: the blind spot is the problem.

## Rationale

Impact is a spectrum, not a boolean, so the model should be tiered. The mechanical `applied` tier is
the cheapest honest improvement — it turns "0 useful" into a real "shipped-with" number using data
already on disk, and it cannot be gamed by an agent forgetting to self-report. The semantic `used`
tier keeps the high-quality judgment where judgment belongs: a human-gated curate pass that can read
the reasoning. Option A refuses to fake precision (rejecting B) while refusing to stay blind
(rejecting C).

An early curate pass surfaced exactly this class of false positive: a session credited a knowledge id
as loaded+applied because the file **path string appeared in test fixtures the session wrote**, not
because the file was read. The mechanical `loaded` regex matches paths in any tool input. This is
exactly the case the human-gated `used` tier (and curate judgment) exists to catch — the curator
excluded that credit rather than skew the signal.

## Consequences

### Positive
- `/metrics` gains a real impact column (load → applied → used funnel); the dead-weight heuristic
  (high load, zero *applied*) becomes meaningful and can finally flag genuine cruft.
- Graduation/archival decisions gain an evidence basis beyond raw loads.
- No new data collected; the change only *reads* what the capture already holds.

### Negative / Accepted trade-offs
- `applied` over-credits every co-loaded file in a shipping session — accepted; the `used` tier and
  human judgment correct it. Report labels `applied` as a proxy, never as proof.
- The mechanical `loaded`/`applied` regex can be tripped by a knowledge-file path appearing in tool
  input that is not a genuine read (e.g. test fixtures, docs). Curate judgment excludes such false
  positives before crediting; the coarse signal is never authoritative on its own.
- `git commit` in a session may commit unrelated files, or knowledge may inform a draft committed
  later — so `applied` is directional, not exact. Documented.
- Two impact fields (`applied_count`, `useful_count`) to reconcile; `used` still requires `/curate`
  to run to populate.

### Risks and mitigation
| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| `applied` read as ground-truth impact | Medium | Medium | Report/docs label it a mechanical proxy; the `used` tier is the precise signal |
| Over-credit inflates a weak tidbit's apparent value | Medium | Low | Graduation still gates on `distinct_projects_used` + human-approved confidence; `used` disambiguates |
| Path-string false positive credits an unread file | Medium | Low | Curate judgment excludes it before writing telemetry (as in the curate pass that surfaced it) |
| Commit detection misfires (unrelated commit) | Low | Low | `applied` is directional by design; curate's `used` corrects; never blocks anything |

## Affected components (implementation)

- `hooks/capture_session.py` — detect mutations + `git commit` in the transcript; emit
  `applied: [ids]` + `committed: true|false` into the auto-derived `## Retrieval Feedback` block.
- `agents/memory.md` — telemetry Step: credit `applied_count`/`last_applied` mechanically
  from the block; define the semantic `used` tier (curate reads `thinking` to judge which loaded
  tidbits informed the output → `useful_count`); reconcile-seed the new fields.
- `skills/metrics/report.py` — add the `applied` tier (load → applied → used funnel);
  base the dead-weight heuristic on `applied` once present.
- `docs/FRAMEWORK.md` §4 — document `applied_count`/`last_applied` + the tiered signal.
- `knowledge/INDEX.md` header + `.telemetry.json` schema — the new counters seed into
  existing rows on a `/curate` reconcile; the INDEX schema note is updated in the same gated pass.

## References
- `skills/metrics/report.py` + `SKILL.md` (the report that surfaced `useful_count = 0`)
- `agents/memory.md` (Retrieval Feedback + telemetry counters)
- `hooks/capture_session.py` (mechanical `loaded` derivation this extends)
- `docs/FRAMEWORK.md` §4 (knowledge library + telemetry sidecar)
