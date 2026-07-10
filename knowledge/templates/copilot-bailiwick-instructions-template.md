---
applyTo: "**"
---
# Bailiwick — framework instructions (complement)

> Auto-applied by GitHub Copilot in this repo **in addition to** the team's
> `.github/copilot-instructions.md` — it does NOT replace it. This file is framework wiring,
> kept local/hidden (excluded via `.git/info/exclude`); the team's shared instructions are untouched.

## Framework
Agents and the knowledge library live in the Bailiwick repo (`$BAILIWICK`).
Absolute path: /path/to/bailiwick

Open agent roles and knowledge files by absolute path from there — nothing is copied into this repo.

- **Knowledge index:** `$BAILIWICK/knowledge/INDEX.md`. Load topics/patterns on-demand
  (start with `topics/`, then `patterns/`; descend domain sub-indexes under `indexes/` if present).
  Maximum 5 content files per task; index navigation doesn't count.
- **The framework is the default** — orchestration is proportional (see
  `$BAILIWICK/agents/lead.md`): route substantial work through the Lead; handle
  trivial edits inline with knowledge loaded.
- **Capture/curation** is Claude Code-only (hooks); under Copilot, knowledge promotion is manual via
  the Memory agent flow (`$BAILIWICK/agents/memory.md`).

## Engineering defaults (always)
Before writing, **scan the repo and knowledge library for existing modules/patterns/code you can
reuse or extend — prefer that over creating new**. Apply least privilege, CAF naming + required
labels, pinned provider/module versions, no secrets in code, plan-before-apply, and match the
surrounding style. Full baseline: `$BAILIWICK/knowledge/context/engineering-defaults.md`.

## Non-Negotiable Rules
- Never run `terraform apply`/`destroy` or side-effecting cloud CLI.
- Never `git commit`/`push` without explicit approval.
- Never modify `$BAILIWICK/knowledge/` without a human gate (via `/curate`).
- All outputs are drafts for human review.
