# Bailiwick — roadmap & non-goals

Bailiwick is **single-user by design today** — one owner, one primary machine. That is a deliberate
scope choice, not an oversight (see [FRAMEWORK.md §13](docs/FRAMEWORK.md)). This document keeps the
honest analysis of what it would take to grow beyond that, plus smaller items on the radar, out of
the core reference where it would otherwise read as unfinished.

**Nothing here is a commitment or a shipped feature** — it is design thinking. Discussion and
contributions are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## A team / multi-contributor version

The largest possible evolution is a shared, governed, multi-contributor "team brain." This section is
honest about what already points that way and what would have to change, so you can judge whether to
adopt Bailiwick as-is (single practitioner / small trusted team) or invest in generalising it.

### What already points the right way
- **Federation** is the brain-to-brain connector. Two viable topologies, already supported in
  primitive form:
  - *Hub-and-spoke (consume):* the team/company brain is a **federation source**; each person's
    Bailiwick clone consults it read-only and ingests under gate. Confidentiality-safe, low-coordination.
  - *Contribute-up:* the central brain is a git repo; personal Bailiwick clones are **satellites** that
    push `sync/<machine>` PRs into it (the existing sync model). Central merge authority governs.
- **Scope namespaces** (`generic` / `client:<id>` / `external:<id>`) already segregate provenance —
  the backbone of a multi-tenant brain.
- **Security Review's leakage check** already prevents client-cross-contamination on promotion — a
  governance control a team brain needs.
- **Tool-neutral** (Claude Code / Codex / Gemini / Copilot) — fits a mixed-tooling team.
- **Hidden wiring** keeps the framework invisible in client/colleague repos — relevant if a team
  brain is consumed inside client engagements.

### What must change (the hard parts)
1. **Telemetry is single-writer.** `.telemetry.json` explicitly loses concurrent increments; today
   it is patched by making one machine "central". A team brain needs **per-contributor telemetry
   shards aggregated on read**, or a small service/DB. This is the #1 structural change.
2. **Curation is single-human-gated.** A team brain needs **governance roles** — who may run
   `/curate`, who approves promotions, domain owners, cadence — and an audit trail of who promoted
   what. The gate must become a reviewable workflow (PR review is the natural fit).
3. **Identity & attribution.** Frontmatter has no author/contributor field; graduation counts
   `distinct_projects_used` but not `distinct_contributors`. A team brain needs per-entry
   attribution and contributor-aware graduation signals.
4. **Access control & confidentiality boundaries.** Personal (own-org) vs company (employer) vs
   client (`acme`) knowledge must be **segregated with read/write policy** — who can see and
   promote which scope. Today this is convention, not enforcement. Client-identifying detail must
   never cross clients; company knowledge must not leak into client deliverables or vice-versa.
5. **Conflict scale.** Append-heavy `INDEX.md` / `.telemetry.json` already conflict at two writers.
   At team scale: shard indexes aggressively, move telemetry off a single file, and/or front the
   brain with a service. Branch-per-contributor + PR is a stopgap, not an end state.
6. **Retrieval at volume.** The INDEX tree is a **manually-curated map** — excellent at small scale,
   labour-intensive at large scale. Evaluate semantic/vector retrieval as a complement (keep the
   curated map for trust; add embeddings for recall).
7. **Read-only is policy, not enforced.** Federation read-only depends on agent discipline. A team
   brain exposed to many users needs a hardware/protocol guarantee (read-only mount, a read-only
   MCP server, or an API with auth) — especially if the central brain holds others' IP.
8. **Storage substrate.** Today: git + Markdown + JSON. Evaluate whether that scales for a team
   brain or whether a thin service (API + index + access control) is warranted, with git/Markdown
   as the source-of-truth backing store.

### A possible tiered topology to evaluate
```
   Project brain         Team brain              Company brain
   (per repo)            (org shared)             (company / external)
   .bailiwick-outputs +    ──▶  Bailiwick       ──▶  federation source
   project CLAUDE.md     (this, generalised)     (read-only consume;
   client:<id> scope     governed, multi-writer   contribute via their gate)
        │  promote-up (gated)   │  consult + ingest (gated)
        └───────────────────────┴───────────────────────────────▶
            each tier promotes upward under a human/governance gate;
            federation connects tiers read-only with explicit scope + provenance
```
- **Project brain:** ephemeral, repo-scoped (the existing `.bailiwick-outputs/` + `clients/<id>/`); the
  natural source of candidates that promote up.
- **Team brain:** Bailiwick, generalised per *What must change* above (multi-writer telemetry,
  governance, attribution, access control).
- **Company brain:** consumed via federation (read-only) and contributed to through *their* gate.

### Open questions
- Hub-and-spoke vs contribute-up vs hybrid — which topology per tier?
- Where does the human gate live when contributors are many (PR review? designated curators?)?
- Telemetry: per-contributor shards vs a service — and what graduation signal replaces
  single-writer counts?
- How is scope/confidentiality **enforced** (not just conventional) across personal/company/client?
- Does the curated INDEX tree stay the retrieval mechanism, or is semantic search added?
- Git-Markdown-as-substrate vs a thin brain service — at what team size does the trade flip?

---

## Smaller items on the radar

- **Federation transports beyond filesystem.** Federation consults `filesystem` sources today
  (implemented); the `git` / `mcp` / `http` source kinds are reserved in `.bailiwick-sources.json`
  but not yet implemented ([FRAMEWORK.md §9](docs/FRAMEWORK.md)).
- **Enforced read-only federation.** Read-only is currently agent policy, not transport-enforced;
  a read-only mount, a read-only MCP server, or an authed HTTP source would make it a real control.
- **Semantic / vector retrieval** as a complement to the curated INDEX tree — keep the curated map
  for trust, add embeddings for recall.
- **Provider / stack frontmatter tagging** on seed knowledge, so the GCP/Terraform-leaning seed
  patterns are cleanly filterable and swappable for other stacks (the machinery is domain-neutral;
  only the seed content leans a particular way).
