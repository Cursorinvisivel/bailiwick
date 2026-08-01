#!/usr/bin/env python3
"""Enforced raw session capture for the bailiwick knowledge pipeline.

Invoked by the Stop and SessionEnd hooks. Reads the hook JSON payload on stdin,
and — when the session shows substantive work — copies the session transcript
into <project>/.bailiwick-outputs/raw/<session_id>.jsonl and writes a small markdown
header for human/nag visibility.

Raw captures are gitignored and never committed. Promotion into the curated
knowledge library happens only via /curate, under a human gate. This script
performs NO intelligence and NO promotion — it only guarantees nothing is lost.
"""
import datetime
import functools
import json
import os
import re
import shutil
import sys

# File-mutating tools: their presence alone marks a session worth capturing.
MUTATING_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Research-only sessions still matter once they cross this many tool calls.
MIN_TOOL_CALLS = 3
# Mechanical Retrieval Feedback: which curated knowledge files this session actually READ.
# This is the ENFORCED emission of the `loaded` signal: it no longer depends on an agent
# self-reporting a `## Retrieval Feedback` block.
# Tightened (BACKLOG §4 / ADR-004 follow-up): a path *mention* in an arbitrary tool input — e.g.
# Write/Edit of a doc that quotes the path — is NOT a load. Only genuine read operations count:
#   - the Read tool (file_path input)
#   - MCP filesystem read tools (read_file / read_text_file / read_multiple_files / …), under
#     either the seeded-mode server name `filesystem` or the shadow-mode `bailiwick-filesystem`
#   - Bash, only when the command actually reads content (cat/head/tail/less/more/grep/rg/sed/awk)
# id = filename stem for topics/patterns/context; clients/<cid>/<stem>.md carries id <cid>-<stem>
# (per the observed frontmatter convention, e.g. clients/acme/project-map.md → acme-project-map).
KNOWLEDGE_RE = re.compile(r"knowledge/(?:topics|patterns|context)/([a-z0-9][a-z0-9-]*)\.md")
CLIENT_KNOWLEDGE_RE = re.compile(r"knowledge/clients/([a-z0-9][a-z0-9-]*)/([a-z0-9][a-z0-9-]*)\.md")
MCP_FS_READ_RE = re.compile(r"^mcp__(?:bailiwick-)?filesystem__read_")
BASH_READ_RE = re.compile(r"\b(cat|head|tail|less|more|grep|rg|sed|awk)\b")


def knowledge_ids(text):
    """Telemetry ids referenced by path in `text` (topics/patterns/context + clients)."""
    ids = set(KNOWLEDGE_RE.findall(text))
    ids.update("{}-{}".format(cid, stem) for cid, stem in CLIENT_KNOWLEDGE_RE.findall(text))
    return ids
# `applied` signal (ADR-004): a git commit in a Bash tool call marks that this session SHIPPED work.
# Combined with a mutation, it upgrades a loaded tidbit from "read" to "in play when work shipped".
COMMIT_RE = re.compile(r"\bgit\b[^\n]*\bcommit\b")


# Self-gating, shadow gate, home resolution, and health logging live in the shared
# hooks/bw_common.py substrate (one implementation for this hook and guardrails.py).
# Re-exported by name here because bash callers and the tests address them via this module.
from bw_common import bw_home, is_bailiwick_repo, is_shadow_repo  # noqa: F401
import bw_common


def _health(event, detail):
    """Health line for this component (shared writer — see bw_common.health)."""
    bw_common.health("capture_session", event, detail)


def repo_key(project_dir):
    """Stable, collision-resistant key for central capture staging (FRAMEWORK.md §6).

    Readable basename + a short hash of the git remote URL (stable across clones and machines) or,
    when there is no remote, the repo's realpath. Two different repos that share a basename
    (`infra`, `api`, ...) therefore never collide on one staging dir. This is the single source of
    truth for the key: the writer (this file), the SessionStart pending-capture nag, and
    capture_backup.sh all call it, so all three always agree.
    """
    import hashlib
    remote = origin_remote(project_dir)
    if remote:
        # Prefix from the remote's repo name + hash of the full remote: same remote -> same key,
        # regardless of the local clone path or dir name.
        name = re.sub(r"\.git$", "", remote.rstrip("/").split("/")[-1].split(":")[-1]) or "repo"
        src = remote
    else:
        # No remote: fall back to the realpath so two different repos sharing a basename don't collide.
        name = os.path.basename(os.path.normpath(project_dir)) or "repo"
        src = os.path.realpath(project_dir)
    base = re.sub(r"[^A-Za-z0-9._-]", "-", name)
    return "{}-{}".format(base, hashlib.sha256(src.encode("utf-8", "ignore")).hexdigest()[:8])


