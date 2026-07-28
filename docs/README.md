# Bailiwick documentation

Start with the [project README](../README.md) for the overview, then pick a path below.

## By goal

| I want to… | Read |
|---|---|
| **Understand what this is** and whether it fits | [../README.md](../README.md) → [FRAMEWORK.md §1 (Essence)](FRAMEWORK.md) and [§14 (Strengths & limitations)](FRAMEWORK.md) |
| **Install it and wire my first repo** | [getting-started.md](getting-started.md) |
| **Run it day to day** — updates, multiple machines, backup, external knowledge | [operations.md](operations.md) |
| **Keep my work private** — and contribute upstream without leaking | [staying-private.md](staying-private.md) |
| **Understand the design in depth** | [FRAMEWORK.md](FRAMEWORK.md) — the complete reference |
| **Assess the security posture** | [threat-model.md](threat-model.md) |
| **Trust the telemetry** before relying on it | [telemetry-validation-protocol.md](telemetry-validation-protocol.md) |
| **Contribute** | [../CONTRIBUTING.md](../CONTRIBUTING.md) · [../SECURITY.md](../SECURITY.md) |

## The documents

- **[getting-started.md](getting-started.md)** — a hands-on tutorial: prerequisites, once-per-machine
  install, wiring a repo (shadow vs seeded), verifying it works, and your first knowledge cycle.
- **[operations.md](operations.md)** — day-2 reference: updating wired repos, multi-machine sync
  (central/satellite), the optional encrypted capture backup, federated external knowledge, and a
  manual-wiring reference of what `bootstrap.sh` does by hand.
- **[staying-private.md](staying-private.md)** — how to keep your knowledge and work private: the
  public-upstream / private-downstream topology (two clones, single-purpose remotes), what never
  crosses upstream, and how contributors send generic improvements back without leaking.
- **[FRAMEWORK.md](FRAMEWORK.md)** — the single authoritative spec. Architecture and layers, the
  orchestration model, the knowledge library and index tree, the capture→curate→promote
  lifecycle, the runtime guardrail, shadow/seeded modes, multi-tool adapters, scope & non-goals,
  and a strengths-&-limitations self-assessment. Other files and code cross-reference its sections
  (e.g. "§7.1", "§10").
- **[ROADMAP.md](../ROADMAP.md)** — non-goals and possibilities kept out of the reference: what a
  shared multi-contributor "team brain" would require (Bailiwick is single-user by design today),
  plus smaller items on the radar. Nothing here is a commitment.
- **[threat-model.md](threat-model.md)** — assets, trust boundaries, an enumerated threat table with
  mitigations, and the residual risks the design explicitly accepts.
- **[compatibility.md](compatibility.md)** — per-adapter status and the tool versions Bailiwick is
  verified against (the guardrail/hook surfaces are fast-moving; revalidate on CLI upgrades).
- **[telemetry-validation-protocol.md](telemetry-validation-protocol.md)** — a lightweight protocol
  for checking that the usage-telemetry signal is trustworthy before letting it drive any decisions.
- **[traffic-metrics.md](traffic-metrics.md)** — how the repo's views/cloners badges accumulate
  beyond GitHub's 14-day window, and where the maintainer-facing top-referrers/top-content report
  lives (the `traffic-data` branch — deliberately not a badge).

## Conventions in these docs

- `$BAILIWICK` — the path where you cloned this repo (the Bailiwick root).
- `/path/to/repo` — a target repository you are wiring to the framework.
- Placeholder org/host names are `acme`, `globex`, `example.com` — never real identities.
