#!/usr/bin/env python3
"""bailiwick knowledge metrics — read-only report over the telemetry sidecar + frontmatter.

Answers "is the stored knowledge actually earning its place?" from data already collected:
retrieval (what gets loaded, how often, reach), the load-vs-useful gap, cold/dead weight,
staleness, and telemetry↔file reconciliation. Reads only; writes nothing; needs no gate.

Usage:  report.py [--json] [--top N] [--knowledge <dir>]
Defaults to Bailiwick's knowledge/ relative to this script.
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys
import sys

CONTENT_DIRS = ("topics", "patterns", "context", "clients")
STALE_DAYS = 270  # ~9 months — matches memory.md Periodic Curation staleness scan.
FM = re.compile(r"^---\s*(.*?)\n---", re.DOTALL)


def find_knowledge(explicit):
    if explicit:
        return explicit
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", "knowledge"))


def parse_frontmatter(path):
    """Minimal YAML-frontmatter scalar reader (id/type/confidence/last_validated/scope)."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            m = FM.search(fh.read())
    except Exception:
        return {}
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def scan_files(kdir):
    """Return {id: {type, confidence, last_validated, scope, path}} for content files."""
    files = {}
    for d in CONTENT_DIRS:
        base = os.path.join(kdir, d)
        if not os.path.isdir(base):
            continue
        for root, _, names in os.walk(base):
            for name in names:
                if not name.endswith(".md") or name.upper() == "README.MD":
                    continue
                p = os.path.join(root, name)
                fm = parse_frontmatter(p)
                cid = fm.get("id") or os.path.splitext(name)[0]
                files[cid] = {
                    "type": fm.get("type", d.rstrip("s")),
                    "confidence": fm.get("confidence", "?"),
                    "last_validated": fm.get("last_validated", ""),
                    "scope": fm.get("scope", "generic"),
                    "path": os.path.relpath(p, kdir),
                }
    return files


def age_days(iso, today):
    try:
        d = datetime.date.fromisoformat(iso)
        return (today - d).days
    except Exception:
        return None


def bw_home():
    return os.environ.get("BAILIWICK_HOME") or os.path.join(os.path.expanduser("~"), ".bailiwick")


def log_health(event, detail):
    """Append a framework-health line to this machine's per-source shard (best-effort)."""
    try:
        import socket
        machine = ""
        try:
            bailiwick_root = os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))
            with open(os.path.join(bailiwick_root, ".bailiwick-sync.json"), encoding="utf-8") as fh:
                machine = (json.load(fh).get("machine") or "").strip()
        except Exception:
            pass
        machine = re.sub(r"[^a-z0-9._-]", "-", (machine or socket.gethostname()).lower())
        hdir = os.path.join(bw_home(), "health")
        os.makedirs(hdir, exist_ok=True)
        with open(os.path.join(hdir, machine + ".jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "machine": machine, "component": "metrics", "event": event,
                "detail": str(detail)[:300]}) + "\n")
    except Exception:
        pass


def load_health_shards():
    """Per-machine health events: local shards first (authoritative), then remote/ copies
    pulled from the encrypted backup by capture_backup.sh (fleet view on the central machine)."""
    shards = {}
    hdir = os.path.join(bw_home(), "health")
    paths = sorted(glob.glob(os.path.join(hdir, "*.jsonl")))
    paths += sorted(glob.glob(os.path.join(hdir, "remote", "*.jsonl")))
    for p in paths:
        machine = os.path.splitext(os.path.basename(p))[0]
        if machine in shards:
            continue  # local shard wins over a pulled remote copy of the same machine
        events = []
        try:
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        events.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            continue
        shards[machine] = events
    return shards


def report_health(shards, today):
    print("\n[framework health — per source]")
    if not shards:
        print("  (no health shards yet — components log failures to ~/.bailiwick/health/)")
        return

    def within(ev, days):
        d = age_days((ev.get("ts") or "")[:10], today)
        return d is not None and d <= days

    for machine, events in sorted(shards.items()):
        last = (events[-1].get("ts") or "-")[:19] if events else "-"
        err7 = [e for e in events if e.get("event") == "error" and within(e, 7)]
        warn7 = [e for e in events if e.get("event") == "warn" and within(e, 7)]
        print("  {:<20} last event {} · errors 7d: {} · warns 7d: {}".format(
            machine, last, len(err7), len(warn7)))
        push_ok = [e for e in events if e.get("component") == "capture_backup"
                   and e.get("event") == "info" and "push ok" in (e.get("detail") or "")]
        push_err = [e for e in events if e.get("component") == "capture_backup"
                    and e.get("event") == "error"]
        if push_ok or push_err:
            drift = ""
            if push_err and (not push_ok or push_err[-1]["ts"] > push_ok[-1]["ts"]):
                drift = "  ⚠ last push FAILED — remote copy lagging"
            print("  {:<20} backup last push ok: {}{}".format(
                "", push_ok[-1]["ts"][:19] if push_ok else "never", drift))
        by_comp = {}
        for e in err7:
            by_comp.setdefault(e.get("component") or "?", []).append(e)
        for comp, evs in sorted(by_comp.items(), key=lambda x: -len(x[1])):
            print("  {:<20}   {}× {} — last: {}".format(
                "", len(evs), comp, (evs[-1].get("detail") or "")[:90]))


