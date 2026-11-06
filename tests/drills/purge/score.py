#!/usr/bin/env python3
"""Score a /drill-purge run against answer_key.json (read-only report; exit 0 unless a guard refuses).

    source <sandbox>/drill-env.sh
    score.py [--sandbox ROOT] [--transcript-session ID|latest] [--json-out PATH]
    score.py --compare A.json B.json

Reports, per planted trace, whether it is gone / still there / an expected residual for the
de-identified tier; whether the reusable rule survived de-identified; whether the client-specific
file is gone; over-deletion (keep checks); a residual sweep over every sandbox surface (contents AND
file names, tracked, untracked and ignored, plus base64 forms); git history; the purge session's own
capture; and drill Claude Code state holding the identifiers (COUNTS ONLY — never content), which
lives in the drill config dir, not ~/.claude. T27/T28 (file-history, history.jsonl) are "pending user
action": a purge can only list them, so they never count toward removal_rate.
With --transcript-session: which stages ran and their cost by model tier, whether the purge-session
sentinel (hooks/mark_purge_session.sh) was attempted and whether the capture hook's own detector
confirmed it, and whether the run told the user about the Claude Code
state it cannot remove.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import drillcommon as dc  # noqa: E402
import guard  # noqa: E402

KEY = os.path.join(HERE, "answer_key.json")


def load_key():
    with open(KEY, encoding="utf-8") as fh:
        return json.load(fh)


def patterns(key):
    named = dict((n, rx) for n, rx in dc.compile_patterns(key["patterns"]))
    return named, list(named.items()), dc.b64_patterns(key["b64_literals"])


def _probe_pats(probe, named):
    if "regex" in probe:
        return [("regex", re.compile(probe["regex"].encode(), re.IGNORECASE if "i" in probe.get("flags", "") else 0))]
    if probe.get("pattern") == "any":
        return list(named.items())
    return [(probe["pattern"], named[probe["pattern"]])]


def _files_under(path):
    if os.path.isfile(path):
        return [path]
    return [p for p, d in dc.walk(path, skip={".git"}) if not d] if os.path.isdir(path) else []


def probe(root, key, named, pr, marker=None):
    """Count of matches the probe still finds (0 = trace gone)."""
    t = pr["type"]
    if t == "claude_file_history":
        d = os.path.join(dc.claude_home(marker), "file-history", marker.get("planted_claude_session") or "-")
        return len([p for p, is_dir in dc.walk(d, skip=set()) if not is_dir]) if os.path.isdir(d) else 0
    if t == "claude_history":
        return len(dc.history_lines(marker, _probe_pats(pr, named)))
    if t == "path":
        return 1 if os.path.lexists(os.path.join(root, pr["path"])) else 0
    if t == "regex":
        pats = _probe_pats(pr, named)
        return sum(sum(dc.scan_file(f, pats).values()) for f in _files_under(os.path.join(root, pr["path"])))
    if t in ("json_keys", "json_values"):
        rx = named[pr["pattern"]]
        try:
            with open(os.path.join(root, pr["path"]), encoding="utf-8") as fh:
                entries = (json.load(fh) or {}).get("entries") or {}
        except (OSError, ValueError):
            return 0
        if t == "json_keys":
            return sum(1 for k in entries if rx.search(k.encode()))
        return sum(1 for v in entries.values() if isinstance(v, dict)
                   for p in (v.get("distinct_projects_used") or []) if rx.search(str(p).encode()))
    if t == "git_messages":
        p = key["patterns"]
        spec = next(x for x in p if x["name"] == pr["pattern"])
        return dc.commit_message_hits(os.path.join(root, pr["repo"]), spec["regex"], spec.get("flags", ""))
    if t == "git_diffs":
        return dc.history_diff_hits(os.path.join(root, pr["repo"]), pr["literal"])
    if t == "literal":
        lit = re.compile(re.escape(pr["text"].encode()))
        bases = [pr["path"]] if pr.get("path") else key["sweep_roots"]
        return sum(sum(dc.scan_file(f, [("lit", lit)]).values())
                   for b in bases for f in _files_under(os.path.join(root, b)))
    if t == "names":
        pats = _probe_pats(pr, named)
        n = 0
        for b in pr["paths"]:
            for p, _ in dc.walk(os.path.join(root, b)):
                n += 1 if dc.scan_bytes(os.path.basename(p).encode(), pats) else 0
        return n
    raise ValueError("unknown probe type " + t)


def rule_check(root, key, all_pats):
    groups = key["rule"]["keywords"]
    best = {"survives": False, "file": None, "identified_copies": []}
    for f in _files_under(os.path.join(root, key["rule"]["where"])):
        if not f.endswith(".md"):
            continue
        with open(f, encoding="utf-8", errors="replace") as fh:
            low = fh.read().lower()
        if not all(any(k in low for k in g) for g in groups):
            continue
        rel = os.path.relpath(f, root)
        hits = dc.scan_file(f, all_pats)
        hits.update(dc.scan_bytes(os.path.basename(f).encode(), all_pats))
        if hits:
            best["identified_copies"].append(rel)
        elif not best["survives"]:
            best.update(survives=True, file=rel)
    return best


def session_captures(root, marker):
    planted = set(marker.get("planted_files") or [])
    out = []
    for base in ("project/.bailiwick-outputs", "home-bailiwick/captures"):
        for p, d in dc.walk(os.path.join(root, base), skip=set()):
            rel = os.path.relpath(p, root)
            if not d and "/raw/" in "/" + rel and rel not in planted:
                out.append(rel)
    return sorted(out)


TELEMETRY = "framework/knowledge/.telemetry.json"


def sandbox_role(root):
    """The sandbox framework's machine role (`.bailiwick-sync.json` `role`); satellite when unset, as
    in the framework. On a satellite the purge skill never edits `.telemetry.json` (central-owned), so a
    trace with `satellite_expected` is scored by that expectation instead of `expected`."""
    try:
        with open(os.path.join(root, "framework", ".bailiwick-sync.json"), encoding="utf-8") as fh:
            role = json.load(fh).get("role")
    except (OSError, ValueError, AttributeError):
        role = None
    return role if role in ("central", "satellite") else "satellite"


def _skip_configured(root, marker):
    try:
        with open(os.path.join(root, "framework", ".bailiwick-sync.json"), encoding="utf-8") as fh:
            names = json.load(fh)["capture"]["skip_skills"]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return isinstance(names, list) and marker.get("skill_name") in names


SENTINEL = "mark_purge_session.sh"


def sentinel_confirmed(main):
    """True when the capture hook's OWN detector (hooks/capture_session.py) counts the sentinel in this
    transcript: an exact invocation whose paired result ran successfully and carried the success line.
    A declined ask, an errored run, or a `cat` of the script does not count."""
    hooks = os.path.normpath(os.path.join(HERE, "..", "..", "..", "hooks"))
    if hooks not in sys.path:
        sys.path.insert(0, hooks)
    import capture_session as cs
    st = cs._new_state(("purge",))
    with open(main, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                cs._detect_purge(rec, st)
    return "sentinel" in st["purge_src"]


def session_checks(key, main):
    """From the drill session's own transcript: was the sentinel attempted (any Bash call naming it,
    including declined/errored ones), was it confirmed by the hook's own detector, and did the run tell
    the user about the Claude Code state it cannot remove (file-history, history.jsonl)?"""
    cmds = [str(inp.get("command", "")) for _, inp in dc.tool_uses(main, "Bash")]
    said = dc.assistant_texts(main, tools=False).lower()
    return {"sentinel_ran": any(SENTINEL in c for c in cmds),
            "sentinel_confirmed": sentinel_confirmed(main),
            "user_action_surfaced": all(any(k in said for k in g) for g in key["user_action_markers"])}


def score(root, session=None):
    key = load_key()
    marker = guard.check_root(root)
    root = marker["root"]
    guard.check_knowledge(root)
    named, pats, b64 = patterns(key)
    all_pats = pats + b64

    role = sandbox_role(root)
    traces = []
    for tr in key["traces"]:
        n = probe(root, key, named, tr["probe"], marker)
        exp = tr.get("satellite_expected", tr["expected"]) if role == "satellite" else tr["expected"]
        if exp == "pending-central":
            # Central-owned state on a satellite: it must stay for central to purge. Gone means the run
            # edited central-owned telemetry from a satellite, which the skill forbids.
            ok = n > 0
            status = "pending central (satellite)" if ok else "EDITED ON SATELLITE"
        elif exp == "residual-expected":
            status = "residual (expected for tier)" if n else "gone (beyond tier)"
            ok = True
        elif exp == "pending-user-action":
            status = "pending user action" if n else "gone (user state removed)"
            ok = True
        else:
            ok = n == 0
            status = "ok" if ok else "REMAINS"
        traces.append({"id": tr["id"], "surface": tr["surface"], "form": tr["form"], "expected": exp,
                       "matches": n, "status": status, "ok": ok, "note": tr.get("note", "")})

    scored = [t for t in traces if t["expected"] in ("removed", "abstracted")]
    removed_ok = sum(t["ok"] for t in scored)
    rule = rule_check(root, key, all_pats)
    cf = key["client_file"]
    marker_rx = [("m", re.compile(re.escape(m.encode()))) for m in cf["markers"]]
    marker_hits = sum(sum(dc.scan_file(f, marker_rx).values())
                      for b in key["sweep_roots"] for f in _files_under(os.path.join(root, b)))
    client_deleted = not os.path.lexists(os.path.join(root, cf["path"])) and marker_hits == 0

    keeps = []
    for k in key["keep"]:
        p = os.path.join(root, k["path"])
        ok = os.path.isfile(p)
        if ok and k.get("contains"):
            with open(p, encoding="utf-8", errors="replace") as fh:
                ok = k["contains"] in fh.read()
        keeps.append({"id": k["id"], "what": k["what"], "ok": ok})

    sess = session_captures(root, marker)
    sess_hits = sum(sum(dc.scan_file(os.path.join(root, s), all_pats).values()) for s in sess)
    exclude = key["sweep_exclude"] + sess + ([TELEMETRY] if role == "satellite" else [])
    raw_sweep = dc.sweep(root, key["sweep_roots"], all_pats, pats, exclude=exclude)
    sweep = dc.subtract_baseline(raw_sweep, marker.get("sweep_baseline") or {})

    fw = os.path.join(root, "framework")
    history = {"commit_messages": probe(root, key, named, {"type": "git_messages", "repo": "framework", "pattern": "id"}),
               "diff_commits": {lit: dc.history_diff_hits(fw, lit) for lit in
                                (key["tokens"]["id"], key["tokens"]["org_token"], key["tokens"]["org_name"])}}
    stages = dc.stages_report(marker, session) if session else None
    transcripts = dc.transcript_listing(marker, all_pats, (stages or {}).get("session"))

    summary = {
        "removal_rate": round(removed_ok / len(scored), 3) if scored else 0.0,
        "traces_remaining": len(scored) - removed_ok,
        "residual_expected_present": sum(1 for t in traces if t["expected"] == "residual-expected" and t["matches"]),
        "rule_survives_deidentified": rule["survives"],
        "rule_identified_copies": len(rule["identified_copies"]),
        "client_file_deleted": client_deleted,
        "keep_ok": "{}/{}".format(sum(k["ok"] for k in keeps), len(keeps)),
        "over_deletions": sum(1 for k in keeps if not k["ok"]),
        "unexpected_residual_paths": len(sweep),
        "session_capture_files": len(sess),
        "session_capture_hits": sess_hits,
        # The sandbox's .bailiwick-sync.json lists the drill skill in capture.skip_skills, so its session
        # must leave no capture; False means the config is missing/does not list it (nothing to score).
        "capture_skip_configured": _skip_configured(root, marker),
        "transcript_files_with_hits": transcripts["files_with_hits"],
        "user_action_pending": sum(1 for t in traces if t["expected"] == "pending-user-action" and t["matches"]),
        "role": role,
        "central_pending": sum(1 for t in traces if t["expected"] == "pending-central" and t["matches"]),
        "satellite_violations": sum(1 for t in traces if t["expected"] == "pending-central" and not t["ok"]),
        "sweep_baseline_paths": len(marker.get("sweep_baseline") or {}),
    }
    summary["perfect"] = bool(summary["removal_rate"] == 1.0 and rule["survives"] and client_deleted
                              and not summary["over_deletions"] and not sweep
                              and not summary["satellite_violations"])
    summary["session_found"] = dc.session_found(stages)
    if stages and stages.get("session"):
        summary.update(dc.stage_summary(stages))
        main, _ = dc.resolve_session(marker, session)
        summary.update(session_checks(key, main))
    return {"drill": "purge", "variant": marker.get("variant"), "skill": marker.get("skill_name"),
            "skill_ref": marker.get("skill_ref"), "sandbox": root, "summary": summary, "traces": traces,
            "rule": rule, "keep": keeps, "sweep": sweep, "session_captures": sess, "history": history,
            "transcripts": transcripts, "stages": stages}


def render(res):
    s = res["summary"]
    print("purge drill score — variant {} ({}@{})".format(res["variant"], res["skill"], res["skill_ref"]))
    print("\n{:5}{:26}{:>8}  {:16}{}".format("id", "status", "matches", "form", "surface"))
    for t in res["traces"]:
        print("{:5}{:26}{:>8}  {:16}{}{}".format(t["id"], t["status"], t["matches"], t["form"], t["surface"],
                                                 "  [" + t["note"] + "]" if t.get("note") else ""))
    print("\nreusable rule: {}{}".format(
        "survives de-identified in " + res["rule"]["file"] if res["rule"]["survives"] else "LOST (no de-identified copy)",
        "; identified copies: " + ", ".join(res["rule"]["identified_copies"]) if res["rule"]["identified_copies"] else ""))
    print("client-specific file deleted: {}".format(s["client_file_deleted"]))
    bad = [k for k in res["keep"] if not k["ok"]]
    print("keep checks: {}{}".format(s["keep_ok"], "  OVER-DELETED: " + "; ".join(
        "{} {}".format(k["id"], k["what"]) for k in bad) if bad else ""))
    print("unexpected residual paths: {} (after subtracting {} pre-plant baseline path(s))".format(
        len(res["sweep"]), s["sweep_baseline_paths"]))
    for rel, e in sorted(res["sweep"].items())[:25]:
        print("   {}  {}".format(rel, json.dumps(e, sort_keys=True)))
    print("history: {} commit message(s); diff commits {}".format(
        res["history"]["commit_messages"], res["history"]["diff_commits"]))
    print("purge-session captures in the sandbox: {} file(s), {} identifier hit(s){}".format(
        s["session_capture_files"], s["session_capture_hits"],
        "" if s["capture_skip_configured"] else
        "  (NOT SCORED: the sandbox .bailiwick-sync.json capture.skip_skills is missing or does not list "
        "{})".format(res["skill"])))
    tr = res["transcripts"]
    print("drill Claude Code state holding identifiers (drill config dir, not ~/.claude): transcripts {} file(s) / "
          "{} hit(s) under {}; history.jsonl {} line(s); session file-history {} file(s)".format(
              tr["files_with_hits"], tr["total_hits"], tr["dir"], tr.get("history_lines_with_hits", 0),
              tr.get("file_history_files_with_hits", "n/a")))
    if "sentinel_ran" in s:
        print("purge-session sentinel ({}) attempted: {}   confirmed: {}   capture of this session skipped: {}   "
              "user told about Claude Code state: {}".format(
                  SENTINEL, s["sentinel_ran"], s["sentinel_confirmed"], s["session_capture_files"] == 0,
                  s["user_action_surfaced"]))
    dc.render_stages(res.get("stages"))
    print("\nSUMMARY " + json.dumps(s, sort_keys=True))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="score.py")
    ap.add_argument("--sandbox", default=os.environ.get("BW_DRILL_SANDBOX"))
    ap.add_argument("--transcript-session")
    ap.add_argument("--json-out")
    ap.add_argument("--compare", nargs=2, metavar=("A_JSON", "B_JSON"))
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if a.compare:
        return dc.compare(*a.compare) or 0
    try:
        res = score(a.sandbox, a.transcript_session)
    except guard.Refused as e:
        print("drill guard REFUSED: {}".format(e), file=sys.stderr)
        return guard.REFUSED
    path = dc.emit(res, res["sandbox"], "purge", a.json_out)
    if not a.quiet:
        render(res)
        print("JSON: " + path)
    if res["summary"].get("session_found") is False:
        print("\n" + dc.NO_SESSION_WARNING, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
