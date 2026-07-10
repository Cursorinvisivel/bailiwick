---
name: bailiwick-curate
description: Curate Bailiwick captures and session outputs into the knowledge library under the same human gate as Claude Code `/curate`. Use when the user asks Codex to curate, run `/curate`, process pending `.bailiwick-outputs/` or `~/.bailiwick/captures/` items, restore encrypted dirty-zone captures, update telemetry, deduplicate candidates, or propose knowledge-library updates.
---

# Bailiwick Curate

## Overview

Run the Bailiwick curation workflow from Codex without copy-pasting the Claude Code `/curate`
prompt. This is a thin Codex wrapper; the canonical procedure remains in Bailiwick's
`skills/curate/SKILL.md`.

## Workflow

1. Resolve the Bailiwick root:
   - Prefer `$BAILIWICK`.
   - If unset and this skill is symlinked from the framework, infer the repo root two directories above this skill.
   - Fallback to `/path/to/bailiwick` if it exists.
2. Read the canonical instructions completely:
   - `$BAILIWICK/skills/curate/SKILL.md`
   - `$BAILIWICK/agents/memory.md`
3. Follow the canonical `/curate` procedure exactly, with these Codex adaptations:
   - Treat a user request for `/curate`, `curate`, `bailiwick curate`, or pending-capture processing as an invocation of this skill.
   - Codex does not run the Claude Code slash-command UI; do the workflow directly in the current turn.
   - Codex does not run Claude Code Stop/SessionEnd hooks; include manual Codex session outputs from `.bailiwick-outputs/*.md` and shadow-mode `~/.bailiwick/captures/*/*.md`.
   - Preserve the same human gate: do not write to `$BAILIWICK/knowledge/` unless the user explicitly approves the proposed batch in this session.
4. When encrypted dirty-zone backup is enabled in `$BAILIWICK/.bailiwick-sync.json`, run the canonical restore command only when needed:
   - `bash $BAILIWICK/hooks/capture_backup.sh pull`
   - If decryption needs a passphrase or pinentry and fails, report the blocker and continue with local pending inputs.
5. At the end, write or update a short Codex session output in `.bailiwick-outputs/` unless the user explicitly asked not to.

## Guardrails

- Never commit or push.
- Never promote raw captures directly; abstract and sanitize before proposing knowledge content.
- Never delete unreviewed inputs. Retire only processed inputs according to the canonical procedure.
- Do not modify `$BAILIWICK/knowledge/` without explicit approval.
