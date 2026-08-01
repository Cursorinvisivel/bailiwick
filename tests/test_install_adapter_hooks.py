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


def test_legacy_markers_are_swept_not_duplicated(tmp_path):
    # A prior install under the framework's former name left old-marker blocks behind;
    # the sweep must remove exactly those and leave ONE current guardrail per adapter.
    (tmp_path / "codex").mkdir()
    (tmp_path / "codex" / "config.toml").write_text(
        "# keep me\n"
        "# BEGIN arch-toolkit hooks\n[[hooks.PreToolUse]]\nstale = true\n# END arch-toolkit hooks\n")
    (tmp_path / "gemini").mkdir()
    (tmp_path / "gemini" / "settings.json").write_text(json.dumps({
        "hooks": {"BeforeTool": [{"matcher": "run_shell_command",
                                  "hooks": [{"name": "arch-toolkit-guardrail"}]}]},
    }))
    r = run(tmp_path)
    assert r.returncode == 0
    toml = (tmp_path / "codex" / "config.toml").read_text()
    assert "arch-toolkit" not in toml, "legacy block must be swept"
    assert toml.count("BEGIN bailiwick hooks") == 1
    assert "# keep me" in toml
    cfg = json.loads((tmp_path / "gemini" / "settings.json").read_text())
    names = inner_names(cfg)
    assert names.count("bailiwick-guardrail") == 1 and "arch-toolkit-guardrail" not in names


def test_malformed_gemini_settings_refused_untouched(tmp_path):
    (tmp_path / "gemini").mkdir()
    (tmp_path / "gemini" / "settings.json").write_text("{ not json")
    r = run(tmp_path, "gemini")
    assert r.returncode != 0
    assert "ERROR" in r.stdout
    assert (tmp_path / "gemini" / "settings.json").read_text() == "{ not json"
