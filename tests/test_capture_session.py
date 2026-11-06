"""Contract tests for hooks/capture_session.py — gating, keying, and the capture itself.

The capture hook fires in EVERY project (installed once at user level), so the load-bearing
behavior is as much about staying inert in unrelated repos as about capturing in wired ones.
"""
import json
import os
import subprocess
import sys

import pytest

HOOKS = os.path.join(os.path.dirname(__file__), "..", "hooks")
sys.path.insert(0, HOOKS)
import capture_session  # noqa: E402


# ---- gating ------------------------------------------------------------------------------------

def test_unwired_repo_is_inert(tmp_path):
    assert not capture_session.is_bailiwick_repo(str(tmp_path))


def test_seeded_marker_wires_a_repo(tmp_path):
    (tmp_path / "CLAUDE.local.md").write_text("uses $BAILIWICK framework\n")
    assert capture_session.is_bailiwick_repo(str(tmp_path))


def test_marker_without_token_does_not_wire(tmp_path):
    (tmp_path / "CLAUDE.local.md").write_text("just a local note\n")
    assert not capture_session.is_bailiwick_repo(str(tmp_path))


def test_shadow_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("BAILIWICK_SHADOW", "1")
    assert capture_session.is_shadow_repo(str(tmp_path))


def test_shadow_allowlist(tmp_path, monkeypatch):
    monkeypatch.delenv("BAILIWICK_SHADOW", raising=False)
    home = tmp_path / "bw-home"
    home.mkdir()
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setenv("BAILIWICK_HOME", str(home))
    (home / "allowlist").write_text("# comment\n{}\n".format(proj))
    assert capture_session.is_shadow_repo(str(proj))
    assert not capture_session.is_shadow_repo(str(tmp_path))


# ---- repo_key: stable + collision-resistant ----------------------------------------------------

def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def test_repo_key_same_remote_same_key_across_clones(tmp_path):
    a, b = tmp_path / "clone-a", tmp_path / "dir-named-differently"
    for d in (a, b):
        d.mkdir()
        _git(d, "init", "-q")
        _git(d, "remote", "add", "origin", "git@host:Owner/thing.git")
    assert capture_session.repo_key(str(a)) == capture_session.repo_key(str(b))


def test_repo_key_same_basename_different_repos_never_collide(tmp_path):
    a, b = tmp_path / "x" / "infra", tmp_path / "y" / "infra"
    for d in (a, b):
        d.mkdir(parents=True)
    assert capture_session.repo_key(str(a)) != capture_session.repo_key(str(b))


# ---- the capture itself (invoked exactly as the harness invokes it) ----------------------------

def _make_transcript(path, tool_calls):
    lines = []
    for name, inp in tool_calls:
        lines.append(json.dumps({
            "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}
        }))
    path.write_text("\n".join(lines) + "\n")


def _run_hook(project_dir, transcript, session_id="sess-test", event="SessionEnd"):
    payload = json.dumps({
        "hook_event_name": event,
        "session_id": session_id,
        "transcript_path": str(transcript),
        "cwd": str(project_dir),
    })
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project_dir))
    return subprocess.run(
        [sys.executable, os.path.join(HOOKS, "capture_session.py")],
        input=payload, text=True, capture_output=True, env=env,
    )


def test_substantive_session_is_captured_and_source_layout_correct(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "CLAUDE.local.md").write_text("$BAILIWICK\n")
    transcript = tmp_path / "t.jsonl"
    _make_transcript(transcript, [("Write", {"file_path": "a"}), ("Bash", {"command": "git commit -m x"})])
    r = _run_hook(proj, transcript)
    assert r.returncode == 0, r.stderr
    raw = proj / ".bailiwick-outputs" / "raw"
    assert (raw / "sess-test.jsonl").exists(), "transcript copy missing"
    meta = (raw / "sess-test.md").read_text()
    assert "committed: true" in meta
    assert "mode: seeded" in meta


def test_trivial_session_is_not_captured(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "CLAUDE.local.md").write_text("$BAILIWICK\n")
    transcript = tmp_path / "t.jsonl"
    _make_transcript(transcript, [("Read", {"file_path": "a"})])  # 1 read < MIN_TOOL_CALLS, no mutation
    r = _run_hook(proj, transcript)
    assert r.returncode == 0
    assert not (proj / ".bailiwick-outputs").exists(), "trivial session must not stage a capture"


def test_unwired_repo_never_captures_even_substantive_work(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()  # no marker, no shadow
    transcript = tmp_path / "t.jsonl"
    _make_transcript(transcript, [("Write", {"file_path": "a"})] * 5)
    r = _run_hook(proj, transcript)
    assert r.returncode == 0
    assert not (proj / ".bailiwick-outputs").exists(), "hook must stay inert outside wired repos"


# ---- Codex transcripts (codex-cli >= 0.147 fires the same Stop/SessionEnd hooks) ---------------
# Record shapes below are copied from real ~/.codex/sessions rollouts, not invented: a rollout is
# {"type": "response_item"|"event_msg", "payload": {...}}, shell calls carry the command as
# `"cmd": "..."` (doubly escaped inside a code-mode `exec` JS snippet), and a landed patch also
# emits patch_apply_end.

def _codex_exec(cmd):
    """A code-mode shell call: the command lives inside the JS `tools.exec_command({...})` input."""
    return {"type": "response_item", "payload": {
        "type": "custom_tool_call", "name": "exec",
        "input": "const r = await tools.exec_command(" + json.dumps({"cmd": cmd}) + "); text(r.output);\n",
    }}


def _codex_call(name, arguments):
    """A plain function call: arguments are a JSON *string*, as the rollout stores them."""
    return {"type": "response_item", "payload": {
        "type": "function_call", "name": name, "arguments": json.dumps(arguments),
    }}


def _make_codex_transcript(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def _wired(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "CLAUDE.local.md").write_text("$BAILIWICK\n")
    return proj


def test_codex_transcript_is_captured_with_its_signals(tmp_path):
    proj = _wired(tmp_path)
    transcript = tmp_path / "rollout.jsonl"
    _make_codex_transcript(transcript, [
        {"type": "session_meta", "payload": {"session_id": "x", "cwd": str(proj)}},
        _codex_exec("sed -n '1,40p' knowledge/topics/agent-cli-hook-contracts.md"),
        {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "apply_patch",
                                              "input": "*** Begin Patch\n*** Update File: a.tf\n"}},
        _codex_exec("git commit -m 'x'"),
    ])
    r = _run_hook(proj, transcript, session_id="cx-1")
    assert r.returncode == 0, r.stderr
    meta = (proj / ".bailiwick-outputs" / "raw" / "cx-1.md").read_text()
    assert "agent: codex" in meta
    assert "mutating: 1" in meta
    assert "committed: true" in meta
    assert "agent-cli-hook-contracts" in meta, "a read command must emit the `loaded` id"
    assert "apply_patch" in meta and "exec" in meta


def test_codex_function_call_shape_is_read_too(tmp_path):
    # Non-code-mode Codex calls the shell as a function_call with JSON `arguments`.
    proj = _wired(tmp_path)
    transcript = tmp_path / "rollout.jsonl"
    _make_codex_transcript(transcript, [
        _codex_call("exec_command", {"cmd": "cat knowledge/topics/claude-mcp-wiring.md", "workdir": "/x"}),
        _codex_call("exec_command", {"cmd": "git commit -m y"}),
        _codex_call("update_plan", {"plan": []}),
    ])
    r = _run_hook(proj, transcript, session_id="cx-2")
    assert r.returncode == 0, r.stderr
    meta = (proj / ".bailiwick-outputs" / "raw" / "cx-2.md").read_text()
    assert "claude-mcp-wiring" in meta and "committed: true" in meta


def test_codex_code_mode_patch_counts_as_a_mutation(tmp_path):
    # A patch applied from INSIDE an exec call leaves no apply_patch tool call — only the event.
    # Without the patch_apply_end floor this session would be dropped as non-substantive.
    proj = _wired(tmp_path)
    transcript = tmp_path / "rollout.jsonl"
    _make_codex_transcript(transcript, [
        _codex_exec("apply_patch <<'EOF'\n*** Begin Patch\nEOF"),
        {"type": "event_msg", "payload": {"type": "patch_apply_end", "success": True,
                                          "changes": {"/repo/main.tf": {}}}},
    ])
    r = _run_hook(proj, transcript, session_id="cx-3")
    assert r.returncode == 0, r.stderr
    meta = (proj / ".bailiwick-outputs" / "raw" / "cx-3.md").read_text()
    assert "mutating: 1" in meta, "code-mode patch must still register as a mutation"


def test_codex_failed_patch_is_not_a_mutation(tmp_path):
    proj = _wired(tmp_path)
    transcript = tmp_path / "rollout.jsonl"
    _make_codex_transcript(transcript, [
        {"type": "event_msg", "payload": {"type": "patch_apply_end", "success": False}},
        _codex_exec("ls"),
    ])
    r = _run_hook(proj, transcript, session_id="cx-4")
    assert r.returncode == 0
    assert not (proj / ".bailiwick-outputs").exists(), "a failed patch is no mutation to capture"


def test_codex_tool_output_text_never_fakes_a_signal(tmp_path):
    # The load-bearing anti-false-positive: `git commit` and a knowledge path appear constantly in
    # instruction text and command OUTPUT. Only what the agent actually RAN may set the signals.
    proj = _wired(tmp_path)
    transcript = tmp_path / "rollout.jsonl"
    _make_codex_transcript(transcript, [
        {"type": "response_item", "payload": {"type": "message", "role": "developer", "content": [
            {"type": "input_text", "text": "never run git commit; see knowledge/topics/ghost.md"}]}},
        {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c1",
                                              "output": [{"type": "input_text",
                                                          "text": "git commit -m nope knowledge/topics/ghost.md"}]}},
        _codex_exec("apply_patch <<'EOF'\nx\nEOF"),
        {"type": "event_msg", "payload": {"type": "patch_apply_end", "success": True}},
    ])
    r = _run_hook(proj, transcript, session_id="cx-5")
    assert r.returncode == 0, r.stderr
    meta = (proj / ".bailiwick-outputs" / "raw" / "cx-5.md").read_text()
    assert "committed: false" in meta
    assert "ghost" not in meta, "a path quoted in text/output is not a load"


