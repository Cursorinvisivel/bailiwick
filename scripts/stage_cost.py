#!/usr/bin/env python3
"""Per-stage token cost of Bailiwick native subagent runs, split before/after a cutoff date.

Reads Claude Code's own subagent transcripts (<config>/projects/*/*/subagents/*.jsonl, where
<config> is $CLAUDE_CONFIG_DIR or ~/.claude). Those carry per-turn usage; the raw captures in
.bailiwick-outputs/ only hold dispatch prompts and final reports, so they cannot show context
growth. Read-only: prints a table, writes nothing.

Usage: python3 scripts/stage_cost.py [YYYY-MM-DD]
       The default cutoff is 2026-11-03 (ADR-010 Amendment 3, Lead skill by default).
"""
import collections
import datetime
import glob
import json
import os
import statistics
import sys

DEFAULT_CUTOFF = "2026-11-03"
# Relative price of each token kind against plain input (cache read 0.1x, cache write 1.25x,
# output 5x). Shape only; real prices vary by model.
WEIGHTS = {"input_tokens": 1.0, "cache_read_input_tokens": 0.1,
           "cache_creation_input_tokens": 1.25, "output_tokens": 5.0}
CONTEXT_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
KB_MARKERS = ("knowledge/INDEX", "knowledge/topics", "knowledge/patterns", "engineering-defaults")


def parse_cutoff(argv):
    if len(argv) == 2 and argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        sys.exit(0)
    if len(argv) > 2:
        sys.exit(__doc__.strip())
    raw = argv[1] if len(argv) == 2 else DEFAULT_CUTOFF
    try:
        return datetime.date.fromisoformat(raw).isoformat()
    except ValueError:
        sys.exit(f"stage_cost: cutoff must be YYYY-MM-DD, got {raw!r}")


