<!-- Not sure about the change yet? Discussions → Ideas is the cheaper place to find out:
     https://github.com/Cursorinvisivel/bailiwick/discussions/categories/ideas -->

## What & why

<!-- What changes, and the problem it solves. Link the issue or discussion if there is one. -->

## How to verify

<!-- The commands you ran. For bootstrap/installer changes, the scratch-repo round-trip with
     HOME and BAILIWICK_HOME redirected (CONTRIBUTING.md → Testing your change). -->

## Checklist

- [ ] CI checks pass locally — `pytest tests/ -q`, `py_compile` on hooks, `bash -n` on shell scripts
- [ ] **No private or client data** — placeholders only (`acme`, `example.com`, `<project-id>`)
- [ ] Conventional commit messages; `knowledge:` and `telemetry:` changes in **separate commits** from code
- [ ] No AI attribution signatures in commits or this description (`Co-Authored-By`, "Generated with …", 🤖) unless you genuinely want them

If it applies to your change:

- [ ] Guardrail change (`hooks/guardrails.py`) has a matching case in `tests/test_guardrails.py`
- [ ] Knowledge addition is generic + cited, has its `INDEX.md` row and a `## Related` section
- [ ] Invariant-touching change (human gate, drafts-only, guardrail narrowing) has an ADR under `docs/decisions/`
- [ ] `bootstrap.sh` and `bootstrap.ps1` kept at parity (and the `.ps1` is still UTF-8 **with BOM**)