@functools.lru_cache(maxsize=8)
def origin_remote(project_dir):
    """Best-effort git remote for provenance stamping (scope routing happens at /curate)."""
    try:
        import subprocess
        out = subprocess.run(
            ["git", "-C", project_dir, "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, timeout=3,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # Never block the harness on a malformed payload.
    if not isinstance(payload, dict):
        # Valid JSON that isn't an object ("[]", "3") passes the parse but has no .get() —
        # same never-block contract as above (guardrails.py guards this identically).
        return 0

    transcript = payload.get("transcript_path")
    session_id = payload.get("session_id") or "unknown-session"
    event = payload.get("hook_event_name", "")
    project_dir = bw_common.resolve_project_dir(payload)

    if not transcript or not os.path.isfile(transcript):
        return 0

    seeded = is_bailiwick_repo(project_dir)
    shadow = is_shadow_repo(project_dir)
    if not (seeded or shadow):
        return 0  # Inert outside bailiwick-wired repos (seeded or shadow-activated).

    tool_calls = 0
    mutating = 0
    committed = False
    tools_used = set()
    loaded_ids = set()
    try:
        with open(transcript, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                content = (rec.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name", "")
                        tool_calls += 1
                        tools_used.add(name)
                        if name in MUTATING_TOOLS:
                            mutating += 1
                        # Derive `loaded` knowledge ids from genuine READ operations only
                        # (never from a path merely appearing in a Write/Edit/other input).
                        try:
                            inp = block.get("input") or {}
                            if name == "Read":
                                loaded_ids.update(knowledge_ids(str(inp.get("file_path") or "")))
                            elif MCP_FS_READ_RE.match(name):
                                loaded_ids.update(knowledge_ids(json.dumps(inp)))
                            elif name == "Bash":
                                cmd = inp.get("command") or ""
                                if BASH_READ_RE.search(cmd):
                                    loaded_ids.update(knowledge_ids(cmd))
                                # `committed`: a git commit in a Bash call means work shipped.
                                if COMMIT_RE.search(cmd):
                                    committed = True
                        except Exception:
                            pass
    except Exception as e:
        _health("error", "transcript read failed for {}: {!r}".format(session_id, e)[:200])
        return 0

    substantive = mutating > 0 or tool_calls >= MIN_TOOL_CALLS
    if not substantive:
        return 0  # Pure conversation / trivial read — nothing to curate.

    # `applied` (ADR-004): loaded tidbits get applied credit when this session SHIPPED work —
    # produced a file mutation and/or a git commit. Coarse by design (all co-loaded ids credited);
    # the semantic `used` tier at /curate disambiguates which one actually informed the output.
    applied_ids = sorted(loaded_ids) if (mutating > 0 or committed) else []

    # Seeded repos stage in-repo; shadow-only repos stage centrally, keyed by origin repo, so the
    # target repo tree stays untouched (FRAMEWORK.md §7.1). Seeded wins if a repo is somehow both.
    if seeded:
        raw_dir = os.path.join(project_dir, ".bailiwick-outputs", "raw")
    else:
        raw_dir = os.path.join(bw_home(), "captures", repo_key(project_dir), "raw")
    try:
        os.makedirs(raw_dir, exist_ok=True)
        dest = os.path.join(raw_dir, session_id + ".jsonl")
        shutil.copyfile(transcript, dest)
    except Exception as e:
        _health("error", "capture copy failed for {}: {!r}".format(session_id, e)[:200])
        return 0

    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    meta = os.path.join(raw_dir, session_id + ".md")
    try:
        with open(meta, "w", encoding="utf-8") as fh:
            fh.write("# Raw capture — {}\n\n".format(session_id))
            fh.write("- captured: {}\n".format(stamp))
            fh.write("- event: {}\n".format(event))
            fh.write("- project_dir: {}\n".format(project_dir))
            fh.write("- mode: {}\n".format("seeded" if seeded else "shadow"))
            if not seeded:
                fh.write("- origin_remote: {}\n".format(origin_remote(project_dir) or "(none)"))
            fh.write("- tool_calls: {} (mutating: {})\n".format(tool_calls, mutating))
            fh.write("- tools: {}\n".format(", ".join(sorted(tools_used)) or "none"))
            fh.write("- transcript: {}\n\n".format(os.path.basename(dest)))
            # Mechanical Retrieval Feedback — the `loaded` signal /curate Step 2 applies to telemetry
            # (load_count, last_loaded, and distinct_projects_used credited to this project). Derived
            # from the transcript, so it is emitted even when no agent wrote a session-output file.
            project_id = os.path.basename(os.path.normpath(project_dir)) or "unknown"
            fh.write("## Retrieval Feedback (auto-derived)\n")
            fh.write("- project: {}\n".format(project_id))
            fh.write("- loaded: [{}]\n".format(", ".join(sorted(loaded_ids))))
            # `applied` = loaded ids credited because this session shipped (mutation and/or commit);
            # `committed` records whether a git commit ran. Consumed by /curate telemetry (ADR-004).
            fh.write("- applied: [{}]\n".format(", ".join(applied_ids)))
            fh.write("- committed: {}\n\n".format("true" if committed else "false"))
            fh.write("Pending curation. Run `/curate` to distill into the knowledge library (human-gated).\n")
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
