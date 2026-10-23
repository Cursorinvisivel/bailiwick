"""Contract tests for hooks/install_hooks.py — merge, adoption, and the guards around adoption.

Adoption re-points Bailiwick-owned hook commands installed by ANOTHER clone (renamed/retired
predecessor, old claude-code/hooks layout, baked canonical path) at this clone. The dangerous
edge is rewriting something the framework does NOT own — these tests pin the guard: a rewrite
is committed only when the result lands exactly on one of the template's own commands.
"""
import json
import os
import subprocess
import sys

HOOKS = os.path.join(os.path.dirname(__file__), "..", "hooks")
TEMPLATE = os.path.join(HOOKS, "settings.template.json")
ROOT = os.path.realpath(os.path.join(HOOKS, ".."))
HOOKS_DIR = os.path.join(ROOT, "hooks")


def run_installer(settings_path):
    # The installer also writes the fetch-guard launcher under BAILIWICK_HOME — keep it in tmp.
    env = dict(os.environ, BAILIWICK_HOME=str(launcher_home(settings_path)))
    return subprocess.run(
        [sys.executable, os.path.join(HOOKS, "install_hooks.py"), str(settings_path), TEMPLATE],
        capture_output=True, text=True, env=env,
    )


def launcher_home(settings_path):
    return os.path.join(os.path.dirname(str(settings_path)), "bw-home")


def run_launcher(settings_path, payload):
    launcher = os.path.join(launcher_home(settings_path), "hooks", "fetch_guard.py")
    env = dict(os.environ, BAILIWICK_HOME=launcher_home(settings_path))
    r = subprocess.run([sys.executable, "-I", launcher, "--scoped"], input=json.dumps(payload),
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] if r.stdout.strip() else None


OFF_REGISTRY = {"tool_name": "WebFetch", "tool_input": {"url": "https://evil.test/", "prompt": "x"}}


def test_fetch_launcher_runs_this_clones_guard_without_agent_type(tmp_path):
    s = tmp_path / "settings.json"
    r = run_installer(s)
    assert "LAUNCHER: " in r.stdout
    assert run_launcher(s, OFF_REGISTRY) == "deny"
    allowed = {"tool_name": "WebFetch",
               "tool_input": {"url": "https://docs.cloud.google.com/iam/docs/release-notes"}}
    assert run_launcher(s, allowed) is None
    assert "LAUNCHER: " not in run_installer(s).stdout, "unchanged launcher is not rewritten"


def test_fetch_launcher_denies_when_the_clone_is_gone(tmp_path):
    s = tmp_path / "settings.json"
    run_installer(s)
    launcher = os.path.join(launcher_home(s), "hooks", "fetch_guard.py")
    text = open(launcher).read().replace(os.path.join(HOOKS_DIR, "fetch_guard.py"),
                                         str(tmp_path / "moved" / "fetch_guard.py"))
    open(launcher, "w").write(text)
    assert run_launcher(s, OFF_REGISTRY) == "deny"
    log = open(os.path.join(launcher_home(s), "guardrail-audit.log")).read()
    assert "fetch-deny-launcher:scoped" in log, "launcher failures are audited"


def test_unwritable_launcher_home_still_installs_hooks(tmp_path):
    s = tmp_path / "settings.json"
    os.makedirs(launcher_home(s))
    open(os.path.join(launcher_home(s), "hooks"), "w").write("a file where the directory goes")
    r = run_installer(s)
    assert r.returncode == 0, r.stderr
    assert "WARN: fetch-guard launcher not written" in r.stdout and "INSTALLED" in r.stdout
    assert any("fetch_guard.py" in c for c in commands(s)), "settings written despite the launcher failure"


def test_launcher_owner_line_is_plain_text_on_windows_paths():
    sys.path.insert(0, HOOKS_DIR)
    import install_hooks
    content = install_hooks.launcher_content(r"C:\Users\me\bailiwick\hooks\fetch_guard.py")
    # bootstrap.ps1 matches this line; the TARGET repr doubles every backslash.
    assert "# bailiwick-launcher-target: C:/Users/me/bailiwick/hooks/fetch_guard.py\n" in content
    assert "TARGET = 'C:\\\\Users" in content


def test_agent_frontmatter_hook_calls_the_launcher_path():
    agent = open(os.path.join(ROOT, "agents", "cloud-research-freshness.md")).read().split("\n---\n")[0]
    assert "matcher: \"WebFetch\"" in agent
    assert '"${BAILIWICK_HOME:-$HOME/.bailiwick}/hooks/fetch_guard.py" --scoped' in agent


def commands(settings_path):
    cfg = json.load(open(settings_path))
    return [
        h["command"]
        for groups in cfg.get("hooks", {}).values()
        for grp in groups
        for h in grp.get("hooks", [])
    ]


def write_settings(path, hooks):
    path.write_text(json.dumps({"model": "keep-me", "hooks": hooks}, indent=2))


