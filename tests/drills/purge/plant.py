#!/usr/bin/env python3
"""Plant the synthetic client `acme-drill` ("Acme Drill Industries", {org} token `acdr`, informal
abbreviation "ADI") on every surface /purge and purge_verify.sh name, plus the hard cases a scan can
miss. Every trace planted here is listed in answer_key.json; tests/test_drills.py proves the two agree.

    plant.py <sandbox-root>      (requires BAILIWICK=<root>/framework — checked by the guard)

All data is synthetic. KB content is committed in the sandbox clone so the history surfaces exist.
Two traces (T27, T28) go OUTSIDE the sandbox, into the drill's own Claude Code config dir
(guard.check_claude_home: never the real ~/.claude): a file-history/<session>/ copy and a history.jsonl
line, the Claude Code state a real purge can only list for the user (scored "pending user action").
Before planting, the residual sweep runs once over the seeded sandbox and is stored in the marker as
`sweep_baseline`: framework text that already matches a pattern (an unrelated "ADI") is not a residual.
"""
import base64
import hashlib
import json
import os
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import drillcommon as dc  # noqa: E402
import guard  # noqa: E402
import sandbox  # noqa: E402

B64_BLOB = base64.b64encode(b"cluster: acme-drill-gke-prd\nproject: acdr-prj-data-prd\n").decode()

CLIENT_MAP = """---
id: acme-drill-project-map
type: context
tags: [client, project-map, landing-zone]
confidence: medium
last_validated: 2026-10-01
supersedes: []
scope: client:acme-drill
---

# Acme Drill Industries — project map

Synthetic drill fixture (bailiwick purge drill). Not real data.

| Project | Purpose | Folder |
|---|---|---|
| acdr-prj-data-prd | data platform (prod) | folders/918273645501 |
| acdr-prj-net-hub | shared VPC host | folders/918273645502 |

- Billing account: 01DR1L-L0ACME-000000
- Change window: Tuesdays 06:00-08:00 UTC, approver: platform lead at ADI
- Terraform state bucket: gs://acdr-tfstate-prd
"""

RULE_TOPIC = """---
id: acme-drill-vpc-sc-rollout
type: topic
tags: [gcp, vpc-sc, security, rollout]
confidence: medium
last_validated: 2026-10-01
supersedes: []
scope: client:acme-drill
---

# VPC Service Controls rollout at Acme Drill Industries

## Context
While putting the acme_drill data platform (`acdr-prj-data-prd`) behind a VPC-SC perimeter, the first
enforced attempt broke the nightly Dataflow export.

## Rule (reusable)
Run every new VPC Service Controls perimeter in **dry-run mode for at least 14 days** and review the
dry-run violation logs (`protoPayload.metadata.dryRun=true`) before switching it to enforced. Add
ingress/egress rules for every flagged identity first; only then enforce.

## Pitfall
Perimeter changes take minutes to propagate; test after propagation, not immediately.

## Related
- [GCP IAM conventions](../patterns/gcp-iam-conventions.md)
"""

NAMING_EXAMPLE = """## Example from client work
`acdr-prj-data-prd` — the ACME-DRILL data platform project (prefix = `{org}` token, then type,
workload, env).

"""

LABELS_NOTE = """> Seen in practice: ADI's FinOps team rejects any project without `cost-center` — enforce the
> label in CI policy, not in code review.

"""

DEF_BUILD = """# Document build spec (synthetic drill fixture)
client: Acme Drill Industries
id: acme-drill
documents:
  - hld-landing-zone
"""

