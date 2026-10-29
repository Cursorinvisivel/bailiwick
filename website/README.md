# Docs site

Theme and build tooling for the GitHub Pages site at <https://cursorinvisivel.github.io/bailiwick/>.
The site renders [`docs/`](../docs/README.md) and nothing else. `docs/` stays the single source of
truth, written to be read on GitHub first. Nothing in this folder is documentation content.

| Path | What it is |
|---|---|
| [`../mkdocs.yml`](../mkdocs.yml) | Site config: nav, theme, Markdown extensions, strict validation |
| [`requirements.txt`](requirements.txt) | Pinned MkDocs + Material. MkDocs stays on 1.6.x: 2.0 drops the plugin and theme-override systems this site relies on |
| [`hooks.py`](hooks.py) | Rewrites links that leave `docs/` (`../README.md`, `../hooks/…`) to their GitHub URL, opens the home page with the landing hero, and keeps ADR `status:` front matter from rendering as a Material page-status icon |
| [`overrides/`](overrides/) | Material theme overrides: landing hero (`home.html`), font loading (`main.html`), wordmark (`partials/logo.html`), brand stylesheet |
| `overrides/assets/brand/` | CursorInvisível logo files, vendored from the brand repository. Do not edit or redraw them; replace them with the brand repo's files |
| `overrides/.icons/lucide/` | The few Lucide icons the theme uses, at 1.5px stroke (ISC, see its `LICENSE`) |

## Build locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r website/requirements.txt
.venv/bin/mkdocs serve          # http://127.0.0.1:8000, live reload
.venv/bin/mkdocs build --strict # what CI runs; any warning fails
```

`site/` is the build output and is gitignored.

## Deploy

[`.github/workflows/pages.yml`](../.github/workflows/pages.yml) runs a strict build on every PR that
touches `docs/`, `mkdocs.yml` or `website/`, and deploys to Pages on push to `main`. The repo's
Pages source is set to **GitHub Actions**.

## Adding a page

Add the Markdown file under `docs/` and list it in the `nav:` of `mkdocs.yml`. A new ADR goes
under **Decisions**. The strict build fails if a file under `docs/` is left out of the nav.
