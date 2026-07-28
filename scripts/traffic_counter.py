#!/usr/bin/env python3
"""Accumulate GitHub traffic counts beyond the API's 14-day window.

GitHub's traffic API (/traffic/views, /traffic/clones) only returns the last
14 days, so an all-time total has to be accumulated externally. This script is
run daily by .github/workflows/traffic-counter.yml: it merges the current
14-day window into a per-day ledger (re-snapshotting a day overwrites it, so
the partial count for "today" self-corrects on later runs), then emits
shields.io endpoint-badge JSON with the running totals for the README.

Requires TRAFFIC_TOKEN — a PAT that can read the traffic API (fine-grained
with repository permission "Administration: read-only", or classic with the
`repo` scope). The Actions-issued GITHUB_TOKEN cannot read these endpoints.

Note on "unique" figures: GitHub's uniques are deduplicated only within the
window it reports, so the accumulated unique totals here are sums of per-day
uniques — an upper bound, not true all-time uniques.
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_VERSION = "2022-11-28"
METRICS = ("views", "unique_views", "clones", "unique_clones")


def fetch_window(repo: str, token: str, kind: str) -> dict:
    """Fetch the 14-day daily breakdown for `kind` ("views" or "clones")."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/traffic/{kind}?per=day",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": API_VERSION,
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def merge_window(days: dict, window: dict, kind: str) -> dict:
    """Merge one API window into the per-day ledger, overwriting by date."""
    for entry in window.get(kind, []):
        rec = days.setdefault(entry["timestamp"][:10], {})
        rec[kind] = entry["count"]
        rec[f"unique_{kind}"] = entry["uniques"]
    return days


def totals(days: dict) -> dict:
    out = dict.fromkeys(METRICS, 0)
    for rec in days.values():
        for key in METRICS:
            out[key] += rec.get(key, 0)
    return out


def humanize(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def badge(label: str, count: int, color: str) -> dict:
    return {
        "schemaVersion": 1,
        "label": label,
        "message": humanize(count),
        "color": color,
        "cacheSeconds": 3600,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="path of the JSON ledger (read+write)")
    parser.add_argument("--badge-dir", required=True, help="directory for badge endpoint JSON")
    args = parser.parse_args()

    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ.get("TRAFFIC_TOKEN", "")
    if not token:
        sys.exit(
            "TRAFFIC_TOKEN is empty. Create a fine-grained PAT with repository permission "
            "'Administration: read-only' (or a classic PAT with `repo` scope) and store it "
            "as the Actions secret TRAFFIC_PAT — the default GITHUB_TOKEN cannot read the "
            "traffic API."
        )

    data_path = Path(args.data)
    data = json.loads(data_path.read_text()) if data_path.exists() else {"days": {}}

    for kind in ("views", "clones"):
        merge_window(data["days"], fetch_window(repo, token, kind), kind)

    data["totals"] = totals(data["days"])
    data["since"] = min(data["days"], default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    data["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["days"] = dict(sorted(data["days"].items()))
    data_path.write_text(json.dumps(data, indent=2) + "\n")

    badge_dir = Path(args.badge_dir)
    badge_dir.mkdir(parents=True, exist_ok=True)
    (badge_dir / "views.json").write_text(
        json.dumps(badge("views", data["totals"]["views"], "blue")) + "\n"
    )
    (badge_dir / "clones.json").write_text(
        json.dumps(badge("clones", data["totals"]["clones"], "brightgreen")) + "\n"
    )

    t = data["totals"]
    print(
        f"since {data['since']}: {t['views']} views ({t['unique_views']} unique/day-sum), "
        f"{t['clones']} clones ({t['unique_clones']} unique/day-sum) "
        f"across {len(data['days'])} days"
    )


if __name__ == "__main__":
    main()
