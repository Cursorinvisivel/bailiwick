---
id:            adr-005-guardrail-fail-closed
type:          decision
status:        accepted
date:          2026-07-02
authors:       [Francisco Ferrinho]
tags:          [adr, guardrail, security, enforcement, fail-closed, break-glass, hooks]
supersedes:    []
superseded_by:
scope:         generic
---

# ADR-005 — Guardrail failure mode: fail-closed on ambiguity for destructive commands

---

## Context

`guardrails.py` (the Claude Code PreToolUse control) **failed open** on any internal error: a parser
bug, missing dependency, exception, or malformed payload returned "no decision," which permitted the
command. That included the exact operations the framework claims to block — `terraform destroy`,
`terragrunt apply`, `gcloud … delete`, `kubectl delete`, `aws … terminate`. External review named this
precisely: *"a useful safety rail, not reliable enforcement under failure."*

Fail-open is deliberate — a guardrail bug must never wedge the harness. But "fail-open **always**" is
too blunt: it means the *most dangerous* commands are permitted in exactly the failure case where the
guardrail can least reason about them.

Interim mitigations shipped first (no behaviour-model change):
- **Honest scope docs** — documented as a direct-command rail for supported patterns, *not a complete
  security boundary* (misses `make apply`, wrappers, aliases, Terraform-MCP actions).
- **Break-glass + audit** — `BAILIWICK_BREAK_GLASS=1` downgrades deny→ask; every deny/ask/override
  is logged to `~/.bailiwick/guardrail-audit.log`.

This ADR decides — and its acceptance implements — the remaining structural question: **the failure
mode itself.**

## Decision

Adopt a **tiered failure mode** keyed on a cheap, broad "potentially destructive" pre-filter that runs
independently of the main pattern engine:

| Situation | Behaviour |
|---|---|
| Main engine parses successfully, finds a dangerous op | **Deny** (unchanged) |
| Main engine throws / can't evaluate **AND** the raw command trips the danger pre-filter | **Deny** (fail **closed**) |
| Main engine throws on a command with **no** destructive tokens | **Allow** (fail open, safely) |
| Genuine emergency | **Break-glass** env var → deny becomes ask, audited |

The **danger pre-filter** is a single compiled regex over the raw command string — the destructive
verbs and tools already enumerated (`terraform|terragrunt|gcloud|az|kubectl|aws` × `apply|destroy|
delete|terminate|remove`) — cheap enough to run with near-zero failure surface. So "the guardrail
crashed on something that *looks* destructive" resolves to **deny**, while a crash on an
obviously-harmless command still fails open and never wedges the harness. An outer guard makes any
unexpected top-level error exit 0 (fail open) rather than crash.

**Explicitly out of scope:** indirection hardening (`make`, wrapper scripts, aliases, Terraform-MCP
tool actions) — those bypass a direct-command guardrail by design; the honest-scope docs state this,
and reproducing enforcement inside other tools (Gemini `BeforeTool` / Codex `PreToolUse` deny hooks)
is a separate adapter effort.

## Options Considered

### Option A — Tiered fail-closed on danger pre-filter (CHOSEN)
**Pros:** Closes the "most dangerous commands permitted on failure" gap without wedging the harness on
unrelated crashes. Cheap, self-contained; break-glass provides the escape.
**Cons:** A harmless command that *contains* a destructive token could be denied on a crash — a false
positive. Bounded (only on fault) and escapable (break-glass); the pre-filter already ignores
non-command mentions like `echo terraform …` / `cat …-destroy.md` because it requires a tool+verb pair.

### Option B — Fail closed always (deny on any error)
**Cons:** A guardrail bug now blocks *all* Bash — wedges the harness, the exact outcome fail-open
exists to prevent. Rejected.

### Option C — Status quo (fail open always)
**Cons:** The named gap: destructive commands permitted precisely when the guardrail fails. Rejected.

## Rationale

The failure mode should be proportional to the stakes of the command, not uniform. Option A ties the
fail direction to a near-zero-failure pre-filter, so the harness only ever locks up around commands
that already look destructive — and even then break-glass releases it deliberately, with an audit
trail. B trades a real bug (permit-on-failure) for a worse one (wedge-on-failure); C leaves the gap.

## Consequences

### Positive
- The class of "guardrail crashed → destructive command ran" is closed for pre-filter-matching commands.
- Fail direction is now explicit and auditable, not an accident of where the exception landed.

### Negative / Accepted trade-offs
- Possible false denials on safe commands containing a tool+verb pair during a guardrail fault —
  bounded (only on fault), escapable (break-glass), logged for review.
- The pre-filter is a second pattern surface to keep in lockstep with `DENY_PATTERNS`.

### Risks and mitigation
| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Pre-filter itself throws | Low | Medium | Single compiled regex; its evaluation is wrapped, defaulting to no-deny |
| False denial during a fault | Low-Med | Low | Break-glass (deny→ask) + audit log; the fault itself is a signal to investigate |
| "Fail-closed" read as "complete boundary" | Medium | Medium | Docs keep the "not a complete security boundary" statement prominent |

## Implementation (landed on acceptance)
- `hooks/guardrails.py` — `DANGER_PREFILTER`; the match loop is wrapped so an exception
  routes through the pre-filter (deny if matched, else allow); `_decide_deny` respects break-glass;
  outer `__main__` guard exits 0 on any unexpected error. Verified: destructive+engine-failure → deny,
  harmless+engine-failure → allow, regression deny/ask/allow intact.
- `docs/FRAMEWORK.md` §3/§5 — guardrail description updated from "fails open" to the tiered model.

## References
- `hooks/guardrails.py`
- `docs/FRAMEWORK.md` §3 (policy/guardrail/enforcement terminology), §5 (hooks)
- External review (2026-07): guardrail fail-open, scope, and break-glass recommendations
