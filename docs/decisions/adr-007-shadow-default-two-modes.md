---
id:            adr-007-shadow-default-two-modes
type:          decision
status:        accepted
date:          2026-07-05
authors:       [Francisco Ferrinho]
tags:          [adr, shadow-mode, bootstrap, activation, privacy, team-baseline, gitignore]
supersedes:    []
superseded_by:
scope:         generic
---

# ADR-007 — Two operating modes; shadow is the default activation

> Amends ADR-003: the shadow mechanism is unchanged; this decision flips the **default** and
> names the framework's two intentional repo-interaction modes.

## Context

ADR-003 introduced shadow mode as an **opt-in** alternative to seeded mode (hidden in-repo wiring
via `.git/info/exclude`), motivated by client clones that must stay untouched. Operating experience
sharpened the model: the framework is, first, a **private knowledge base and ways-of-working layer**
— its presence must be invisible in every repo colleagues or clients can see. Separately, some repos
are deliberately bootstrapped **for a team**: committed, shared,
framework-agnostic baselines (Cloud/Terraform/DevOps standards and smart-LLM-usage instructions
such as reuse-first over proposing new code). Treating visibility as a per-flag afterthought
blurred that boundary — e.g. templates and agent docs still instructed adding `.bailiwick-outputs/` to the
tracked `.gitignore`, which alone reveals the framework's existence to anyone who clones.

## Decision

1. **Exactly two repo-interaction modes, by intent:**
   - **Hidden personal (default):** the private framework layer. Invisible by construction.
   - **Team baseline (`--with-standards`):** intentionally tracked, shared, framework-agnostic
     instruction baselines (CLAUDE.md / AGENTS.md / copilot-instructions per tool flags) that set a
     project's ways of working. The only deliberately visible output; works in both wiring modes.
2. **Shadow is the default bootstrap mode** (both `bootstrap.sh` and `bootstrap.ps1`): a
   no-mode-flag run writes **zero files** into the repo — activation lives in
   `~/.bailiwick/allowlist` + each tool's user-scope config; captures stage centrally.
   `--shadow` remains an explicit alias. **`--seeded`** opts into the in-repo hidden wiring;
   `--visible` and `--init` imply seeded (they write repo files by design).
3. **No framework trace ever lands in a tracked `.gitignore`.** The gitignore entry itself exposes
   the framework. Seeded mode hides via `.git/info/exclude` only; shadow mode needs no entry at
   all. All templates/docs instructing `.gitignore` additions were corrected (2026-07-05).

## Consequences

- A plain bootstrap can no longer accidentally leave artifacts in a client repo — the safe mode is
  the default, not the remembered flag.
- Seeded mode remains available for repos where in-repo wiring is preferred (e.g. Bailiwick's own
  development, or machines where user-scope config is undesirable).
- `bootstrap.ps1` reached feature parity as part of this decision (shadow block, `-Seeded`,
  global-only `-InstallTools`, `-Update -WithStandards` patch, PS 5.1 compatibility) — Windows
  validation is tracked in BACKLOG §3.
- Docs updated: README (Per-Project Setup), CLAUDE.md (Usage in Other Repositories), FRAMEWORK.md
  (§1, §7, §7.1, glossary), lead.md (Bootstrapping a New Project).