def test_antigravity_capture_derives_signals(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "CLAUDE.local.md").write_text("uses $BAILIWICK\n")
    transcript = tmp_path / "agy-transcript.jsonl"
    lines = [
        json.dumps({
            "step_index": 1,
            "type": "PLANNER_RESPONSE",
            "tool_calls": [
                {"name": "read_file", "args": {"Path": "/path/knowledge/topics/my-topic.md"}}
            ]
        }),
        json.dumps({
            "step_index": 2,
            "type": "PLANNER_RESPONSE",
            "tool_calls": [
                {"name": "write_file", "args": {"Path": "/path/foo.py", "Content": "print('hello')"}}
            ]
        }),
        json.dumps({
            "step_index": 3,
            "type": "PLANNER_RESPONSE",
            "tool_calls": [
                {"name": "run_command", "args": {"CommandLine": "git commit -m 'feat: init'"}}
            ]
        })
    ]
    transcript.write_text("\n".join(lines) + "\n")
    payload = {
        "conversationId": "agy-123",
        "transcriptPath": str(transcript),
        "workspacePaths": [str(proj)],
        "terminationReason": "NO_TOOL_CALL"
    }
    r = subprocess.run(
        [sys.executable, os.path.join(HOOKS, "capture_session.py")],
        input=json.dumps(payload), text=True, capture_output=True,
    )
    assert r.returncode == 0, r.stderr
    meta_path = proj / ".bailiwick-outputs" / "raw" / "agy-123.md"
    assert meta_path.exists()
    meta = meta_path.read_text()
    assert "- agent: antigravity" in meta
    assert "mutating: 1" in meta
    assert "committed: true" in meta
    assert "my-topic" in meta


def test_malformed_payload_never_blocks_the_harness(tmp_path):
    r = subprocess.run(
        [sys.executable, os.path.join(HOOKS, "capture_session.py")],
        input="not json at all", text=True, capture_output=True,
    )
    assert r.returncode == 0


@pytest.mark.parametrize("payload", ["[]", '"x"', "3", "null"])
def test_valid_json_non_object_payload_never_blocks(payload):
    # Valid JSON that is not an object passes the parse but has no .get() — the never-block
    # contract must hold for it too (this crashed with AttributeError before the guard).
    r = subprocess.run(
        [sys.executable, os.path.join(HOOKS, "capture_session.py")],
        input=payload, text=True, capture_output=True,
    )
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(sys.platform == "win32",
                    reason="the bash mirror only runs on POSIX machines; on the Windows runner "
                           "'bash' resolves to the WSL shim, which has no distribution")
@pytest.mark.parametrize("name", [
    "Orion", "MyMac Pro!", "host_1.local", "café:host", "A B  C", "UPPER-lower_9",
])
def test_machine_normalization_matches_bash_pipeline(name):
    # The python normalization in capture_session._health / guardrails._health must stay
    # byte-identical to the bash pipeline in health_common.sh — a divergence splits one
    # machine's health shard across two filenames and the backup only transports one.
    bash_out = subprocess.run(
        ["bash", "-c", "printf '%s' \"$1\" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9._-'",
         "_", name],
        capture_output=True, text=True,
    ).stdout
    import re as _re
    py_out = _re.sub(r"[^a-z0-9._-]", "", name.lower().replace(" ", "-"))
    assert py_out == bash_out


# ---- subagent transcripts (Claude Code: <dir>/<sid>/subagents/agent-<id>.jsonl) ----------------

def _session(tmp_path, main_calls, sid="sess-sub"):
    """A wired project + a main transcript laid out the way Claude Code stores it."""
    proj = _wired(tmp_path)
    tdir = tmp_path / "projects-dir"
    tdir.mkdir()
    transcript = tdir / (sid + ".jsonl")
    _make_transcript(transcript, main_calls)
    return proj, transcript


def _subagent(transcript, agent_id, calls, depth=1):
    sub = transcript.parent / transcript.stem / "subagents"
    sub.mkdir(parents=True, exist_ok=True)
    path = sub / "agent-{}.jsonl".format(agent_id)
    _make_transcript(path, calls)
    (sub / "agent-{}.meta.json".format(agent_id)).write_text(
        json.dumps({"agentType": "bailiwick-memory", "spawnDepth": depth}))
    return path


def _header(proj, sid="sess-sub"):
    return (proj / ".bailiwick-outputs" / "raw" / (sid + ".md")).read_text()


def _field(meta, name):
    line = next(l for l in meta.splitlines() if l.startswith("- {}:".format(name)))
    inner = line.split(":", 1)[1].strip().strip("[]")
    return sorted(x.strip() for x in inner.split(",") if x.strip())


MAIN_WORK = [("Agent", {"prompt": "x"}), ("Write", {"file_path": "out.tf"})]


def test_subagent_read_is_credited_separately(tmp_path, monkeypatch):
    monkeypatch.setenv("BAILIWICK_HOME", str(tmp_path / "bw-home"))
    proj, t = _session(tmp_path, MAIN_WORK + [("Read", {"file_path": "/b/knowledge/topics/main-one.md"})])
    _subagent(t, "a1", [("Read", {"file_path": "/b/knowledge/topics/sub-only.md"}),
                        ("Read", {"file_path": "/b/knowledge/topics/main-one.md"})])
    assert _run_hook(proj, t, session_id="sess-sub").returncode == 0
    meta = _header(proj)
    assert _field(meta, "loaded") == ["main-one"]
    # disjoint from `loaded`: an id the main session also read is not credited twice
    assert _field(meta, "loaded_via_subagents") == ["sub-only"]
    assert _field(meta, "applied") == ["main-one", "sub-only"]
    assert "- capture_schema: 2" in meta
    assert "- subagents: 1" in meta


def test_subagent_path_mention_in_write_is_not_a_load(tmp_path, monkeypatch):
    monkeypatch.setenv("BAILIWICK_HOME", str(tmp_path / "bw-home"))
    proj, t = _session(tmp_path, MAIN_WORK)
    _subagent(t, "a1", [("Write", {"file_path": "doc.md",
                                   "content": "see knowledge/topics/mentioned.md"})])
    _run_hook(proj, t, session_id="sess-sub")
    assert _field(_header(proj), "loaded_via_subagents") == []


def test_no_subagents_folder_still_captures(tmp_path, monkeypatch):
    monkeypatch.setenv("BAILIWICK_HOME", str(tmp_path / "bw-home"))
    proj, t = _session(tmp_path, MAIN_WORK)
    assert _run_hook(proj, t, session_id="sess-sub").returncode == 0
    meta = _header(proj)
    assert "- subagents: 0" in meta
    assert _field(meta, "loaded_via_subagents") == []


def test_nested_subagents_are_scanned(tmp_path, monkeypatch):
    monkeypatch.setenv("BAILIWICK_HOME", str(tmp_path / "bw-home"))
    proj, t = _session(tmp_path, MAIN_WORK)
    _subagent(t, "parent", [("Agent", {"prompt": "y"})])
    _subagent(t, "child", [("mcp__bailiwick-filesystem__read_text_file",
                            {"path": "/b/knowledge/patterns/deep-read.md"})], depth=2)
    _run_hook(proj, t, session_id="sess-sub")
    meta = _header(proj)
    assert _field(meta, "loaded_via_subagents") == ["deep-read"]
    assert "- subagents: 2" in meta


def test_subagent_only_work_makes_the_session_substantive(tmp_path, monkeypatch):
    """A Lead that only dispatched an Implement stage still shipped what the stage wrote."""
    monkeypatch.setenv("BAILIWICK_HOME", str(tmp_path / "bw-home"))
    proj, t = _session(tmp_path, [("Agent", {"prompt": "implement"})])
    _subagent(t, "impl", [("Read", {"file_path": "/b/knowledge/topics/used-here.md"}),
                          ("Edit", {"file_path": "main.tf"})])
    _run_hook(proj, t, session_id="sess-sub")
    meta = _header(proj)
    assert _field(meta, "applied") == ["used-here"]


def test_later_stop_sees_a_subagent_that_finished_after_the_first(tmp_path, monkeypatch):
    """Stop can fire while a background agent runs; the next Stop/SessionEnd rewrites the capture."""
    monkeypatch.setenv("BAILIWICK_HOME", str(tmp_path / "bw-home"))
    proj, t = _session(tmp_path, MAIN_WORK)
    path = _subagent(t, "bg", [("Bash", {"command": "ls"})])
    _run_hook(proj, t, session_id="sess-sub", event="Stop")
    assert _field(_header(proj), "loaded_via_subagents") == []
    with open(path, "a") as fh:
        fh.write(json.dumps({"message": {"content": [{"type": "tool_use", "name": "Read",
                 "input": {"file_path": "/b/knowledge/topics/late-read.md"}}]}}) + "\n")
    _run_hook(proj, t, session_id="sess-sub", event="SessionEnd")
    assert _field(_header(proj), "loaded_via_subagents") == ["late-read"]


def test_unreadable_subagent_degrades_to_main_transcript(tmp_path, monkeypatch):
    home = tmp_path / "bw-home"
    monkeypatch.setenv("BAILIWICK_HOME", str(home))
    proj, t = _session(tmp_path, MAIN_WORK + [("Read", {"file_path": "/b/knowledge/topics/main-one.md"})])
    bad = t.parent / t.stem / "subagents" / "agent-broken.jsonl"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"\xff\xfe not utf-8\n")  # decoding raises mid-scan
    _subagent(t, "zz-good", [("Read", {"file_path": "/b/knowledge/topics/after-bad.md"})])
    assert _run_hook(proj, t, session_id="sess-sub").returncode == 0
    meta = _header(proj)
    assert _field(meta, "loaded") == ["main-one"]
    assert _field(meta, "loaded_via_subagents") == ["after-bad"]
    shards = list((home / "health").glob("*.jsonl"))
    assert shards and "subagent scan failed" in shards[0].read_text()


# ---- subagent records inlined into the ONE capture file (capture.include_subagents) ------------

def _records(proj, sid="sess-sub"):
    path = proj / ".bailiwick-outputs" / "raw" / (sid + ".jsonl")
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def test_subagent_records_are_appended_tagged_after_the_main_ones(tmp_path, monkeypatch):
    monkeypatch.setenv("BAILIWICK_HOME", str(tmp_path / "bw-home"))
    proj, t = _session(tmp_path, MAIN_WORK)
    path = _subagent(t, "a1", [("Read", {"file_path": "x"}), ("Bash", {"command": "ls"})])
    # one record already tagged the way current Claude Code writes it: kept as is
    with open(path, "a") as fh:
        fh.write(json.dumps({"isSidechain": True, "agentId": "a1", "message": {"content": []}}) + "\n")
    _run_hook(proj, t, session_id="sess-sub")
    recs = _records(proj)
    assert len(recs) == 2 + 3
    assert not any(r.get("isSidechain") for r in recs[:2]), "main records come first, untouched"
    assert all(r["isSidechain"] is True and r["agentId"] == "a1" for r in recs[2:])
    assert "records inlined: 3" in _header(proj)


