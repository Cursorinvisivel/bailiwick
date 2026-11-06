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

# ---- /purge sessions are never captured ---------------------------------------------------------
# A session that ran /purge holds the very client identifiers it removes, but its capture would be
# stamped with the origin of the repo it RAN in — so /purge's origin-based sweep never finds it and a
# later /curate re-ingests it. Only an actual INVOCATION counts, never a mention (prose, a Grep for
# "purge", a Read of the skill file, another skill's args). Shapes verified against real transcripts:
#   Claude Code, model-invoked:  assistant tool_use {"name": "Skill", "input": {"skill": "purge"}}
#     (exact name: bailiwick installs it as the bare user skill `purge`; a plugin's `x:purge` is not it)
#   Claude Code, user-typed:     a user-role TEXT (never tool_result) opening with the command header
#     "<command-message>purge</command-message>\n<command-name>/purge</command-name>\n<command-args>…"
#   Codex, user-typed:           a user `message` whose input_text starts with `$bailiwick-purge`, and
#     the skill body Codex then injects as a user message opening "<skill>\n<name>bailiwick-purge</name>"
#   Positive sentinel (any CLI): /purge's first action is `bash "$BAILIWICK/hooks/mark_purge_session.sh"`.
#     Matched as an INVOCATION only — a Claude Code `Bash` tool_use, or a Codex exec/shell call, whose
#     WHOLE command is that script (optionally behind `bash `/`sh `), reached via `$BAILIWICK` /
#     `${BAILIWICK}` or an absolute path. A Read/grep/cat of it, prose, arguments, or a longer command
#     line is a mention. Covers what name detection cannot see (a Codex skill chosen implicitly).
#     An ABSOLUTE path counts only when it resolves (os.path.realpath) to THIS hook's own sibling
#     mark_purge_session.sh — a nonexistent or foreign path is a mention, so an agent cannot opt a
#     session out of capture by naming any file that merely ends in /hooks/mark_purge_session.sh.
#     The `$BAILIWICK` / `${BAILIWICK}` literal forms still match unresolved: the transcript records
#     the command text, not the shell's expansion, so the hook cannot know what the variable held.
#     Because the sentinel deletes this session's captures and tombstones their backup blobs, the
#     guardrail (guardrails.py ASK_IMPACT) asks the user to confirm it — it is never agent-silent. The
#     one prefix accepted is the exact env assignment `BAILIWICK_BREAK_GLASS=1 ` (the Codex override
#     spelling), so a break-glassed run still marks; any other prefix is a mention.
#     The sentinel counts in the MAIN transcript only: no /purge subagent legitimately runs it
#     (security-review-local has no Bash), so a prompt-injected subagent cannot opt the session out.
#     The sentinel counts only once it has RUN SUCCESSFULLY: the call is paired with its result
#     (Claude Code: the tool_result with the same tool_use_id, not is_error; Codex: the
#     function_call_output with the same call_id, exit code 0), and that result must carry the
#     script's fixed success line (MARK_OK_LINE). A declined ask, a Codex deny, an error exit, or a
#     call with no result yet leaves the session captured — declining the ask stops the effect.
#   Trust tiers. Only a USER-originated trigger may delete anything:
#     trusted   — a user-typed `/purge` header (not in an `isMeta` record: that is harness-injected),
#                 a user-typed Codex `$bailiwick-purge`, and the
#                 sentinel confirmed in the MAIN transcript by a Claude Code / Codex function call:
#                 full skip (write nothing, retract earlier captures, tombstone their backup blobs).
#     unconfirmed — an agent `Skill(skill=…)` tool_use, a Codex injected `<skill><name>` body alone,
#                 a code-mode `exec` sentinel (its output is script-controlled), and ANY detector in a
#                 subagent transcript: the capture is only HELD local (the `purge_detection: error`
#                 header line, so capture_backup.sh never pushes it); nothing is deleted or retracted.
#     Both tiers in one session: the union is reported and the trusted tier wins.
#   Every skip/hold names its detector in the health line (skill / slash command / sentinel / config —
#   `config` = a name added via capture.skip_skills; held ones suffixed ` (unconfirmed)`), never the
#   session, repo, or any client name.
DEFAULT_SKIP_SKILLS = ("purge",)
_MARK_TAIL = r"/hooks/mark_purge_session\.sh"
_MARK_ROOT = r"(?:\$BAILIWICK|\$\{BAILIWICK\})"
MARK_PURGE_RE = re.compile(
    r"(?:BAILIWICK_BREAK_GLASS=1[ \t]+)?(?:(?:bash|sh)[ \t]+)?(?:"
    r'"(?P<dq>(?:' + _MARK_ROOT + r'|/[^"`$\\\n]*?)' + _MARK_TAIL + r')"'        # "…/hooks/mark…"
    r"|'(?P<sq>/[^'\n]*?" + _MARK_TAIL + r")'"                                    # '/abs/…' (no expansion)
    r"|(?P<uq>(?:" + _MARK_ROOT + r"|/[^\s\"'`$\\;&|<>()]*?)" + _MARK_TAIL + r")" +  # unquoted
    r")[ \t\r\n]*\Z")
