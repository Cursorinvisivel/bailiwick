"""Shared helpers for drill seeding and scoring (stdlib only).

Fixture builders (synthetic Claude Code transcripts + capture headers in the capture hook's shape),
token scanning (plain, case, slug, base64 forms), Claude Code transcript discovery (under the drill's
own config dir, never ~/.claude), per-stage cost (token shape from scripts/stage_cost.py read_run) and a
per-model-tier breakdown with a relative priced estimate, and the JSON/compare output.
"""
import base64
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import guard  # noqa: E402
import sandbox  # noqa: E402

sys.path.insert(0, os.path.join(guard.SOURCE_REPO, "scripts"))
import stage_cost  # noqa: E402  (read_run is the single source of per-run token accounting)

# Never scanned for residuals: drill plumbing, and git internals (history is probed via git log).
SWEEP_SKIP = {".git", "drill-results", "logs", "git-hooks", "cache", "home"}

# Relative per-token price by model tier, haiku = 1.0. RELATIVE, not dollars: the ratio of list prices
# (Haiku 4.5 / Sonnet 4.5 / Opus 4.5 = $1 / $3 / $5 per MTok input, and the same 1:3:5 ratio for output),
# as of PRICE_FACTORS_AS_OF. Edit here when prices change. None = unpriced (reported, never guessed):
# fable has no list price on record here; set it when known.
PRICE_FACTORS_AS_OF = "2026-11-03"
PRICE_FACTORS = {"haiku": 1.0, "sonnet": 3.0, "opus": 5.0, "fable": None}
TOKEN_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")


# ---------------------------------------------------------------------------- fixture builders
def claude_session(session_id, cwd, turns, start=None, model="claude-drill"):
    """Claude Code transcript records for `turns`: dicts with one of
    {"user": text} | {"assistant": text} | {"tool": name, "input": {...}, "result": text}; a turn may
    carry "model" to override the session's model for that record."""
    t = start or datetime.datetime(2026, 10, 20, 9, 0, 0, tzinfo=datetime.timezone.utc)
    recs, parent, ctx = [], None, 9000

    def stamp():
        nonlocal t
        t += datetime.timedelta(seconds=7)
        return t.isoformat().replace("+00:00", "Z")

    def base(kind):
        nonlocal parent
        seed = int(hashlib.sha256(session_id.encode()).hexdigest()[:12], 16)
        u = str(uuid.UUID(int=seed * 10 ** 6 + len(recs) + 1))
        rec = {"type": kind, "uuid": u, "parentUuid": parent, "sessionId": session_id, "cwd": cwd,
               "timestamp": stamp(), "isSidechain": False, "userType": "external", "version": "2.1.317"}
        parent = u
        return rec

    def usage():
        nonlocal ctx
        ctx += 900
        return {"input_tokens": 6, "cache_read_input_tokens": ctx, "cache_creation_input_tokens": 700,
                "output_tokens": 180}

    for i, turn in enumerate(turns):
        if "user" in turn:
            r = base("user")
            r["message"] = {"role": "user", "content": turn["user"]}
            recs.append(r)
        elif "assistant" in turn:
            r = base("assistant")
            r["message"] = {"id": "msg_drill_{}_{}".format(session_id[-6:], i), "type": "message",
                            "role": "assistant", "model": turn.get("model", model),
                            "content": [{"type": "text", "text": turn["assistant"]}], "usage": usage()}
            recs.append(r)
        else:
            tid = "toolu_drill_{}_{}".format(session_id[-6:], i)
            r = base("assistant")
            r["message"] = {"id": "msg_drill_{}_{}".format(session_id[-6:], i), "type": "message",
                            "role": "assistant", "model": turn.get("model", model),
                            "content": [{"type": "tool_use", "id": tid, "name": turn["tool"],
                                         "input": turn.get("input", {})}], "usage": usage()}
            recs.append(r)
            r = base("user")
            r["message"] = {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tid, "content": turn.get("result", "")}]}
            recs.append(r)
    return [json.dumps(r, ensure_ascii=False) for r in recs]