def test_repeated_stop_never_duplicates_inlined_records(tmp_path, monkeypatch):
    monkeypatch.setenv("BAILIWICK_HOME", str(tmp_path / "bw-home"))
    proj, t = _session(tmp_path, MAIN_WORK)
    _subagent(t, "a1", [("Read", {"file_path": "x"})])
    for event in ("Stop", "Stop", "SessionEnd"):
        _run_hook(proj, t, session_id="sess-sub", event=event)
    assert len(_records(proj)) == 2 + 1


def test_include_subagents_false_keeps_signals_but_not_records(tmp_path, monkeypatch):
    """Flag off: the capture stays main-only, yet subagent reads are still credited."""
    import shutil
    monkeypatch.setenv("BAILIWICK_HOME", str(tmp_path / "bw-home"))
    fw = tmp_path / "fw"
    shutil.copytree(HOOKS, fw / "hooks", ignore=shutil.ignore_patterns("__pycache__"))
    (fw / ".bailiwick-sync.json").write_text(json.dumps({"capture": {"include_subagents": False}}))
    proj, t = _session(tmp_path, MAIN_WORK)
    _subagent(t, "a1", [("Read", {"file_path": "/b/knowledge/topics/sub-only.md"})])
    payload = json.dumps({"hook_event_name": "SessionEnd", "session_id": "sess-sub",
                          "transcript_path": str(t), "cwd": str(proj)})
    r = subprocess.run([sys.executable, str(fw / "hooks" / "capture_session.py")], input=payload,
                       text=True, capture_output=True, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(proj)))
    assert r.returncode == 0, r.stderr
    assert len(_records(proj)) == 2
    meta = _header(proj)
    assert "records inlined: 0" in meta
    assert _field(meta, "loaded_via_subagents") == ["sub-only"]


# ---- /purge sessions are never captured --------------------------------------------------------
# A session that ran /purge holds the client identifiers it removes, yet its capture would carry the
# origin of the repo it RAN in — invisible to /purge's origin-based sweep. Only an INVOCATION may
# skip a capture (a wrong skip loses data); a mere mention must still be captured.

WORK = [("Write", {"file_path": "a.tf"}), ("Bash", {"command": "terraform fmt"})]


def _rec_tool(name, inp):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "name": name, "input": inp}]}}


def _rec_user(content):
    return {"type": "user", "message": {"role": "user", "content": content}}


def _rec_assistant_text(text):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": text}]}}


def _cmd_header(name, args=""):
    # Real Claude Code shape (verified): the slash command lands as a user string with this header.
    return "<command-message>{0}</command-message>\n<command-name>/{0}</command-name>\n" \
           "<command-args>{1}</command-args>".format(name, args)


def _codex_user(text, role="user"):
    return {"type": "response_item", "payload": {"type": "message", "role": role,
                                                 "content": [{"type": "input_text", "text": text}]}}


def _write_records(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def _work_records():
    return [_rec_tool(n, i) for n, i in WORK]


def _health_text(home):
    hdir = home / "health"
    return "".join(p.read_text() for p in hdir.glob("*.jsonl")) if hdir.is_dir() else ""


def _instance(tmp_path, cfg=None):
    """A private copy of hooks/ so sync_config() reads THIS sandbox's config, never the real
    clone's — a backup purge must never be spawned against a real backup repo from a test."""
    import shutil
    inst = tmp_path / "inst"
    shutil.copytree(HOOKS, inst / "hooks", ignore=shutil.ignore_patterns("__pycache__"))
    if cfg is not None:
        (inst / ".bailiwick-sync.json").write_text(json.dumps(cfg))
    return inst / "hooks"


def _run(hooks, proj, transcript, sid, home, event="Stop", extra_env=None):
    payload = json.dumps({"hook_event_name": event, "session_id": sid,
                          "transcript_path": str(transcript), "cwd": str(proj)})
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj), BAILIWICK_HOME=str(home))
    env.pop("BAILIWICK_SHADOW", None)
    env.update(extra_env or {})
    return subprocess.run([sys.executable, os.path.join(str(hooks), "capture_session.py")],
                          input=payload, text=True, capture_output=True, env=env)


PURGE_INVOCATIONS = {
    "skill-tool": _rec_tool("Skill", {"skill": "purge", "args": "acme --to generic"}),
    "slash-command-string": _rec_user(_cmd_header("purge", "acme")),
    # The api-request-blob shape: same header as a text block, followed by the skill body.
    "slash-command-text-block": _rec_user([{"type": "text", "text": _cmd_header("purge", "acme")},
                                           {"type": "text", "text": "Base directory for this skill"}]),
    "codex-dollar": _codex_user("$bailiwick-purge acme"),
    "codex-skill-inject": _codex_user("<skill>\n<name>bailiwick-purge</name>\n<path>/x/SKILL.md</path>"),
}
# Trust tiers: only a USER-typed trigger (or a confirmed sentinel) skips and retracts. An agent's
# Skill call and a Codex injected skill body alone are UNCONFIRMED: the capture is held local.
TRUSTED_PURGE = ("slash-command-string", "slash-command-text-block", "codex-dollar")
UNCONFIRMED_PURGE = ("skill-tool", "codex-skill-inject")
HOLD_LINE = "- purge_detection: error"


def _held(proj, sid):
    md = proj / ".bailiwick-outputs" / "raw" / (sid + ".md")
    return md.exists() and HOLD_LINE in md.read_text().splitlines()


@pytest.mark.parametrize("kind", TRUSTED_PURGE)
def test_purge_invocation_is_not_captured(tmp_path, kind):
    hooks, home = _instance(tmp_path), tmp_path / "bw-home"
    proj = _wired(tmp_path)
    t = tmp_path / "t.jsonl"
    _write_records(t, _work_records() + [PURGE_INVOCATIONS[kind]] + _work_records())
    r = _run(hooks, proj, t, "sess-p", home, event="SessionEnd")
    assert r.returncode == 0, r.stderr
    raw = proj / ".bailiwick-outputs" / "raw"
    assert not (raw / "sess-p.jsonl").exists() and not (raw / "sess-p.md").exists()
    health = _health_text(home)
    assert "capture skipped: purge session" in health
    assert "sess-p" not in health and str(proj) not in health, "health line must be content-free"


@pytest.mark.parametrize("kind", UNCONFIRMED_PURGE)
def test_unconfirmed_purge_trigger_is_held_local_not_skipped(tmp_path, kind):
    hooks, home = _instance(tmp_path), tmp_path / "bw-home"
    proj = _wired(tmp_path)
    t = tmp_path / "t.jsonl"
    _write_records(t, _work_records() + [PURGE_INVOCATIONS[kind]] + _work_records())
    r = _run(hooks, proj, t, "sess-p", home, event="SessionEnd")
    assert r.returncode == 0, r.stderr
    assert (proj / ".bailiwick-outputs" / "raw" / "sess-p.jsonl").exists(), "held, not dropped"
    assert _held(proj, "sess-p"), "the hold line keeps it off the backup"
    health = _health_text(home)
    assert "skill (unconfirmed)" in health and "capture skipped: purge session" not in health
    assert "sess-p" not in health and str(proj) not in health, "health line must be content-free"


MENTIONS = {
    "assistant-prose": _rec_assistant_text("Next, run /purge later to remove acme."),
    "assistant-prose-codex": {"type": "response_item", "payload": {
        "type": "message", "role": "assistant",
        "content": [{"type": "output_text", "text": "$bailiwick-purge removes a client"}]}},
    "grep-for-purge": _rec_tool("Grep", {"pattern": "purge", "path": "skills/"}),
    "read-purge-skill": _rec_tool("Read", {"file_path": "/b/skills/purge/SKILL.md"}),
    "other-skill-args": _rec_tool("Skill", {"skill": "lead", "args": "then /purge acme"}),
    "plugin-qualified-skill": _rec_tool("Skill", {"skill": "otherplugin:purge"}),
    "other-command-args": _rec_user(_cmd_header("lead", "<command-name>/purge</command-name>")),
    "user-prose": _rec_user("should I run /purge? <command-name>/purge</command-name> is the header"),
    "tool-result-quotes-header": _rec_user([{"type": "tool_result", "tool_use_id": "t1",
                                             "content": _cmd_header("purge", "acme")}]),
    "codex-not-first-token": _codex_user("do not run $bailiwick-purge yet"),
    "codex-longer-skill-name": _codex_user("$bailiwick-purger x"),
    "codex-developer-skill-list": _codex_user(
        "<skills_instructions>\n- bailiwick-purge: remove a client\n$bailiwick-purge", role="developer"),
}


@pytest.mark.parametrize("kind", sorted(MENTIONS))
def test_purge_mention_is_still_captured(tmp_path, kind):
    hooks, home = _instance(tmp_path), tmp_path / "bw-home"
    proj = _wired(tmp_path)
    t = tmp_path / "t.jsonl"
    _write_records(t, _work_records() + [MENTIONS[kind]])
    r = _run(hooks, proj, t, "sess-m", home)
    assert r.returncode == 0, r.stderr
    assert (proj / ".bailiwick-outputs" / "raw" / "sess-m.jsonl").exists(), \
        "a mention of purge is not an invocation — the session must still be captured"
    assert "purge session" not in _health_text(home)
    assert not _held(proj, "sess-m"), "a mention does not hold the capture either"


@pytest.mark.parametrize("mode", ["seeded", "shadow"])
def test_later_stop_retracts_an_earlier_capture_of_the_same_session(tmp_path, mode):
    hooks, home = _instance(tmp_path), tmp_path / "bw-home"
    if mode == "seeded":
        proj, env = _wired(tmp_path), {}
        raw = proj / ".bailiwick-outputs" / "raw"
    else:
        proj, env = tmp_path / "proj", {"BAILIWICK_SHADOW": "1"}
        proj.mkdir()
        raw = home / "captures" / capture_session.repo_key(str(proj)) / "raw"
    t = tmp_path / "t.jsonl"
    _write_records(t, _work_records())
    assert _run(hooks, proj, t, "sess-r", home, extra_env=env).returncode == 0
    assert (raw / "sess-r.jsonl").exists() and (raw / "sess-r.md").exists(), "precondition: captured"
    (raw / "other-session.jsonl").write_text("{}\n")
    # A TRUSTED trigger (user-typed /purge): an agent Skill call would only hold (see the tier tests).
    _write_records(t, _work_records() + [PURGE_INVOCATIONS["slash-command-string"]])
    r = _run(hooks, proj, t, "sess-r", home, extra_env=env)
    assert r.returncode == 0, r.stderr
    assert not (raw / "sess-r.jsonl").exists() and not (raw / "sess-r.md").exists()
    assert (raw / "other-session.jsonl").exists(), "only THIS session's capture is retracted"
    assert "earlier capture files removed: 2" in _health_text(home)


