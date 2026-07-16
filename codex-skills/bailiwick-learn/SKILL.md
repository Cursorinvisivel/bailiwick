---
name: bailiwick-learn
description: Onboard an existing repository's knowledge into the Bailiwick pipeline from Codex — scan the repo (decisions, IaC patterns, conventions, pitfalls) and stage the distilled candidates as a pre-digested capture that `/curate` promotes under the human gate. Use once after bootstrapping an existing project, alongside `$bailiwick-enrich`.
---

# Bailiwick Learn

## Overview

Run the Bailiwick project-onboarding scan from Codex without copy-pasting the Claude Code
`/learn` prompt. This is a thin Codex wrapper; the canonical procedure remains in the
Bailiwick's `skills/learn/SKILL.md`.

## Workflow

1. Resolve the Bailiwick root:
   - Prefer `$BAILIWICK`.
   - If unset and this skill is symlinked from the framework, infer the repo root two directories above this skill.
   - Fallback to `/path/to/bailiwick` if it exists.
2. Read the canonical instructions completely:
   - `$BAILIWICK/skills/learn/SKILL.md`
   - `$BAILIWICK/agents/memory.md` (Step 1: what /curate extracts from the capture)
3. Follow the canonical `/learn` procedure exactly, with these Codex adaptations:
   - Treat "learn this repo", "onboard this project's knowledge", or "seed the KB from this repo"
     as an invocation of this skill.
   - Do the repo scan with Codex's own file tooling; keep the same distill-don't-transcribe filter.
   - Honor the canonical skill's batching rule on larger repos: inventory first, scan in bounded
     batches sequentially (no subagent delegation in Codex — just one batch at a time), and append
     each batch's distilled findings to a working notes file outside the repo before reading the
     next. Author the final capture from the notes, never from recall of a long scan.
   - Write the capture to the same staging the canonical skill resolves (seeded:
     `.bailiwick-outputs/`; shadow: `~/.bailiwick/captures/<repo-key>/`) — it is a manual
     session output, the channel Codex already uses.
4. Do NOT promote anything: the capture is the only output. Promotion happens later via
   `/curate` (or `$bailiwick-curate`), under the human gate.

## Guardrails

- Never commit or push without an explicit user go-ahead (the capture staging is never committed).
- Never write to `$BAILIWICK/knowledge/` — `/learn` has no promotion path; the gate lives in `/curate`.
- The capture is dirty-zone data: client detail is allowed in it, but it is never shared or promoted unsanitised.
