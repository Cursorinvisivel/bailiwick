---
name: bailiwick-enrich
description: Scan a bootstrapped repository and draft enriched LLM instruction files using the same workflow as Claude Code `/enrich`. Use when the user asks Codex to enrich repo instructions, run `/enrich`, fill project-specific `CLAUDE.local.md` or `.bailiwick.local.md`, draft public-safe `AGENTS.md`/`CLAUDE.md`/Copilot/Gemini instructions, or inspect a bootstrapped repo for instruction-file gaps.
---

# Bailiwick Enrich

## Overview

Run the Bailiwick enrichment workflow from Codex without copy-pasting the Claude Code `/enrich`
prompt. This is a thin Codex wrapper; the canonical procedure remains in Bailiwick's
`skills/enrich/SKILL.md`.

## Workflow

1. Resolve the Bailiwick root:
   - Prefer `$BAILIWICK`.
   - If unset and this skill is symlinked from the framework, infer the repo root two directories above this skill.
   - Fallback to `/path/to/bailiwick` if it exists.
2. Read the canonical instructions completely:
   - `$BAILIWICK/skills/enrich/SKILL.md`
   - `$BAILIWICK/agents/docs.md`
   - Any domain context file named by the canonical workflow after scanning the repo.
3. Follow the canonical `/enrich` procedure exactly, with these Codex adaptations:
   - Treat a user request for `/enrich`, `enrich`, `bailiwick enrich`, or instruction-file enrichment as an invocation of this skill.
   - Codex does not run the Claude Code slash-command UI; do the workflow directly in the current turn.
   - Keep the same draft-only posture: propose diffs and ask for approval before writing instruction files when the canonical workflow requires approval.
4. Preserve the two-layer boundary:
   - Public/team files remain framework-agnostic and public-safe.
   - Hidden complements carry framework wiring and concrete project context.
5. At the end, write or update a short Codex session output in `.bailiwick-outputs/` unless the user explicitly asked not to.

## Guardrails

- Never commit or push.
- Never leak framework paths, personal identifiers, client names, cloud IDs, secrets, or concrete backend details into committed team instruction files.
- Never overwrite existing team instruction files wholesale; merge or propose targeted diffs.
- Do not modify `$BAILIWICK/knowledge/` as part of enrichment.