# Codex exec tools whose arguments carry the command: `exec`/`exec_command` (`cmd`), the older `shell`
# (`command` argv list), `shell_command` (`command` string). Only that ONE field is read for the
# sentinel (_codex_commands): any other key in the arguments is not what the tool executed.
CODEX_SENTINEL_TOOLS = CODEX_EXEC_TOOLS | {"shell_command"}
_SHELLS = ("bash", "sh", "zsh")
# The shell a sentinel `-c`/`-lc` may be unwrapped from (and the `shell` an exec_command may name):
# the bare name (PATH lookup, as the tool resolves it) or the system dirs, EXACTLY. Any other path —
# /tmp/evil/bash, /usr/local/bin/bash, ./sh — is a program that could print the success line itself.
# Deliberately narrow: /opt/homebrew/bin, /usr/local/bin and /run/current-system/sw/bin shells are
# real but often user-writable, so a genuine sentinel run through one is NOT credited — that fails
# safe (the session is captured, never skipped). The bare name stays trusted although PATH resolves
# it: the Codex guardrail already denies the exact sentinel shapes, so this check only narrows
# forgery by an agent-chosen non-system shell binary; it is not the sentinel's primary gate.
_TRUSTED_SHELLS = frozenset(_SHELLS) | frozenset(
    d + s for d in ("/bin/", "/usr/bin/") for s in _SHELLS)
OWN_MARK_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mark_purge_session.sh")
# The first stdout line mark_purge_session.sh prints on success (exit 0) — and only then. Keep the
# two in step (tests/test_capture_session.py pins it against the script's real output).
MARK_OK_LINE = "[bailiwick] purge session marked: capture_session.py will not capture this session"
# Codex exec-result exit codes, text shapes: `shell_command` freeform ("Exit code: N") and unified
# exec ("Process exited with code N"). The structured `shell` JSON and code-mode results carry an
# `exit_code` key instead (see _codex_result_units).
_CODEX_EXIT_RE = re.compile(r"^(?:Exit code:|Process exited with code)\s*(-?\d+)\s*$", re.MULTILINE)


def is_mark_purge_command(cmd):
    """True when `cmd` is exactly an invocation of hooks/mark_purge_session.sh (see above): the
    `$BAILIWICK` forms as written, an absolute path only when it resolves to this hook's own script."""
    if not isinstance(cmd, str):
        return False
    m = MARK_PURGE_RE.match(cmd.lstrip())
    if not m:
        return False
    path = m.group("dq") or m.group("sq") or m.group("uq")
    if path.startswith("$"):
        return True
    try:
        return os.path.realpath(path) == os.path.realpath(OWN_MARK_SCRIPT)
    except (OSError, ValueError):
        return False


def _unique_pairs(pairs):
    """json object_pairs_hook: a repeated key (at any depth) is a forgery shape — which copy the tool
    ran is parser-defined — so the whole arguments object is rejected."""
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise ValueError("duplicate key")
        obj[k] = v
    return obj


def _codex_commands(raw, name, kind="function_call"):
    """The command a Codex tool call EXECUTES. A `function_call` yields only the one field its tool
    runs — exec_command/exec: `cmd` (str); shell_command: `command` (str); shell: `command` (argv) —
    so a stray or nested `cmd`/`command` key (which the guardrail never sees, since it is handed only
    the executed command) cannot pass for the sentinel. Non-JSON, a duplicate key or a wrong type
    yields nothing. A shell is trusted only in a _TRUSTED_SHELLS form: exec_command's `shell` must be
    absent/null or trusted, and a `shell` argv is unwrapped (`<sh> -c|-lc <line>`) only when argv[0]
    is trusted — otherwise its quoted join, which never matches the sentinel, is returned.
    Only a code-mode `custom_tool_call` (JS input, never more than a hold) is regex-scanned."""
    import shlex
    cmds = []
    if kind == "custom_tool_call":
        for quoted in CODEX_CMD_RE.findall(raw):
            try:
                cmds.append(json.loads(quoted))
            except Exception:
                pass
        return cmds
    try:
        args = json.loads(raw, object_pairs_hook=_unique_pairs)
    except Exception:
        return cmds
    if not isinstance(args, dict):
        return cmds
    if name in ("exec_command", "exec"):
        shell = args.get("shell")
        if isinstance(args.get("cmd"), str) and (
                shell is None or (isinstance(shell, str) and shell in _TRUSTED_SHELLS)):
            cmds.append(args["cmd"])
        return cmds
    command = args.get("command")
    if name == "shell_command":
        if isinstance(command, str):
            cmds.append(command)
        return cmds
    if name != "shell":
        return cmds
    if isinstance(command, list) and command and all(isinstance(a, str) for a in command):
        if (len(command) == 3 and command[0] in _TRUSTED_SHELLS
                and command[1] in ("-c", "-lc")):
            cmds.append(command[2])  # ["bash", "-lc", "<command line>"]
        else:
            cmds.append(" ".join(shlex.quote(a) for a in command))  # a bare argv: no expansion
    return cmds
