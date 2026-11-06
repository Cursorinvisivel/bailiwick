---
name: bailiwick-lead
description: Default way of working for substantial tasks in a Bailiwick-wired repository (a .bailiwick.local.md or CLAUDE.local.md complement references the framework, the repo is in ~/.bailiwick/allowlist, BAILIWICK_SHADOW=1 is set, or it is the framework repo itself) — more than one file beyond typos/formatting/mechanical renames, any other IaC change, any IAM/network/secrets/security-control change, a single-file change adding behaviour beyond a small fix, a new module/document/test suite or substantive doc rewrite, a design decision, or a requested review or researched recommendation. Coordinates specialist subagents with explicit dependencies, independent review, and an execution report; use it without being asked. Skip it for questions, lookups, explanations, typos/formatting/mechanical renames, and small single-file fixes. Outside wired repositories, use it only when the user invokes $bailiwick-lead.
---

# Bailiwick Lead

This is a thin entry point to the shared, tool-neutral Lead skill.

1. Resolve `$BAILIWICK` from the environment or active private operator guidance. If absent,
   resolve this wrapper's physical path (following symlinks); the framework root is the
   parent of `codex-skills/`. Confirm `agents/lead.md` exists; ask for
   the framework path if it cannot be resolved.
2. Read `$BAILIWICK/skills/lead/SKILL.md` completely and follow its execution contract.
   It owns the lead-or-inline decision ("When to lead"), stage selection, dispatch briefs,
   dependency order, review, and completion evidence.
3. Keep the current main session as coordinator. Use the available native `bailiwick-*`
   custom agents for the applicable stages. If the runtime prohibits or lacks delegation,
   apply the canonical skill's disclosed fallback and report the limitation honestly.
   Follow its "Size the stages" section. Pass reasoning effort as an explicit spawn value for
   `bailiwick-implement`, whose adapter leaves it unset. The other stages' adapters fix
   `model_reasoning_effort` in the file, so record those values as applied.
4. Preserve the shared skill's human gates and its session-output procedure (manual output
   only when Codex capture hooks are not active and trusted). Loading this
   wrapper does not authorize commits, pushes, PRs, deployment, or knowledge promotion.