def capture_header(session_id, project_dir, mode, turns, origin=None, captured="2026-10-20T09:30:00"):
    """The .md header capture_session.py writes beside each capture (same field order)."""
    tools = sorted({t["tool"] for t in turns if "tool" in t})
    calls = sum(1 for t in turns if "tool" in t)
    mutating = sum(1 for t in turns if t.get("tool") in ("Write", "Edit"))
    lines = ["# Raw capture — {}".format(session_id), "",
             "- captured: {}".format(captured), "- capture_schema: 2", "- event: SessionEnd",
             "- project_dir: {}".format(project_dir), "- mode: {}".format(mode), "- agent: claude"]
    if mode == "shadow":
        lines.append("- origin_remote: {}".format(origin or "(none)"))
    lines += ["- tool_calls: {} (mutating: {})".format(calls, mutating), "- tools: {}".format(", ".join(tools) or "none"),
              "- subagents: 0 (records inlined: 0)", "- transcript: {}.jsonl".format(session_id), "",
              "## Retrieval Feedback (auto-derived)", "- project: {}".format(os.path.basename(project_dir)),
              "- loaded: []", "- loaded_via_subagents: []", "- applied: []", "- committed: false", "",
              "Pending curation. Run `/curate` to distill into the knowledge library (human-gated).", ""]
    return "\n".join(lines)


def write_capture(raw_dir, session_id, project_dir, mode, turns, origin=None):
    os.makedirs(raw_dir, exist_ok=True)
    paths = []
    p = os.path.join(raw_dir, session_id + ".jsonl")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("\n".join(claude_session(session_id, project_dir, turns)) + "\n")
    paths.append(p)
    p = os.path.join(raw_dir, session_id + ".md")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(capture_header(session_id, project_dir, mode, turns, origin))
    paths.append(p)
    return paths


