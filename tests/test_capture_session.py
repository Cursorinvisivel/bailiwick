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