@pytest.mark.parametrize("kind", sorted(PURGE_INVOCATIONS))
def test_purge_by_a_subagent_holds_the_capture_and_never_retracts(tmp_path, kind):
    # Subagent records are inlined into the capture, so a subagent's /purge could leak the same way —
    # but a subagent is never a user, so ANY detector there only holds the capture local: an earlier
    # capture is kept (never deleted) and rewritten with the hold line. (Was: skip + retract.)
    hooks, home = _instance(tmp_path), tmp_path / "bw-home"
    proj, t = _session(tmp_path, MAIN_WORK, sid="sess-sa")
    assert _run(hooks, proj, t, "sess-sa", home).returncode == 0
    raw = proj / ".bailiwick-outputs" / "raw"
    assert (raw / "sess-sa.jsonl").exists() and not _held(proj, "sess-sa"), "precondition: captured"
    sub = t.parent / t.stem / "subagents"
    sub.mkdir(parents=True)
    _write_records(sub / "agent-a1.jsonl", [PURGE_INVOCATIONS[kind]])
    assert _run(hooks, proj, t, "sess-sa", home, event="SessionEnd").returncode == 0
    assert (raw / "sess-sa.jsonl").exists(), "a subagent trigger never deletes"
    assert _held(proj, "sess-sa")
    health = _health_text(home)
    assert "(unconfirmed)" in health and "capture skipped: purge session" not in health


def _inproc(tmp_path, monkeypatch, main_recs, sub_recs=None, sid="sess-t", pre_capture=True, cfg=None):
    """Run main() in-process with spies on drop_session_capture / request_backup_purge, so a test can
    prove a HELD session never reaches either. pre_capture lays down an earlier Stop's capture."""
    import io
    home = tmp_path / "bw-home"
    monkeypatch.setenv("BAILIWICK_HOME", str(home))
    monkeypatch.delenv("BAILIWICK_SHADOW", raising=False)
    proj = _wired(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    monkeypatch.setattr(capture_session.bw_common, "sync_config", lambda: cfg or {})
    raw = proj / ".bailiwick-outputs" / "raw"
    if pre_capture:
        raw.mkdir(parents=True)
        (raw / (sid + ".jsonl")).write_text("{}\n")
        (raw / (sid + ".md")).write_text("# Raw capture\n")
    tdir = tmp_path / "projects-dir"
    tdir.mkdir()
    t = tdir / (sid + ".jsonl")
    _write_records(t, main_recs)
    if sub_recs:
        sub = tdir / sid / "subagents"
        sub.mkdir(parents=True)
        _write_records(sub / "agent-a1.jsonl", sub_recs)
    calls = {"drop": 0, "retract": 0}
    real_drop = capture_session.drop_session_capture

    def drop(p, s):
        calls["drop"] += 1
        return real_drop(p, s)

    def retract(p, s):
        calls["retract"] += 1
        return 2
    monkeypatch.setattr(capture_session, "drop_session_capture", drop)
    monkeypatch.setattr(capture_session, "request_backup_purge", retract)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        {"hook_event_name": "SessionEnd", "session_id": sid, "transcript_path": str(t), "cwd": str(proj)})))
    assert capture_session.main() == 0
    return {"captured": (raw / (sid + ".jsonl")).exists(), "held": _held(proj, sid),
            "calls": calls, "health": _health_text(home)}


@pytest.mark.parametrize("where", ["main", "subagent"])
def test_agent_skill_call_is_held_and_never_drops_or_retracts(tmp_path, monkeypatch, where):
    rec = PURGE_INVOCATIONS["skill-tool"]
    main_recs = _work_records() + ([rec] if where == "main" else [])
    out = _inproc(tmp_path, monkeypatch, main_recs, sub_recs=[rec] if where == "subagent" else None)
    assert out["captured"] and out["held"]
    assert out["calls"] == {"drop": 0, "retract": 0}, "drop/request_backup_purge never called"
    assert "skill (unconfirmed)" in out["health"]
    assert "capture skipped: purge session" not in out["health"]


@pytest.mark.parametrize("kind", TRUSTED_PURGE)
def test_typed_purge_skips_retracts_and_tombstones(tmp_path, monkeypatch, kind):
    out = _inproc(tmp_path, monkeypatch, _work_records() + [PURGE_INVOCATIONS[kind]])
    assert not out["captured"], "the earlier capture is retracted"
    assert out["calls"] == {"drop": 1, "retract": 1}
    assert "capture skipped: purge session (detected by: slash command;" in out["health"]
    assert "backup retraction requested: yes" in out["health"]


@pytest.mark.parametrize("unconfirmed", ["main", "subagent"])
def test_typed_plus_agent_skill_call_trusted_wins(tmp_path, monkeypatch, unconfirmed):
    skill = PURGE_INVOCATIONS["skill-tool"]
    main_recs = _work_records() + [PURGE_INVOCATIONS["slash-command-string"]]
    if unconfirmed == "main":
        main_recs.append(skill)
    out = _inproc(tmp_path, monkeypatch, main_recs, sub_recs=[skill] if unconfirmed == "subagent" else None)
    assert not out["captured"] and out["calls"] == {"drop": 1, "retract": 1}
    assert "detected by: skill (unconfirmed), slash command;" in out["health"], "the union is reported"


def test_codex_skill_body_alone_is_held(tmp_path, monkeypatch):
    out = _inproc(tmp_path, monkeypatch, _work_records() + [PURGE_INVOCATIONS["codex-skill-inject"]])
    assert out["captured"] and out["held"] and out["calls"] == {"drop": 0, "retract": 0}


def test_codex_typed_dollar_plus_injected_body_is_trusted(tmp_path, monkeypatch):
    out = _inproc(tmp_path, monkeypatch, _work_records() + [PURGE_INVOCATIONS["codex-dollar"],
                                                            PURGE_INVOCATIONS["codex-skill-inject"]])
    assert not out["captured"] and out["calls"] == {"drop": 1, "retract": 1}


def test_scan_error_with_an_agent_trigger_is_still_held(tmp_path, monkeypatch):
    """The scan-error hold is unchanged, and stacks with an unconfirmed trigger (still only a hold)."""
    real = capture_session._detect_purge
    seen = []

    def flaky(rec, st):
        seen.append(1)
        if len(seen) == 1:
            raise RuntimeError("detector bug")
        return real(rec, st)
    monkeypatch.setattr(capture_session, "_detect_purge", flaky)
    out = _inproc(tmp_path, monkeypatch, _work_records() + [PURGE_INVOCATIONS["skill-tool"]])
    assert out["captured"] and out["held"] and out["calls"] == {"drop": 0, "retract": 0}
    assert "purge detection failed" in out["health"] and "skill (unconfirmed)" in out["health"]


def test_detection_error_falls_back_to_capturing(tmp_path, monkeypatch):
    home = tmp_path / "bw-home"
    monkeypatch.setenv("BAILIWICK_HOME", str(home))
    proj = _wired(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    t = tmp_path / "t.jsonl"
    _write_records(t, _work_records() + [PURGE_INVOCATIONS["skill-tool"]])

    def boom(rec, st):
        raise RuntimeError("detector bug")
    monkeypatch.setattr(capture_session, "_detect_purge", boom)
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        {"hook_event_name": "Stop", "session_id": "sess-e", "transcript_path": str(t), "cwd": str(proj)})))
    assert capture_session.main() == 0
    assert (proj / ".bailiwick-outputs" / "raw" / "sess-e.jsonl").exists(), "fail toward capture"
    assert "purge detection failed" in _health_text(home)
    # ...but LOCAL only: the exact header line capture_backup.sh push holds the capture on.
    meta = (proj / ".bailiwick-outputs" / "raw" / "sess-e.md").read_text().splitlines()
    assert "- purge_detection: error" in meta
    assert "- captured:" in "\n".join(meta), "the full header still follows the hold marker"


def test_clean_scan_writes_no_detection_error_line(tmp_path):
    hooks, home = _instance(tmp_path), tmp_path / "bw-home"
    proj = _wired(tmp_path)
    t = tmp_path / "t.jsonl"
    _write_records(t, _work_records())
    assert _run(hooks, proj, t, "sess-ok", home).returncode == 0
    assert "purge_detection" not in _header(proj, "sess-ok")


def test_hostile_session_id_never_steers_a_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("BAILIWICK_HOME", str(tmp_path / "bw-home"))
    proj = _wired(tmp_path)
    victim = proj / ".bailiwick-outputs" / "x.md"
    victim.parent.mkdir(parents=True)
    victim.write_text("keep")
    for sid in ("../x", "..", "", "a/../../x"):
        assert capture_session.drop_session_capture(str(proj), sid) == ([], 0)
    assert victim.exists()


def _fake_popen(monkeypatch):
    calls = []

    class FakePopen:
        def __init__(self, argv, **kw):
            if argv[0] == "bash":
                calls.append((argv, kw))

        def wait(self, timeout=None):
            return 0
    import subprocess as sp
    monkeypatch.setattr(sp, "Popen", FakePopen)
    monkeypatch.delenv("BW_BACKUP_SYNC", raising=False)
    return calls


BACKUP_ON = {"machine": "Test Sat", "capture_backup": {"enabled": True, "confidentiality_ack": True}}


