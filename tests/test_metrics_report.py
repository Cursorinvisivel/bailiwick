"""Contract tests for skills/metrics/report.py: the capture-coverage caveat and the reach/graduation output.

Captures before capture_schema 2 never saw subagent reads, so "never loaded" is no archive verdict
until subagent-aware captures have covered SUBAGENT_WINDOW_DAYS. Synthetic headers only.
"""
import datetime
import importlib.util
import json
from pathlib import Path

import pytest

REPORT = Path(__file__).resolve().parent.parent / "skills" / "metrics" / "report.py"


@pytest.fixture
def report():
    spec = importlib.util.spec_from_file_location("_bw_metrics_report", REPORT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _capture(dirpath, name, captured, schema=None):
    dirpath.mkdir(parents=True, exist_ok=True)
    lines = ["# Raw capture — {}\n".format(name), "- captured: {}T10:00:00".format(captured)]
    if schema is not None:
        lines.append("- capture_schema: {}".format(schema))
    (dirpath / (name + ".md")).write_text("\n".join(lines) + "\n")


@pytest.fixture
def layout(tmp_path, monkeypatch):
    kdir = tmp_path / "fw" / "knowledge"
    kdir.mkdir(parents=True)
    home = tmp_path / "bw-home"
    monkeypatch.setenv("BAILIWICK_HOME", str(home))
    return kdir, tmp_path / "fw" / ".bailiwick-outputs" / "raw", home / "captures" / "repo-abc" / "raw"


def test_coverage_counts_old_and_new_across_both_staging_roots(report, layout):
    kdir, seeded, shadow = layout
    _capture(seeded, "old-1", "2026-09-01")
    _capture(seeded / ".curated", "old-2", "2026-09-02", schema=1)
    _capture(shadow, "new-1", "2026-10-20", schema=2)
    _capture(shadow / ".curated", "new-0", "2026-10-10", schema=2)
    (seeded / "notes.md").write_text("not a capture header\n")
    cov = report.capture_coverage(str(kdir))
    assert cov == {"total": 4, "old": 2, "first_subagent_aware": "2026-10-10"}


def test_caveat_holds_until_the_window_is_covered(report):
    cov = {"total": 4, "old": 2, "first_subagent_aware": "2026-10-10"}
    early = report.subagent_caveat(cov, datetime.date(2026, 10, 27))
    assert early and "2 of 4" in early and "do not archive" in early
    late = datetime.date(2026, 10, 10) + datetime.timedelta(days=report.SUBAGENT_WINDOW_DAYS)
    assert report.subagent_caveat(cov, late) is None


def test_caveat_when_no_capture_is_subagent_aware(report):
    cov = {"total": 0, "old": 0, "first_subagent_aware": None}
    assert "since never" in report.subagent_caveat(cov, datetime.date(2026, 10, 27))


def test_graduation_prints_reach_label_and_used_evidence(report, tmp_path, capsys):
    kdir = tmp_path / "knowledge"
    (kdir / "topics").mkdir(parents=True)
    (kdir / "topics" / "demo.md").write_text(
        "---\nid: demo\ntype: topic\nconfidence: high\nlast_validated: 2026-10-01\n---\n# Demo\n")
    (kdir / "topics" / "bump.md").write_text(
        "---\nid: bump\ntype: topic\nconfidence: medium\nlast_validated: 2026-10-01\n---\n# Bump\n")
    (kdir / "topics" / "held.md").write_text(
        "---\nid: held\ntype: topic\nconfidence: low\nlast_validated: 2026-10-01\n---\n# Held\n")
    (kdir / ".telemetry.json").write_text(json.dumps({"entries": {
        "demo": {"load_count": 3, "useful_count": 1,
                 "distinct_projects_used": ["a", "b", "c"]},
        "bump": {"load_count": 4, "useful_count": 0,
                 "distinct_projects_used": ["a", "b", "c"]},
        "held": {"load_count": 3, "useful_count": 1,
                 "distinct_projects_used": ["a", "b", "c"]}}}))
    rows, orphans, missing = report.build(str(kdir))
    assert rows["demo"]["useful_count"] == 1 and rows["demo"]["projects"] == 3
    report.report_text(rows, orphans, missing, 5)
    out = capsys.readouterr().out
    assert "reach: loaded in >=3 distinct projects" in out
    assert "loads=3, used=1, projects=3" in out
    assert "confidence=medium, used=0, projects=3" in out
    assert "confidence=low, used=1, projects=3; needs used>=2 for medium" in out
    assert "projects=3; needs" not in out.split("→ bump")[1].splitlines()[0]
