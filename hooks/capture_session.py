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
#   - MCP filesystem read tools (read_file / read_text_file / read_multiple_files / …)
#   - Bash, only when the command actually reads content (cat/head/tail/less/more/grep/rg/sed/awk)
# id = filename stem for topics/patterns/context; clients/<cid>/<stem>.md carries id <cid>-<stem>
# (per the observed frontmatter convention, e.g. clients/acme/project-map.md → acme-project-map).
KNOWLEDGE_RE = re.compile(r"knowledge/(?:topics|patterns|context)/([a-z0-9][a-z0-9-]*)\.md")
CLIENT_KNOWLEDGE_RE = re.compile(r"knowledge/clients/([a-z0-9][a-z0-9-]*)/([a-z0-9][a-z0-9-]*)\.md")
MCP_FS_READ_RE = re.compile(r"^mcp__filesystem__read_")
BASH_READ_RE = re.compile(r"\b(cat|head|tail|less|more|grep|rg|sed|awk)\b")


def knowledge_ids(text):
    """Telemetry ids referenced by path in `text` (topics/patterns/context + clients)."""
    ids = set(KNOWLEDGE_RE.findall(text))
    ids.update("{}-{}".format(cid, stem) for cid, stem in CLIENT_KNOWLEDGE_RE.findall(text))
    return ids
# `applied` signal (ADR-004): a git commit in a Bash tool call marks that this session SHIPPED work.
# Combined with a mutation, it upgrades a loaded tidbit from "read" to "in play when work shipped".
COMMIT_RE = re.compile(r"\bgit\b[^\n]*\bcommit\b")


def is_bailiwick_repo(project_dir):
    """Self-gating guard: only act in bailiwick-wired repos.

    The hooks are installed once at user level (~/.claude/settings.json) and fire
    in every project. This keeps them inert in unrelated repos: a wired project carries
    Bailiwick marker ($BAILIWICK) in a framework complement file — the team's own
    shared CLAUDE.md/AGENTS.md are never touched.
    """
    for name in (
        ".bailiwick.local.md",
        "CLAUDE.local.md",
        ".github/instructions/bailiwick.instructions.md",
    ):
        try:
            with open(os.path.join(project_dir, name), "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
            if "BAILIWICK" in text:
                return True
        except Exception:
            continue
    return False


def bw_home():
    """Per-machine global-state root for shadow mode (allowlist + central captures)."""
    return os.environ.get("BAILIWICK_HOME") or os.path.join(os.path.expanduser("~"), ".bailiwick")


def _health(event, detail):
    """Append a framework-health line to this machine's per-source shard (best-effort, never
    raises). Aggregated fleet-wide by /metrics; transported by capture_backup.sh (encrypted)."""
    try:
        import socket
        machine = ""
        try:
            bailiwick_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
                "machine": machine, "component": "capture_session", "event": event,
                "detail": str(detail)[:300]}) + "\n")
    except Exception:
        pass


def is_shadow_repo(project_dir):
    """Shadow activation — no in-repo marker (FRAMEWORK.md §7.1). True when
    BAILIWICK_SHADOW=1 (per-shell) or this repo root is listed in
    ~/.bailiwick/allowlist (one absolute path per line; # comments)."""
    if os.environ.get("BAILIWICK_SHADOW") == "1":
        return True
    try:
        here = os.path.realpath(project_dir)
        with open(os.path.join(bw_home(), "allowlist"), "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                entry = line.split("#", 1)[0].strip().rstrip("/")
                if entry and os.path.realpath(entry) == here:
                    return True
    except Exception:
        pass
    return False


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

    transcript = payload.get("transcript_path")
    session_id = payload.get("session_id") or "unknown-session"
    event = payload.get("hook_event_name", "")
    project_dir = (
        os.environ.get("CLAUDE_PROJECT_DIR")
        or payload.get("cwd")
        or os.getcwd()
    )

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