def test_backup_retraction_is_ledgered_hash_only_and_detached(tmp_path, monkeypatch):
    # The hashed relpath must be the one capture_backup.sh push wrote: <machine token>/<repo_key>/<f>.gpg
    # (end-to-end agreement is pinned in tests/shell/test_capture_backup.sh).
    import hashlib
    import stat
    import subprocess as sp
    home = tmp_path / "bw-home"
    monkeypatch.setenv("BAILIWICK_HOME", str(home))
    proj = _wired(tmp_path)
    key = capture_session.repo_key(str(proj))  # before the fake: repo_key itself runs git
    calls = _fake_popen(monkeypatch)
    monkeypatch.setattr(capture_session.bw_common, "sync_config", lambda: BACKUP_ON)
    assert capture_session.request_backup_purge(str(proj), "sess-b") == 2
    rels = ["test-sat/{}/sess-b.{}.gpg".format(key, e) for e in ("jsonl", "md")]
    ledger = home / "backup-retract.pending"
    assert ledger.read_text().split() == [hashlib.sha256(r.encode()).hexdigest() for r in rels]
    assert "sess-b" not in ledger.read_text() and key not in ledger.read_text(), "hash only"
    assert stat.S_IMODE(ledger.stat().st_mode) == 0o600
    assert not (home / "backup-retract.pending.lock").exists(), "ledger lock released"
    (argv, kw), = calls
    assert argv[1].endswith("capture_backup.sh") and argv[2:] == ["retract"], \
        "no relpath in argv: it would show in ps"
    assert kw["start_new_session"] is True
    assert kw["stdin"] == kw["stdout"] == kw["stderr"] == sp.DEVNULL, "no inherited pipe (hook budget)"
    # Idempotent: a repeated request never duplicates an entry.
    assert capture_session.request_backup_purge(str(proj), "sess-b") == 2
    assert len(ledger.read_text().split()) == 2


@pytest.mark.parametrize("cfg", [{}, {"capture_backup": {"enabled": True}},
                                 {"capture_backup": {"enabled": False, "confidentiality_ack": True}},
                                 {"capture_backup": {"enabled": True, "confidentiality_ack": False}}])
def test_backup_retraction_needs_enabled_and_ack(tmp_path, monkeypatch, cfg):
    monkeypatch.setenv("BAILIWICK_HOME", str(tmp_path / "bw-home"))
    proj = _wired(tmp_path)
    calls = _fake_popen(monkeypatch)
    monkeypatch.setattr(capture_session.bw_common, "sync_config", lambda: cfg)
    assert capture_session.request_backup_purge(str(proj), "sess-b") is None
    assert calls == [] and not (tmp_path / "bw-home" / "backup-retract.pending").exists()


def test_skip_line_reports_pending_count_and_only_when_relevant(tmp_path):
    hooks, home = _instance(tmp_path, BACKUP_ON), tmp_path / "bw-home"
    proj = _wired(tmp_path)
    t = tmp_path / "t.jsonl"
    _write_records(t, _work_records())
    assert _run(hooks, proj, t, "sess-l", home).returncode == 0
    _write_records(t, _work_records() + [PURGE_INVOCATIONS["slash-command-string"]])
    # BW_BACKUP_SYNC so the spawned retract finishes inside the test; with no repo configured it
    # cannot drain, so both entries stay pending.
    assert _run(hooks, proj, t, "sess-l", home, extra_env={"BW_BACKUP_SYNC": "1"}).returncode == 0
    health = _health_text(home)
    assert "earlier capture files removed: 2; backup retraction requested: yes; " \
           "backup retractions pending: 2" in health
    assert "backup purge requested" not in health
    n = health.count("capture skipped: purge session")
    # A later Stop with nothing left to retract stays silent; SessionEnd reports once more.
    assert _run(hooks, proj, t, "sess-l", home).returncode == 0
    assert _health_text(home).count("capture skipped: purge session") == n
    assert _run(hooks, proj, t, "sess-l", home, event="SessionEnd").returncode == 0
    assert _health_text(home).count("capture skipped: purge session") == n + 1


def test_fallback_session_id_never_retracts(tmp_path):
    hooks, home = _instance(tmp_path), tmp_path / "bw-home"
    proj = _wired(tmp_path)
    raw = proj / ".bailiwick-outputs" / "raw"
    raw.mkdir(parents=True)
    (raw / "unknown-session.jsonl").write_text("{}\n")  # some OTHER id-less session's capture
    t = tmp_path / "t.jsonl"
    _write_records(t, _work_records() + [PURGE_INVOCATIONS["slash-command-string"]])
    payload = json.dumps({"hook_event_name": "SessionEnd", "transcript_path": str(t), "cwd": str(proj)})
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj), BAILIWICK_HOME=str(home))
    r = subprocess.run([sys.executable, os.path.join(str(hooks), "capture_session.py")],
                       input=payload, text=True, capture_output=True, env=env)
    assert r.returncode == 0, r.stderr
    assert (raw / "unknown-session.jsonl").exists(), "fallback id names no session: never delete"
    assert "earlier capture files removed: 0" in _health_text(home)


@pytest.mark.parametrize("sid", ["../x", "..", "a/b", "a\0b", 7])
def test_unsafe_session_id_is_never_written(tmp_path, sid):
    hooks, home = _instance(tmp_path), tmp_path / "bw-home"
    proj = _wired(tmp_path)
    t = tmp_path / "t.jsonl"
    _write_records(t, _work_records())
    r = _run(hooks, proj, t, sid, home)
    assert r.returncode == 0, r.stderr
    written = [p for p in tmp_path.rglob("*") if p.is_file() and p.suffix in (".jsonl", ".md")
               and p.parent.name == "raw"]
    assert written == [] and not (tmp_path / "x.jsonl").exists()
    assert "capture refused: session id is not a safe file name" in _health_text(home)


# ---- positive sentinel: hooks/mark_purge_session.sh ---------------------------------------------
def _codex_tool(name, args, kind="function_call"):
    key = "arguments" if kind == "function_call" else "input"
    return {"type": "response_item", "payload": {"type": kind, "name": name, key: json.dumps(args)
                                                 if kind == "function_call" else args}}


MARK = '"$BAILIWICK/hooks/mark_purge_session.sh"'
SENTINEL_INVOCATIONS = {
    "bash-bailiwick": _rec_tool("Bash", {"command": "bash " + MARK}),
    "sh-braced": _rec_tool("Bash", {"command": "  sh ${BAILIWICK}/hooks/mark_purge_session.sh \n"}),
    "bare-quoted": _rec_tool("Bash", {"command": MARK}),
    # @ROOT@ = the instance's framework root; @SPACE@ = a symlink to it whose path holds a space.
    # Absolute forms count only when they resolve to the hook's own sibling script (realpath).
    "absolute": _rec_tool("Bash", {"command": "bash @ROOT@/hooks/mark_purge_session.sh"}),
    "absolute-quoted-space": _rec_tool("Bash", {"command": "bash '@SPACE@/hooks/mark_purge_session.sh'"}),
    # A path THROUGH capture_backup.sh: realpath() folds `..` lexically, so the detector accepts it —
    # the guardrail must ask on it too (its capture_backup.sh exemption must not swallow it).
    "through-capture-backup": _rec_tool(
        "Bash", {"command": "bash @ROOT@/hooks/capture_backup.sh/../../hooks/mark_purge_session.sh"}),
    "through-capture-backup-bare": _rec_tool(
        "Bash", {"command": "@ROOT@/hooks/capture_backup.sh/../../hooks/mark_purge_session.sh"}),
    "codex-exec-command": _codex_tool("exec_command", {"cmd": "bash " + MARK, "workdir": "/x"}),
    "codex-shell-argv-lc": _codex_tool("shell", {"command": ["bash", "-lc", "bash " + MARK]}),
    "codex-shell-argv-bare": _codex_tool("shell", {"command": ["bash", "@ROOT@/hooks/mark_purge_session.sh"]}),
    "codex-shell-command": _codex_tool("shell_command", {"command": "bash " + MARK}),
    # The one accepted prefix: the exact Codex break-glass env assignment.
    "break-glass-prefix": _rec_tool("Bash", {"command": "BAILIWICK_BREAK_GLASS=1 bash " + MARK}),
    "codex-break-glass-prefix": _codex_tool("exec_command", {"cmd": "BAILIWICK_BREAK_GLASS=1 bash " + MARK}),
}
SENTINEL_MENTIONS = {
    "read-script": _rec_tool("Read", {"file_path": "/opt/bailiwick/hooks/mark_purge_session.sh"}),
    "grep-script": _rec_tool("Grep", {"pattern": "mark_purge_session", "path": "hooks/"}),
    "cat-script": _rec_tool("Bash", {"command": "cat " + MARK}),
    "grep-in-bash": _rec_tool("Bash", {"command": "grep -n purge " + MARK}),
    "chained": _rec_tool("Bash", {"command": "bash " + MARK + " && rm -rf x"}),
    "with-args": _rec_tool("Bash", {"command": "bash " + MARK + " acme"}),
    "syntax-check": _rec_tool("Bash", {"command": "bash -n " + MARK}),
    "echo": _rec_tool("Bash", {"command": "echo bash " + MARK}),
    "relative": _rec_tool("Bash", {"command": "bash hooks/mark_purge_session.sh"}),
    "other-name": _rec_tool("Bash", {"command": 'bash "$BAILIWICK/hooks/mark_purge_session.sh.bak"'}),
    "single-quoted-var": _rec_tool("Bash", {"command": "bash '$BAILIWICK/hooks/mark_purge_session.sh'"}),
    "second-line": _rec_tool("Bash", {"command": "bash " + MARK + "\nls"}),
    "write-content": _rec_tool("Write", {"file_path": "x.md", "content": "bash " + MARK}),
    "prose": _rec_assistant_text("bash " + MARK),
    "tool-result": _rec_user([{"type": "tool_result", "tool_use_id": "t", "content": "bash " + MARK}]),
    "codex-cat": _codex_tool("exec_command", {"cmd": "cat " + MARK}),
    "codex-other-tool": _codex_tool("read_text_file", {"cmd": "bash " + MARK}),
    "codex-user-text": _codex_user("bash " + MARK),
    # Spoofing: an absolute path that merely ENDS in /hooks/mark_purge_session.sh is not the sentinel.
    "absolute-nonexistent": _rec_tool("Bash", {"command": "bash /opt/bailiwick/hooks/mark_purge_session.sh"}),
    "absolute-quoted-nonexistent": _rec_tool("Bash", {"command": "bash '/a b/bw/hooks/mark_purge_session.sh'"}),
    "absolute-foreign-file": _rec_tool("Bash", {"command": "bash @FOREIGN@/hooks/mark_purge_session.sh"}),
    "codex-argv-nonexistent": _codex_tool("shell", {"command": ["bash", "/opt/bw/hooks/mark_purge_session.sh"]}),
    # Only `BAILIWICK_BREAK_GLASS=1 ` is accepted as a prefix — any other assignment is a mention.
    "other-env-prefix": _rec_tool("Bash", {"command": "FOO=1 bash " + MARK}),
    "break-glass-other-value": _rec_tool("Bash", {"command": "BAILIWICK_BREAK_GLASS=0 bash " + MARK}),
    "two-prefixes": _rec_tool("Bash", {"command": "X=1 BAILIWICK_BREAK_GLASS=1 bash " + MARK}),
}
CODE_MODE_SENTINEL = _codex_tool("exec", "await tools.exec_command(" + json.dumps({"cmd": "bash " + MARK})
                                 + ");", kind="custom_tool_call")