def read_run(jsonl):
    """Return one run's per-turn context sizes, weighted cost, date, KB use, and shell output."""
    seen, ctxs, cost, date, kb, bash_out, names = set(), [], 0.0, None, False, 0, {}
    out_by_id = {}  # output_tokens grows across a message's lines (streaming); keep the max
    with open(jsonl, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            date = date or (d.get("timestamp") or "")[:10]
            msg = d.get("message") or {}
            content = msg.get("content")
            if d.get("type") == "assistant":
                usage = msg.get("usage") or {}
                mid = msg.get("id")
                if mid and "output_tokens" in usage:
                    out_by_id[mid] = max(out_by_id.get(mid, 0), usage["output_tokens"])
                # One line per content block repeats the same id and usage: count each turn once.
                # Lines without an id or without input usage (synthetic messages) are not turns.
                if mid and mid not in seen and any(k in usage for k in CONTEXT_KEYS):
                    seen.add(mid)
                    ctxs.append(sum(usage.get(k, 0) for k in CONTEXT_KEYS))
                    cost += sum(usage.get(k, 0) * WEIGHTS[k] for k in CONTEXT_KEYS)
                for c in content or []:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        names[c.get("id")] = c.get("name")
                        if any(k in json.dumps(c.get("input")) for k in KB_MARKERS):
                            kb = True
            elif isinstance(content, list):
                for c in content:
                    if (isinstance(c, dict) and c.get("type") == "tool_result"
                            and names.get(c.get("tool_use_id")) == "Bash"):
                        v = c.get("content")
                        bash_out += len(v) if isinstance(v, str) else len(json.dumps(v))
    cost += WEIGHTS["output_tokens"] * sum(out_by_id[m] for m in seen if m in out_by_id)
    return ctxs, cost, date or "", kb, bash_out


def main():
    cutoff = parse_cutoff(sys.argv)
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    runs, skipped = [], 0
    for meta in glob.glob(os.path.join(config, "projects", "*", "*", "subagents", "*.meta.json")):
        try:
            with open(meta, encoding="utf-8", errors="replace") as fh:
                stage = json.load(fh).get("agentType", "")
            if not stage.startswith("bailiwick-"):
                continue
            ctxs, cost, date, kb, bash_out = read_run(meta[: -len(".meta.json")] + ".jsonl")
        except (OSError, ValueError):
            skipped += 1
            continue
        if ctxs:
            # <config>/projects/<project>/<session>/subagents/<run>.meta.json -> parent session
            session = os.path.basename(os.path.dirname(os.path.dirname(meta)))
            runs.append(dict(stage=stage, after=date >= cutoff, date=date, session=session,
                             turns=len(ctxs), first=ctxs[0],
                             peak=max(ctxs), total=sum(ctxs), cost=cost, kb=kb, bash=bash_out))

    def med(rs, key):
        return int(statistics.median(r[key] for r in rs))

    print(f"cutoff {cutoff}  ({len(runs)} stage runs" + (f", {skipped} unreadable skipped" if skipped else "") + ")\n")
    if not runs:
        return
    w = max(len(r["stage"]) for r in runs) + 2
    print(f"{'stage':{w}}{'when':>7}{'n':>4}{'turns':>7}{'start ctx':>11}{'peak ctx':>10}"
          f"{'tokens in':>12}{'cost-eq':>11}{'bash out':>10}{'KB touched':>12}")
    for stage in sorted({r["stage"] for r in runs}):
        for after in (False, True):
            rs = [r for r in runs if r["stage"] == stage and r["after"] == after]
            if not rs:
                continue
            print(f"{stage:{w}}{'after' if after else 'before':>7}{len(rs):>4}{med(rs, 'turns'):>7}"
                  f"{med(rs, 'first'):>11}{med(rs, 'peak'):>10}{med(rs, 'total'):>12}"
                  f"{med(rs, 'cost'):>11}{med(rs, 'bash'):>10}{sum(r['kb'] for r in rs):>7}/{len(rs)}")
    print("\nMedians per run. 'tokens in' = context tokens processed across all turns (mostly cache"
          "\nreads); 'cost-eq' = the same weighted by relative price (cache read 0.1x, cache write"
          "\n1.25x, output 5x) in plain-input-token equivalents. 'bash out' = characters of shell"
          "\noutput; 'KB touched' = runs that read the knowledge library by any tool.")
    print_totals(runs, w)


def print_totals(runs, w):
    """Total spend per period. Medians cannot show it: leading more work mostly adds runs."""
    periods = {}
    for after in (False, True):
        rs = [r for r in runs if r["after"] == after]
        if rs:
            periods["after" if after else "before"] = rs
    print("\nTotals per period (all stages). Periods differ in length, so compare the rates:")
    print(f"{'period':8}{'runs':>6}{'active days':>13}{'sessions':>10}{'cost-eq total':>15}"
          f"{'cost-eq/day':>13}{'cost-eq/session':>17}{'runs/day':>10}")
    for name, rs in periods.items():
        days = len({r["date"] for r in rs})
        sessions = len({r["session"] for r in rs})
        total = sum(r["cost"] for r in rs)
        print(f"{name:8}{len(rs):>6}{days:>13}{sessions:>10}{int(total):>15}"
              f"{int(total / days):>13}{int(total / sessions):>17}{len(rs) / days:>10.1f}")
    print(f"\nRuns per active day, by stage (where extra runs come from):")
    print(f"{'stage':{w}}" + "".join(f"{n:>9}" for n in periods))
    days = {n: len({r["date"] for r in rs}) for n, rs in periods.items()}
    for stage in sorted({r["stage"] for r in runs}):
        print(f"{stage:{w}}" + "".join(
            f"{sum(r['stage'] == stage for r in rs) / days[n]:>9.2f}" for n, rs in periods.items()))
    print("\n'active days' = days with at least one stage run; 'sessions' = parent sessions that"
          "\ndispatched stages (a rough per-task proxy: one session can hold several tasks).")


if __name__ == "__main__":
    main()
