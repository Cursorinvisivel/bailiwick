---
name: bailiwick-lead
description: Coordinate a task as Bailiwick Lead using specialist subagents, explicit dependencies, independent review, and an execution report. Use when the user requests the Lead, team orchestration, or the full Quality Workflow for a concrete task.
---

# Bailiwick Lead

This is a thin entry point to the shared, tool-neutral Lead skill.

1. Resolve `$BAILIWICK` from the environment or active private operator guidance. If absent,
   resolve this wrapper's physical path (following symlinks); the framework root is two
   directories above `codex-skills/bailiwick-lead`. Confirm `agents/lead.md` exists; ask for
   the framework path if it cannot be resolved.
2. Read `$BAILIWICK/skills/lead/SKILL.md` completely and follow its execution contract.
   It owns stage selection, dispatch briefs, dependency order, review, and completion evidence.
3. Keep the current main session as coordinator. Use the available native `bailiwick-*`
   custom agents for the applicable stages. If the runtime prohibits or lacks delegation,
   apply the canonical skill's disclosed fallback and report the limitation honestly.
4. Preserve the shared skill's human gates and manual capture procedure. Loading this
   wrapper does not authorize commits, pushes, PRs, deployment, or knowledge promotion.
