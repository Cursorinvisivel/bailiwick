---
id:            adr-XXX-slug          # matches filename (without .md)
type:          decision
status:        proposed              # proposed | accepted | deprecated | superseded
date:          YYYY-MM-DD
authors:       [names]
tags:          [list]
supersedes:    []                    # ADR ids this replaces
superseded_by:                       # ADR id that replaces this (set when deprecated/superseded)
scope:         generic               # generic | client:<id> | external:<id>
---

# ADR-XXX — [Title]

> Decision record. The frontmatter above is canonical (`id`, `status`, `date`, `authors`).
> Decisions are **status-tracked** — exempt from `.telemetry.json` counters and topic→pattern
> graduation. Index this file under INDEX.md `## decisions`.

---

## Context

Describe the problem, the pressure driving the decision, and the relevant technical context.
Include known constraints.

## Decision

Describe the decision taken clearly and directly.

## Options Considered

### Option A — [Name]
**Description:** ...
**Pros:** ...
**Cons:** ...

### Option B — [Name]
**Description:** ...
**Pros:** ...
**Cons:** ...

### Option C — [Name]
**Description:** ...
**Pros:** ...
**Cons:** ...

## Rationale

Why the selected option was chosen over alternatives.
Which trade-offs were accepted and why.

## Consequences

### Positive
- ...

### Negative / Accepted trade-offs
- ...

### Risks and mitigation
| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| ... | ... | ... | ... |

## References
- [link to relevant documentation]
- [related ADR]
