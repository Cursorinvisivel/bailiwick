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
