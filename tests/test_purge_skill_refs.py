"""The /purge skill splits gates (SKILL.md) from mechanics (reference/*.md, docs/history-purge.md).
An agent follows the pointers mid-run, so a renamed file or renumbered section would silently drop a
rule. Pin it: every run-card Ref and every `<file>.md` §N mention resolves to a file with that heading.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "purge", "SKILL.md")
REF = os.path.join(ROOT, "skills", "purge", "reference")
DOCS = os.path.join(ROOT, "docs", "history-purge.md")
CODEX = os.path.join(ROOT, "codex-skills", "bailiwick-purge", "SKILL.md")
SEC = r"§(\w+)(?:–(\w+))?"


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def resolve(name):
    """`host-state` / `host-state.md` / `reference/attest.md` / `docs/history-purge.md` -> path."""
    base = os.path.basename(name)
    if not base.endswith(".md"):
        base += ".md"
    for cand in (os.path.join(REF, base), os.path.join(ROOT, name), os.path.join(ROOT, "docs", base)):
        if os.path.isfile(cand):
            return cand
    raise AssertionError("referenced file not found: {}".format(name))


def sections(lo, hi):
    if hi is None:
        return [lo]
    if lo.isdigit() and hi.isdigit():
        return [str(n) for n in range(int(lo), int(hi) + 1)]
    return [lo, hi]


def assert_heading(path, sec):
    assert re.search(r"(?m)^#{2,3} " + re.escape(sec) + r"\.\s", read(path)), \
        "{} has no `## {}.` heading".format(os.path.relpath(path, ROOT), sec)


def run_card_refs():
    text = read(SKILL)
    card = text.split("## Run card", 1)[1].split("\n## ", 1)[0]
    rows = [ln for ln in card.splitlines() if ln.startswith("| ") and not ln.startswith("| Step")]
    assert len(rows) >= 14, "run card lost rows"
    out = []
    for row in rows:
        ref = row.rstrip().rstrip("|").rsplit("|", 1)[1].strip()
        for item in filter(None, (s.strip() for s in ref.split(","))):
            m = re.match(r"([\w-]+)(?:\s+" + SEC + ")?$", item)
            assert m, "unparseable Ref entry {!r}".format(item)
            out.append((m.group(1), m.group(2), m.group(3)))
    return out


def test_run_card_refs_resolve():
    refs = run_card_refs()
    assert refs
    for name, lo, hi in refs:
        path = resolve(name)
        for sec in sections(lo, hi) if lo else []:
            assert_heading(path, sec)


@pytest.mark.parametrize("src", [SKILL, CODEX] + sorted(
    os.path.join(REF, f) for f in os.listdir(REF) if f.endswith(".md")))
def test_file_section_mentions_resolve(src):
    found = 0
    for m in re.finditer(r"`([\w./-]+\.md)`\s+" + SEC, read(src)):
        path = resolve(m.group(1))
        for sec in sections(m.group(2), m.group(3)):
            assert_heading(path, sec)
            found += 1
    if src in (SKILL, CODEX):
        assert found, "expected §-references in {}".format(src)


def test_step6_sections_exist_in_history_purge_doc():
    text = read(SKILL)
    step6 = text.split("6. **(`--history`)", 1)[1].split("\n7. **", 1)[0]
    secs = {s for m in re.finditer(SEC, step6) for s in sections(m.group(1), m.group(2))}
    assert {"0", "1", "2", "3"} <= secs
    for sec in secs:
        assert_heading(DOCS, sec)


def test_run_card_lists_the_purge_steps_in_order():
    first_cells = [ln.split("|")[1].strip().split()[0] for ln in
                   read(SKILL).split("## Run card", 1)[1].split("\n## ", 1)[0].splitlines()
                   if ln.startswith("| ") and not ln.startswith("| Step")]
    assert first_cells == ["1.1", "1.2", "1.3–1.4", "2", "3", "3a", "3b", "4", "5.1–5.6", "5a", "5b",
                           "5.7", "6/7", "5b"]
