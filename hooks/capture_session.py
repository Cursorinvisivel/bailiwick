#!/usr/bin/env python3
"""Enforced raw session capture for the bailiwick knowledge pipeline.

Invoked by the Stop and SessionEnd hooks of Claude Code AND Codex CLI (>= 0.147, which
added those events). Reads the hook JSON payload on stdin, and — when the session shows
substantive work — copies the session transcript into
<project>/.bailiwick-outputs/raw/<session_id>.jsonl and writes a small markdown header for
human/nag visibility. Both CLIs pass the same payload fields; only the transcript shape
differs, which the per-record dispatch below absorbs (see "Codex transcript vocabulary").

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

# ---- Codex transcript vocabulary ---------------------------------------------------------------
# Both CLIs hand this hook the SAME envelope (session_id / transcript_path / cwd / hook_event_name —
# verified against codex `stop.command.input` and `session-end.command.input`), so only the
# transcript SHAPE differs: Claude Code writes {"message": {"content": [{"type": "tool_use", ...}]}},
# Codex a rollout of {"type": "response_item"|"event_msg"|..., "payload": {...}}. Records are
# dispatched per line on that shape, so one hook covers both (and a resumed/mixed file cannot lie).
# Antigravity passes {"conversationId", "transcriptPath", "workspacePaths"} and writes
# step records {"step_index", "tool_calls": [{"name": "...", "args": {...}}]}.
# `exec`/`exec_command` are Codex's shell (code mode wraps the same call in a JS snippet);
# `apply_patch` is its file-mutating tool — the Edit/Write of MUTATING_TOOLS above.
CODEX_MUTATING_TOOLS = {"apply_patch"}
CODEX_EXEC_TOOLS = {"exec", "exec_command", "shell"}
ANTIGRAVITY_MUTATING_TOOLS = {"write_file", "edit_file"}
ANTIGRAVITY_READ_TOOLS = {"read_file", "view_file"}
# The command inside either shape: `"cmd": "..."` in the function-call arguments JSON, or the same
# key inside the `tools.exec_command({...})` JS of a code-mode call. Captured WITH its quotes so
# json.loads does the un-escaping (a code-mode input is doubly escaped).
CODEX_CMD_RE = re.compile(r'"cmd"\s*:\s*("(?:[^"\\]|\\.)*")')
# MCP reads appear in a rollout under the BARE tool name (`read_text_file`), not the
# `mcp__server__tool` form PreToolUse matches on — accept either.
CODEX_READ_TOOL_RE = re.compile(r"^(?:mcp__[a-z0-9-]+__)?read_")


def knowledge_ids(text):
    """Telemetry ids referenced by path in `text` (topics/patterns/context + clients)."""
    ids = set(KNOWLEDGE_RE.findall(text))
    ids.update("{}-{}".format(cid, stem) for cid, stem in CLIENT_KNOWLEDGE_RE.findall(text))
    return ids
# `applied` signal (ADR-004): a git commit in a Bash tool call marks that this session SHIPPED work.
# Combined with a mutation, it upgrades a loaded tidbit from "read" to "in play when work shipped".
COMMIT_RE = re.compile(r"\bgit\b[^\n]*\bcommit\b")

# Header schema. 2 = subagent transcripts are scanned too, so `/metrics` can tell captures that see
# subagent reads from older ones (whose cold counts undercount anything a stage agent read).
CAPTURE_SCHEMA = 2
# Claude Code writes each subagent's transcript BESIDE the main one, not inline:
#   <projects-dir>/<session_id>/subagents/agent-<id>.jsonl  (+ agent-<id>.meta.json)
# Nested agents (spawnDepth > 1) land in the same flat folder; the walk is recursive anyway. Without
# this, every knowledge read by a Memory Query, Lead stage, or fork was invisible to telemetry.
# Claude Code only: Codex and Antigravity subagent transcript locations are not yet verified.
SUBAGENT_GLOB = re.compile(r"^agent-[\w-]+\.jsonl$")


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


def _scan_command(cmd, st):
    """A shell command from EITHER flavor: read ops emit `loaded` ids, a git commit marks shipped."""
    if not cmd:
        return
    if BASH_READ_RE.search(cmd):
        st["loaded"].update(knowledge_ids(cmd))
    if COMMIT_RE.search(cmd):
        st["committed"] = True


def _scan_claude(rec, st):
    """Claude Code transcript record: tool calls live in message.content[] as `tool_use` blocks."""
    message = rec.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return
    for block in content:
        if not (isinstance(block, dict) and block.get("type") == "tool_use"):
            continue
        name = block.get("name", "")
        st["tool_calls"] += 1
        st["tools"].add(name)
        if name in MUTATING_TOOLS:
            st["mutating"] += 1
        # Derive `loaded` knowledge ids from genuine READ operations only
        # (never from a path merely appearing in a Write/Edit/other input).
        try:
            inp = block.get("input") or {}
            if name == "Read":
                st["loaded"].update(knowledge_ids(str(inp.get("file_path") or "")))
            elif MCP_FS_READ_RE.match(name):
                st["loaded"].update(knowledge_ids(json.dumps(inp)))
            elif name == "Bash":
                _scan_command(inp.get("command") or "", st)
        except Exception:
            pass


def _scan_codex(rec, st):
    """Codex rollout record: the same signals, carried by `payload` instead of `message`.

    `function_call` (name + `arguments` JSON string) and `custom_tool_call` (name + `input`, JS in
    code mode) are the two tool-call shapes; `patch_apply_end` is the event Codex emits when a patch
    actually lands, which is the only mutation trace left when the patch went through code mode.
    """
    payload = rec.get("payload")
    if not isinstance(payload, dict):
        return
    kind = payload.get("type")
    if kind == "patch_apply_end":
        if payload.get("success"):
            st["patch_events"] += 1
        return
    if kind not in ("function_call", "custom_tool_call"):
        return
    name = payload.get("name") or ""
    st["tool_calls"] += 1
    st["tools"].add(name)
    if name in CODEX_MUTATING_TOOLS:
        st["mutating"] += 1
        return  # the patch body is a diff, not a command — no read/commit signal in it
    raw = payload.get("arguments")
    if not isinstance(raw, str):
        raw = payload.get("input")
    if not isinstance(raw, str):
        return
    if name in CODEX_EXEC_TOOLS:
        for quoted in CODEX_CMD_RE.findall(raw):
            try:
                cmd = json.loads(quoted)
            except Exception:
                cmd = quoted[1:-1]  # un-escaping failed: the raw text still carries the signal
            _scan_command(cmd, st)
    elif CODEX_READ_TOOL_RE.match(name):
        st["loaded"].update(knowledge_ids(raw))


def _scan_antigravity(rec, st):
    """Antigravity transcript record: tool calls live in rec.tool_calls as [{name, args}]."""
    tool_calls = rec.get("tool_calls")
    if not isinstance(tool_calls, list):
        return
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        name = call.get("name", "")
        args = call.get("args") or {}
        st["tool_calls"] += 1
        st["tools"].add(name)
        if name in ANTIGRAVITY_MUTATING_TOOLS:
            st["mutating"] += 1
        if name == "run_command":
            _scan_command(args.get("CommandLine") or "", st)
        elif name in ANTIGRAVITY_READ_TOOLS or MCP_FS_READ_RE.match(name):
            path_str = str(args.get("Path") or args.get("file_path") or "")
            st["loaded"].update(knowledge_ids(path_str))


def _new_state():
    return {"tool_calls": 0, "mutating": 0, "patch_events": 0, "committed": False,
            "tools": set(), "loaded": set(), "agent": "claude"}


def _scan_file(path, st):
    """Scan one transcript into `st`, dispatching each record on its shape (Claude/Codex/agy)."""
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not isinstance(rec, dict):
                continue
            if isinstance(rec.get("payload"), dict) and "message" not in rec:
                st["agent"] = "codex"
                _scan_codex(rec, st)
            elif "tool_calls" in rec or "step_index" in rec or rec.get("source") in ("USER_INPUT", "PLANNER_RESPONSE", "MODEL", "SYSTEM"):
                st["agent"] = "antigravity"
                _scan_antigravity(rec, st)
            else:
                _scan_claude(rec, st)


def subagent_transcripts(transcript):
    """Sorted subagent transcript paths for a Claude Code session ([] when it spawned none)."""
    stem = os.path.splitext(os.path.basename(transcript))[0]
    root = os.path.join(os.path.dirname(transcript), stem, "subagents")
    found = []
    for dirpath, _dirs, files in os.walk(root):
        found.extend(os.path.join(dirpath, f) for f in files if SUBAGENT_GLOB.match(f))
    return sorted(found)


def include_subagents():
    """`capture.include_subagents` in .bailiwick-sync.json — default on."""
    capture = bw_common.sync_config().get("capture")
    if isinstance(capture, dict) and capture.get("include_subagents") is False:
        return False
    return True


def append_subagents(dest, paths):
    """Append each subagent's records to the copied capture, tagged the way older Claude Code wrote
    them inline (isSidechain: true + agentId), so the capture stays ONE .jsonl per session and
    backup, /curate, and /purge need no change. The caller copies the main transcript fresh first,
    so a repeated Stop never duplicates records. Returns the number of records appended."""
    count = 0
    with open(dest, "a", encoding="utf-8") as out:
        for path in paths:
            agent_id = os.path.basename(path)[len("agent-"):-len(".jsonl")]
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        try:
                            rec = json.loads(line)
                        except Exception:
                            continue
                        if not isinstance(rec, dict):
                            continue
                        rec["isSidechain"] = True
                        rec.setdefault("agentId", agent_id)
                        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        count += 1
            except Exception as e:  # one bad file never drops the others
                _health("warn", "subagent append failed for {}: {!r}".format(
                    os.path.basename(path), e)[:200])
    return count


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # Never block the harness on a malformed payload.
    if not isinstance(payload, dict):
        # Valid JSON that isn't an object ("[]", "3") passes the parse but has no .get() —
        # same never-block contract as above (guardrails.py guards this identically).
        return 0

    transcript = payload.get("transcript_path") or payload.get("transcriptPath")
    session_id = payload.get("session_id") or payload.get("conversationId") or "unknown-session"
    event = payload.get("hook_event_name") or payload.get("terminationReason") or ""
    project_dir = bw_common.resolve_project_dir(payload)

    if not transcript or not os.path.isfile(transcript):
        return 0

    seeded = is_bailiwick_repo(project_dir)
    shadow = is_shadow_repo(project_dir)
    if not (seeded or shadow):
        return 0  # Inert outside bailiwick-wired repos (seeded or shadow-activated).

    st = _new_state()
    try:
        _scan_file(transcript, st)
    except Exception as e:
        _health("error", "transcript read failed for {}: {!r}".format(session_id, e)[:200])
        return 0

    # Subagent transcripts (Claude Code). A Stop can fire while a background agent still runs; the
    # capture is rewritten on every Stop and at SessionEnd, so the last one sees finished agents.
    # An unreadable subagent file degrades to the main transcript with a health warn — never blocks.
    sub = _new_state()
    sub_count = 0
    sub_paths = subagent_transcripts(transcript) if st["agent"] == "claude" else []
    for path in sub_paths:
        try:
            _scan_file(path, sub)
            sub_count += 1
        except Exception as e:  # one bad file never hides the others
            _health("warn", "subagent scan failed for {} ({}): {!r}".format(
                session_id, os.path.basename(path), e)[:200])

    # Subagent work counts toward the session: a Lead that only dispatched an Implement stage
    # still shipped what that stage wrote.
    tool_calls = st["tool_calls"] + sub["tool_calls"]
    mutating = st["mutating"] + sub["mutating"]
    committed = st["committed"] or sub["committed"]
    tools_used = st["tools"] | sub["tools"]
    loaded_ids = st["loaded"]
    # Disjoint from `loaded`, so crediting both never counts one id twice for a session.
    loaded_via_subagents = sub["loaded"] - loaded_ids
    # Code-mode Codex applies a patch from INSIDE an `exec` call, so the only trace left is the
    # patch_apply_end event. Use it as a FLOOR, never an addition — an `apply_patch` tool call and
    # its patch_apply_end are the same edit counted from two sides.
    if not mutating:
        mutating = st["patch_events"]

    substantive = mutating > 0 or tool_calls >= MIN_TOOL_CALLS
    if not substantive:
        return 0  # Pure conversation / trivial read — nothing to curate.

    # `applied` (ADR-004): loaded tidbits get applied credit when this session SHIPPED work —
    # produced a file mutation and/or a git commit. Coarse by design (all co-loaded ids credited);
    # the semantic `used` tier at /curate disambiguates which one actually informed the output.
    applied_ids = sorted(loaded_ids | loaded_via_subagents) if (mutating > 0 or committed) else []

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
    inlined = 0
    if sub_paths and include_subagents():
        try:
            inlined = append_subagents(dest, sub_paths)
        except Exception as e:
            _health("warn", "subagent append failed for {}: {!r}".format(session_id, e)[:200])

    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    meta = os.path.join(raw_dir, session_id + ".md")
    try:
        with open(meta, "w", encoding="utf-8") as fh:
            fh.write("# Raw capture — {}\n\n".format(session_id))
            fh.write("- captured: {}\n".format(stamp))
            fh.write("- capture_schema: {}\n".format(CAPTURE_SCHEMA))
            fh.write("- event: {}\n".format(event))
            fh.write("- project_dir: {}\n".format(project_dir))
            fh.write("- mode: {}\n".format("seeded" if seeded else "shadow"))
            fh.write("- agent: {}\n".format(st["agent"]))
            if not seeded:
                fh.write("- origin_remote: {}\n".format(origin_remote(project_dir) or "(none)"))
            fh.write("- tool_calls: {} (mutating: {})\n".format(tool_calls, mutating))
            fh.write("- tools: {}\n".format(", ".join(sorted(tools_used)) or "none"))
            fh.write("- subagents: {} (records inlined: {})\n".format(sub_count, inlined))
            fh.write("- transcript: {}\n\n".format(os.path.basename(dest)))
            # Mechanical Retrieval Feedback — the `loaded` signal /curate Step 2 applies to telemetry
            # (load_count, last_loaded, and distinct_projects_used credited to this project). Derived
            # from the transcript, so it is emitted even when no agent wrote a session-output file.
            project_id = os.path.basename(os.path.normpath(project_dir)) or "unknown"
            fh.write("## Retrieval Feedback (auto-derived)\n")
            fh.write("- project: {}\n".format(project_id))
            fh.write("- loaded: [{}]\n".format(", ".join(sorted(loaded_ids))))
            # Read only by a subagent (Memory Query, Lead stages, forks). Credit like `loaded`.
            fh.write("- loaded_via_subagents: [{}]\n".format(", ".join(sorted(loaded_via_subagents))))
            # `applied` = loaded ids (both lists) credited because this session shipped (mutation and/or commit);
            # `committed` records whether a git commit ran. Consumed by /curate telemetry (ADR-004).
            fh.write("- applied: [{}]\n".format(", ".join(applied_ids)))
            fh.write("- committed: {}\n\n".format("true" if committed else "false"))
            fh.write("Pending curation. Run `/curate` to distill into the knowledge library (human-gated).\n")
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