# The sentinel counts only once it has RUN SUCCESSFULLY: its call is paired (tool_use_id / call_id)
# with a result that is not an error / exits 0 and carries the script's fixed success line.
SID, CID = "toolu_s1", "call_s1"
OK_STDOUT = capture_session.MARK_OK_LINE + "\n[bailiwick] counts only if the command you ran was exactly"


def _codex_output(name, code=0, text=OK_STDOUT):
    """A Codex exec result in the shape its tool writes (shapes seen in real rollouts)."""
    if name == "shell":  # structured
        return json.dumps({"output": text, "metadata": {"exit_code": code, "duration_seconds": 0.0}})
    if name == "shell_command":  # freeform
        return "Exit code: {}\nWall time: 0.0 seconds\nOutput:\n{}".format(code, text)
    if name == "exec":  # code mode: the cell's text plus the exec_command result as JSON
        return [{"type": "input_text", "text": "Script completed\nWall time 0.1 seconds\nOutput:\n"},
                {"type": "input_text", "text": json.dumps({"chunk_id": "1a", "wall_time_seconds": 0.0,
                                                           "exit_code": code, "original_token_count": 3,
                                                           "output": text})}]
    return ("Chunk ID: 1a\nWall time: 0.0100 seconds\nProcess exited with code {}\n"
            "Original token count: 30\nOutput:\n{}".format(code, text))  # unified exec


def _claude_result(content=OK_STDOUT, is_error=None, tid=SID):
    block = {"type": "tool_result", "tool_use_id": tid, "content": content}
    if is_error is not None:
        block["is_error"] = is_error
    return _rec_user([block])


def _codex_result(name, code=0, text=OK_STDOUT, cid=CID, output=None):
    kind = "custom_tool_call_output" if name == "exec" else "function_call_output"
    return {"type": "response_item", "payload": {
        "type": kind, "call_id": cid, "output": _codex_output(name, code, text) if output is None else output}}


def _with_ids(rec):
    rec = json.loads(json.dumps(rec))
    content = (rec.get("message") or {}).get("content")
    for b in content if isinstance(content, list) else []:
        if isinstance(b, dict) and b.get("type") == "tool_use":
            b["id"] = SID
    p = rec.get("payload")
    if isinstance(p, dict) and p.get("type") in ("function_call", "custom_tool_call"):
        p["call_id"] = CID
    return rec


def _with_ok(rec):
    """The call (with its ids) followed by a SUCCESSFUL sentinel result for either CLI's id."""
    rec = _with_ids(rec)
    return [rec, _claude_result(), _codex_result((rec.get("payload") or {}).get("name") or "exec_command")]


def _sentinel_rec(tmp_path, hooks, rec):
    """Resolve the @ROOT@/@SPACE@/@FOREIGN@ placeholders against this test's instance."""
    root = os.path.dirname(str(hooks))
    space = tmp_path / "a b"
    if not space.exists():
        space.symlink_to(root)
    foreign = tmp_path / "foreign"
    if not foreign.exists():
        (foreign / "hooks").mkdir(parents=True)  # a real file, but not this hook's sibling
        (foreign / "hooks" / "mark_purge_session.sh").write_text("exit 0\n")
    text = json.dumps(rec)
    for k, v in (("@ROOT@", root), ("@SPACE@", str(space)), ("@FOREIGN@", str(foreign))):
        text = text.replace(k, v.replace("\\", "\\\\"))
    return json.loads(text)


def _sentinel_recs(tmp_path, hooks, recs):
    return [_sentinel_rec(tmp_path, hooks, r) for r in recs]


@pytest.mark.parametrize("kind", sorted(SENTINEL_INVOCATIONS))
def test_sentinel_invocation_is_not_captured(tmp_path, kind):
    hooks, home = _instance(tmp_path), tmp_path / "bw-home"
    proj = _wired(tmp_path)
    t = tmp_path / "t.jsonl"
    _write_records(t, _work_records() + _sentinel_recs(tmp_path, hooks, _with_ok(SENTINEL_INVOCATIONS[kind])))
    assert _run(hooks, proj, t, "sess-s", home, event="SessionEnd").returncode == 0
    assert not (proj / ".bailiwick-outputs" / "raw" / "sess-s.jsonl").exists()
    assert "capture skipped: purge session" in _health_text(home)


@pytest.mark.parametrize("kind", sorted(SENTINEL_MENTIONS))
def test_sentinel_mention_is_still_captured(tmp_path, kind):
    """Even followed by a success result for its id, a mention is not a mark."""
    hooks, home = _instance(tmp_path), tmp_path / "bw-home"
    proj = _wired(tmp_path)
    t = tmp_path / "t.jsonl"
    _write_records(t, _work_records() + _sentinel_recs(tmp_path, hooks, _with_ok(SENTINEL_MENTIONS[kind])))
    assert _run(hooks, proj, t, "sess-s", home).returncode == 0
    assert (proj / ".bailiwick-outputs" / "raw" / "sess-s.jsonl").exists(), "a mention is not a mark"
    assert not _held(proj, "sess-s")


def test_sentinel_skip_names_its_detector_content_free(tmp_path):
    hooks, home = _instance(tmp_path), tmp_path / "bw-home"
    proj = _wired(tmp_path)
    t = tmp_path / "t.jsonl"
    _write_records(t, _work_records() + _with_ok(SENTINEL_INVOCATIONS["bash-bailiwick"]))
    assert _run(hooks, proj, t, "sess-s", home, event="SessionEnd").returncode == 0
    health = _health_text(home)
    assert "detected by: sentinel;" in health and "sess-s" not in health and str(proj) not in health


@pytest.mark.parametrize("kind", ["bash-bailiwick", "codex-exec-command", "break-glass-prefix"])
def test_sentinel_in_a_subagent_transcript_is_ignored(tmp_path, kind):
    """No /purge subagent runs the sentinel, so a (prompt-injected) subagent cannot opt the session
    out of capture — nor retract its earlier captures — by running it, even successfully."""
    hooks, home = _instance(tmp_path), tmp_path / "bw-home"
    proj, t = _session(tmp_path, MAIN_WORK, sid="sess-sa")
    sub = t.parent / t.stem / "subagents"
    sub.mkdir(parents=True)
    _write_records(sub / "agent-a1.jsonl", _sentinel_recs(tmp_path, hooks, _with_ok(SENTINEL_INVOCATIONS[kind])))
    assert _run(hooks, proj, t, "sess-sa", home, event="SessionEnd").returncode == 0
    assert (proj / ".bailiwick-outputs" / "raw" / "sess-sa.jsonl").exists(), "captured: subagent sentinel ignored"
    assert not _held(proj, "sess-sa"), "ignored outright, not even a hold"
    assert "capture skipped: purge session" not in _health_text(home)


def _purge_state(records):
    st = capture_session._new_state(("purge",))
    for rec in records:
        capture_session._detect_purge(rec, st)
    return st


CLAUDE_CALL = _with_ids(SENTINEL_INVOCATIONS["bash-bailiwick"])
DECLINED = "The user doesn't want to proceed with this tool use. The tool use was rejected."
# Each case: the sentinel call and what came back for it. None of these may mark (nor hold) the session.
SENTINEL_NOT_RUN = {
    # The reviewer's probe: the ask was declined -> is_error tool_result.
    "claude-declined": [CLAUDE_CALL, _claude_result(DECLINED, is_error=True)],
    "claude-errored": [CLAUDE_CALL, _claude_result("Exit code 2\n[bailiwick] this session is NOT marked",
                                                   is_error=True)],
    # is_error wins even when the output somehow carried the success line.
    "claude-error-with-ok-line": [CLAUDE_CALL, _claude_result(OK_STDOUT, is_error=True)],
    "claude-no-ok-line": [CLAUDE_CALL, _claude_result("done")],
    "claude-missing-result": [CLAUDE_CALL],
    "claude-result-for-another-id": [CLAUDE_CALL, _claude_result(tid="toolu_other")],
    "claude-result-before-call": [_claude_result(), CLAUDE_CALL],
    "claude-call-without-id": [SENTINEL_INVOCATIONS["bash-bailiwick"], _claude_result()],
    "claude-ok-line-not-alone": [CLAUDE_CALL, _claude_result("echo " + capture_session.MARK_OK_LINE)],
    "codex-denied": [_with_ids(SENTINEL_INVOCATIONS["codex-exec-command"]), _codex_result(
        "exec_command", output="Command blocked by PreToolUse hook: [bailiwick guardrail] HIGH-IMPACT")],
    "codex-exit-2": [_with_ids(SENTINEL_INVOCATIONS["codex-shell-command"]),
                     _codex_result("shell_command", code=2, text="[bailiwick] NOT marked")],
    "codex-exit-1-with-ok-line": [_with_ids(SENTINEL_INVOCATIONS["codex-exec-command"]),
                                  _codex_result("exec_command", code=1)],
    "codex-structured-exit-1": [_with_ids(SENTINEL_INVOCATIONS["codex-shell-argv-lc"]),
                                _codex_result("shell", code=1)],
    "codex-no-exit-code": [_with_ids(SENTINEL_INVOCATIONS["codex-exec-command"]),
                           _codex_result("exec_command", output="Process running with session ID 7\n"
                                         + capture_session.MARK_OK_LINE)],
    "codex-missing-result": [_with_ids(SENTINEL_INVOCATIONS["codex-exec-command"])],
    "codex-result-for-another-id": [_with_ids(SENTINEL_INVOCATIONS["codex-exec-command"]),
                                    _codex_result("exec_command", cid="call_other")],
}


@pytest.mark.parametrize("case", sorted(SENTINEL_NOT_RUN))
def test_sentinel_that_did_not_run_successfully_does_not_count(case):
    st = _purge_state(SENTINEL_NOT_RUN[case])
    assert not st["purge"] and not st["held"], case
    assert st["purge_src"] == set() and st["held_src"] == set()


