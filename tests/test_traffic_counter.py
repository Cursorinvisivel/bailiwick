#!/usr/bin/env python3
"""Unit tests for scripts/traffic_counter.py — the pure ledger/badge helpers.

The network fetch and CLI wiring are exercised by the Traffic counter workflow itself;
what CI proves here is the accumulation contract: merging an API window into the per-day
ledger overwrites by date (so partial "today" counts self-correct), totals sum every
metric, and the badge JSON matches the shields.io endpoint schema.
"""
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "traffic_counter", REPO_ROOT / "scripts" / "traffic_counter.py"
)
tc = importlib.util.module_from_spec(_spec)
sys.modules["traffic_counter"] = tc
_spec.loader.exec_module(tc)


def _window(kind, *entries):
    return {
        kind: [
            {"timestamp": f"{day}T00:00:00Z", "count": count, "uniques": uniques}
            for day, count, uniques in entries
        ]
    }


def test_merge_overwrites_same_day_and_keeps_older_days():
    days = {}
    tc.merge_window(days, _window("views", ("2026-07-27", 5, 2), ("2026-07-28", 3, 1)), "views")
    # Next snapshot: the 27th fell out of the window, the 28th grew from partial to final.
    tc.merge_window(days, _window("views", ("2026-07-28", 9, 4), ("2026-07-29", 1, 1)), "views")
    assert days["2026-07-27"] == {"views": 5, "unique_views": 2}
    assert days["2026-07-28"] == {"views": 9, "unique_views": 4}
    assert days["2026-07-29"] == {"views": 1, "unique_views": 1}


def test_merge_kinds_share_a_day_record():
    days = {}
    tc.merge_window(days, _window("views", ("2026-07-28", 3, 1)), "views")
    tc.merge_window(days, _window("clones", ("2026-07-28", 7, 6)), "clones")
    assert days["2026-07-28"] == {
        "views": 3,
        "unique_views": 1,
        "clones": 7,
        "unique_clones": 6,
    }


def test_totals_sum_all_metrics_and_tolerate_missing_keys():
    days = {
        "2026-07-27": {"views": 5, "unique_views": 2},
        "2026-07-28": {"views": 3, "unique_views": 1, "clones": 7, "unique_clones": 6},
    }
    assert tc.totals(days) == {
        "views": 8,
        "unique_views": 3,
        "clones": 7,
        "unique_clones": 6,
    }


def test_badge_matches_shields_endpoint_schema():
    b = tc.badge("views", tc.humanize(12345), "blue")
    assert b["schemaVersion"] == 1
    assert b["label"] == "views"
    assert b["message"] == "12.3k"
    assert b["color"] == "blue"


def test_record_popular_overwrites_by_day_and_keeps_older_days():
    store = {}
    tc.record_popular(store, "2026-07-27", [{"referrer": "news.ycombinator.com"}], [])
    tc.record_popular(store, "2026-07-28", [{"referrer": "github.com"}], [{"path": "/x"}])
    # Re-snapshotting the same day overwrites it (later runs carry the fuller window).
    tc.record_popular(store, "2026-07-28", [{"referrer": "reddit.com"}], [{"path": "/y"}])
    assert store["snapshots"]["2026-07-27"]["referrers"] == [{"referrer": "news.ycombinator.com"}]
    assert store["snapshots"]["2026-07-28"] == {
        "referrers": [{"referrer": "reddit.com"}],
        "paths": [{"path": "/y"}],
    }


def test_humanize_thresholds():
    assert tc.humanize(9999) == "9999"
    assert tc.humanize(10_000) == "10.0k"
    assert tc.humanize(2_500_000) == "2.5M"
