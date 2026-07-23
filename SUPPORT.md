# Getting help

Bailiwick is maintained in the open, best-effort — there's no SLA and no support contract. Use the
channel that matches what you have, and you'll get a useful answer faster.

## Where to go

| You have… | Go here |
|---|---|
| A question — install, bootstrap modes, adapters, curation, "how do I …" | **[Discussions → Q&A](https://github.com/Cursorinvisivel/bailiwick/discussions/categories/q-a)** |
| An idea, feature proposal, or feedback on [ROADMAP.md](ROADMAP.md) | **[Discussions → Ideas](https://github.com/Cursorinvisivel/bailiwick/discussions/categories/ideas)** |
| A setup, knowledge library, or adaptation worth showing | **[Discussions → Show and tell](https://github.com/Cursorinvisivel/bailiwick/discussions/categories/show-and-tell)** |
| A reproducible bug — a hook that errors, a guardrail that misses or over-fires, a bootstrap that writes the wrong thing | **[Open an issue](https://github.com/Cursorinvisivel/bailiwick/issues/new)** |
| A security vulnerability, or private data spotted in the repo | **[Private advisory](https://github.com/Cursorinvisivel/bailiwick/security/advisories/new)** — never a public issue. See [SECURITY.md](SECURITY.md) |
| Code, docs, or knowledge to contribute | **[CONTRIBUTING.md](CONTRIBUTING.md)** |

Rule of thumb: **if you're not sure it's a bug, it's a discussion.** Q&A threads get converted to
issues when they turn out to be real defects — nothing is lost by starting there.

## Read these first

Most questions are answered in the docs, and they're written to be read cold:

- **[docs/getting-started.md](docs/getting-started.md)** — install, wire a repo, verify, first `/curate`.
- **[docs/operations.md](docs/operations.md)** — day-2: updating/un-wiring repos, multi-machine sync,
  encrypted backup, federation.
- **[docs/FRAMEWORK.md](docs/FRAMEWORK.md)** — the complete design; **§10** is the honest per-adapter
  difference table and **§14** the strengths & limitations.
- **[docs/compatibility.md](docs/compatibility.md)** — which tool versions each adapter is verified against.
- **[docs/staying-private.md](docs/staying-private.md)** — running a private instance on top of the
  public core.

## Posting a good question

Include the parts that make it answerable without a round-trip:

1. **Which tool** — Claude Code, Codex CLI, Gemini CLI, or Copilot (they differ; see FRAMEWORK.md §10)
   — and its version, plus your OS (macOS / Linux / WSL / Windows PowerShell).
2. **Which mode** — shadow (default) or seeded, and the exact `bootstrap.sh` / `bootstrap.ps1`
   invocation you ran.
3. **The exact command and output** — expected vs. actual. `--dry-run` output is ideal for
   bootstrap questions; a failing `tests/test_guardrails.py` case is ideal for guardrail ones.

## One hard rule

**No private or client data — ever**, in discussions, issues, or pasted logs: no real project IDs,
org names, client codenames, internal domains, or secrets. Redact to placeholders (`acme`, `globex`,
`example.com`, `<project-id>`) before you post. Captures and transcripts routinely contain the real
thing — scrub them. If you spot private data already posted somewhere in this repo, report it
[privately](https://github.com/Cursorinvisivel/bailiwick/security/advisories/new) rather than
quoting it in public.
