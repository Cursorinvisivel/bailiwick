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
uniques — an upper bound, not true all-time uniques (hence the "~" on the
cloners badge).

With --referrers-data it additionally snapshots /traffic/popular/referrers and
/traffic/popular/paths into a separate ledger. Those endpoints return a whole
rolling-14-day top-10 (no per-day breakdown), so snapshots are stored raw by
date rather than summed. --report renders the latest snapshot plus the
all-time totals as a small markdown page; both are published on the
traffic-data branch — deliberately off the README (no badge), linked only
from docs/traffic-metrics.md.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_VERSION = "2022-11-28"
METRICS = ("views", "unique_views", "clones", "unique_clones")


def api_get(repo: str, token: str, endpoint: str):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/{endpoint}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": API_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as err:
        if err.code in (401, 403, 404):
            sys.exit(
                f"GitHub traffic API returned {err.code} for {repo}/{endpoint}: the token "
                "cannot read the traffic endpoints. A fine-grained PAT needs the repository "
                "permission 'Administration: read-only', must list this repository, and its "
                "resource owner must be the account/org that owns the repo; a classic PAT "
                "needs the `repo` scope. Either way the token's owner needs push access."
            )
        raise


def fetch_window(repo: str, token: str, kind: str) -> dict:
    """Fetch the 14-day daily breakdown for `kind` ("views" or "clones")."""
    return api_get(repo, token, f"traffic/{kind}?per=day")


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


def badge(label: str, message: str, color: str) -> dict:
    return {
        "schemaVersion": 1,
        "label": label,
        "message": message,
        "color": color,
        "cacheSeconds": 3600,
    }


def record_popular(store: dict, day: str, referrers: list, paths: list) -> dict:
    """Store one day's top-referrers/top-paths snapshot, overwriting by date.

    Unlike views/clones there is no per-day breakdown — each snapshot is a whole
    rolling 14-day top-10, so successive days overlap and cannot be summed. The
    ledger keeps the raw snapshots for later trend analysis instead.
    """
    store.setdefault("snapshots", {})[day] = {"referrers": referrers, "paths": paths}
    return store


def render_report(data: dict | None, store: dict) -> str:
    """Render the markdown traffic report: all-time totals + the latest top-10s."""

    def table(rows: list, field: str, header: str) -> str:
        if not rows:
            return "_Nothing in the current window._"
        lines = [f"| {header} | Views | Unique visitors |", "|---|---:|---:|"]
        for r in rows:
            name = str(r.get(field, "")).replace("|", "\\|")
            lines.append(f"| {name} | {r['count']} | {r['uniques']} |")
        return "\n".join(lines)

    day, snap = max(store.get("snapshots", {"—": {"referrers": [], "paths": []}}).items())
    parts = [
        "# Traffic report",
        "",
        "_Auto-generated daily by the Traffic counter workflow — do not edit._",
        "",
    ]
    if data:
        t = data["totals"]
        parts += [
            f"**All-time since {data['since']}:** {t['views']} views · "
            f"{t['clones']} clones · ~{t['unique_clones']} unique cloners "
            f"(day-sum upper bound) · {len(data['days'])} days recorded.",
            "",
        ]
    parts += [
        f"## Top referrers (14 days ending {day})",
        "",
        table(snap["referrers"], "referrer", "Referrer"),
        "",
        f"## Top content (14 days ending {day})",
        "",
        table(snap["paths"], "path", "Path"),
        "",
        "Historical snapshots: [referrers-data.json](referrers-data.json) · "
        "per-day ledger: [traffic-data.json](traffic-data.json)",
        "",
    ]
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", help="path of the JSON ledger (read+write)")
    parser.add_argument("--badge-dir", help="directory for badge endpoint JSON")
    parser.add_argument(
        "--referrers-data",
        help="path of the top-referrers/top-paths snapshot ledger (read+write)",
    )
    parser.add_argument("--report", help="path of the markdown traffic report (write)")
    args = parser.parse_args()
    if bool(args.data) != bool(args.badge_dir):
        parser.error("--data and --badge-dir must be used together")
    if not args.data and not args.referrers_data:
        parser.error("nothing to do: pass --data/--badge-dir and/or --referrers-data")
    if args.report and not args.referrers_data:
        parser.error("--report needs --referrers-data")

    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ.get("TRAFFIC_TOKEN", "")
    if not token:
        sys.exit(
            "TRAFFIC_TOKEN is empty. Create a fine-grained PAT with repository permission "
            "'Administration: read-only' (or a classic PAT with `repo` scope) and store it "
            "as the Actions secret TRAFFIC_PAT — the default GITHUB_TOKEN cannot read the "
            "traffic API."
        )
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    data = None

    if args.data:
        data_path = Path(args.data)
        data = json.loads(data_path.read_text()) if data_path.exists() else {"days": {}}

        for kind in ("views", "clones"):
            merge_window(data["days"], fetch_window(repo, token, kind), kind)

        data["totals"] = totals(data["days"])
        data["since"] = min(data["days"], default=today)
        data["updated"] = now.isoformat(timespec="seconds")
        data["days"] = dict(sorted(data["days"].items()))
        data_path.write_text(json.dumps(data, indent=2) + "\n")

        badge_dir = Path(args.badge_dir)
        badge_dir.mkdir(parents=True, exist_ok=True)
        (badge_dir / "views.json").write_text(
            json.dumps(badge("views", humanize(data["totals"]["views"]), "blue")) + "\n"
        )
        # "~" because summed per-day uniques are an upper bound, not true all-time uniques.
        (badge_dir / "clones.json").write_text(
            json.dumps(
                badge("cloners", "~" + humanize(data["totals"]["unique_clones"]), "brightgreen")
            )
            + "\n"
        )

        t = data["totals"]
        print(
            f"since {data['since']}: {t['views']} views ({t['unique_views']} unique/day-sum), "
            f"{t['clones']} clones ({t['unique_clones']} unique/day-sum) "
            f"across {len(data['days'])} days"
        )

    if args.referrers_data:
        ref_path = Path(args.referrers_data)
        store = json.loads(ref_path.read_text()) if ref_path.exists() else {}
        record_popular(
            store,
            today,
            api_get(repo, token, "traffic/popular/referrers"),
            api_get(repo, token, "traffic/popular/paths"),
        )
        store["updated"] = now.isoformat(timespec="seconds")
        store["snapshots"] = dict(sorted(store["snapshots"].items()))
        ref_path.write_text(json.dumps(store, indent=2) + "\n")

        snap = store["snapshots"][today]
        print(
            f"popular snapshot {today}: {len(snap['referrers'])} referrers, "
            f"{len(snap['paths'])} paths ({len(store['snapshots'])} snapshots total)"
        )

        if args.report:
            Path(args.report).write_text(render_report(data, store))


if __name__ == "__main__":
    main()
