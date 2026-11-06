#!/usr/bin/env python3
"""Drift tests for the lead-or-inline rule (ADR-010 Amendment 3).

The skill's body only loads after a session has already decided to invoke it, so the decision is
made from copies: the skill descriptions, the session-start banner, and the host templates. The
canonical one-line rule lives in skills/lead/SKILL.md ("When to lead"). These tests read it from
there and fail when any copy drifts, instead of hardcoding a second version that would rot.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "lead" / "SKILL.md"
CODEX_SKILL = REPO_ROOT / "codex-skills" / "bailiwick-lead" / "SKILL.md"

RULE_COPIES = [
    REPO_ROOT / "hooks" / "session_start.sh",
    REPO_ROOT / "hooks" / "codex-global-agents.tmpl.md",
    REPO_ROOT / "hooks" / "antigravity-global.tmpl.md",
]
OVERRIDE_COPIES = RULE_COPIES + [
    REPO_ROOT / "CLAUDE.md",
    REPO_ROOT / "agents" / "lead.md",
    REPO_ROOT / "docs" / "FRAMEWORK.md",
]
FORCE = ['"lead it"', '"run the full Quality Workflow"', "naming the stages"]
# Each host names its own command: Claude Code /lead, Codex $bailiwick-lead, others the skill path.
FORCE_COMMANDS = ["/lead", "$bailiwick-lead", "skills/lead/SKILL.md"]
INLINE = ['"just do it"', '"inline"']


def text(path):
    return path.read_text(encoding="utf-8")


def flat(s):
    """Collapse whitespace and Markdown emphasis so line wrapping does not count as drift."""
    return re.sub(r"\s+", " ", s.replace("*", "")).strip()


def canonical_rule():
    m = re.search(r"^\s*> (Lead it: .+)$", text(SKILL), re.MULTILINE)
    assert m, "skills/lead/SKILL.md lost its canonical '> Lead it: …' line"
    return m.group(1).strip()


def description(path):
    m = re.search(r"^description: (.+)$", text(path), re.MULTILINE)
    assert m, f"{path} has no description"
    return m.group(1)


def test_rule_line_is_copied_verbatim():
    rule = flat(canonical_rule())
    for path in RULE_COPIES:
        assert rule in flat(text(path)), f"{path.relative_to(REPO_ROOT)} does not carry the canonical rule"


def test_override_phrases_match_everywhere():
    for path in [SKILL] + OVERRIDE_COPIES:
        body = flat(text(path))
        for phrase in FORCE + INLINE:
            assert flat(phrase) in body, f"{path.relative_to(REPO_ROOT)} is missing override phrase {phrase}"
        assert any(c in body for c in FORCE_COMMANDS), f"{path.relative_to(REPO_ROOT)} names no force command"


def test_descriptions_default_on_only_in_wired_repos():
    for path in (SKILL, CODEX_SKILL):
        d = description(path)
        assert "without being asked" in d
        assert "Bailiwick-wired" in d, f"{path} would self-invoke in unrelated repositories"
        assert "Outside wired repositories" in d
        assert len(d) <= 1024, f"{path} description exceeds 1024 characters"


def test_descriptions_name_every_trigger_and_inline_case():
    triggers = ["more than one file", "IaC", "IAM", "secrets", "security-control", "new module",
                "design decision", "review",
                "questions", "lookups", "small single-file fixes"]
    for path in (SKILL, CODEX_SKILL):
        d = description(path)
        for t in triggers:
            assert t in d, f"{path.relative_to(REPO_ROOT)} description lacks '{t}'"


def test_security_triggers_are_pinned():
    """Tightening the rule to curb over-triggering must never drop the security triggers."""
    rule = canonical_rule()
    for t in ("IAM", "network", "secrets", "security-control"):
        assert t in rule, f"canonical rule lost the '{t}' trigger"


def test_loading_the_skill_is_not_a_decision_to_lead():
    assert "Loading this skill does not make a task led" in text(SKILL)
