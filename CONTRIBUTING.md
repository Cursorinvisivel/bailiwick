# Contributing to Bailiwick

Thanks for your interest. Bailiwick is domain-neutral machinery for AI coding agents, grown out of
real cloud / infrastructure engineering and opened up so others can adopt, adapt, and improve it.
Contributions are welcome — with a few ground rules that reflect how the framework is built.

> **Keeping a private superset?** Most contributors run their own private instance (private knowledge,
> client work) on top of the public core and send only generic improvements upstream. The
> public-upstream / private-downstream setup that keeps the two cleanly separated — so private content
> can never ride along on a PR — is in **[docs/staying-private.md](docs/staying-private.md)**. Read it
> before you push.

## Get the feel first (orientation)

Bailiwick has **no service and no build step** — it's plain Markdown + Python + shell that AI coding
tools read live. Five moving parts, and how a session flows through them:

1. **`knowledge/`** — a curated Markdown library indexed by `INDEX.md` (a lean "map of maps" injected
   into every session). Files carry frontmatter (`id`, `type`, `tags`, `confidence`, `scope`, …) and
   a telemetry sidecar tracks usage.
2. **`agents/`** — Markdown *role definitions* (lead + domain-context + execution) the tool adopts on
   demand. Not code, not installed anywhere — the agent reads the role and acts as it.
3. **`hooks/`** — the only things that *run*: the runtime guardrail (`guardrails.py`), capture, sync,
   and health hooks, plus the installers that wire them in.
4. **`skills/`** — human-gated procedures (`SKILL.md` files): `/curate`, `/enrich`, `/learn`,
   `/metrics`, `/investigate`, `/purge`. Markdown procedures, not programs.
5. **`scripts/bootstrap.sh`** (+ `bootstrap.ps1`) — onboards a repo (shadow or seeded) and installs
   the once-per-machine global wiring.

A session, end to end: `bootstrap` wires a repo → the SessionStart hook injects the index → the agent
loads the few knowledge files a task needs → the guardrail intercepts risky commands → capture hooks
stage the transcript → you run `/curate` to promote what's worth keeping.

For the full design (readable cold), see **[docs/FRAMEWORK.md](docs/FRAMEWORK.md)** — especially §2
(architecture), §3 (agents), and §14 (strengths & limitations). The **[docs/](docs/README.md)** set is
the depth layer; this file is the practical how-to-help.

## Ground rules

1. **No private or client data — ever.** Everything here must stay generic — no real project IDs,
   org names, client codenames, internal domains, or secrets. Use placeholder examples (`acme`,
   `globex`, `example.com`, `<project-id>`).
2. **Knowledge is human-gated.** Content under `knowledge/` is curated deliberately — propose
   additions via PR with a clear rationale. Generic, reusable, well-sourced knowledge only.
3. **Everything the agent produces is a draft for human review.** The framework never auto-applies
   infrastructure changes; keep that invariant.
4. **Respect the guardrails.** `hooks/guardrails.py` forces confirmation on high-impact actions.
   Don't weaken it without an ADR explaining why.
5. **`.telemetry.json` is the only ungated write, and it's single-writer.** Don't hand-edit it in a
   PR; the `/curate`/Memory flow owns it.

## Ways to contribute

Pick the recipe that matches your change — each notes where it lives and how to verify it.

