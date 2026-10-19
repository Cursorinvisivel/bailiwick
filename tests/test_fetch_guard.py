"""Contract tests for hooks/fetch_guard.py — the freshness agent's fetch-time URL allowlist.

Inside scope (WebFetch from bailiwick-cloud-research-freshness) the hook must deny anything the
registry does not allow and fail closed on errors; outside scope it must emit nothing at all.
Every subprocess gets BAILIWICK_HOME pointed at a tmp dir, so the real audit log is never touched.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "fetch_guard.py"
AGENT = "bailiwick-cloud-research-freshness"
ALLOWED = "https://docs.cloud.google.com/iam/docs/release-notes"


@pytest.fixture(autouse=True)
def bw_home(tmp_path, monkeypatch):
    home = tmp_path / "bw-home"
    monkeypatch.setenv("BAILIWICK_HOME", str(home))
    return home


def run(payload, hook=HOOK):
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    # -I as in the installed command (settings.template.json).
    return subprocess.run([sys.executable, "-I", str(hook)], input=stdin, capture_output=True,
                          text=True, env=dict(os.environ))


def fetch(url, agent_type=AGENT, tool="WebFetch"):
    payload = {"tool_name": tool, "tool_input": {"url": url, "prompt": "summarize"}}
    if agent_type is not None:
        payload["agent_type"] = agent_type
    return payload


def decision(result):
    assert result.returncode == 0, result.stderr
    if not result.stdout.strip():
        return None
    return json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]


def test_registry_url_passes_without_a_decision():
    assert decision(run(fetch(ALLOWED))) is None


@pytest.mark.parametrize("url", [
    "https://evil.test/?q=claim",
    "https://docs.cloud.google.com/iam/docs/..;/x",
    "https://cloud.google.com/blog/products/identity-security/example",
    "https://docs.cloud.google.com/iam/docs/release-notes#frag",
    "https://docs.cloud.google.com/iam/docs/release-notes?leak=1",
    "",
    None,
])
def test_out_of_registry_urls_are_denied(url):
    result = run(fetch(url))
    assert decision(result) == "deny"
    assert "fetch guard" in json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("payload", [
    fetch("https://evil.test/", agent_type=None),
    fetch("https://evil.test/", agent_type="bailiwick-cloud-research"),
    fetch("https://evil.test/", tool="WebSearch"),
])
def test_other_callers_and_tools_are_untouched(payload):
    assert decision(run(payload)) is None


@pytest.mark.parametrize("tool_input", ["https://evil.test/", None, ["https://evil.test/"]])
def test_unusable_tool_input_fails_closed(tool_input):
    assert decision(run({"agent_type": AGENT, "tool_name": "WebFetch", "tool_input": tool_input})) == "deny"


def test_missing_tool_name_is_not_a_fetch():
    assert decision(run({"agent_type": AGENT, "tool_input": {"url": "https://evil.test/"}})) is None


def test_deny_is_audited_without_the_raw_url(bw_home):
    run(fetch("https://evil.test/secret-claim-text"))
    log = (bw_home / "guardrail-audit.log").read_text()
    assert "fetch-deny" in log and AGENT in log and "https://evil.test sha256:" in log
    assert "secret-claim-text" not in log


def test_malformed_payload_from_the_freshness_agent_fails_closed():
    assert decision(run('{"agent_type": "%s", broken' % AGENT)) == "deny"


def test_unrelated_malformed_payload_is_ignored():
    assert decision(run("not json")) is None


def test_broken_registry_fails_closed(tmp_path):
    fake = tmp_path / "fw"
    (fake / "hooks").mkdir(parents=True)
    (fake / "skills/curate/scripts").mkdir(parents=True)
    (fake / "skills/curate/references").mkdir(parents=True)
    (fake / "hooks/fetch_guard.py").write_text(HOOK.read_text())
    (fake / "skills/curate/scripts/check_source.py").write_text(
        (ROOT / "skills/curate/scripts/check_source.py").read_text())
    (fake / "skills/curate/references/gcp-sources.json").write_text("{")
    assert decision(run(fetch(ALLOWED), hook=fake / "hooks/fetch_guard.py")) == "deny"
