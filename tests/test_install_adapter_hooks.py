"""Contract tests for hooks/install_adapter_hooks.py — the Codex/Gemini guardrail wiring.

Same danger class as install_hooks.py (which has its own suite): these rewrite files the
framework does NOT own (~/.codex/config.toml, ~/.gemini/settings.json). The contract is
"touch only the managed block/entry, sweep only the framework's own legacy markers,
refuse rather than clobber on malformed input".
"""
import json
import os
import subprocess
import sys

HOOKS = os.path.join(os.path.dirname(__file__), "..", "hooks")
SCRIPT = os.path.join(HOOKS, "install_adapter_hooks.py")


def inner_names(cfg):
    """Hook names as gemini stores them — inside each BeforeTool group's hooks list."""
    return [h.get("name")
            for g in cfg.get("hooks", {}).get("BeforeTool", [])
            for h in (g.get("hooks", []) if isinstance(g, dict) else [])
            if isinstance(h, dict)]


def run(tmp_path, *args):
    env = dict(os.environ,
               CODEX_HOME=str(tmp_path / "codex"),
               GEMINI_HOME=str(tmp_path / "gemini"))
    return subprocess.run([sys.executable, SCRIPT, *args],
                          capture_output=True, text=True, env=env)


def test_fresh_install_then_idempotent(tmp_path):
    r = run(tmp_path)
    assert r.returncode == 0
    assert "codex: INSTALLED" in r.stdout and "gemini: INSTALLED" in r.stdout
    toml = (tmp_path / "codex" / "config.toml").read_text()
    assert "BEGIN bailiwick hooks" in toml and "guardrails.py" in toml
    cfg = json.loads((tmp_path / "gemini" / "settings.json").read_text())
    assert inner_names(cfg).count("bailiwick-guardrail") == 1
    r = run(tmp_path)
    assert r.returncode == 0
    assert "codex: PRESENT" in r.stdout and "gemini: PRESENT" in r.stdout


def test_unrelated_content_survives(tmp_path):
    (tmp_path / "codex").mkdir()
    (tmp_path / "codex" / "config.toml").write_text(
        '# my own header\n[model]\nname = "gpt-x"\n')
    (tmp_path / "gemini").mkdir()
    (tmp_path / "gemini" / "settings.json").write_text(json.dumps({
        "theme": "dark",
        "hooks": {"BeforeTool": [{"matcher": "x", "hooks": [{"name": "my-own-hook"}]}]},
    }))
    r = run(tmp_path)
    assert r.returncode == 0
    toml = (tmp_path / "codex" / "config.toml").read_text()
    assert "# my own header" in toml and '[model]' in toml and 'name = "gpt-x"' in toml
    cfg = json.loads((tmp_path / "gemini" / "settings.json").read_text())
    assert cfg["theme"] == "dark"
    names = inner_names(cfg)
    assert "my-own-hook" in names and "bailiwick-guardrail" in names


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


def test_malformed_gemini_settings_refused_untouched(tmp_path):
    (tmp_path / "gemini").mkdir()
    (tmp_path / "gemini" / "settings.json").write_text("{ not json")
    r = run(tmp_path, "gemini")
    assert r.returncode != 0
    assert "ERROR" in r.stdout
    assert (tmp_path / "gemini" / "settings.json").read_text() == "{ not json"
