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

## Amendment 1 (2026-07-28) — per-segment tier evaluation

A security review of the engine found three evasions, all the same root cause: tier decisions were
matched against the **whole command string** rather than the tokens actually executed in one
segment — the discipline this ADR already promised ("patterns stop at command separators"). Each
produced *no decision at all*, so the forced reconfirmation never fired.

1. **Quoted command token.** `strip_quoted()` blanked every quoted span on the premise that
   destructive verbs are "always command tokens, never inside quotes". Quoting a whole token is
   ordinary shell that executes identically, so `terraform "apply"`, `rm '-rf' /x`,
   `kubectl 'delete' ns prod`, and `git 'push'` all reduced to a non-matching string.
2. **Unanchored EXEMPT substring.** `capture_backup\.sh` / `capture-mirror` were searched as free
   text anywhere in the command, ahead of every other tier, so a 14-character trailing comment
   (`terraform apply # capture-mirror`) or a `capture-mirror.tfvars` argument disarmed the engine
   entirely.
3. **Leaking dry-run exemption.** `dry_run = "--dry-run" in command` was computed once over the
   whole line, so `kubectl delete ns prod --dry-run=client; kubectl delete ns prod` — an idiomatic
   validate-then-apply one-liner — suppressed the live mutation, as did a `# --dry-run` comment.

**Decision:** evaluate tiers per executed segment. The command is normalised, whole-token quoting is
unwrapped (`unwrap_token_quotes()`) *before* genuine quoted arguments are blanked, `#` comments are
dropped, and the result is split on `;` `&&` `||` `|` and newline (`segments()`). EXEMPT clears only
its own segment and is anchored to command position (the backup script as a command word; the mirror
only as a `git -C` target), and the dry-run exemption applies only within the segment that matched.
Separately, the ADR-005 fail-closed pre-filter now reads the **raw** command as that ADR specifies —
it had been fed the quote-stripped form, so evasion #1 blinded the fail-closed path too.

**Consequence:** the quoted-argument false positive this ADR accepted (`gcloud logging read
'methodName:"delete"'`, `echo "terraform apply"`) stays suppressed — those are distinguished by
content, holding whitespace or a nested quote. On the error path, a quoted destructive verb now
fails closed where it previously fell through; that is the direction ADR-005 intends and only
applies once the engine has already errored.

**Follow-on (same amendment):** anchoring alone left the mirror clause too broad — `git -C <any path
containing capture-mirror>` granted an unconfirmed push to an arbitrary remote, and because
`--git-dir`/`--work-tree` override `-C`, a decoy mirror path could be presented while git operated on
the client repo. The clause is now scoped to the canonical mirror (`…/bailiwick/capture-mirror`, per
`capture_backup.sh`) with `-C` immediately after `git`, and any segment carrying `--git-dir`,
`--work-tree`, `--exec-path`, or an explicit remote URL is disqualified from exemption entirely. Note
this is a capability grant, not a pattern: it is deliberately narrower than the plumbing needs, since
`capture_backup.sh` is invoked by the Stop/SessionEnd hook rather than through the agent's Bash tool,
so the guardrail never sees the mirror's own git calls. A bare relative `git -C capture-mirror push`
is no longer exempt.

**Residual, documented in the module's scope statement:** quoting only *part* of a token
(`terraform ap"ply"`) still evades. The transformation that would catch it is indistinguishable from
the quoted-argument false positive above, so it joins `make apply`, wrappers, aliases, and MCP
actions on the known-bypass list rather than being silently assumed covered.
