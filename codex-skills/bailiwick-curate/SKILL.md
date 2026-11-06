---
name: bailiwick-curate
description: Curate Bailiwick captures and session outputs into the knowledge library under the same human gate as Claude Code `/curate`. Use when the user asks Codex to curate, run `/curate`, process pending `.bailiwick-outputs/` or `$BAILIWICK_HOME/captures/` (default `~/.bailiwick`) items, restore encrypted dirty-zone captures, update telemetry, deduplicate candidates, or propose knowledge-library updates.
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
   - Codex does not run Claude Code Stop/SessionEnd hooks; include manual Codex session outputs from `.bailiwick-outputs/*.md` and shadow-mode `$BAILIWICK_HOME/captures/*/*.md` (`$BAILIWICK_HOME` defaults to `~/.bailiwick`).
   - For periodic requests, follow `$BAILIWICK/skills/curate/references/gcp-freshness.md` even when
     captures are empty. Dispatch `bailiwick-cloud-research-freshness` (fetch-only; pass the
     procedure and registry inline) using native delegation if available, alongside independent
     capture processing. The generated Codex adapter does not carry its tool restriction, so
     disclose that weaker isolation and collect the research result **before** restoring
     off-machine captures. Disclose sequential/inline fallback; no durable
     background execution is implied. Persist the result in the framework root and collect it
     before session end or explicitly mark the run incomplete. Only previously completed reports
     in the initial gather snapshot are curation candidates.
   - For canonical Steps 2a (distill) and 5a (independent review), delegate when the host can spawn
     the named stage; pass the sizing it can express (Codex cannot pick the model, so record the
     model tier as inherit and pass effort where the adapter accepts it). Otherwise run them inline
     and disclose "inline fallback" (never call an inline self-review independent). Honour the
     canonical inbox rule: delete the decrypted `.bailiwick-inbox/` copies after extraction and
     before any 5a dispatch, and use `bailiwick-security-review-local` for the 5a security pass.
   - Preserve the same human gate: do not write to `$BAILIWICK/knowledge/` unless the user explicitly approves the proposed batch in this session.
4. When encrypted dirty-zone backup is enabled in `$BAILIWICK/.bailiwick-sync.json`, run the canonical restore command only when needed:
   - `bash $BAILIWICK/hooks/capture_backup.sh pull`
   - If decryption needs a passphrase or pinentry and fails, report the blocker and continue with local pending inputs.
5. At the end, write or update a short Codex session output in `.bailiwick-outputs/` unless the user explicitly asked not to. When a freshness run happened, include its run ID and `freshness_only_ids` so a later curation excludes those maintenance reads from telemetry.

## Guardrails

- Never commit or push.
- Never promote raw captures directly; abstract and sanitize before proposing knowledge content.
- Never delete unreviewed inputs. Retire only processed inputs according to the canonical procedure.
- Do not modify `$BAILIWICK/knowledge/` without explicit approval.