> **Not sure yet? Start in [Discussions](https://github.com/Cursorinvisivel/bailiwick/discussions).**
> Questions and setup help go to **Q&A**; a change you'd like to propose before building it goes to
> **Ideas** — worth doing for anything invariant-touching, so the ADR conversation happens before the
> PR. [SUPPORT.md](SUPPORT.md) has the full routing.

- **A bug or behavior report.** Open an issue naming the tool (Claude Code / Codex / Gemini /
  Copilot), the exact command, expected vs. actual, and the relevant hook/adapter. A failing
  `tests/test_guardrails.py` case is the ideal repro for guardrail issues. If you're not yet sure
  it's a defect, ask in Q&A first — threads get converted to issues when they turn out to be one.
- **Knowledge (topics / patterns).** Add a Markdown file under `knowledge/topics/` or
  `knowledge/patterns/` following the frontmatter schema (see the `INDEX.md` header and
  `knowledge/templates/topic-file-template.md`), add its `INDEX.md` row, and author a `## Related`
  section (1–5 peer notes as relative links). **Generic and cited only** — official docs, dated
  sources; no client-derived specifics. Use the `knowledge:` commit prefix.
- **A guardrail pattern.** Edit the relevant list in `hooks/guardrails.py` —
  `EXEMPT_PATTERNS`, `ASK_IMPACT_PATTERNS`, or `ASK_GOAHEAD_PATTERNS` — and **add a matching case to
  `tests/test_guardrails.py`** (the decision contract is the spec). Widening what's guarded is
  usually fine; narrowing or exempting needs an ADR.
- **An agent role or domain-context file.** Edit the Markdown under `agents/`. Keep roles focused and
  proportional; domain-context files (`gcp.md`, `kubernetes.md`, …) encode retrieval hints +
  checklists, they don't execute.
- **A skill.** Skills are `SKILL.md` procedures under `skills/` (with Codex wrappers in
  `codex-skills/` that point back to the canonical file — keep them single-source). Preserve the
  human gate; destructive skills (`/purge`) present a plan and wait for approval.
- **Bootstrap / hooks / installers.** The wiring in `scripts/` and `hooks/`. Test against a
  **throwaway repo with `HOME` and `BAILIWICK_HOME` redirected** so nothing touches your real global
  config, and always try `--dry-run` first.
- **A design decision.** Significant or invariant-touching changes get an ADR under `docs/decisions/`
  (template: `knowledge/templates/adr-template.md`). Reference its number from the code/docs it governs.

## Testing your change

CI (`.github/workflows/ci.yml`) runs the same checks — run them locally before opening a PR:

```bash
python -m pytest tests/ -q                       # guardrail decision contract (install pytest first)
python3 -m py_compile hooks/*.py skills/metrics/report.py   # hooks/scripts parse
for f in scripts/*.sh hooks/*.sh; do bash -n "$f"; done     # shell scripts parse
```

For bootstrap/installer changes, exercise a full round-trip against a scratch repo with redirected
global state, e.g.:

```bash
tmp=$(mktemp -d); ( cd "$tmp" && git init -q )
HOME=$(mktemp -d) BAILIWICK_HOME=$(mktemp -d) \
  scripts/bootstrap.sh --seeded --dry-run "$tmp"     # preview; then drop --dry-run to apply
```

If you touch docs, sanity-check that relative links resolve.

## Commit & PR conventions

- **Conventional commits:** `type(scope): description` — `feat | fix | docs | refactor | chore |
  knowledge | telemetry`. Keep **`knowledge:`** (and `telemetry:`) changes in **separate commits**
  from code.
- **No AI attribution signatures** in commit/PR messages unless you genuinely want them
  (`Co-Authored-By`, "Generated with … Claude", 🤖) — the framework's own guardrail flags them.
- **PR checklist:** the CI checks pass; a guardrail change has a test; a knowledge addition is
  generic + cited + has its `INDEX.md` row; an invariant change has an ADR; no private/client data.

## Development notes

- Plain Markdown + Python + shell — no build step, no runtime service.
- **`bootstrap.ps1` must stay UTF-8 _with BOM_** (Windows PowerShell 5.1 misparses BOM-less non-ASCII
  — see `knowledge/topics/powershell-utf8-bom-parsing.md`), and its switches are single-dash
  (`-Seeded`, not `--seeded`). Keep bash/PowerShell behavior at parity.
- Path-scoped and marker-delimited edits are a recurring safety pattern (installers only ever touch
  *their own* marked blocks / this clone's paths) — preserve it when editing the installers.

## Code of conduct

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md) (Contributor Covenant 2.1).
Reporting runs through GitHub's own abuse tooling; content that leaks private or client data goes
through the private security channel instead — both are spelled out there.

## Security

Please report security issues privately — see [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE).