AUDIT_LINES = [
    "2026-10-18T10:02:11\task\t/home/op/code/acme-drill-landing-zone\tgit push origin main",
    "2026-10-18T10:05:40\tdeny\t/home/op/code/acme-drill-landing-zone\tgsutil rm -r gs://acdr-tfstate-prd/old",
    "2026-10-19T08:00:00\task\t/home/op/code/other-repo\tgit commit -m 'chore: bump'",
]
HEALTH_LOCAL = [
    {"ts": "2026-10-18T10:06:00", "machine": "drillbox", "component": "capture_backup", "event": "info",
     "detail": "pushed drillbox/landing-zone-1a2b3c4d (acme-drill) ok"},
    {"ts": "2026-10-19T08:00:00", "machine": "drillbox", "component": "session_start", "event": "info",
     "detail": "index injected"},
]
HEALTH_REMOTE = [
    {"ts": "2026-10-17T12:00:00", "machine": "otherbox", "component": "capture_backup", "event": "info",
     "detail": "pushed otherbox/landing-zone-1a2b3c4d for Acme Drill Industries"},
]


LEARN_CAPTURE = """# Learn capture — landing-zone

- captured: 2026-10-18T10:15:00
- mode: shadow
- origin_remote: git@github.com:acme-drill/landing-zone.git
- commit: 0000000000000000000000000000000000000000
- agent: claude

## Candidates for Promotion

### VPC-SC dry-run window (likely NEW, scope client:acme-drill)
The acdr data perimeter ran in dry-run for 14 days before enforcement at Acme Drill Industries.
Provenance: vpcsc.tf, docs/adr-004-vpc-sc.md
"""


def _turns_acme(extra_result=""):
    return [
        {"user": "Tighten the VPC-SC perimeter for the acme-drill data platform (acdr-prj-data-prd)."},
        {"tool": "Bash", "input": {"command": "gcloud access-context-manager perimeters describe acdr_data"},
         "result": "name: accessPolicies/1234/servicePerimeters/acdr_data\nstatus: dry-run" + extra_result},
        {"tool": "Read", "input": {"file_path": "/home/op/code/acme-drill-landing-zone/vpcsc.tf"},
         "result": "resource \"google_access_context_manager_service_perimeter\" \"acdr_data\" {}"},
        {"assistant": "Perimeter stays in dry-run for 14 days for Acme Drill Industries, then enforce."},
    ]


def _turns_other(topic):
    return [
        {"user": "Fix the {} CI lint warnings.".format(topic)},
        {"tool": "Bash", "input": {"command": "make lint"}, "result": "2 warnings fixed"},
        {"tool": "Bash", "input": {"command": "git status --short"}, "result": " M main.tf"},
        {"assistant": "Lint is clean."},
    ]


def insert_before(path, anchor, text):
    with open(path, encoding="utf-8") as fh:
        body = fh.read()
    i = body.find("\n" + anchor)
    body = body[:i + 1] + text + body[i + 1:] if i >= 0 else body.rstrip("\n") + "\n\n" + text
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


def append(path, text):
    with open(path, encoding="utf-8") as fh:
        body = fh.read()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body.rstrip("\n") + "\n" + text)


def write(path, text, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode, encoding="utf-8" if "b" not in mode else None) as fh:
        fh.write(text)


def _load_key():
    with open(os.path.join(HERE, "answer_key.json"), encoding="utf-8") as fh:
        return json.load(fh)


def sweep_baseline(root, key):
    """The residual sweep over the seeded, not-yet-planted sandbox (see the module docstring)."""
    named = dc.compile_patterns(key["patterns"])
    return dc.sweep(root, key["sweep_roots"], named + dc.b64_patterns(key["b64_literals"]), named,
                    exclude=key["sweep_exclude"])


def plant_claude_state(marker, session_id):
    """T27/T28 in the drill config dir. Returns the absolute paths written (file-history only)."""
    ch = guard.check_claude_home(marker["claude_home"])
    fh_dir = os.path.join(ch, "file-history", session_id)
    guard.check_claude_home(fh_dir)  # still clear of the real ~/.claude once joined
    name = hashlib.sha256(b"topics/acme-drill-vpc-sc-rollout.md").hexdigest()[:16] + "@v1"
    write(os.path.join(fh_dir, name), RULE_TOPIC)
    line = {"display": "/drill-purge acme-drill (planted drill trace T28)", "pastedContents": {},
            "timestamp": int(time.time() * 1000), "project": marker["project"], "sessionId": session_id}
    write(os.path.join(ch, "history.jsonl"), json.dumps(line) + "\n", mode="a")
    return [os.path.join(fh_dir, name)]


