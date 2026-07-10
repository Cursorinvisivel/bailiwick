---
id: org-shorthands
type: context
tags: [org, client, shorthand, scope, naming, registry]
confidence: low
last_validated: 2026-06-26
supersedes: []
scope: generic
---

# Org / Client Shorthands

Controlled registry of organisation shorthands. **One shorthand per org**, reused as the
single identifier across the framework — never invent a second scheme for the same org:

| Used as | Where |
|---|---|
| `clients/<id>/` folder | Client-specific knowledge files |
| `scope: client:<id>` | Topic / pattern frontmatter |
| `scope: external:<id>` | Frontmatter on knowledge **ingested from a federation source** (`agents/federation.md`) — provenance from a KB we do not own (e.g. `external:globex`) |
| `project_id` association | Memory telemetry (`agents/memory.md`) |
| `{org}` token | Resource names (`patterns/caf-naming-taxonomy.md`) |

## Registry

| Shorthand (`<id>`) | `{org}` token | Organisation | Notes |
|---|---|---|---|
| `acme` | `acme` | Acme Corp (example) | **Default** — own resources / not client-owned |
| `wombat` | `wmb` | Wombat Industries — Web Platform engagement (example) | `<id>` keeps the engagement form; `{org}` token tightened for name-length limits |

## Rules
- `<id>` (folder + scope) and the `{org}` token are normally **identical**. They diverge only when
  the engagement `<id>` is too long/hyphenated for a name token (2–4 chars, no inner hyphen) — then
  record both columns, as for `wombat` → `wmb`.
- Lowercase always.
- When no client owns the resource, default to your own org shorthand (`acme` in these examples).
- **`external:<id>`** is a distinct scope namespace for federation-ingested knowledge — it is neither
  `client:<id>` (work we do for a client) nor `generic` (our own reusable knowledge). It flags
  knowledge whose origin is an external/company KB; the Federation Agent sets it on ingest, with a
  matching `source:` field. Keep `<id>` aligned with the source's `scope` in `.bailiwick-sources.json`.
- **Never invent** a shorthand — add a row here (human-gated via `/curate`) before first use.

## Related
- [CAF naming taxonomy](../patterns/caf-naming-taxonomy.md)
