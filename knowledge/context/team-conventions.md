---
id: team-conventions
type: context
tags: [conventions, team, patterns, commits, git]
confidence: low
last_validated: 2026-06-25
supersedes: []
scope: generic
---

# Team Conventions

## Language
- Code and commits: English
- Technical documentation: [your team's language(s)]
- Code comments: English

## Git

### Commits
Format: `type(scope): short description`

Types:
- feat: new feature
- fix: bug fix
- docs: documentation
- refactor: refactoring without behaviour change
- chore: maintenance
- knowledge: knowledge library update (always a separate commit)

### Branches
- `main`: production
- `develop`: integration
- `feat/`: new features
- `fix/`: bug fixes

## Code Review
- Minimum one reviewer before merging to main
- Quality Agent invoked before submitting PR
- No merge with open critical-severity issues

## Terraform
- terraform fmt before any commit
- terraform validate and tflint in pre-commit
- plan mandatory before apply
- apply in production requires explicit approval

## Documentation
- ADR for structural decisions before implementation
- README.md in all Terraform modules
- Runbook for any operational component

## Knowledge Library — Size Policy

### Limits
- **Soft cap**: 150 lines per file
- **Hard cap**: 200 lines — above this, split mandatory

### When to split
If a file exceeds the soft cap:
1. Separate into `name-core.md` (essential rules, minimal examples) and `name-extended.md` (edge cases, full reference)
2. Update the relevant index node (root `INDEX.md`, or the domain sub-index if that domain is sharded) with both entries — core with frequent trigger, extended with specific trigger
3. `name-extended.md` should reference: `See also: name-core.md`

> **File size vs index sharding — distinct axes.** This policy splits an individual *content file* by
> length (core/extended). It is independent of *index-tree sharding* (see `agents/memory.md` → Index
> Health & Sharding), which splits an *index node* when it lists too many topics. A file split adds
> entries to a node; if that pushes the node over its topic threshold, sharding then moves a cluster
> down a level. Apply both as needed.

### Writing principles
- Tables and lists over prose
- One concrete example replaces three sentences of explanation
- Do not duplicate guidance already present in another file — reference it
- Review files older than 90 days without updates: compress or remove

## Related
- [Engineering defaults](engineering-defaults.md)
