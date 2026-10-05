---
id:            adr-011-knowledge-vs-definitions
type:          decision
status:        proposed
date:          2026-10-05
authors:       [Francisco Ferrinho]
tags:          [adr, definitions, knowledge, documentation, docs-stage, boundary, privacy, purge]
supersedes:    []
superseded_by:
scope:         generic
---

# ADR-011 — Knowledge vs definitions; an external documentation tool builds documents

> Status is **proposed** (2026-10-05). This PR implements the framework side: `definitions/README.md`,
> the Docs-stage hand-off, the Lead routing note, and `/purge` coverage. Instance content (practice
> knowledge, a first client's definitions) is added in the private instance, not here.

## Context

Bailiwick holds knowledge: how its owner works, design best practices, and client facts, all
curated from sessions under a human gate. Its Docs stage drafts ADRs, HLDs, LLDs, runbooks and
workshops from Markdown templates in `knowledge/templates/`.

Client documentation outgrew that model. A client HLD has a fixed section structure, wording rules,
a branded AsciiDoc/PDF theme, a draw.io template and component library, and traffic rules between
landing zones that a validator enforces. Building and checking that takes a dedicated engine
(parsing, diagram layout, rule validation, rendering). That is a separate tool, tech-scribe, which is
meant to be open source and so must contain no client material.

That leaves a placement question for the per-client build specs ("definitions"). Two easy answers
are both wrong:

- **Inside the documentation tool.** The tool would have to segment, protect and purge client data
  by itself, which duplicates what Bailiwick already does (`clients/<id>/`, scopes, the
  `org-shorthands.md` registry, `/purge`, ADR-009). It would also keep client material in a repo
  meant for publication.
- **Inside `knowledge/`.** Definitions are not knowledge. They are authored on purpose rather than
  curated from sessions. Confidence levels, usage telemetry and graduation mean nothing for a PDF
  theme. They include binaries (draw.io libraries, fonts, logos) that would bloat Memory search and
  the index. And `/curate` is the wrong gate for a file whose real review is a diff.

## Decision

1. **Two kinds of content, two homes, one repo.**
   - `knowledge/` holds facts and judgement, curated through `/curate`. No change.
   - `definitions/` (new, at the repo root, outside `knowledge/`) holds per-client document build
     specs under `definitions/clients/<client-id>/`, where `<client-id>` matches
     `knowledge/clients/<client-id>/` and the `org-shorthands.md` registry.
   - **One home per fact:** a definition that needs a fact references the knowledge `id` and never
     copies it.

2. **Definitions follow their own lifecycle.** They are written by hand or by the documentation
   tool's builder, only when the user asks. Review is a git diff, the commit prefix is
   `definitions:`, and the commit needs the user's go-ahead (guardrail). `/curate` does not handle
   them, and they never come from captures. The "never modify `knowledge/` without `/curate`" rule
   is unchanged, because `definitions/` is outside `knowledge/`. Propagation across machines uses the
   existing `hooks/sync_knowledge.sh`, which pushes whole commits whatever paths they touch.

3. **Definitions sit outside the knowledge machinery.** No frontmatter schema, telemetry,
   confidence or graduation. They are not in the injected index, not in Memory search, and not served
   by the Desktop `bailiwick-knowledge` MCP server. All of this follows from the location (each of
   those mechanisms is scoped to `knowledge/`), so no code changes are needed.

4. **The documentation tool owns the format; Bailiwick only stores it.** The layout inside
   `definitions/clients/<client-id>/` is the tool's profile schema (for tech-scribe: `profile.toml`,
   `document/`, `diagram/`, `review/`). The tool validates it, and it must treat it as data only,
   never executing anything from it. The tool reaches Bailiwick only through filesystem roots it is
   configured with (`definitions/clients/` for profiles, `knowledge/` for context resolved by `id`).
   It has no Bailiwick-specific code and works without Bailiwick. The tool never writes to
   `knowledge/`. What it learns comes back as candidates through the normal capture → `/curate` path.

5. **The Docs stage hands off when definitions exist.** When `definitions/clients/<client-id>/`
   exists for the client, HLD and LLD work, and any document needing that client's profile or a
   diagram, goes to the documentation tool. The Docs stage reports the hand-off instead of drafting.
   ADRs, runbooks, module READMEs and workshops stay with the Docs stage. Without definitions (any
   public-repo user, or a client with no profile), the Docs stage drafts from `knowledge/templates/`
   as before, which is why those templates stay. The hand-off is optional, and Bailiwick has no
   dependency on the tool.

6. **Privacy matches client knowledge.** `definitions/clients/` lives only in the private instance.
   ADR-009's contribute-only rule already stops a public-origin clone from propagating. `/purge`
   deletes `definitions/clients/<id>/` with the rest of the client, and its `--history` output covers
   the path.

## Options considered

- **Definitions inside the documentation tool's repo.** Rejected: it duplicates segmentation and
  purge, and puts client material in a repo meant for open source.
- **Definitions under `knowledge/clients/<id>/delivery/`, exempt from telemetry.** Rejected: every
  `knowledge/`-scoped mechanism (index, Memory, Desktop server, metrics reconciliation, `/curate`)
  would need an exception, and one missed exception leaks binaries into search or the wrong gate onto
  a diff-reviewed file. A separate root needs no exceptions at all.
- **A separate private definitions repo that Bailiwick points to.** Rejected for now: it adds a
  second private remote, sync path and purge surface for one consumer. It is easy to revisit, because
  the tool only sees a filesystem root.
- **Merge the documentation engine into Bailiwick.** Rejected: rendering, diagram layout and
  validation have a different lifecycle and audience from a governed knowledge framework, and the
  engine is meant to be open source on its own.

## Consequences

- A new top-level folder with its own rules (`definitions/README.md`). Users who never install a
  documentation tool see only that README.
- The Docs stage narrows for clients with definitions, and is unchanged for everyone else.
- `/purge` has one more surface to scan and delete. Its residual check (`git grep`) already covers
  the whole tree.
- Binaries in a synced repo: every fleet machine clones them. This is acceptable at expected sizes
  (tens of MB at most per client). Revisit with Git LFS or a separate repo (see Options) if that
  stops being true.
- Raw `git push` by hand stays outside ADR-009's guard, as for knowledge.
- Practice knowledge (the owner's architecture framework, writing style) and client facts used by
  definitions go into `knowledge/` through `/curate` in the private instance, so definitions can
  cite them by `id`.
