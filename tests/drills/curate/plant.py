#!/usr/bin/env python3
"""Stage the /curate drill inputs: an existing KB topic the captures duplicate (committed), and
synthetic raw captures (fixtures/sessions.json) in the seeded staging dir of the fake project.

    plant.py <sandbox-root> [--small]     (requires BAILIWICK=<root>/framework — checked by the guard)

Step 2a's delegation threshold: more than 2 captures, or one over ~200 KB. Every arm stages the SAME
two captures (same count), so the arms differ only where intended:
  default (large)  one capture padded past 200 KB with realistic no-knowledge turns -> 2a delegates
                   (arms A = new skill, B = baseline, D = new skill with 2a forced off)
  --small          the same two captures, unpadded -> below the threshold, inline (arm C)
C differs from A only in input size; with two captures the count leg of the threshold never fires.
Same answer key in every arm.
"""
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import drillcommon as dc  # noqa: E402
import guard  # noqa: E402
import sandbox  # noqa: E402

FIX = os.path.join(HERE, "fixtures")
PAD_TARGET = 230 * 1024  # comfortably over the ~200 KB threshold
DUP_ID = "terraform-state-lock-recovery"


def pad_turn(i):
    """One realistic no-knowledge turn: a long no-op plan."""
    body = "\n".join(
        '  # data.google_compute_subnetwork.sn_{i}_{j} will be read during apply\n'
        '  <= data "google_compute_subnetwork" "sn_{i}_{j}" {{\n'
        '      + id        = (known after apply)\n'
        '      + name      = "snet-shared-{j:02d}"\n'
        '      + region    = "europe-west1"\n'
        '    }}'.format(i=i, j=j) for j in range(24))
    return {"tool": "Bash", "input": {"command": "terraform plan -target=module.net_{} -no-color".format(i)},
            "result": body + "\n\nNo changes. Your infrastructure matches the configuration."}


def padded(turns):
    out, i = list(turns), 0
    while len(json.dumps(out)) < PAD_TARGET:
        out.insert(1 + (i % max(1, len(turns) - 1)), pad_turn(i))  # interleave, keep the opening question first
        i += 1
    return out


def plant(root, small=False):
    marker = guard.check_root(root)
    root = marker["root"]
    fw = guard.check_knowledge(root)
    project = guard.check_target(root, marker["project"])
    guard.check_target(root, marker["bailiwick_home"])
    kb = os.path.join(fw, "knowledge")

    shutil.copyfile(os.path.join(FIX, DUP_ID + ".md"), os.path.join(kb, "topics", DUP_ID + ".md"))
    idx_path = os.path.join(kb, "INDEX.md")
    with open(idx_path, encoding="utf-8") as fh:
        index = fh.read()
    at = index.index("|---|---|---|\n", index.index("## topics")) + len("|---|---|---|\n")
    index = index[:at] + ("| {}.md | terraform, state, gcs, lock, pitfall | Recovering from a stale GCS "
                          "state lock (force-unlock) |\n".format(DUP_ID)) + index[at:]
    with open(idx_path, "w", encoding="utf-8") as fh:
        fh.write(index)
    tel_path = os.path.join(kb, ".telemetry.json")
    tel = sandbox.read_json(tel_path)
    tel["entries"][DUP_ID] = {"load_count": 2, "applied_count": 1, "useful_count": 1, "source_sessions": 1,
                              "last_loaded": "2026-09-15", "last_applied": "2026-09-15",
                              "last_useful": "2026-09-15", "open_contradictions": 0,
                              "distinct_projects_used": ["drill-ops"]}
    with open(tel_path, "w", encoding="utf-8") as fh:
        json.dump(tel, fh, indent=2)
        fh.write("\n")
    sandbox.git(["add", "-A", "knowledge"], fw)
    sandbox.git(["commit", "-q", "-m", "knowledge: add {} topic".format(DUP_ID)], fw,
                hooks_dir=os.path.join(root, "git-hooks"))
    planted_sha = sandbox.git(["rev-parse", "HEAD"], fw).stdout.strip()

    with open(os.path.join(FIX, "sessions.json"), encoding="utf-8") as fh:
        sessions = json.load(fh)["sessions"]
    raw = os.path.join(project, ".bailiwick-outputs", "raw")
    files, sizes = [], {}
    for s in sessions:
        turns = padded(s["turns"]) if (s.get("pad") and not small) else s["turns"]
        written = dc.write_capture(raw, s["id"], project, "seeded", turns)
        files += written
        sizes[s["id"]] = os.path.getsize(written[0])

    sandbox.update_marker(root, planted_sha=planted_sha, planted_epoch=time.time(), small=small,
                          capture_sizes=sizes, kb_snapshot=sandbox.snapshot(fw),
                          planted_files=sorted(os.path.relpath(f, root) for f in files))
    return sizes


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--small"]
    if len(args) != 1:
        sys.exit("usage: plant.py <sandbox-root> [--small]")
    try:
        print(json.dumps(plant(args[0], "--small" in sys.argv[1:])))
    except guard.Refused as e:
        print("drill guard REFUSED: {}".format(e), file=sys.stderr)
        sys.exit(guard.REFUSED)
