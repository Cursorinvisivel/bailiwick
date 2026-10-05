# definitions/ — how documents are built, per client

`knowledge/` holds what we **know**: facts, judgement, patterns, client context. `definitions/`
holds how a **document is built** for a client: section structure, wording rules, document and
diagram templates, PDF themes, zone rules as data, logos and fonts. Knowledge informs judgement.
Definitions are binding specs that a documentation tool loads, validates and enforces. The two have
different lifecycles, so they live apart (ADR-011).

```
definitions/
  README.md                 this file (the only file that ships in the public repo)
  clients/<client-id>/      one folder per client; <client-id> matches knowledge/clients/<client-id>/
                            and the org-shorthands.md registry
```

The layout **inside** `clients/<client-id>/` belongs to the documentation tool that builds it, for
example tech-scribe's profile format: a `profile.toml` plus `document/`, `diagram/` and `review/`.
Bailiwick stores those files and does not interpret them. The tool validates them against its own
schema.

## Rules

- **Authored on purpose, not curated from sessions.** Definitions are written by hand or by the
  documentation tool's builder (e.g. `scribe profile publish`), and only when you ask for it.
  They never come from captures, and `/curate` does not promote them.
- **Reviewed by git diff.** A change is a normal commit, and committing still needs your go-ahead
  (guardrail). Use the `definitions:` commit prefix. On a multi-machine setup, run
  `bash hooks/sync_knowledge.sh` afterwards to propagate the change. It pushes whole commits, so
  definitions travel the same way as knowledge.
- **One home per fact.** When a definition needs a fact ("Corp is internal-facing"), it references
  the knowledge `id` instead of copying the text. If the fact changes, it changes once, in
  `knowledge/`.
- **Outside the knowledge machinery.** Definitions get no frontmatter schema, telemetry rows,
  confidence levels or graduation. They are not in the index injected each session, not in Memory
  search, and not served by the Desktop `bailiwick-knowledge` server (rooted at `knowledge/`).
- **Binaries are allowed.** Draw.io templates and libraries, fonts and logos may live here. Keep
  them reasonably small, because every machine in the sync fleet clones them.
- **Data only, never code.** A documentation tool must not execute anything it finds here.

## Privacy

`definitions/clients/` is client material, exactly like `knowledge/clients/`:

- It lives only in your **private instance**. A public-origin clone is contribute-only (ADR-009):
  sync refuses to push from it and `/curate` refuses to run in it. Never commit client definitions
  to the public repo, and remember that a raw `git push` by hand is outside that guard.
- `/purge <client-id>` deletes `definitions/clients/<client-id>/` along with the client's knowledge,
  and its `--history` output covers that path too.

## Who uses it

The Docs stage (`agents/docs.md`) checks here first. When `definitions/clients/<client-id>/` exists
for the client, HLD and LLD work for that client goes to the documentation tool that owns the
definitions, and the Docs stage hands it off instead of drafting from `knowledge/templates/`.
Without definitions, the Docs stage works as before. See ADR-011.
