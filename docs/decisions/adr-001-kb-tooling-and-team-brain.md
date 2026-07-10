---
id:            adr-001-kb-tooling-and-team-brain
type:          decision
status:        accepted
date:          2026-06-26
authors:       [Francisco Ferrinho]
tags:          [adr, knowledge-base, team-brain, tooling, obsidian-wiki, federation, build-vs-buy]
supersedes:    []
superseded_by:
scope:         generic
---

# ADR-001 — Knowledge-base tooling: keep Bailiwick (agent-first, git-native, gated); decline obsidian-wiki; defer a team brain

---

## Context

Bailiwick is a markdown-only, agent-consumed, human-gated knowledge substrate. Two questions came
up while shaping it:

1. Should it adopt a **ready-made** knowledge framework — specifically
   [obsidian-wiki](https://github.com/Ar9av/obsidian-wiki) — instead of (or alongside) the bespoke
   substrate?
2. Should the framework grow toward **team / shared brains** (per-contributor KBs + a transversal KB
   a whole team uses to share and level ways-of-working)?

Hard constraints that shape the answer: knowledge lives in **git repositories the operator controls**;
strict **confidentiality separation between scopes** (an operator's own work vs. work performed for
others must never cross-contaminate — the `generic` / `client:<id>` / `external:<id>` scopes exist for
exactly this); the primary consumer is an **AI coding agent**, with humans a secondary
(learning/leveling) audience.

This ADR records the evaluation so the reasoning is reusable — notably if a future project asks for a
team brain (see `ROADMAP.md`, which analyses what that separate effort would require).

## Decision

1. **Keep Bailiwick as the agent-first, git-native, human-gated substrate.** Do not replace it.
2. **Do not adopt obsidian-wiki** (the framework). Its core value — automated ingestion/merge and a
   human-first Obsidian wiki — does not fit an agent-first, confidentiality-gated use case.
3. **A graphical / "brain-like" view is a standing, zero-cost option — via the *app*, not the
   framework.** Because the library is nothing but markdown with relative cross-links and frontmatter
   tags, any Obsidian-compatible tool (Obsidian, Logseq, Foam, …) can open `knowledge/`
   as a vault and render the graph, backlinks, tag panes, and search **read-only over the same files**
   — no conversion, no framework change, no lock-in. This is what to borrow if human browsing is
   wanted: the *viewer app*, never the obsidian-wiki framework, its Python runtime, or its auto-ingest.
   (The graph today is built from the existing markdown links + tags; adopting `[[wikilinks]]` would
   enrich it but is not required.)
4. **Defer any team / shared brain to a separate future effort.** The framework stays deliberately
   single-user. Federation (§9) is the policy-read-only bridge that lets it sit alongside other brains
   without becoming one.

## Options Considered

### Option A — Adopt obsidian-wiki wholesale
**Description:** A standalone Python framework of "skill" files that drive an AI agent to build and
maintain an Obsidian markdown wiki (Karpathy "LLM Wiki" pattern): document/PDF/transcript ingestion,
multi-agent chat-history mining, delta manifests, wikilink graph + Obsidian graph view, orphan /
broken-link / contradiction linting, optional QMD semantic search. Human-first; Obsidian + Python
dependencies; installable via pip / npm skills registry.
**Pros:** Ready to adopt; community + ongoing updates; strong human-browsing UX (graph, backlinks);
linting and semantic-search features Bailiwick lacks; good at human knowledge-sharing.
**Cons:** Human-first, not agent-first (no injected lean index, no token budgeting, no proportional
orchestration); **auto-ingest/merge is a confidentiality liability** for sensitive data — the opposite
of the human-gated promotion the framework relies on; adds a Python runtime + Obsidian dependency on
locked-down laptops; no federation / multi-tier model; adopting it means inheriting its governance
posture (or bolting the framework's own onto it anyway).

### Option B — Keep and extend Bailiwick (CHOSEN)
**Description:** Continue with the markdown + git + thin-agent-instruction substrate already built:
injected recursive INDEX tree, enforced capture, `/curate` gated promotion, scopes
(`generic`/`client:<id>`/`external:<id>`), federation, multi-machine sync.
**Pros:** Agent-first and token-disciplined; git-native to the repositories and laptops it already runs
on; governance (human gate, sanitization, scope segregation) already built — and more important with
confidential data, not less; federation already provides the brain-to-brain bridge; tool-neutral
(Claude Code / Codex / Copilot / Gemini).
**Cons:** Bespoke — maintenance burden and bus factor; small/nascent community; no human-browsing UX
out of the box; manual curation effort.

### Option C — A SaaS / hosted KB (Notion, Obsidian Sync, mem0, etc.)
**Description:** Adopt a hosted knowledge/memory product as the store.
**Pros:** Turnkey; good human UX; some offer team sharing natively.
**Cons:** Off-machine, third-party storage of confidential knowledge → data-residency / confidentiality
concerns; weak fit for git-native, agent-consumed, locked-down-laptop constraints. Rejected on
governance grounds despite a hosted-KB MCP (e.g. Notion) being readily available.

## Rationale

- **Agent-first vs human-first is the deciding axis.** The whole workflow is agent-consumed; the one
  thing obsidian-wiki adds that the framework lacks (human browsing) is already obtainable at
  near-zero cost by opening the same files in any Obsidian-compatible *app* — a property of the
  plain-markdown substrate, not something obsidian-wiki's framework is needed for.
- **"Ready" ≠ "right."** obsidian-wiki is ready, but for a human-first, low-governance use case that
  isn't this one. Its headline feature (auto-ingest) is precisely what a confidentiality-gated posture
  forbids.
- **Governance is already built here and is non-negotiable with confidential data.** Human-gated
  promotion, scope segregation, and the Security-Review leakage check exist; adopting a tool that
  lacks them would be a step backward.
- **The team-brain question is a federation/governance problem, not a tooling gap.** Neither tool is
  turnkey for the per-contributor + transversal topology; Bailiwick is closer (federation + sync
  already exist), but it still needs the structural changes catalogued in `ROADMAP.md`. That is a
  separate effort, not this repo.

## Consequences

### Positive
- Fit, governance, and confidentiality posture preserved; no new runtime/dependency on locked-down laptops.
- The evaluation is now durable knowledge — a future team-brain decision starts from here + `ROADMAP.md`
  rather than re-litigating obsidian-wiki.
- A cheap, well-scoped human-browsing path (any Obsidian-compatible app as a read-only graph/backlink
  view over the same markdown) is available whenever human leveling becomes a priority — standing, not
  hypothetical.

### Negative / Accepted trade-offs
- Continued **bespoke maintenance** and bus-factor risk.
- **No human-browsing UX** until/unless the Obsidian-app view is added.
- Curation stays **manual effort** (the price of the human gate).

### Risks and mitigation
| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Bespoke substrate rots / hard to hand over | Medium | Medium | Keep it boring: plain markdown + git + MCP; no custom runtime required to function |
| Lack of human browsing slows team leveling later | Medium | Low | Any Obsidian-compatible app as a read-only graph/backlink view over the same markdown (Decision pt 3) |
| A real team-brain need arrives and this decision is mistaken for "never" | Low | Medium | This ADR defers, not forbids; `ROADMAP.md` holds the design analysis; revisit as a separate repo consuming this via federation |

## References
- obsidian-wiki — https://github.com/Ar9av/obsidian-wiki
- `docs/FRAMEWORK.md` §9 (Federated memory — the brain-to-brain bridge)
- `docs/FRAMEWORK.md` §13 (Scope & non-goals) · `ROADMAP.md` (the team-version design analysis)
- `agents/federation.md`
