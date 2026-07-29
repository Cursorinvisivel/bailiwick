---
id:            adr-009-public-origin-contribute-only
type:          decision
status:        accepted
date:          2026-07-15
authors:       [Francisco Ferrinho]
tags:          [adr, privacy, sync, curation, public-oss, topology, guardrail]
supersedes:    []
superseded_by:
scope:         generic
---

# ADR-009 — Public-origin instances are contribute-only (ingestion blocked)

> **Implementation status (as of 2026-07-29): IMPLEMENTED.** Detection lives in
> `hooks/public_origin.sh` (canonical-slug match, host- and protocol-agnostic; optional `gh`
> visibility check for forks; `allow_public_push` override), and all four enforcement points call it:
> `sync_knowledge.sh` refuses to propagate and exits 1 (commits stay local), `/curate` aborts at
> Step 0 before extracting anything, `session_start.sh` injects the contribute-only notice, and
> `bootstrap.sh --install-tools` warns (never fatal). The private-first **topology** (Decision §1,
> [staying-private.md](../staying-private.md)) remains the documented default and is still
> convention — the mechanism now backs it rather than standing in for it.
>
> Two limits worth stating plainly, both unchanged from the Consequences below: `sync_knowledge.sh`
> is the framework's *own* automation, so a raw `git push` by hand is still uncontrolled; and the
> `gh` layer needs an authenticated `gh`, without which coverage falls back to the canonical slug.

## Context

Bailiwick is published as a public OSS repository, but every user's *instance* of it is private by
nature: the `knowledge/` library grown from their own work is **tracked in git** (that is how
multi-machine sync works), so whichever remote `origin` points at is where that knowledge will
land. The original "use" instructions had users clone the public repo and run `--install-tools`
from that clone directly — which makes the public clone the daily driver. From there, one
`/curate` plus one push (deliberate or accidental — `sync_knowledge.sh` pushes `origin` on the
central role by design) publishes private, possibly client-derived knowledge to the public
repository. A public push is a publish: it may be cached or indexed even if reverted.

Two gaps compounded this: the documentation offered no first-class path to a private downstream
(the topology lived only in `staying-private.md`, off the happy path), and nothing *mechanical*
distinguished a contribute-only public clone from a real instance — the distinction was pure
convention.

## Decision

1. **Topology: private-instance-first.** The documented default (README quick start,
   getting-started §1) is a single clone with two single-purpose remotes: `origin` → a **new
   private repo the user owns** (created empty, then `git push -u origin main`), `upstream` → the
   public OSS with its push URL set to `DISABLED` (pull-only). Contributors keep a *second*,
   contribute-only clone whose `origin` is the public OSS; generic changes are re-created there.
   GitHub forks are never a private downstream (a fork of a public repo is itself public).

2. **Mechanism (PLANNED — not yet implemented; see the status note above): a public-origin instance
   is contribute-only, ingestion-blocked.** The marker is
   the remote itself — `git remote get-url origin` — matched against the canonical OSS slug
   (`Cursorinvisivel/bailiwick`) under any host alias or protocol. Enforcement is layered:
   - `hooks/sync_knowledge.sh` **refuses to propagate** (exit 1, commits stay local) on a
     canonical-slug origin — and, when `gh` is available, on **any** origin that resolves as a
     public GitHub repo (`gh api repos/<slug>` visibility), which covers forks. Fail-open when
     `gh` is absent/unauthenticated: the canonical-slug check still holds.
   - `/curate` (and its Codex wrapper) **aborts at Step 0** before extracting anything; captures
     stay staged and curate normally once the instance is private. `/investigate` promotion is
     covered by the same rule.
   - `session_start.sh` injects a **contribute-only notice** so both user and agent know; the
     bootstrap installers warn at `--install-tools` time (warning, not fatal — validating or
     developing in the OSS clone stays legitimate).
   - Tier-1 (local-only, no private remote) users still rename `origin` → `upstream`; a clone
     that keeps the public repo as `origin` cannot curate. Renaming the remote is what marks a
     clone as *yours*.

3. **Override: deliberate, machine-local, maintainer-only.** `"allow_public_push": true` in the
   gitignored `.bailiwick-sync.json` lifts the block on that machine — it exists solely so the
   OSS maintainer can update the public **seed** library, and must never be set on an instance
   holding private or client-derived knowledge.

## Options considered

- **Documentation only (status quo plus better docs).** Rejected alone: the failure mode is
  exactly the careless/default path, and convention does not stop it. Kept as the first layer
  (private-first quick start), backed by mechanism.
- **A tracked marker file in the public repo** (e.g. `.bailiwick-public`). Rejected: the marker
  survives `git pull upstream` into every private downstream, inverting the signal; requiring
  users to delete it is the same convention problem again.
- **Blocking `git push` itself via the guardrail engine.** Rejected: `guardrails.py` already
  gates every push behind a user go-ahead; the leak vector is the framework's *own* sync
  automation plus curation, which is precisely where the new checks live. Raw git remains the
  user's tool (residual risk accepted, see threat model T9).
- **`gh`-based visibility check as the only mechanism.** Rejected as sole check: `gh` may be
  absent or unauthenticated. Used as the second layer over the always-on canonical-slug match.

## Rationale

The remote URL is the one signal that is always present, needs no network, survives every clone
shape, and directly encodes the thing that matters — *where a push would land*. Matching the
canonical slug host-agnostically handles SSH host aliases; the optional `gh` visibility check
generalizes the invariant from "not the canonical repo" to "no public remote at all". Blocking
ingestion (not just the push) keeps the dangerous state from ever existing: no knowledge commits
accumulate one push away from public. The override is machine-local and gitignored so it can
never propagate to another clone by sync.

## Consequences

- The public clone becomes a safe place to *contribute from* and an impossible place to *ingest
  into* — intentional or accidental contamination of the OSS repo through the framework's own
  machinery is closed off (threat model **T9**).
- The maintainer's own dev clone (origin = canonical) sees the contribute-only notice every
  session and must set `allow_public_push` to update the seed library — a deliberate speed bump
  on the highest-risk push path.
- Residual (accepted): raw `git push` outside the framework is uncontrolled (`gitleaks`/pre-push
  hooks recommended on contribute-only clones); public repos on non-GitHub hosts with a
  non-canonical slug are not detected; an unauthenticated `gh` reduces coverage to the canonical
  slug.
- `--install-tools` also persists `export BAILIWICK` in `~/.bashrc`/`~/.zshrc` (Windows: a User
  environment variable) as a managed, path-scoped line — never overwriting a differing export —
  so two-clone setups keep pointing at the installed private instance.

## References

- [staying-private.md](../staying-private.md) — the topology and the full protection stack
- [threat-model.md](../threat-model.md) — T9
- [operations.md](../operations.md) → Multi-machine sync — the guard in the sync flow
- `hooks/sync_knowledge.sh`, `hooks/session_start.sh`, `skills/curate/SKILL.md` (Step 0),
  `scripts/bootstrap.sh` / `bootstrap.ps1` — the enforcement points
- [ADR-003](adr-003-shadow-mode.md) / [ADR-007](adr-007-shadow-default-two-modes.md) — the
  repo-level privacy layers this complements (this ADR is the *repository-topology* layer)
