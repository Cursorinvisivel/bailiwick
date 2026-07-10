---
id:            adr-006-guardrail-confirmation-tiers
type:          decision
status:        accepted
date:          2026-07-05
authors:       [Francisco Ferrinho]
tags:          [adr, guardrail, enforcement, hooks, confirmation, attribution, capture]
supersedes:    []
superseded_by:
scope:         generic
---

# ADR-006 — Guardrail redesign: confirmation tiers replace hard deny

## Context

The original guardrail model had two decisions: **deny** (terraform/terragrunt apply+destroy,
cloud-resource delete/destroy/terminate — "never, even with approval") and **ask** (git
commit/push). Review findings (2026-07) showed real gaps inside the guardrail's own stated scope:
line-continuation splits evaded every pattern; ordinary destructive commands (`aws s3 rm`,
`gcloud storage rm`, `kubectl drain/scale/patch`, `helm uninstall`) passed silently; PR opening and
AI attribution signatures were uncontrolled; and the hard deny left no in-band path for a
genuinely-intended action other than the break-glass env var.

The intended operating model is finer-grained than deny/ask:
1. **High-impact actions** (infra/cluster/storage mutations, `git merge`, recursive `rm`) must be
   blocked from agent initiative — and **even when the user instructed them**, the agent must
   re-confirm that this specific execution is really the intent.
2. **Lesser-impact actions** (git commit/push, PR opening) may run only on a **clear user
   go-ahead**, never by agent initiative.
3. **AI attribution signatures** in commit/PR messages (Co-Authored-By: Claude, "Generated with …
   Claude", 🤖) must never land unnoticed — the framework's premise is that the framework stays
   invisible in client-facing artifacts.
4. **Dirty-zone capture plumbing is exempt** — capture exists to guarantee no data loss; blocking
   its commits/pushes would defeat the framework's own backstop.
5. **Validation-only commands** (terraform plan/validate/fmt, kubectl get/--dry-run, read-only
   cloud CLI) run freely.

## Decision

Replace deny/ask with **three ordered tiers, all resolving to forced confirmations** (a PreToolUse
hook cannot distinguish user-instructed from agent-initiated, so "re-confirm even when instructed"
and "block agent initiative" both map to `permissionDecision: ask` — the dialog is the re-confirmation):

1. **EXEMPT** — commands referencing `capture_backup.sh` or the capture-mirror pass untouched.
2. **ASK-IMPACT** — terraform/terragrunt `apply|destroy` (subcommand-anchored, so `plan -destroy`
   stays free); kubectl `apply|delete|patch|replace|scale|drain|cordon` + mutating `rollout` verbs;
   helm `install|upgrade|uninstall|delete|rollback`; gcloud/gsutil/az `delete|destroy|update|patch|rm`;
   aws `delete-|terminate-|remove-|update-` + `s3 rm|rb|mv`; `rm` with recursive/force flags;
   `git merge`; `gh repo delete|archive`. Reason text says explicitly: *blocked from agent
   initiative; re-confirm this is really the intent.* `--dry-run` forms of kubectl/helm are exempt
   (validation-only).
3. **ASK-SIGNATURE / ASK-GO-AHEAD** — `git commit|push` and `gh pr create|merge|close|ready`
   require a go-ahead confirmation; if the message carries an AI attribution signature, a distinct
   confirmation names it so it can be stripped.

Robustness fixes shipped with the redesign: backslash-newline continuations are folded before
matching; patterns stop at command separators (`;`, `&`, `|`) so a verb in a chained *next* command
is not attributed to the previous tool.

**Unchanged:** ADR-005 failure tiering (fail closed via the danger pre-filter on engine error, else
open; break-glass downgrades only that error-path deny), self-gating to wired/shadow repos, the
audit log, and the honest scope statement (direct-command rail, not a security boundary — `make
apply`, wrappers, aliases, MCP actions remain out of scope).

## Consequences

- There is no longer a hard "never, even with approval" class: a user who confirms the dialog can
  run `terraform apply`. This is deliberate — the reconfirmation *is* the control; the out-of-band
  break-glass env var is no longer the only path for intended destructive work.
- The ask surface widens (update/patch/rm/merge/PR verbs), so occasional false-positive
  confirmations are accepted as annoyance-cost (e.g. `git log --grep=merge`); deny false-positives
  no longer exist in normal operation.
- Gemini/Codex adapters (BACKLOG §2) should reproduce the same tier semantics when wired.