_NEVER = re.compile(r"(?!)")
_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
# The skill names are configurable (`capture.skip_skills` in .bailiwick-sync.json, see skip_skills()).
# Matching stays EXACT per name — never a prefix/suffix: a wrong skip loses data.


def _skip_patterns(names):
    """(claude_command_re, codex_re) matching an invocation of exactly one of `names`."""
    if not names:
        return _NEVER, _NEVER
    alt = "|".join(re.escape(n) for n in names)
    claude = re.compile(
        r"^\s*(?:<command-message>[^<]*</command-message>\s*)?<command-name>/(?P<cmd>" + alt + r")</command-name>")
    codex = re.compile(r"^\s*(?:\$bailiwick-(?P<cmd>" + alt + r")(?:\s|$)"
                       r"|<skill>\s*<name>bailiwick-(?P<skill>" + alt + r")</name>)")
    return claude, codex



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


def _user_texts(content):
    """Plain text a user-role message carries: the string itself, or its `text`/`input_text` blocks.
    tool_result blocks are excluded on purpose — they are tool OUTPUT (a Read of a transcript, a
    grep hit), which can quote a command header without anything having been invoked."""
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    return [b["text"] for b in content
            if isinstance(b, dict) and b.get("type") in ("text", "input_text")
            and isinstance(b.get("text"), str)]


def skip_skills():
    """Exact skill names whose sessions are never captured: "purge" always, plus any names listed in
    `capture.skip_skills` in .bailiwick-sync.json (the list adds names; it can never remove
    "purge", so a config slip cannot re-enable capture of purge sessions). Anything but a list of
    valid name strings falls back to the default with a health warning — a bad config must never
    widen the skip (data loss). main() calls this ONCE per run, so a bad config warns once."""
    capture = bw_common.sync_config().get("capture")
    raw = capture.get("skip_skills") if isinstance(capture, dict) else None
    if raw is None:
        return DEFAULT_SKIP_SKILLS
    if (isinstance(raw, list) and all(isinstance(n, str) and _SKILL_NAME_RE.match(n) for n in raw)):
        return tuple(dict.fromkeys(DEFAULT_SKIP_SKILLS + tuple(raw)))
    _health("warn", "capture.skip_skills is not a list of skill names — using the default")
    return DEFAULT_SKIP_SKILLS


def _mark(st, source, name=None, trusted=True):
    """Record a purge detection and its detector label (content-free: the name is never stored).
    Trusted (user-originated, main transcript) sets st["purge"]: full skip + retraction. Anything
    else — an agent-originated trigger, or any detector in a subagent transcript — only sets
    st["held"]: the capture stays local, nothing is deleted (trust tiers: see above)."""
    label = "config" if name is not None and name not in DEFAULT_SKIP_SKILLS else source
    if trusted and not st.get("subagent"):
        st["purge"] = True
        st["purge_src"].add(label)
    else:
        st["held"] = True
        st["held_src"].add(label + " (unconfirmed)")


def _mark_by_name(st, regex, texts):
    """Mark when a user text is a typed command (`cmd` group, trusted) or an injected skill body
    (`skill`, unconfirmed: Codex injects it for an implicitly chosen skill too)."""
    for t in texts:
        m = regex.match(t)
        if m:
            groups = m.groupdict()
            if groups.get("skill"):
                _mark(st, "skill", groups["skill"], trusted=False)
            else:
                _mark(st, "slash command", groups.get("cmd"))


def _result_texts(content):
    """Every text string a tool result carries: a plain string, or the `text` of its blocks."""
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)]
    return []