def build(kdir):
    tel_path = os.path.join(kdir, ".telemetry.json")
    try:
        with open(tel_path, encoding="utf-8") as fh:
            tel = json.load(fh)
    except (OSError, ValueError) as e:
        log_health("error", "telemetry parse failed: {}".format(e))
        sys.exit("error: cannot read/parse {}: {}".format(tel_path, e))
    entries = tel.get("entries", tel)
    files = scan_files(kdir)
    today = datetime.date.today()

    rows = {}
    for cid, f in files.items():
        t = entries.get(cid, {})
        proj = t.get("distinct_projects_used") or []
        rows[cid] = {
            **f,
            "load_count": int(t.get("load_count", 0)),
            "applied_count": int(t.get("applied_count", 0)),
            "useful_count": int(t.get("useful_count", 0)),
            "projects": len(proj),
            "last_loaded": t.get("last_loaded"),
            "has_row": cid in entries,
            "stale_days": age_days(f["last_validated"], today),
        }
    orphans = [cid for cid in entries if cid not in files]  # telemetry row, no file
    missing = [cid for cid, r in rows.items() if not r["has_row"]]  # file, no telemetry row
    return rows, orphans, missing


def report_text(rows, orphans, missing, top):
    R = rows.values()
    n = len(rows)
    loaded = [r for r in R if r["load_count"] > 0]
    applied = [r for r in R if r["applied_count"] > 0]
    useful = [r for r in R if r["useful_count"] > 0]
    cold = [c for c, r in rows.items() if r["load_count"] == 0]
    total_loads = sum(r["load_count"] for r in R)
    grad = [c for c, r in rows.items()
            if r["type"] == "topic" and r["confidence"] == "high" and r["projects"] >= 3]
    reach = [c for c, r in rows.items() if r["projects"] >= 3 and r["confidence"] != "high"]
    stale = [(c, r["stale_days"]) for c, r in rows.items()
             if r["stale_days"] is not None and r["stale_days"] > STALE_DAYS]
    # Dead-weight prefers the `applied` signal, falls back to `used`, else OFF (signal missing).
    if applied:
        dead_sig = "applied"
        dead = [(c, r["load_count"]) for c, r in rows.items()
                if r["load_count"] >= 3 and r["applied_count"] == 0]
    elif useful:
        dead_sig = "useful"
        dead = [(c, r["load_count"]) for c, r in rows.items()
                if r["load_count"] >= 3 and r["useful_count"] == 0]
    else:
        dead_sig, dead = None, []

    def line(label, val):
        print(f"  {label:<44} {val}")

    print("\n=== bailiwick knowledge metrics ===")
    print("\n[library]")
    line("content files (topics/patterns/context/clients)", n)
    for typ in ("topic", "pattern", "context"):
        line(f"  {typ}s", sum(1 for r in R if r["type"] == typ))

    print("\n[retrieval]")
    line("ever loaded", f"{len(loaded)}/{n}")
    line("total load events", total_loads)
    line("cold (never loaded)", f"{len(cold)}/{n}")

    print("\n[impact — funnel: load → applied → used]")
    line("loaded (read)", f"{len(loaded)}/{n}")
    line("applied (loaded + session shipped: mutation/commit)", f"{len(applied)}/{n}")
    line("used (curate-judged: informed the output)", f"{len(useful)}/{n}")
    if not applied and not useful:
        print("  note: no `applied`/`used` signal yet — until captures record shipped/used work")
        print("  (ADR-004), impact reads BLIND, not zero. `loaded` above is the reliable signal.")

    print("\n[reach & graduation]")
    line("used in >=3 distinct projects", sum(1 for r in R if r["projects"] >= 3))
    line("graduation-eligible (topic, high, >=3 projects)", len(grad))
    for c in grad:
        print(f"    → {c}  (promote topics/ → patterns/)")
    if reach:
        line("reach>=3 but confidence<high (bump candidate)", len(reach))
        for c in reach[:top]:
            print(f"    → {c}  (confidence={rows[c]['confidence']}, projects={rows[c]['projects']})")

    print(f"\n[top {top} by loads]")
    for c, r in sorted(rows.items(), key=lambda x: -x[1]["load_count"])[:top]:
        print(f"  {r['load_count']:>3} loads · {r['projects']} proj · {c}")

    print("\n[archival / rewrite candidates]")
    if dead:
        print(f"  loaded repeatedly but never {dead_sig} (rewrite or archive):")
        for c, lc in sorted(dead, key=lambda x: -x[1]):
            print(f"    {lc} loads, 0 {dead_sig} · {c}")
    elif dead_sig is None:
        print("  (loaded-but-not-useful heuristic OFF — no `applied`/`used` signal library-wide yet;")
        print("   high load with 0 impact here means the signal is missing, NOT that the file is dead)")
    if cold:
        print(f"  never loaded ({len(cold)}) — candidates to archive or advertise better:")
        for c in sorted(cold):
            print(f"    · {c}")

    if stale:
        print(f"\n[stale — last_validated > {STALE_DAYS}d]")
        for c, d in sorted(stale, key=lambda x: -x[1]):
            print(f"    {d}d · {c}")

    if orphans or missing:
        print("\n[reconciliation — run /curate to fix]")
        if orphans:
            print(f"  telemetry rows with NO file (orphans): {', '.join(orphans)}")
        if missing:
            print(f"  files with NO telemetry row (seed on next curate): {', '.join(missing)}")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--knowledge", default="")
    a = ap.parse_args()
    kdir = find_knowledge(a.knowledge)
    if not os.path.isfile(os.path.join(kdir, ".telemetry.json")):
        print(f"error: no .telemetry.json under {kdir}", file=sys.stderr)
        return 2
    rows, orphans, missing = build(kdir)
    health = load_health_shards()
    if a.json:
        json.dump({"knowledge": kdir, "rows": rows, "orphans": orphans, "missing": missing,
                   "health": health},
                  sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        report_text(rows, orphans, missing, a.top)
        report_health(health, datetime.date.today())
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