def test_fresh_install_then_idempotent(tmp_path):
    s = tmp_path / "settings.json"
    r = run_installer(s)
    assert r.returncode == 0 and "INSTALLED" in r.stdout
    assert any(HOOKS_DIR in c for c in commands(s)), "commands must point at this clone"
    r = run_installer(s)
    assert r.returncode == 0 and "PRESENT" in r.stdout, "second run must be a no-op"
    cfg = json.load(open(s))
    guard = [g for g in cfg["hooks"]["PreToolUse"]
             if any("fetch_guard.py" in h.get("command", "") for h in g["hooks"])]
    assert [g.get("matcher") for g in guard] == ["WebFetch"], "fetch guard must stay WebFetch-scoped"


def test_pre_fetch_guard_install_gains_the_guard_once(tmp_path):
    s = tmp_path / "settings.json"
    guard_group = {"matcher": "Bash", "hooks": [{"type": "command",
                   "command": f"python3 {HOOKS_DIR}/guardrails.py"}]}
    write_settings(s, {
        "Stop": [{"hooks": [{"type": "command", "command": f"python3 {HOOKS_DIR}/capture_session.py"}]}],
        "PreToolUse": [guard_group],
    })
    r = run_installer(s)
    assert r.returncode == 0 and "INSTALLED" in r.stdout
    cfg = json.load(open(s))
    assert cfg["model"] == "keep-me"
    pre = cfg["hooks"]["PreToolUse"]
    assert pre[0] == guard_group, "existing group untouched"
    assert [g["matcher"] for g in pre if "fetch_guard.py" in g["hooks"][0]["command"]] == ["WebFetch"]
    assert "PRESENT" in run_installer(s).stdout


def test_foreign_clone_and_old_layout_are_adopted(tmp_path):
    s = tmp_path / "settings.json"
    write_settings(s, {
        "SessionStart": [{"hooks": [{"type": "command",
            "command": "bash /fake/old-fw/claude-code/hooks/session_start.sh"}]}],
        "Stop": [{"hooks": [{"type": "command",
            "command": "python3 /fake/old-fw/claude-code/hooks/capture_session.py"}]},
                 {"hooks": [{"type": "command",
            "command": "python3 /path/to/bailiwick/hooks/capture_session.py"}]}],
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command",
            "command": "python3 /fake/old-fw/claude-code/hooks/guardrails.py"}]}],
    })
    r = run_installer(s)
    assert r.returncode == 0
    assert "MIGRATED: /fake/old-fw/claude-code/hooks ->" in r.stdout
    cmds = commands(s)
    assert not any("/fake/old-fw" in c or "/path/to/bailiwick" in c for c in cmds), \
        "no stale roots may survive adoption"
    cfg = json.load(open(s))
    # dedupe: the two Stop capture_session commands collapsed onto one WITHIN the event
    # (the same command legitimately appears again under SessionEnd — that's the template)
    stop_cmds = [h["command"] for g in cfg["hooks"]["Stop"] for h in g["hooks"]]
    assert stop_cmds.count("python3 {}/capture_session.py".format(HOOKS_DIR)) == 1
    # matcher preserved on the adopted guardrail group
    pre = [g for g in cfg["hooks"]["PreToolUse"] if any("guardrails.py" in h.get("command", "") for h in g["hooks"])]
    assert pre and pre[0].get("matcher") == "Bash"
    assert cfg["model"] == "keep-me", "unrelated settings keys must survive"


def test_user_hook_reusing_owned_filename_is_not_hijacked(tmp_path):
    s = tmp_path / "settings.json"
    mine = "bash /home/u/dotfiles/hooks/session_start.sh --my-own-thing"
    write_settings(s, {"SessionStart": [{"hooks": [{"type": "command", "command": mine}]}]})
    run_installer(s)
    assert mine in commands(s), \
        "a user hook with an owned filename under a hooks/ dir must NOT be re-pointed (extra args break the template match)"


def test_quoted_path_with_spaces_is_not_splice_corrupted(tmp_path):
    s = tmp_path / "settings.json"
    spaced = 'python3 "/fake/sp aced/hooks/capture_session.py"'
    write_settings(s, {"SessionEnd": [{"hooks": [{"type": "command", "command": spaced}]}]})
    run_installer(s)
    assert spaced in commands(s), \
        "a quoted spaced path must survive untouched (the \\S* match starts mid-path there)"


def test_unowned_names_and_non_hooks_paths_untouched(tmp_path):
    s = tmp_path / "settings.json"
    keep = [
        "bash /home/u/my/own/hooks/notify.sh",          # unowned filename under hooks/
        "python3 /home/u/scripts/capture_session.py",   # owned filename, no hooks/ segment
    ]
    write_settings(s, {"Stop": [{"hooks": [{"type": "command", "command": c}]} for c in keep]})
    run_installer(s)
    cmds = commands(s)
    for c in keep:
        assert c in cmds


def test_invalid_settings_json_refused_untouched(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text("{ not json")
    r = run_installer(s)
    assert r.returncode != 0 and "ERROR" in r.stdout
    assert s.read_text() == "{ not json", "invalid file must be left exactly as it was"