@pytest.mark.parametrize("kind", sorted(SENTINEL_INVOCATIONS))
def test_sentinel_with_a_successful_result_counts(kind):
    if "@" in json.dumps(SENTINEL_INVOCATIONS[kind]):
        pytest.skip("absolute-path forms resolve against an instance: covered end to end above")
    st = _purge_state(_with_ok(SENTINEL_INVOCATIONS[kind]))
    assert st["purge"] and st["purge_src"] == {"sentinel"} and not st["held"]


def test_claude_sentinel_result_as_text_blocks_counts():
    st = _purge_state([CLAUDE_CALL, _claude_result([{"type": "text", "text": OK_STDOUT}])])
    assert st["purge"]


def test_declined_sentinel_keeps_the_session_captured_end_to_end(tmp_path):
    hooks, home = _instance(tmp_path), tmp_path / "bw-home"
    proj = _wired(tmp_path)
    t = tmp_path / "t.jsonl"
    _write_records(t, _work_records() + SENTINEL_NOT_RUN["claude-declined"])
    assert _run(hooks, proj, t, "sess-d", home, event="SessionEnd").returncode == 0
    assert (proj / ".bailiwick-outputs" / "raw" / "sess-d.jsonl").exists() and not _held(proj, "sess-d")
    assert "purge session" not in _health_text(home)


def test_sentinel_result_on_a_later_stop_retracts_the_earlier_capture(tmp_path):
    """Call with no result yet -> captured; once its successful result lands, the next Stop retracts."""
    hooks, home = _instance(tmp_path), tmp_path / "bw-home"
    proj = _wired(tmp_path)
    t = tmp_path / "t.jsonl"
    raw = proj / ".bailiwick-outputs" / "raw"
    _write_records(t, _work_records() + [CLAUDE_CALL])
    assert _run(hooks, proj, t, "sess-l", home).returncode == 0
    assert (raw / "sess-l.jsonl").exists(), "no result yet: not counted"
    _write_records(t, _work_records() + [CLAUDE_CALL, _claude_result()])
    assert _run(hooks, proj, t, "sess-l", home).returncode == 0
    assert not (raw / "sess-l.jsonl").exists() and "detected by: sentinel;" in _health_text(home)


def test_code_mode_sentinel_only_holds(tmp_path, monkeypatch):
    """A code-mode cell controls what its own result says, so even a 'successful' one only holds."""
    st = _purge_state(_with_ok(CODE_MODE_SENTINEL))
    assert not st["purge"] and st["held"] and st["held_src"] == {"sentinel (unconfirmed)"}
    st = _purge_state([_with_ids(CODE_MODE_SENTINEL), _codex_result("exec", code=1)])
    assert not st["held"], "failed run: not even a hold"
    out = _inproc(tmp_path, monkeypatch, _work_records() + _with_ok(CODE_MODE_SENTINEL))
    assert out["captured"] and out["held"] and out["calls"] == {"drop": 0, "retract": 0}


# Forgery: the EXECUTED field runs printf of the success line while a stray/nested key names the
# sentinel. The guardrail only sees the executed command, so it never asks; these must not count.
_OK_PRINTF = "printf '%s\\n' '" + capture_session.MARK_OK_LINE + "'"
CODEX_FORGED = {
    "shell_command-extra-cmd": ("shell_command", {"command": _OK_PRINTF, "cmd": "bash " + MARK}),
    "exec_command-nested-cmd": ("exec_command", {"cmd": _OK_PRINTF, "extra": {"cmd": "bash " + MARK}}),
    "shell-argv-extra-cmd": ("shell", {"command": ["bash", "-lc", _OK_PRINTF], "cmd": "bash " + MARK}),
    "exec_command-cmd-is-list": ("exec_command", {"cmd": ["bash", "-lc", "bash " + MARK]}),
    "shell_command-command-is-list": ("shell_command", {"command": ["bash", "-lc", "bash " + MARK]}),
    "shell-command-is-str": ("shell", {"command": "bash " + MARK}),
}
# The legitimate counterpart of each forged shape: the sentinel in the field the tool executes.
CODEX_LEGIT = {
    "shell_command": ("shell_command", {"command": "bash " + MARK, "workdir": "/x"}),
    "exec_command": ("exec_command", {"cmd": "bash " + MARK, "yield_time_ms": 1000}),
    "shell": ("shell", {"command": ["bash", "-lc", "bash " + MARK], "workdir": "/x"}),
}


@pytest.mark.parametrize("case", sorted(CODEX_FORGED))
def test_codex_sentinel_named_outside_the_executed_field_does_not_count(case):
    name, args = CODEX_FORGED[case]
    st = _purge_state(_with_ok(_codex_tool(name, args)))
    assert not st["purge"] and not st["held"], case
    assert "sentinel" not in st["purge_src"]


def test_codex_non_json_arguments_are_not_a_sentinel():
    rec = _with_ids(_codex_tool("exec_command", {}))
    rec["payload"]["arguments"] = '{"cmd": "bash ' + MARK.replace('"', '\\"') + '"'  # truncated JSON
    st = _purge_state([rec, _codex_result("exec_command")])
    assert not st["purge"] and not st["held"]


@pytest.mark.parametrize("case", sorted(CODEX_LEGIT))
def test_codex_sentinel_in_the_executed_field_counts(case):
    name, args = CODEX_LEGIT[case]
    st = _purge_state(_with_ok(_codex_tool(name, args)))
    assert st["purge"] and st["purge_src"] == {"sentinel"} and not st["held"], case


def test_is_meta_command_header_is_not_a_typed_command():
    """isMeta user records are harness-injected text, never something the user typed."""
    meta = json.loads(json.dumps(PURGE_INVOCATIONS["slash-command-string"]))
    meta["isMeta"] = True
    st = _purge_state([meta])
    assert not st["purge"] and not st["held"]
    st = _purge_state([PURGE_INVOCATIONS["slash-command-string"]])
    assert st["purge"] and st["purge_src"] == {"slash command"}, "the typed (non-meta) record still counts"


def test_agent_skill_then_confirmed_sentinel_is_a_trusted_skip(tmp_path, monkeypatch):
    """The model-invoked skill alone only holds; once the sentinel it runs is confirmed (asked, run
    successfully, main transcript), the session is a trusted skip and earlier captures are retracted."""
    main_recs = (_work_records() + [PURGE_INVOCATIONS["skill-tool"]]
                 + _with_ok(SENTINEL_INVOCATIONS["bash-bailiwick"]))
    out = _inproc(tmp_path, monkeypatch, main_recs)
    assert not out["captured"] and out["calls"] == {"drop": 1, "retract": 1}
    assert "detected by: sentinel, skill (unconfirmed);" in out["health"], out["health"]


def test_every_sentinel_form_the_detector_accepts_makes_the_guardrail_ask(tmp_path):
    """Parity: a command capture_session.py reads as the sentinel is never agent-silent."""
    hooks = _instance(tmp_path)
    guard = os.path.join(HOOKS, "guardrails.py")
    env = dict(os.environ, BAILIWICK_SHADOW="1", BAILIWICK_HOME=str(tmp_path / "gh"),
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    env.pop("BAILIWICK_BREAK_GLASS", None)
    env.pop("CLAUDE_PROJECT_DIR", None)
    checked = 0
    for kind, rec in SENTINEL_INVOCATIONS.items():
        rec = _sentinel_rec(tmp_path, hooks, rec)
        block = (rec.get("message") or {}).get("content", [{}])[0]
        if block.get("name") != "Bash":
            continue  # Codex records: same command strings, covered by the guardrail's own tests
        cmd = block["input"]["command"]
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(tmp_path)})
        r = subprocess.run([sys.executable, guard], input=payload, text=True, capture_output=True, env=env)
        decision = json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] if r.stdout.strip() else None
        assert decision == "ask", (kind, cmd)
        checked += 1
    assert checked >= 6


def test_skip_health_line_names_skill_and_slash_and_config_sources(tmp_path):
    for i, (cfg, rec, label) in enumerate([
            (None, PURGE_INVOCATIONS["skill-tool"], "detected by: skill (unconfirmed))"),
            (None, PURGE_INVOCATIONS["slash-command-string"], "detected by: slash command;"),
            (None, PURGE_INVOCATIONS["codex-dollar"], "detected by: slash command;"),
            (None, PURGE_INVOCATIONS["codex-skill-inject"], "detected by: skill (unconfirmed))"),
            ({"capture": {"skip_skills": ["drill-purge"]}}, DRILL_INVOCATIONS["slash-command"],
             "detected by: config;"),
            ({"capture": {"skip_skills": ["drill-purge"]}}, DRILL_INVOCATIONS["skill-tool"],
             "detected by: config (unconfirmed))")]):
        d = tmp_path / "c{}".format(i)
        d.mkdir()
        out = _session_full(d, cfg, rec)
        # Unconfirmed (agent-originated) triggers are held local; trusted ones are skipped.
        assert out["captured"] == ("unconfirmed" in label) == out["held"], label
        assert label in out["health"], (label, out["health"])
        assert "drill-purge" not in out["health"] and "acme" not in out["health"]