def plant(root):
    marker = guard.check_root(root)
    root = marker["root"]
    fw = guard.check_knowledge(root)
    project = guard.check_target(root, marker["project"])
    home = guard.check_target(root, marker["bailiwick_home"])
    kb = os.path.join(fw, "knowledge")
    hooks_dir = os.path.join(root, "git-hooks")
    baseline = sweep_baseline(root, _load_key())

    # --- committed KB surfaces -------------------------------------------------------------------
    write(os.path.join(kb, "clients", "acme-drill", "project-map.md"), CLIENT_MAP)
    write(os.path.join(kb, "topics", "acme-drill-vpc-sc-rollout.md"), RULE_TOPIC)
    with open(os.path.join(kb, "INDEX.md"), encoding="utf-8") as fh:
        index = fh.read()
    topics_at = index.index("## topics")
    sep = index.index("|---|---|---|\n", topics_at) + len("|---|---|---|\n")
    row = ("| acme-drill-vpc-sc-rollout.md | gcp, vpc-sc, security, acme-drill | VPC-SC rollout lessons from "
           "the Acme Drill Industries engagement |\n")
    index = index[:sep] + row + index[sep:]
    clients_at = index.index("## clients")
    nxt = index.index("\n## ", clients_at + 3)
    index = index[:nxt] + "\n- [acme-drill](clients/acme-drill/project-map.md) — Acme Drill Industries project map\n" + index[nxt:]
    write(os.path.join(kb, "INDEX.md"), index)
    append(os.path.join(kb, "patterns", "gcp-iam-conventions.md"),
           "- [VPC-SC rollout (acme-drill)](../topics/acme-drill-vpc-sc-rollout.md)\n")
    insert_before(os.path.join(kb, "patterns", "caf-naming-taxonomy.md"), "## Related", NAMING_EXAMPLE)
    insert_before(os.path.join(kb, "patterns", "gcp-labels-required.md"), "## Related", LABELS_NOTE)
    reg = os.path.join(kb, "context", "org-shorthands.md")
    with open(reg, encoding="utf-8") as fh:
        text = fh.read()
    wombat = text.index("| `wombat` |")
    eol = text.index("\n", wombat) + 1
    text = text[:eol] + ("| `acme-drill` | `acdr` | Acme Drill Industries (synthetic drill client) | "
                         "`{org}` token tightened (inner hyphen) |\n") + text[eol:]
    write(reg, text)
    tel_path = os.path.join(kb, ".telemetry.json")
    tel = sandbox.read_json(tel_path)
    row0 = {"load_count": 3, "applied_count": 2, "useful_count": 2, "source_sessions": 2,
            "last_loaded": "2026-10-18", "last_applied": "2026-10-18", "last_useful": "2026-10-18",
            "open_contradictions": 0}
    tel["entries"]["acme-drill-project-map"] = dict(row0, distinct_projects_used=["acme-drill-landing-zone"])
    tel["entries"]["acme-drill-vpc-sc-rollout"] = dict(row0, distinct_projects_used=["acme-drill-landing-zone", "drill-ops"])
    first = sorted(k for k in tel["entries"] if not k.startswith("acme-drill"))[0]
    tel["entries"][first]["distinct_projects_used"] = sorted(
        set(tel["entries"][first].get("distinct_projects_used") or []) | {"acme-drill-landing-zone"})
    with open(tel_path, "w", encoding="utf-8") as fh:
        json.dump(tel, fh, indent=2)
        fh.write("\n")
    write(os.path.join(fw, "definitions", "clients", "acme-drill", "build.yaml"), DEF_BUILD)
    os.makedirs(os.path.join(fw, "definitions", "clients", "acme-drill"), exist_ok=True)
    with open(os.path.join(fw, "definitions", "clients", "acme-drill", "logo.png"), "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + b"\0" * 32 + b"tEXtauthor\0acme-drill" + b"\0" * 32)
    sandbox.git(["add", "-A", "knowledge", "definitions"], fw)
    sandbox.git(["commit", "-q", "-m", "knowledge: add acme-drill landing-zone notes (Acme Drill Industries engagement)"],
                fw, hooks_dir=hooks_dir)
    planted_sha = sandbox.git(["rev-parse", "HEAD"], fw).stdout.strip()

    # --- untracked / machine-local surfaces ------------------------------------------------------
    files = []
    files += dc.write_capture(os.path.join(project, ".bailiwick-outputs", "raw"), "drill0001-acme",
                              project, "seeded", _turns_acme())
    files += dc.write_capture(os.path.join(home, "captures", "landing-zone-1a2b3c4d", "raw"), "drill0002-acme",
                              "/home/op/code/landing-zone", "shadow",
                              _turns_acme("\n# kubeconfig (base64): " + B64_BLOB),
                              origin="git@github.com:acme-drill/landing-zone.git")
    files += dc.write_capture(os.path.join(home, "captures", "landing-zone-5e6f7a8b", "raw"), "drill0005-globex",
                              "/home/op/code/landing-zone", "shadow", _turns_other("landing-zone"),
                              origin="git@github.com:globex/landing-zone.git")
    files += dc.write_capture(os.path.join(home, "captures", "other-repo-9f8e7d6c", "raw"), "drill0003-other",
                              "/home/op/code/other-repo", "shadow", _turns_other("other-repo"),
                              origin="git@github.com:example-org/other-repo.git")
    files += dc.write_capture(os.path.join(fw, ".bailiwick-inbox", "raw", "drillbox", "landing-zone-1a2b3c4d"),
                              "drill0004-acme", "/home/op/code/landing-zone", "shadow", _turns_acme(),
                              origin="git@github.com:acme-drill/landing-zone.git")
    learn = os.path.join(home, "captures", "landing-zone-1a2b3c4d", "learn-20261018-101500.md")
    write(learn, LEARN_CAPTURE)  # T29: /learn's shadow staging dir (curate's manual gather, not raw/)
    files.append(learn)
    write(os.path.join(home, "guardrail-audit.log"), "\n".join(AUDIT_LINES) + "\n")
    write(os.path.join(home, "health", "drillbox.jsonl"), "".join(json.dumps(h) + "\n" for h in HEALTH_LOCAL))
    write(os.path.join(home, "health", "remote", "otherbox.jsonl"), "".join(json.dumps(h) + "\n" for h in HEALTH_REMOTE))
    files += [os.path.join(home, "guardrail-audit.log"), os.path.join(home, "health", "drillbox.jsonl"),
              os.path.join(home, "health", "remote", "otherbox.jsonl")]

    claude_session = str(uuid.uuid5(uuid.NAMESPACE_URL, "bailiwick-drill:" + root))
    claude_files = plant_claude_state(marker, claude_session)

    sandbox.update_marker(root, planted_sha=planted_sha, planted_epoch=time.time(),
                          planted_files=sorted(os.path.relpath(f, root) for f in files),
                          planted_claude_session=claude_session, planted_claude_files=claude_files,
                          sweep_baseline=baseline)
    return planted_sha


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: plant.py <sandbox-root>")
    try:
        print(plant(sys.argv[1]))
    except guard.Refused as e:
        print("drill guard REFUSED: {}".format(e), file=sys.stderr)
        sys.exit(guard.REFUSED)
