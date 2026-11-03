#!/usr/bin/env python3
"""Drift tests for stage sizing (ADR-010 Amendments 2 and 4).

The rating table in skills/lead/SKILL.md ("Size the stages") is the single definition of which
model tier and effort each stage runs at; the canonical frontmatter in agents/*.md holds the
Standard defaults. These tests read both and fail when a reviewer would run below the stage it
reviews, when the Edge rating loses its Advisor, or when the frontmatter drifts from the table.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "lead" / "SKILL.md"
AGENTS = REPO_ROOT / "agents"

TIERS = ["haiku", "sonnet", "opus", "fable"]
EFFORTS = ["low", "medium", "high"]
RATINGS = ["Trivial", "Standard", "Complex / high-risk", "Edge"]
IMPLEMENT, DOCS, REVIEW, ADVISOR = (
    "Implement", "Docs / Cloud Research", "Quality / Security Review", "Advisor")


def text(path):
    return path.read_text(encoding="utf-8")


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def rating_table():
    """Return {rating: {column: cell}} from the first table under '## Size the stages'."""
    section = re.search(r"^## Size the stages\n(.*?)(?=^## )", text(SKILL), re.MULTILINE | re.DOTALL)
    assert section, "skills/lead/SKILL.md lost its '## Size the stages' section"
    rows = []
    for line in section.group(1).splitlines():
        if line.startswith("|"):
            rows.append(line)
        elif rows:
            break
    assert len(rows) >= 3, "no rating table under '## Size the stages'"
    header = cells(rows[0])
    table = {}
    for line in rows[2:]:
        row = dict(zip(header, cells(line)))
        table[row["Task rating"].replace("*", "")] = row
    return table


def sizing(cell):
    """'opus, high' -> ('opus', 'high'); the tier and effort must both be named."""
    m = re.match(r"(\w+), (\w+)", cell)
    assert m, f"cell {cell!r} is not '<model>, <effort>'"
    tier, effort = m.groups()
    assert tier in TIERS, f"unknown model tier {tier!r} in {cell!r}"
    assert effort in EFFORTS, f"unknown effort {effort!r} in {cell!r}"
    return tier, effort


def frontmatter(name):
    body = text(AGENTS / name)
    m = re.match(r"---\n(.*?)\n---\n", body, re.DOTALL)
    assert m, f"agents/{name} has no frontmatter"
    return dict(re.findall(r"^(\w+):[ \t]*(.+)$", m.group(1), re.MULTILINE))


def test_all_ratings_present():
    table = rating_table()
    for rating in RATINGS:
        assert rating in table, f"rating table lost the {rating!r} row"
        for column in (IMPLEMENT, DOCS, REVIEW, ADVISOR):
            assert column in table[rating], f"{rating!r} row has no {column!r} column"


def test_reviewer_never_below_implementer():
    for rating, row in rating_table().items():
        impl_tier, impl_effort = sizing(row[IMPLEMENT])
        rev_tier, rev_effort = sizing(row[REVIEW])
        assert TIERS.index(rev_tier) >= TIERS.index(impl_tier), \
            f"{rating}: reviewer tier {rev_tier} is below implementer tier {impl_tier}"
        assert EFFORTS.index(rev_effort) >= EFFORTS.index(impl_effort), \
            f"{rating}: reviewer effort {rev_effort} is below implementer effort {impl_effort}"


def test_edge_consults_fable_advisor():
    assert re.match(r"fable, high", rating_table()["Edge"][ADVISOR])


def test_advisor_stage_is_fable_and_read_only():
    fm = frontmatter("advisor.md")
    assert fm.get("name") == "bailiwick-advisor"
    assert fm.get("model") == "fable"
    tools = {t.strip() for t in fm.get("tools", "").split(",") if t.strip()}
    assert tools, "agents/advisor.md must declare tools explicitly (empty inherits all)"
    assert tools <= {"Read", "Grep", "Glob"}, f"agents/advisor.md tools outside the read-only allowlist: {tools}"
    assert fm.get("effort") == "high"


def test_reviewer_frontmatter_matches_standard_row():
    tier, effort = sizing(rating_table()["Standard"][REVIEW])
    for name in ("quality.md", "security-review.md"):
        fm = frontmatter(name)
        assert (fm.get("model"), fm.get("effort")) == (tier, effort), \
            f"agents/{name} frontmatter is not the Standard row's {tier}/{effort}"


def test_docs_and_research_frontmatter_match_standard_row():
    tier, effort = sizing(rating_table()["Standard"][DOCS])
    for name in ("docs.md", "cloud-research.md"):
        fm = frontmatter(name)
        assert (fm.get("model"), fm.get("effort")) == (tier, effort), \
            f"agents/{name} frontmatter is not the Standard row's {tier}/{effort}"


def test_implementer_inherits_and_uses_standard_effort():
    _, effort = sizing(rating_table()["Standard"][IMPLEMENT])
    fm = frontmatter("implementer.md")
    assert (fm.get("model"), fm.get("effort")) == ("inherit", effort)


def test_memory_frontmatter_is_collect_sizing():
    fm = frontmatter("memory.md")
    assert (fm.get("model"), fm.get("effort")) == ("sonnet", "low")


def test_fixed_host_effort():
    expected = {"quality.md": "high", "security-review.md": "high",
                "docs.md": "medium", "cloud-research.md": "medium"}
    for name, effort in expected.items():
        assert frontmatter(name).get("fixed_host_effort") == effort, \
            f"agents/{name} fixed_host_effort is not {effort}"


def test_shared_reach_defined_once_in_skill():
    assert "**Shared reach**" in text(SKILL)