def _codex_result_units(output):
    """(exit_code, text) pairs a Codex exec/shell result reports — one per command it ran. Shapes:
    the structured `shell` JSON {"output", "metadata": {"exit_code"}}, a code-mode result
    {"exit_code", "output"} (also wrapped as {"status", "value": {...}}), and the freeform
    "Exit code: N" / unified-exec "Process exited with code N" text. No exit code -> no unit."""
    units = []

    def walk(obj, depth=0):
        if depth > 3 or not isinstance(obj, dict):
            return
        meta = obj.get("metadata")
        code = obj.get("exit_code", meta.get("exit_code") if isinstance(meta, dict) else None)
        if isinstance(code, int) and not isinstance(code, bool) and isinstance(obj.get("output"), str):
            units.append((code, obj["output"]))
        walk(obj.get("value"), depth + 1)

    for text in _result_texts(output):
        try:
            obj = json.loads(text)
        except Exception:
            obj = None
        if isinstance(obj, dict):
            walk(obj)
            continue
        codes = _CODEX_EXIT_RE.findall(text)
        if len(codes) == 1:  # one command's text result; several codes cannot be told apart
            units.append((int(codes[0]), text))
    return units


def _mark_ok(text):
    """True when `text` holds the sentinel's success line as a whole line of its own."""
    return isinstance(text, str) and any(l.strip() == MARK_OK_LINE for l in text.splitlines())


def _detect_purge(rec, st):
    """Set st["purge"] (trusted) or st["held"] (unconfirmed) when this record is an INVOCATION of a
    skip skill (shapes and trust tiers: see above). A sentinel call is only remembered as pending;
    its paired result, arriving later in the transcript, decides whether it counts. The Bash/exec
    sentinel is ignored in subagent transcripts (st["subagent"]): see above."""
    names, claude_re, codex_re = st["skip"]
    sentinel_ok = not st.get("subagent")
    pending = st["sentinel_pending"]
    payload = rec.get("payload")
    if isinstance(payload, dict) and "message" not in rec:  # Codex rollout record
        kind = payload.get("type")
        if kind == "message" and payload.get("role") == "user":
            _mark_by_name(st, codex_re, _user_texts(payload.get("content")))
        elif (sentinel_ok and kind in ("function_call", "custom_tool_call")
              and payload.get("name") in CODEX_SENTINEL_TOOLS):
            raw = payload.get("arguments")
            if not isinstance(raw, str):
                raw = payload.get("input")
            call_id = payload.get("call_id")
            if (isinstance(call_id, str) and call_id and isinstance(raw, str)
                    and any(is_mark_purge_command(c)
                            for c in _codex_commands(raw, payload.get("name"), kind))):
                pending[call_id] = "codex-code" if kind == "custom_tool_call" else "codex"
        elif (kind in ("function_call_output", "custom_tool_call_output")
              and payload.get("call_id") in pending
              and pending[payload.get("call_id")].startswith("codex")):
            how = pending.pop(payload["call_id"])
            if any(code == 0 and _mark_ok(text) for code, text in _codex_result_units(payload.get("output"))):
                # Code mode: the JS cell controls what its result says — never more than a hold.
                _mark(st, "sentinel", trusted=(how == "codex"))
        return
    message = rec.get("message")
    if not isinstance(message, dict):
        return
    content = message.get("content")
    if message.get("role") == "user":
        if rec.get("isMeta") is not True:  # isMeta = harness-injected text, never a typed command
            _mark_by_name(st, claude_re, _user_texts(content))
        if pending and isinstance(content, list):
            for block in content:
                if not (isinstance(block, dict) and block.get("type") == "tool_result"
                        and pending.get(block.get("tool_use_id")) == "claude"):
                    continue
                pending.pop(block["tool_use_id"])
                if block.get("is_error") is not True and any(
                        _mark_ok(t) for t in _result_texts(block.get("content"))):
                    _mark(st, "sentinel")
    elif isinstance(content, list):
        for block in content:
            if not (isinstance(block, dict) and block.get("type") == "tool_use"
                    and isinstance(block.get("input"), dict)):
                continue
            if block.get("name") == "Skill" and block["input"].get("skill") in names:
                _mark(st, "skill", block["input"]["skill"], trusted=False)  # agent-originated
            elif (sentinel_ok and block.get("name") == "Bash"
                  and isinstance(block.get("id"), str) and block["id"]
                  and is_mark_purge_command(block["input"].get("command"))):
                pending[block["id"]] = "claude"