# ---------------------------------------------------------------------------- token scanning
def b64_variants(literal, min_len=6):
    """Alignment-independent base64 forms of `literal`: the characters fully determined by its
    bytes at each of the three byte offsets. A literal embedded anywhere in base64 shows one."""
    data = literal.encode("utf-8")
    if len(data) < min_len:
        return []
    out = set()
    for off in range(3):
        enc = base64.b64encode(b"\0" * off + data + b"\0\0").decode()
        start, end = -(-8 * off // 6), (8 * (off + len(data))) // 6
        out.add(enc[start:end])
    return sorted(out)


def compile_patterns(spec):
    """[{"name", "regex", "flags"}] -> [(name, compiled bytes regex)]."""
    out = []
    for p in spec:
        flags = re.IGNORECASE if "i" in p.get("flags", "") else 0
        out.append((p["name"], re.compile(p["regex"].encode("utf-8"), flags)))
    return out


def b64_patterns(literals):
    pats = []
    for lit in literals:
        for v in b64_variants(lit):
            pats.append(("b64:" + lit, re.compile(re.escape(v.encode()))))
    return pats


def scan_bytes(data, pats):
    counts = {}
    for name, rx in pats:
        n = len(rx.findall(data))
        if n:
            counts[name] = counts.get(name, 0) + n
    return counts


def scan_file(path, pats):
    try:
        with open(path, "rb") as fh:
            return scan_bytes(fh.read(), pats)
    except OSError:
        return {}


def walk(base, skip=SWEEP_SKIP):
    """Every file and dir under base (paths), skipping plumbing dirs by name."""
    for dp, dn, fn in os.walk(base):
        dn[:] = sorted(d for d in dn if d not in skip)
        for d in dn:
            yield os.path.join(dp, d), True
        for f in sorted(fn):
            yield os.path.join(dp, f), False


def subtract_baseline(hits, baseline):
    """Residual hits minus the post-seed, pre-plant baseline (framework text that already matched a
    pattern, e.g. an unrelated "ADI"), per path, kind and pattern. Entries with nothing left drop out."""
    out = {}
    for rel, entry in hits.items():
        base = baseline.get(rel) or {}
        kept = {}
        for kind, counts in entry.items():
            left = {k: v - (base.get(kind) or {}).get(k, 0) for k, v in counts.items()}
            left = {k: v for k, v in left.items() if v > 0}
            if left:
                kept[kind] = left
        if kept:
            out[rel] = kept
    return out


def sweep(root, rel_bases, pats, name_pats, exclude=()):
    """Residual hits under each base: {relpath: {"content": {...}, "name": {...}}} (counts only)."""
    hits = {}
    for rb in rel_bases:
        base = os.path.join(root, rb)
        if not os.path.exists(base):
            continue
        for p, is_dir in walk(base):
            rel = os.path.relpath(p, root)
            if any(rel == e or rel.startswith(e.rstrip("/") + "/") for e in exclude):
                continue
            entry = {}
            nm = scan_bytes(os.path.basename(p).encode("utf-8", "replace"), name_pats)
            if nm:
                entry["name"] = nm
            if not is_dir:
                c = scan_file(p, pats)
                if c:
                    entry["content"] = c
            if entry:
                hits[rel] = entry
    return hits


# ---------------------------------------------------------------------------- git probes
def git_out(repo, args):
    r = subprocess.run(["git", "-C", repo] + args, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def commit_message_hits(repo, regex, flags=""):
    rx = re.compile(regex, re.IGNORECASE if "i" in flags else 0)
    msgs = git_out(repo, ["log", "--all", "--format=%H%x00%B%x01"]).split("\x01")
    return sum(1 for m in msgs if m.strip() and rx.search(m.split("\x00", 1)[-1]))


def history_diff_hits(repo, literal):
    return len([x for x in git_out(repo, ["log", "--all", "-i", "-S" + literal, "--format=%H"]).split() if x])


def show_at(repo, sha, rel):
    r = subprocess.run(["git", "-C", repo, "show", "{}:{}".format(sha, rel)], capture_output=True)
    return r.stdout if r.returncode == 0 else None


# ---------------------------------------------------------------------------- transcripts / cost
def claude_home(marker):
    """The drill session's Claude Code config dir, as recorded at seed time (guard-checked)."""
    return guard.check_claude_home(marker.get("claude_home") or sandbox.drill_claude_home())


def transcript_dir(marker):
    """Claude Code's per-project transcript dir for the sandbox project, under the DRILL config dir."""
    return marker.get("transcript_dir") or os.path.join(claude_home(marker), "projects",
                                                        sandbox.mangle(marker["project"]))


def resolve_session(marker, session):
    """'latest' or an id -> (main jsonl path or None, [(agentType, jsonl path)])."""
    d = transcript_dir(marker)
    if not session or not os.path.isdir(d):
        return None, []
    if session == "latest":
        mains = [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".jsonl")]
        if not mains:
            return None, []
        main = max(mains, key=os.path.getmtime)
    else:
        main = os.path.join(d, session + ".jsonl")
        if not os.path.isfile(main):
            return None, []
    subdir = os.path.join(d, os.path.basename(main)[:-len(".jsonl")], "subagents")
    subs = []
    if os.path.isdir(subdir):
        for f in sorted(os.listdir(subdir)):
            if f.endswith(".meta.json"):
                meta = sandbox.read_json(os.path.join(subdir, f), {}) or {}
                subs.append((meta.get("agentType", "?"), os.path.join(subdir, f[:-len(".meta.json")] + ".jsonl")))
    return main, subs


def model_tier(model):
    m = (model or "").lower()
    return next((t for t in PRICE_FACTORS if t in m), "other")


def model_usage(path):
    """{tier: {turns, <token keys>, cost_eq}} for one transcript, per record's message.model. Same turn
    accounting as stage_cost.read_run (one count per message id; output = the max seen per id)."""
    turns, out_by_id = {}, {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") != "assistant":
                    continue
                msg = d.get("message") or {}
                usage, mid = msg.get("usage") or {}, msg.get("id")
                if not mid:
                    continue
                if "output_tokens" in usage:
                    out_by_id[mid] = max(out_by_id.get(mid, 0), usage["output_tokens"])
                if mid not in turns and any(k in usage for k in stage_cost.CONTEXT_KEYS):
                    turns[mid] = (model_tier(msg.get("model")), {k: usage.get(k, 0) for k in stage_cost.CONTEXT_KEYS})
    except OSError:
        return {}
    by = {}
    for mid, (tier, ctx) in turns.items():
        row = by.setdefault(tier, dict({k: 0 for k in TOKEN_KEYS}, turns=0))
        row["turns"] += 1
        for k, v in ctx.items():
            row[k] += v
        row["output_tokens"] += out_by_id.get(mid, 0)
    for row in by.values():
        row["cost_eq"] = int(sum(row[k] * stage_cost.WEIGHTS[k] for k in TOKEN_KEYS))
    return by


def merge_models(*maps):
    out = {}
    for m in maps:
        for tier, row in (m or {}).items():
            acc = out.setdefault(tier, {})
            for k, v in row.items():
                acc[k] = acc.get(k, 0) + v
    return out


def priced(by_model):
    """Relative priced estimate (haiku-equivalent units) = sum of cost_eq x PRICE_FACTORS[tier] over the
    priced tiers; unpriced tiers are listed, never guessed."""
    est, unpriced = 0.0, []
    for tier, row in sorted(by_model.items()):
        f = PRICE_FACTORS.get(tier)
        if f is None:
            unpriced.append(tier)
        else:
            est += row.get("cost_eq", 0) * f
    return {"estimate_rel": int(est), "unpriced_tiers": unpriced, "factors": dict(PRICE_FACTORS),
            "factors_as_of": PRICE_FACTORS_AS_OF}


def run_cost(path):
    """stage_cost.read_run summarised: turns, start/peak context, weighted cost."""
    try:
        ctxs, cost, date, kb, bash_out = stage_cost.read_run(path)
    except OSError:
        return None
    if not ctxs:
        return {"turns": 0, "peak_ctx": 0, "cost_eq": int(cost)}
    return {"turns": len(ctxs), "start_ctx": ctxs[0], "peak_ctx": max(ctxs), "cost_eq": int(cost),
            "kb_touched": kb, "bash_out": bash_out}


def stages_report(marker, session):
    main, subs = resolve_session(marker, session)
    if not main:
        return {"session": None, "note": "no transcript found under {}".format(transcript_dir(marker))}
    out = {"session": os.path.basename(main)[:-len(".jsonl")], "main": run_cost(main), "stages": []}
    models = [model_usage(main)]
    for agent_type, path in subs:
        c = run_cost(path) or {}
        c["agentType"] = agent_type
        c["by_model"] = model_usage(path)
        models.append(c["by_model"])
        out["stages"].append(c)
    out["stage_types"] = sorted({s["agentType"] for s in out["stages"]})
    # token-weighted, NOT priced: every model's tokens weigh the same (stage_cost.WEIGHTS)
    out["total_cost_eq"] = (out["main"] or {}).get("cost_eq", 0) + sum(s.get("cost_eq", 0) for s in out["stages"])
    out["by_model"] = merge_models(*models)
    out["priced"] = priced(out["by_model"])
    return out


def stage_summary(stages):
    """The cost/stage lines both scorers put in their summary (flat, so --compare can diff them)."""
    if not stages or not stages.get("session"):
        return {}
    s = {"stages_ran": ",".join(stages["stage_types"]) or "none",
         "stage_runs": len(stages["stages"]),
         "main_peak_ctx": (stages["main"] or {}).get("peak_ctx", 0),
         "cost_eq_token_weighted": stages["total_cost_eq"],
         "cost_priced_rel": stages["priced"]["estimate_rel"]}
    for tier, row in sorted(stages["by_model"].items()):
        s["tokens_" + tier] = sum(row.get(k, 0) for k in TOKEN_KEYS)
        s["cost_eq_" + tier] = row.get("cost_eq", 0)
    if stages["priced"]["unpriced_tiers"]:
        s["unpriced_tiers"] = ",".join(stages["priced"]["unpriced_tiers"])
    return s


def render_stages(st):
    if not st:
        return
    if not st.get("session"):
        print("stages: " + st.get("note", "none"))
        return
    print("session {}: main {}".format(st["session"], json.dumps(st["main"], sort_keys=True)))
    for x in st["stages"]:
        print("   {:34} turns {:>4}  peak {:>8}  cost-eq {:>9}  models {}".format(
            x["agentType"], x.get("turns", 0), x.get("peak_ctx", 0), x.get("cost_eq", 0),
            ",".join(sorted(x.get("by_model") or {})) or "?"))
    print("cost by model tier (cost-eq is token-weighted, not priced):")
    for tier, row in sorted(st["by_model"].items()):
        print("   {:8} turns {:>4}  in {:>9}  cache-read {:>10}  cache-write {:>9}  out {:>8}  cost-eq {:>9}  x{}".format(
            tier, row["turns"], row["input_tokens"], row["cache_read_input_tokens"],
            row["cache_creation_input_tokens"], row["output_tokens"], row["cost_eq"],
            PRICE_FACTORS.get(tier, "?")))
    p = st["priced"]
    print("priced estimate (relative, haiku = 1, factors as of {}): {}{}".format(
        p["factors_as_of"], p["estimate_rel"],
        "  (unpriced, excluded: {})".format(", ".join(p["unpriced_tiers"])) if p["unpriced_tiers"] else ""))


def tool_uses(path, name=None):
    """[(tool name, input)] of one transcript's assistant tool_use blocks (optionally one tool only)."""
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") != "assistant":
                    continue
                for c in (d.get("message") or {}).get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "tool_use" and (name is None or c.get("name") == name):
                        out.append((c.get("name"), c.get("input") or {}))
    except OSError:
        pass
    return out


def assistant_texts(path, tools=True):
    """Assistant-authored text (and, with tools=True, tool inputs) of one transcript — what the agent
    SAID/DID, never its brief or tool output."""
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") != "assistant":
                    continue
                for c in (d.get("message") or {}).get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "text":
                        out.append(c.get("text") or "")
                    elif tools and isinstance(c, dict) and c.get("type") == "tool_use":
                        out.append(json.dumps(c.get("input")))
    except OSError:
        pass
    return "\n".join(out)


def transcript_listing(marker, pats, session=None):
    """Drill Claude Code state holding any identifier: COUNTS ONLY. The sandbox project's transcript dir,
    plus (for a resolved session) its file-history dir, plus history.jsonl lines for the sandbox project."""
    d = transcript_dir(marker)
    rows = []
    if os.path.isdir(d):
        for p, is_dir in walk(d, skip=set()):
            if is_dir:
                continue
            c = scan_file(p, pats)
            if c:
                rows.append({"file": os.path.relpath(p, d), "hits": sum(c.values())})
    out = {"dir": d, "files_with_hits": len(rows), "total_hits": sum(r["hits"] for r in rows), "files": rows}
    ch = claude_home(marker)
    if session:
        fh_dir = os.path.join(ch, "file-history", session)
        out["file_history_files_with_hits"] = sum(
            1 for p, is_dir in walk(fh_dir, skip=set()) if not is_dir and scan_file(p, pats)) if os.path.isdir(fh_dir) else 0
    out["history_lines_with_hits"] = len(history_lines(marker, pats))
    return out


def history_lines(marker, pats):
    """history.jsonl lines (drill config dir) for the sandbox project that hold an identifier."""
    path = os.path.join(claude_home(marker), "history.jsonl")
    hits = []
    try:
        with open(path, "rb") as fh:
            for line in fh:
                try:
                    proj = json.loads(line).get("project")
                except ValueError:
                    continue
                if proj == marker["project"] and scan_bytes(line, pats):
                    hits.append(line)
    except OSError:
        pass
    return hits


# ---------------------------------------------------------------------------- output
def emit(result, root, name, json_out=None):
    path = json_out or os.path.join(root, "drill-results", "{}-score-{}.json".format(
        name, datetime.datetime.now().strftime("%Y%m%dT%H%M%S")))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path


def session_found(stages):
    """True/False when a transcript session was requested; None when it was not (no --transcript-session)."""
    return None if stages is None else bool(stages.get("session"))


NO_SESSION_WARNING = ("INVALID RUN: no drill session transcript found, so the skill never ran in this "
                      "sandbox (launch.sh exited before the /drill-<skill> command?). The numbers below are "
                      "the untouched planted state, not a result.")


def compare(a_path, b_path):
    a, b = (sandbox.read_json(p, {}) or {} for p in (a_path, b_path))
    sa, sb = a.get("summary", {}), b.get("summary", {})
    bad = [n for n, s in (("A", sa), ("B", sb)) if s.get("session_found") is False]
    unk = [n for n, s in (("A", sa), ("B", sb)) if s.get("session_found") is None]
    if unk:
        print("note: arm(s) {} scored without --transcript-session; cannot confirm the skill ran.".format(
            ", ".join(unk)))
    if bad:
        print("COMPARISON INVALID: arm(s) {} have no drill session transcript (session_found != true); "
              "re-run those arms, launching the session and running the skill before scoring.".format(
                  ", ".join(bad)))
        return 2
    keys = sorted(set(sa) | set(sb))
    rows = []
    for k in keys:
        va, vb = sa.get(k), sb.get(k)
        delta = ""
        if (isinstance(va, (int, float)) and isinstance(vb, (int, float))
                and not isinstance(va, bool) and not isinstance(vb, bool)):
            delta = "{:+.3g}".format(vb - va)
        rows.append((k, str(va), str(vb), delta))
    head = ("metric", "A " + str(a.get("variant", "?")), "B " + str(b.get("variant", "?")), "B-A")
    w = [max(len(r[i]) for r in rows + [head]) + 2 for i in range(4)]
    for r in [head] + rows:
        print("{:{}}{:>{}}{:>{}}{:>{}}".format(r[0], w[0], r[1], w[1], r[2], w[2], r[3], w[3]))
    print("\nA = {}\nB = {}".format(a_path, b_path))
