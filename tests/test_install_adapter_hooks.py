"""Contract tests for hooks/install_adapter_hooks.py — the Codex/Antigravity guardrail wiring.

Same danger class as install_hooks.py (which has its own suite): these rewrite files the
framework does NOT own (~/.codex/config.toml, ~/.gemini/config/hooks.json). The contract is
"touch only the managed block/entry, sweep only the framework's own legacy markers,
refuse rather than clobber on malformed input".
"""
import json
import os
import subprocess
import sys

HOOKS = os.path.join(os.path.dirname(__file__), "..", "hooks")
SCRIPT = os.path.join(HOOKS, "install_adapter_hooks.py")


def run(tmp_path, *args):
    env = dict(os.environ,
               CODEX_HOME=str(tmp_path / "codex"),
               GEMINI_HOME=str(tmp_path / "gemini"))
    return subprocess.run([sys.executable, SCRIPT, *args],
                          capture_output=True, text=True, env=env)


def test_fresh_install_then_idempotent(tmp_path):
    r = run(tmp_path)
    assert r.returncode == 0
    assert "codex: INSTALLED" in r.stdout and "antigravity: INSTALLED" in r.stdout
    toml = (tmp_path / "codex" / "config.toml").read_text()
    assert "BEGIN bailiwick hooks" in toml and "guardrails.py" in toml
    hooks_file = tmp_path / "gemini" / "config" / "hooks.json"
    assert hooks_file.exists()
    cfg = json.loads(hooks_file.read_text())
    assert "bailiwick-guardrail" in cfg and "bailiwick-capture" in cfg
    assert cfg["bailiwick-guardrail"]["PreToolUse"][0]["matcher"] == "run_command"
    assert "guardrails.py" in cfg["bailiwick-guardrail"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "capture_session.py" in cfg["bailiwick-capture"]["Stop"][0]["command"]

    r = run(tmp_path)
    assert r.returncode == 0
    assert "codex: PRESENT" in r.stdout and "antigravity: PRESENT" in r.stdout


def test_unrelated_content_survives(tmp_path):
    (tmp_path / "codex").mkdir()
    (tmp_path / "codex" / "config.toml").write_text(
        '# my own header\n[model]\nname = "gpt-x"\n')
    (tmp_path / "gemini" / "config").mkdir(parents=True)
    (tmp_path / "gemini" / "config" / "hooks.json").write_text(json.dumps({
        "my-own-hook": {"PreToolUse": [{"matcher": "x", "hooks": [{"command": "echo 1"}]}]},
    }))
    r = run(tmp_path)
    assert r.returncode == 0
    toml = (tmp_path / "codex" / "config.toml").read_text()
    assert "# my own header" in toml and '[model]' in toml and 'name = "gpt-x"' in toml
    cfg = json.loads((tmp_path / "gemini" / "config" / "hooks.json").read_text())
    assert "my-own-hook" in cfg
    assert "bailiwick-guardrail" in cfg
    assert "bailiwick-capture" in cfg


def test_codex_capture_events_are_wired(tmp_path):
    # codex-cli >= 0.147 fires Stop/SessionEnd with the same payload Claude Code sends, so the
    # capture pair rides the same scripts. Without both events a Codex session is captured only
    # per-turn (Stop) or only on close (SessionEnd) — the pair is the contract.
    run(tmp_path)
    toml = (tmp_path / "codex" / "config.toml").read_text()
    for event in ("Stop", "SessionEnd"):
        assert "[[hooks.{}]]".format(event) in toml
        block = toml.split("[[hooks.{}]]".format(event), 1)[1]
        assert "capture_session.py" in block and "capture_backup.sh" in block


def test_pretooluse_stays_first_so_guardrail_trust_survives(tmp_path):
    # Codex keys hook trust by `<event>:<group>:<index>` over the hook definition. Appending the
    # capture events must not reorder or rewrite the guardrail, or every install re-prompts.
    run(tmp_path)
    toml = (tmp_path / "codex" / "config.toml").read_text()
    assert toml.index("[[hooks.PreToolUse]]") < toml.index("[[hooks.Stop]]") < toml.index("[[hooks.SessionEnd]]")


def test_existing_hook_trust_survives_reinstall(tmp_path):
    run(tmp_path)
    cfg = tmp_path / "codex" / "config.toml"
    toml = cfg.read_text().replace(
        "# END bailiwick hooks",
        '\n[hooks.state]\n\n[hooks.state."cfg:pre_tool_use:0:0"]\n'
        'trusted_hash = "sha256:abc"\nenabled = true\n# END bailiwick hooks')
    cfg.write_text(toml)
    r = run(tmp_path)
    assert r.returncode == 0
    after = cfg.read_text()
    assert "sha256:abc" in after, "a reinstall must not wipe the user's hook trust"
    assert after.count("[hooks.state]") == 1


def test_legacy_gemini_cleanup_and_deprecation_warning(tmp_path):
    # If legacy settings.json has BeforeTool bailiwick hook, it must be pruned with a warning.
    (tmp_path / "gemini").mkdir(parents=True)
    legacy_file = tmp_path / "gemini" / "settings.json"
    legacy_file.write_text(json.dumps({
        "theme": "dark",
        "hooks": {
            "BeforeTool": [
                {
                    "matcher": "run_shell_command",
                    "hooks": [{"name": "bailiwick-guardrail", "command": "python3 guard.py"}]
                }
            ]
        }
    }))
    r = run(tmp_path, "gemini")
    assert r.returncode == 0
    assert "gemini: WARNING: 'gemini' adapter is DEPRECATED" in r.stdout
    assert "Removed legacy Gemini CLI 'bailiwick-guardrail' hook" in r.stdout
    assert "antigravity: INSTALLED" in r.stdout

    # Legacy BeforeTool should be cleaned up, while unrelated settings (theme) survive
    after_legacy = json.loads(legacy_file.read_text())
    assert after_legacy.get("theme") == "dark"
    assert "BeforeTool" not in after_legacy.get("hooks", {})


def test_malformed_antigravity_hooks_refused_untouched(tmp_path):
    (tmp_path / "gemini" / "config").mkdir(parents=True)
    bad_file = tmp_path / "gemini" / "config" / "hooks.json"
    bad_file.write_text("{ not json")
    r = run(tmp_path, "antigravity")
    assert r.returncode != 0
    assert "ERROR" in r.stdout
    assert bad_file.read_text() == "{ not json"