def _new_state(names=None, subagent=False):
    """Fresh scan state. Pass `names` (main() resolves skip_skills() once for both states);
    `subagent=True` for the subagent-transcript state (the sentinel does not count there, and any
    other detector there only holds the capture)."""
    if names is None:
        names = skip_skills()
    return {"skip": (frozenset(names),) + _skip_patterns(names),
            "tool_calls": 0, "mutating": 0, "patch_events": 0, "committed": False,
            "tools": set(), "loaded": set(), "agent": "claude", "subagent": subagent,
            "purge": False, "purge_src": set(), "purge_error": False,
            "held": False, "held_src": set(), "sentinel_pending": {}}


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
            # A detection fault must never cost a capture: flag it, keep scanning, capture anyway.
            try:
                _detect_purge(rec, st)
            except Exception:
                st["purge_error"] = True
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
                _health("warn", "subagent append failed for {}: {}".format(
                    os.path.basename(path), type(e).__name__)[:200])
    return count


FALLBACK_SESSION_ID = "unknown-session"


def safe_session_id(session_id):
    """A session id usable as a file stem inside the staging dir: a non-empty string that is not
    `.`/`..` and holds no path separator or NUL. One check for the write AND the delete path, so a
    hostile id can never steer either outside the staging dir."""
    return (isinstance(session_id, str) and session_id not in ("", ".", "..")
            and "/" not in session_id and "\0" not in session_id
            and os.sep not in session_id and not (os.altsep and os.altsep in session_id))


def drop_session_capture(project_dir, session_id):
    """Delete whatever an earlier Stop of this session staged — seeded AND shadow locations, since
    the mode is decided per run. Returns (sorted removed extensions, failure count)."""
    if not safe_session_id(session_id):
        return [], 0  # never let a hostile id steer a delete outside the staging dir
    dirs = [os.path.join(project_dir, ".bailiwick-outputs", "raw"),
            os.path.join(bw_home(), "captures", repo_key(project_dir), "raw")]
    removed, failed = set(), 0
    for d in dirs:
        for ext in (".jsonl", ".md"):
            path = os.path.join(d, session_id + ext)
            if not os.path.lexists(path):
                continue
            try:
                os.remove(path)
                removed.add(ext)
            except Exception:
                failed += 1
    return sorted(removed), failed


# ---- pending-retraction ledger -------------------------------------------------------------------
# $BAILIWICK_HOME/backup-retract.pending: one sha256(<blob relpath>) per line, NOTHING else. A
# retraction that cannot finish now (mirror busy, offline, push rejected) stays listed, and every
# later `capture_backup.sh push` retries it. No plaintext relpath is stored anywhere: the backup
# side finds the blob by hashing its own mirror tree (`git ls-files`), and the `.purged` tombstone
# IS the hash — so the ledger can neither leak an identifier nor need a second, secret file.
# The ledger is written ONLY under the `<ledger>.lock` mkdir lock it shares with capture_backup.sh's
# rewrite (pending_done). When the lock stays busy, the new hashes go to a SPOOL file instead —
# `<ledger>.spool-<time_ns>-<pid>-<n>`, same content rules, renamed into place whole — because an
# unlocked append could land between the rewrite's read and its `mv` and be lost. The pending set is
# always ledger ∪ spools (here and in capture_backup.sh); whoever next holds the lock folds them in.
# Accepted residual: anything able to write $BAILIWICK_HOME (an agent included) can list a hash in
# the ledger or a spool, and the guardrail-exempt `capture_backup.sh push` then retracts that blob
# with no sentinel ask. Impact: this machine's backup branch drops the blob from its tip (the
# ciphertext stays in git history) and tombstones it, so push never backs that capture up again —
# its local source capture is untouched, but it loses off-machine durability and cross-machine pull.
RETRACT_LEDGER = "backup-retract.pending"
_SPOOL_PREFIX = RETRACT_LEDGER + ".spool-"
_LEDGER_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def ledger_path():
    return os.path.join(bw_home(), RETRACT_LEDGER)


def _spool_paths():
    """The spool files next to the ledger (never the in-flight temp names, which do not match)."""
    home = os.path.dirname(ledger_path())
    try:
        names = os.listdir(home)
    except OSError:
        return []
    return sorted(os.path.join(home, n) for n in names
                  if n.startswith(_SPOOL_PREFIX) and os.path.isfile(os.path.join(home, n)))