def test_sentinel_script_writes_nothing_and_refuses_arguments(tmp_path):
    script = os.path.join(HOOKS, "mark_purge_session.sh")
    env = dict(os.environ, HOME=str(tmp_path), BAILIWICK_HOME=str(tmp_path / "bw"))
    r = subprocess.run(["bash", script], cwd=str(tmp_path), env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "purge session marked" in r.stdout
    assert capture_session.MARK_OK_LINE == r.stdout.splitlines()[0], "the detector's success line"
    assert 'bash "$BAILIWICK/hooks/mark_purge_session.sh"' in r.stdout, "prints the accepted form"
    assert list(tmp_path.iterdir()) == [], "the sentinel writes nothing"
    r = subprocess.run(["bash", script, "acme"], cwd=str(tmp_path), env=env, capture_output=True, text=True)
    assert r.returncode == 2 and "NOT marked" in r.stderr and "acme" not in r.stdout + r.stderr


# ---- drill self-defence (BW_DRILL_SANDBOX) -------------------------------------------------------
STALE_DRILL = "BW_DRILL_SANDBOX set but no drill sandbox applies"


def _drill(tmp_path, marker=True, proj_inside=True):
    """(hooks, home, proj, transcript, sandbox): a sandbox dir, optionally marked, and a wired project
    inside or outside it."""
    hooks, home = _instance(tmp_path), tmp_path / "bw-home"
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    if marker:
        (sandbox / ".drill-sandbox").write_text('{"kind": "bailiwick-drill"}')
    proj = (sandbox if proj_inside else tmp_path) / "dproj"
    proj.mkdir()
    (proj / "CLAUDE.local.md").write_text("$BAILIWICK\n")
    t = tmp_path / "t.jsonl"
    _write_records(t, _work_records())
    return hooks, home, proj, t, sandbox


def test_drill_sandbox_foreign_clone_does_nothing(tmp_path):
    hooks, home, proj, t, sandbox = _drill(tmp_path)
    (sandbox / "framework").mkdir()
    r = _run(hooks, proj, t, "sess-d", home, extra_env={"BW_DRILL_SANDBOX": str(sandbox)})
    assert r.returncode == 0, r.stderr
    assert not (proj / ".bailiwick-outputs" / "raw" / "sess-d.jsonl").exists()
    assert "drill sandbox active and this is not its framework copy" in _health_text(home)


def test_drill_sandbox_own_framework_copy_still_captures(tmp_path):
    hooks, home, proj, t, sandbox = _drill(tmp_path)
    (sandbox / "framework").symlink_to(tmp_path / "inst")  # compared by realpath
    r = _run(hooks, proj, t, "sess-d", home, extra_env={"BW_DRILL_SANDBOX": str(sandbox)})
    assert r.returncode == 0, r.stderr
    assert (proj / ".bailiwick-outputs" / "raw" / "sess-d.jsonl").exists()


@pytest.mark.parametrize("marker,inside", [(False, True), (True, False), (False, False)],
                         ids=["no-marker", "project-outside", "neither"])
def test_stale_drill_sandbox_var_is_ignored_with_a_warn(tmp_path, marker, inside):
    """A leaked/stale BW_DRILL_SANDBOX must never turn capture into a silent no-op (data loss)."""
    hooks, home, proj, t, sandbox = _drill(tmp_path, marker=marker, proj_inside=inside)
    r = _run(hooks, proj, t, "sess-d", home, extra_env={"BW_DRILL_SANDBOX": str(sandbox)})
    assert r.returncode == 0, r.stderr
    assert (proj / ".bailiwick-outputs" / "raw" / "sess-d.jsonl").exists(), "captured normally"
    health = _health_text(home)
    assert STALE_DRILL in health and str(sandbox) not in health, "warned, content-free"


@pytest.mark.parametrize("foreign", [False, True], ids=["stale-var", "active-foreign-sandbox"])
def test_drill_var_is_silent_in_an_unwired_repo(tmp_path, foreign):
    """The drill check runs after the wiring gate: an unwired repo writes nothing, not even health."""
    hooks, home, proj, t, sandbox = _drill(tmp_path, marker=foreign)
    if foreign:
        (sandbox / "framework").mkdir()
    (proj / "CLAUDE.local.md").unlink()  # unwired
    r = _run(hooks, proj, t, "sess-d", home, extra_env={"BW_DRILL_SANDBOX": str(sandbox)})
    assert r.returncode == 0, r.stderr
    assert not (proj / ".bailiwick-outputs").exists()
    assert _health_text(home) == ""


def test_stale_drill_sandbox_var_pointing_nowhere_is_ignored(tmp_path):
    hooks, home, proj, t, _ = _drill(tmp_path)
    r = _run(hooks, proj, t, "sess-d", home, extra_env={"BW_DRILL_SANDBOX": str(tmp_path / "gone")})
    assert r.returncode == 0 and (proj / ".bailiwick-outputs" / "raw" / "sess-d.jsonl").exists()
    assert STALE_DRILL in _health_text(home)


# ---- atomic header writes + ledger lock -----------------------------------------------------------
def test_write_atomic_replaces_whole_and_leaves_no_temp(tmp_path):
    path = str(tmp_path / "s.md")
    capture_session.write_atomic(path, "old\n")
    capture_session.write_atomic(path, "# Raw capture\n\n- purge_detection: error\n")
    assert open(path).read() == "# Raw capture\n\n- purge_detection: error\n"
    assert sorted(os.listdir(str(tmp_path))) == ["s.md"], "no .tmp left behind"


def test_write_atomic_never_exposes_a_partial_file(tmp_path, monkeypatch):
    """The target is untouched until the rename: a failed write leaves the old file whole and no temp."""
    path = str(tmp_path / "s.md")
    capture_session.write_atomic(path, "- purge_detection: error\n")
    seen = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append(open(dst).read())  # what a parallel reader would see right before the rename
        real_replace(src, dst)
    monkeypatch.setattr(capture_session.os, "replace", spy)
    capture_session.write_atomic(path, "- purge_detection: error\n- captured: x\n")
    assert seen == ["- purge_detection: error\n"], "target never truncated before the rename"

    def boom(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(capture_session.os, "replace", boom)
    with pytest.raises(OSError):
        capture_session.write_atomic(path, "partial")
    assert open(path).read() == "- purge_detection: error\n- captured: x\n"
    assert sorted(os.listdir(str(tmp_path))) == ["s.md"]


def test_ledger_lock_gives_up_within_a_third_of_a_second(tmp_path):
    import time
    lock = str(tmp_path / "l.lock")
    os.mkdir(lock)
    t0 = time.time()
    assert capture_session._ledger_lock(lock) is False
    assert time.time() - t0 < 0.6


def test_bad_skip_config_warns_once_per_run(tmp_path):
    hooks, home = _instance(tmp_path, {"capture": {"skip_skills": "nope"}}), tmp_path / "bw-home"
    proj, t = _session(tmp_path, MAIN_WORK, sid="sess-w")
    sub = t.parent / t.stem / "subagents"
    sub.mkdir(parents=True)
    _write_records(sub / "agent-a1.jsonl", _work_records())
    assert _run(hooks, proj, t, "sess-w", home).returncode == 0
    assert _health_text(home).count("capture.skip_skills is not a list of skill names") == 1


# ---- configurable skip skills (`capture.skip_skills`) --------------------------------------------
DRILL_INVOCATIONS = {
    "skill-tool": _rec_tool("Skill", {"skill": "drill-purge", "args": "acme"}),
    "slash-command": _rec_user(_cmd_header("drill-purge", "acme")),
    "codex-dollar": _codex_user("$bailiwick-drill-purge acme"),
    "codex-skill-inject": _codex_user("<skill>\n<name>bailiwick-drill-purge</name>\n<path>/x</path>"),
}


def _session_full(tmp_path, cfg, record):
    """{captured, held, health} for one SessionEnd over work + `record` + work."""
    hooks, home = _instance(tmp_path, cfg), tmp_path / "bw-home"
    proj = _wired(tmp_path)
    t = tmp_path / "t.jsonl"
    _write_records(t, _work_records() + [record] + _work_records())
    r = _run(hooks, proj, t, "sess-c", home, event="SessionEnd")
    assert r.returncode == 0, r.stderr
    return {"captured": (proj / ".bailiwick-outputs" / "raw" / "sess-c.jsonl").exists(),
            "held": _held(proj, "sess-c"), "health": _health_text(home)}


def _session_with(tmp_path, cfg, record):
    out = _session_full(tmp_path, cfg, record)
    return out["captured"], out["health"]


@pytest.mark.parametrize("kind", ["slash-command", "codex-dollar"])
def test_configured_skip_skill_is_not_captured(tmp_path, kind):
    """A configured name TYPED by the user: full skip."""
    captured, health = _session_with(
        tmp_path, {"capture": {"skip_skills": ["purge", "drill-purge"]}}, DRILL_INVOCATIONS[kind])
    assert not captured
    assert "capture skipped: purge session" in health


@pytest.mark.parametrize("kind", ["skill-tool", "codex-skill-inject"])
def test_configured_skip_skill_reached_by_the_agent_is_held(tmp_path, kind):
    """A configured name reached via the Skill tool / an injected body: unconfirmed, held local.
    (Was: skipped — the tier change makes any agent-originated trigger a hold.)"""
    out = _session_full(tmp_path, {"capture": {"skip_skills": ["purge", "drill-purge"]}}, DRILL_INVOCATIONS[kind])
    assert out["captured"] and out["held"]
    assert "config (unconfirmed)" in out["health"] and "capture skipped: purge session" not in out["health"]


@pytest.mark.parametrize("cfg", [None, {"capture": {}}, {"capture": {"skip_skills": ["purge"]}}])
def test_default_or_unlisted_skill_is_captured(tmp_path, cfg):
    for kind in ("slash-command", "skill-tool"):
        out = _session_full(tmp_path / kind, cfg, DRILL_INVOCATIONS[kind])
        assert out["captured"] and not out["held"], "drill-purge is skipped/held only when configured"


@pytest.mark.parametrize("bad", ["drill-purge", [1, 2], ["ok", None], [".*"], ["a b"], {"x": 1}, 7])
def test_bad_skip_config_falls_back_to_default_with_warning(tmp_path, bad):
    cfg = {"capture": {"skip_skills": bad}}
    out = _session_full(tmp_path, cfg, DRILL_INVOCATIONS["slash-command"])
    captured, health = out["captured"] and not out["held"], out["health"]
    assert captured, "bad config must never widen the skip"
    assert "capture.skip_skills is not a list of skill names" in health


def test_bad_skip_config_still_skips_plain_purge(tmp_path):
    captured, _ = _session_with(tmp_path, {"capture": {"skip_skills": "nope"}},
                                PURGE_INVOCATIONS["slash-command-string"])
    assert not captured


@pytest.mark.parametrize("names", [[], ["drill-purge"]])
def test_configured_list_never_removes_purge(tmp_path, names):
    """The list only adds names: an empty or purge-less list still skips /purge sessions (typed), and
    still holds an agent-reached one."""
    captured, _ = _session_with(tmp_path, {"capture": {"skip_skills": names}},
                                PURGE_INVOCATIONS["slash-command-string"])
    assert not captured
    out = _session_full(tmp_path / "skill", {"capture": {"skip_skills": names}}, PURGE_INVOCATIONS["skill-tool"])
    assert out["held"]


def test_skip_matching_is_exact_per_name(tmp_path):
    cfg = {"capture": {"skip_skills": ["drill-purge"]}}
    for rec in (_rec_tool("Skill", {"skill": "drill-purger"}), _rec_tool("Skill", {"skill": "x:drill-purge"}),
                _rec_user(_cmd_header("pre-drill-purge")), _codex_user("$bailiwick-drill-purger x")):
        d = tmp_path / str(abs(hash(json.dumps(rec))))
        d.mkdir()
        out = _session_full(d, cfg, rec)
        assert out["captured"] and not out["held"], rec
