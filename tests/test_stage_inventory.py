#!/usr/bin/env python3
"""Drift tests for the stage inventory: every doc that lists or counts the Quality Workflow
stages must agree with the agents/*.md frontmatter (the source of truth)."""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS = REPO_ROOT / "agents"
# Restricted variants of a stage (fetch-only / no-network, no-shell). They have no variant marker in
# frontmatter, so they are identified by name suffix; add a new suffix here when adding a variant kind.
VARIANT_SUFFIXES = ("-freshness", "-local")


def text(rel):
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def stages():
    """{file basename: stage name} for agents/*.md with a name:, excluding restricted variants (VARIANT_SUFFIXES)."""
    found = {}
    for path in sorted(AGENTS.glob("*.md")):
        m = re.match(r"---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.DOTALL)
        n = re.search(r"^name:[ \t]*(\S+)", m.group(1), re.MULTILINE) if m else None
        if n and not n.group(1).endswith(VARIANT_SUFFIXES):
            found[path.name] = n.group(1)
    return found


def test_stage_tables_list_every_stage():
    for doc in ("CLAUDE.md", "AGENTS.md"):
        # Only rows whose second cell names the file: other tables mentioning it do not count.
        cells = [[c.strip() for c in l.strip().strip("|").split("|")]
                 for l in text(doc).splitlines() if l.startswith("|")]
        files = {Path(r[1]).name for r in cells if len(r) > 1}
        for fname in stages():
            assert fname in files, f"{doc} stage table has no row for {fname}"


def test_getting_started_lists_every_stage():
    body = text("docs/getting-started.md")
    for name in stages().values():
        assert name in body, f"docs/getting-started.md does not list {name}"


def test_stage_counts_in_readme_and_copilot():
    n = len(stages())
    for doc in ("README.md", ".github/copilot-instructions.md"):
        counts = re.findall(r"(\d+) Quality Workflow stages", text(doc))
        assert counts, f"{doc} has no 'N Quality Workflow stages'"
        assert all(int(c) == n for c in counts), f"{doc} says {counts}, agents/ has {n}"


def test_framework_md_counts():
    n, total = len(stages()), len(list(AGENTS.glob("*.md")))
    body = text("docs/FRAMEWORK.md")
    stage_counts = re.findall(r"Stages \((\d+)\)", body)
    assert stage_counts and all(int(c) == n for c in stage_counts), f"Stages ({stage_counts}) != {n}"
    file_counts = re.findall(r"\((\d+) files\)|(\d+) files in three tiers", body)
    file_counts = [a or b for a, b in file_counts]
    assert file_counts and all(int(c) == total for c in file_counts), f"files {file_counts} != {total}"