def _read_hashes(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return {ln.strip() for ln in fh if _LEDGER_HASH_RE.match(ln.strip())}
    except Exception:
        return set()


def pending_retractions():
    """Hashes waiting in the ledger or any spool file (empty when none exists or none is readable)."""
    found = _read_hashes(ledger_path())
    for spool in _spool_paths():
        found |= _read_hashes(spool)
    return sorted(found)


def _write_spool(hashes):
    """Spool `hashes` to a fresh `<ledger>.spool-<time_ns>-<pid>-<n>` (0600): written under a temp name
    that readers ignore, then renamed, so no reader ever folds (and deletes) a half-written spool."""
    import time
    home = os.path.dirname(ledger_path())
    for attempt in range(100):
        stem = "{}{}-{}-{}".format(_SPOOL_PREFIX, time.time_ns(), os.getpid(), attempt)
        final = os.path.join(home, stem)
        tmp = os.path.join(home, "." + stem + ".tmp")
        if os.path.exists(final):
            continue
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write("".join(h + "\n" for h in hashes))
            os.chmod(tmp, 0o600)
            os.rename(tmp, final)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return final
    raise FileExistsError("no free retraction spool name")


def _ledger_lock(path, wait_s=0.3):
    """mkdir lock shared with capture_backup.sh. Held for milliseconds on both sides; a holder older
    than 60 s is stale. Returns False when still busy — the caller then spools (never appends to the
    ledger unlocked: that could race a concurrent rewrite and be lost)."""
    import time
    deadline = time.time() + wait_s
    while True:
        try:
            os.mkdir(path)
            return True
        except FileExistsError:
            try:
                if time.time() - os.stat(path).st_mtime > 60:
                    os.rmdir(path)
                    continue
            except OSError:
                pass
            if time.time() >= deadline:
                return False
            time.sleep(0.05)
        except OSError:
            return False


def add_retractions(hashes):
    """Record the hashes not already pending (mode 0600). Under the lock: append them — plus any
    spooled hashes, whose spool files are then removed — to the ledger. Lock busy: spool them
    (_write_spool). Returns the pending count (ledger ∪ spools)."""
    path = ledger_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lock = path + ".lock"
    locked = _ledger_lock(lock)
    try:
        if not locked:
            listed = set(pending_retractions())
            new = [h for h in dict.fromkeys(hashes) if h not in listed]
            if new:
                _write_spool(new)
            return len(listed | set(new))
        in_ledger = _read_hashes(path)
        spools = _spool_paths()  # exactly these are folded and removed; a later spool stays
        spooled = set()
        for spool in spools:
            spooled |= _read_hashes(spool)
        new = [h for h in dict.fromkeys(list(hashes) + sorted(spooled)) if h not in in_ledger]
        if new:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as fh:
                fh.write("".join(h + "\n" for h in new))
        if os.path.exists(path):
            os.chmod(path, 0o600)
        for spool in spools:  # only after their hashes are in the ledger
            try:
                os.unlink(spool)
            except OSError:
                pass
        return len(in_ledger | set(new))
    finally:
        if locked:
            try:
                os.rmdir(lock)
            except OSError:
                pass


def request_backup_purge(project_dir, session_id):
    """Retract this session's blobs from the encrypted backup — an earlier Stop may have pushed them.

    Gated like `capture_backup.sh push`: `capture_backup.enabled` AND `confidentiality_ack`. Records
    sha256 of both blob relpaths (<machine token>/<repo_key>/<session_id>.{jsonl,md}.gpg — exactly
    what push writes, machine read from the config as that script reads it, "unknown" when unset)
    in the ledger, then runs `capture_backup.sh retract` (no argument, so no identifier in argv or
    `ps`), which tombstones and removes them and drops each entry once origin has it.
    Detached in its own session with stdio closed — the SessionEnd budget (~1.5 s) cannot hold
    fetch+push and an inherited pipe keeps the hook "running". BW_BACKUP_SYNC=1 runs it in the
    foreground (tests, manual runs). Returns the pending count, or None when not requested."""
    import hashlib
    cfg = bw_common.sync_config()
    backup = cfg.get("capture_backup")
    if not (isinstance(backup, dict) and backup.get("enabled") and backup.get("confidentiality_ack")):
        return None
    mtoken = bw_common.machine_token(str(cfg.get("machine") or "unknown"))
    key = repo_key(project_dir)
    rels = ["{}/{}/{}{}.gpg".format(mtoken, key, session_id, ext) for ext in (".jsonl", ".md")]
    pending = add_retractions([hashlib.sha256(r.encode("utf-8")).hexdigest() for r in rels])
    import subprocess
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "capture_backup.sh")
    proc = subprocess.Popen(
        ["bash", script, "retract"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, close_fds=True,
    )
    if os.environ.get("BW_BACKUP_SYNC"):
        proc.wait(timeout=600)
    return pending


def skip_purge_session(project_dir, session_id, event="", sources=()):
    """A /purge session: write nothing, retract what earlier Stops wrote, log a content-free line
    (no session id, no path, no repo key — the shard is aggregated fleet-wide) naming only the
    detector(s) in `sources` (skill / slash command / sentinel / config).

    The fallback id "unknown-session" names no particular session, so it never retracts (it could
    hit another session's capture). The info line is written when something was retracted or at
    SessionEnd — not on every Stop of a long /purge session."""
    removed, failed, requested = [], 0, False
    if session_id != FALLBACK_SESSION_ID:
        try:
            removed, failed = drop_session_capture(project_dir, session_id)
        except Exception as e:
            failed += 1
            _health("error", "purge session: retracting its earlier capture failed ({})".format(type(e).__name__))
    if failed:
        _health("error", "purge session: {} earlier capture file(s) could not be removed — "
                         "delete them before /purge preflight".format(failed))
    if removed or failed:
        try:
            requested = request_backup_purge(project_dir, session_id) is not None
        except Exception as e:
            _health("warn", "purge session: backup retraction not requested ({})".format(type(e).__name__))
    if removed or failed or event == "SessionEnd":
        _health("info", "capture skipped: purge session (detected by: {}; earlier capture files "
                        "removed: {}; backup retraction requested: {}; backup retractions pending: {})"
                .format(", ".join(sorted(sources)) or "unknown", len(removed),
                        "yes" if requested else "no", len(pending_retractions())))
    return 0


DRILL_MARKER = ".drill-sandbox"


def _inside(path, root):
    """True when realpath(path) is `root` itself or below it (`root` already a realpath)."""
    p = os.path.realpath(path)
    return p == root or p.startswith(root.rstrip(os.sep) + os.sep)


def drill_sandbox(project_dir):
    """realpath of the drill sandbox that applies to this run, or None.

    BW_DRILL_SANDBOX counts only when the directory holds its `.drill-sandbox` marker AND the
    session's project resolves inside it. A stale or leaked variable (a shell that kept the export
    after the drill, a sandbox already removed, a real project opened from that shell) would
    otherwise make every capture a silent no-op — data loss. Ignored with a content-free warn
    (no path: the shard is aggregated fleet-wide)."""
    sandbox = os.environ.get("BW_DRILL_SANDBOX")
    if not sandbox:
        return None
    root = os.path.realpath(sandbox)
    if os.path.isfile(os.path.join(root, DRILL_MARKER)) and _inside(project_dir, root):
        return root
    _health("warn", "BW_DRILL_SANDBOX set but no drill sandbox applies (no .drill-sandbox marker, or "
                    "the project is outside it) — variable ignored, capture proceeds")
    return None


def drill_foreign(project_dir):
    """True when a drill sandbox applies (see drill_sandbox) and THIS script is not the sandbox's
    own framework copy — the real clone's global hook firing inside a drill must not act on it."""
    root = drill_sandbox(project_dir)
    if root is None:
        return False
    own_root = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    return own_root != os.path.realpath(os.path.join(root, "framework"))


def write_atomic(path, text):
    """Write `text` to `path` via `<path>.tmp` + os.replace (same directory, so the rename is atomic):
    a concurrent reader — capture_backup.sh push's `grep -qx` for the hold line — sees the old file
    or the whole new one, never a truncated one. The temp file is removed if the write fails."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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
    # After the wiring gate: a set BW_DRILL_SANDBOX must not make every session in every (even
    # unwired) repo write a health line.
    if drill_foreign(project_dir):
        _health("info", "drill sandbox active and this is not its framework copy — capture skipped")
        return 0
    if not safe_session_id(session_id):
        # Content-free: the id itself is the hostile part. No write, no retraction.
        _health("error", "capture refused: session id is not a safe file name")
        return 0

    names = skip_skills()  # once per run: a bad config warns once, not per state
    st = _new_state(names)
    try:
        _scan_file(transcript, st)
    except Exception as e:
        _health("error", "transcript read failed for {}: {}".format(session_id, type(e).__name__))
        return 0

    # Subagent transcripts (Claude Code). A Stop can fire while a background agent still runs; the
    # capture is rewritten on every Stop and at SessionEnd, so the last one sees finished agents.
    # An unreadable subagent file degrades to the main transcript with a health warn — never blocks.
    sub = _new_state(names, subagent=True)
    sub_count = 0
    sub_paths = subagent_transcripts(transcript) if st["agent"] == "claude" else []
    for path in sub_paths:
        try:
            _scan_file(path, sub)
            sub_count += 1
        except Exception as e:  # one bad file never hides the others
            _health("warn", "subagent scan failed for {} ({}): {}".format(
                session_id, os.path.basename(path), type(e).__name__)[:200])

    # A /purge session is never captured — checked BEFORE the substantive gate so a later Stop still
    # retracts an earlier capture. Only a TRUSTED trigger gets here (see the trust tiers above); a
    # subagent's detections are never trusted. Both tiers present: the union is reported, trusted wins.
    if st["purge"] or sub["purge"]:
        return skip_purge_session(project_dir, session_id, event, st["purge_src"] | sub["purge_src"]
                                  | st["held_src"] | sub["held_src"])
    # A detection fault never costs the capture (data-loss prevention), but the capture may be a
    # purge session the detector failed to see: keep it LOCAL. The header line below makes
    # capture_backup.sh push hold both files until a human reviews it and removes the line.
    # An UNCONFIRMED trigger (agent Skill call, injected skill body, code-mode sentinel, anything in
    # a subagent) takes the same hold path: kept local, never deleted, never retracted.
    detection_error = st["purge_error"] or sub["purge_error"]
    if detection_error:
        _health("warn", "purge detection failed on a record — captured locally only, backup held "
                        "until the 'purge_detection: error' header line is removed")
    if st["held"] or sub["held"]:
        _health("warn", "purge detection unconfirmed (detected by: {}) — captured locally only, "
                        "nothing deleted, backup held until the 'purge_detection: error' header line "
                        "is removed".format(", ".join(sorted(st["held_src"] | sub["held_src"]))))
        detection_error = True

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
    meta = os.path.join(raw_dir, session_id + ".md")
    try:
        os.makedirs(raw_dir, exist_ok=True)
        if detection_error:
            # Hold marker FIRST: a push running in parallel must never see the .jsonl without it.
            write_atomic(meta, "# Raw capture — {}\n\n- purge_detection: error\n".format(session_id))
        dest = os.path.join(raw_dir, session_id + ".jsonl")
        shutil.copyfile(transcript, dest)
    except Exception as e:
        _health("error", "capture copy failed for {}: {}".format(session_id, type(e).__name__))
        return 0
    inlined = 0
    if sub_paths and include_subagents():
        try:
            inlined = append_subagents(dest, sub_paths)
        except Exception as e:
            _health("warn", "subagent append failed for {}: {}".format(session_id, type(e).__name__))

    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        out = []
        out.append("# Raw capture — {}\n\n".format(session_id))
        if detection_error:
            # Exact line capture_backup.sh push matches (`grep -x`) to keep this capture local.
            out.append("- purge_detection: error\n")
        out.append("- captured: {}\n".format(stamp))
        out.append("- capture_schema: {}\n".format(CAPTURE_SCHEMA))
        out.append("- event: {}\n".format(event))
        out.append("- project_dir: {}\n".format(project_dir))
        out.append("- mode: {}\n".format("seeded" if seeded else "shadow"))
        out.append("- agent: {}\n".format(st["agent"]))
        if not seeded:
            out.append("- origin_remote: {}\n".format(origin_remote(project_dir) or "(none)"))
        out.append("- tool_calls: {} (mutating: {})\n".format(tool_calls, mutating))
        out.append("- tools: {}\n".format(", ".join(sorted(tools_used)) or "none"))
        out.append("- subagents: {} (records inlined: {})\n".format(sub_count, inlined))
        out.append("- transcript: {}\n\n".format(os.path.basename(dest)))
        # Mechanical Retrieval Feedback — the `loaded` signal /curate Step 2 applies to telemetry
        # (load_count, last_loaded, and distinct_projects_used credited to this project). Derived
        # from the transcript, so it is emitted even when no agent wrote a session-output file.
        project_id = os.path.basename(os.path.normpath(project_dir)) or "unknown"
        out.append("## Retrieval Feedback (auto-derived)\n")
        out.append("- project: {}\n".format(project_id))
        out.append("- loaded: [{}]\n".format(", ".join(sorted(loaded_ids))))
        # Read only by a subagent (Memory Query, Lead stages, forks). Credit like `loaded`.
        out.append("- loaded_via_subagents: [{}]\n".format(", ".join(sorted(loaded_via_subagents))))
        # `applied` = loaded ids (both lists) credited because this session shipped (mutation and/or commit);
        # `committed` records whether a git commit ran. Consumed by /curate telemetry (ADR-004).
        out.append("- applied: [{}]\n".format(", ".join(applied_ids)))
        out.append("- committed: {}\n\n".format("true" if committed else "false"))
        out.append("Pending curation. Run `/curate` to distill into the knowledge library (human-gated).\n")
        write_atomic(meta, "".join(out))
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
