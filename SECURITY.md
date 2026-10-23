# Security Policy

## Reporting a vulnerability

Please report security issues **privately** rather than opening a public issue. Use GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository, or contact the maintainer directly.

Please include: what you found, how to reproduce it, and the impact you expect.

## Sensitive data in the repository

This repository should contain only generic, placeholder examples (`acme`, `example.com`) — never real
client/org names, project IDs, internal hostnames, or credentials, in code, contributions, or issues.
If you ever spot something that looks like real private data, **report it privately** through the same
channel above rather than opening a public issue or PR that quotes it — publicizing the exact string
only widens the exposure. We'll remove it (and, where warranted, rewrite the git history) promptly.

## Scope — what this project is (and is not)

Bailiwick is a **prompt-and-convention framework** for AI coding agents. It is plain Markdown,
Python, and shell — there is no server, no network service, and no data store. The security-relevant
surface is small and specific:

- **The runtime guardrail** (`hooks/guardrails.py`) — a pre-execution hook that forces
  confirmation on high-impact commands (terraform apply/destroy, cluster/cloud mutations, recursive
  `rm`, git merge, commit/push, PR opening). **It is a direct-command productivity guardrail, not a
  complete security boundary.** By design it does not catch actions reached through `make`, wrapper
  scripts, shell aliases/functions, or MCP tool calls. It fails *open* on internal error except when
  a destructive pre-filter trips (then it fails *closed*). Do not rely on it as a sandbox. See
  `docs/threat-model.md`.
- **The freshness fetch guard** (`hooks/fetch_guard.py`) — denies WebFetch calls from the
  `/curate` freshness research agent that fall outside the GCP source registry, in two layers: the
  agent's own frontmatter hook (blocks all of that agent's fetches if its launcher is missing) and
  a global hook keyed on the payload's `agent_type`. It fails closed on errors inside the script,
  but open if the script cannot run (no interpreter, crash, timeout). `doctor.sh` exercises both
  installed layers; `scripts/smoke_fetch_guard.sh` checks them live. It checks the requested URL only (not
  same-host redirects the fetch tool follows) and covers that one agent under Claude Code — not
  the general Cloud Research agent used as a fallback, and not other runtimes.
- **Capture & backup** (`capture_backup.sh`) — optional off-machine backup of session transcripts.
  Only ciphertext leaves the machine (gpg); the private key never does. Transcripts may contain
  sensitive data — treat the local `.bailiwick-outputs/` zone accordingly.
- **Secrets** — the framework reads GitHub tokens lazily from the `gh` CLI keychain at process spawn
  and never persists them. Do not add code that writes tokens to dotfiles or the environment.

## Good-faith use

This framework assists with authorized infrastructure and development work. The guardrail and the
human-gated, drafts-only model exist to keep an agent from taking irreversible action on its own —
keep those invariants intact in any contribution.

## Full threat model

See [`docs/threat-model.md`](docs/threat-model.md) for the enumerated assets, trust boundaries,
threats, and the residual risks the design explicitly accepts.
