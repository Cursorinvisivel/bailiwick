#!/usr/bin/env python3
"""Contract tests for hooks/guardrails.py — the runtime guardrail engine.

These are executable documentation of the guardrail's decision contract. They run it as a
subprocess (the real stdin JSON -> stdout decision path the harness uses) for each of the three
adapters (claude / codex / gemini), plus a handful of white-box unit tests for the pure helpers.

Run:  python -m pytest tests/ -q      (or just: python -m pytest)

Isolation: every subprocess gets BAILIWICK_HOME pointed at a tmp dir, so the audit log and
health shards never touch the real ~/.bailiwick. Activation is forced with BAILIWICK_SHADOW=1
(shadow-mode gate) rather than seeding marker files, except the explicit "inert when not wired" test.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARDRAILS = REPO_ROOT / "hooks" / "guardrails.py"


@pytest.fixture(autouse=True)
def _bw_home(tmp_path, monkeypatch):
    """Redirect the guardrail's audit/health writes into a throwaway dir for every test."""
    monkeypatch.setenv("BAILIWICK_HOME", str(tmp_path / "arch-home"))
    yield


def run_guard(command, adapter="claude", tool=None, wired=True, cwd=None, break_glass=False):
    """Invoke guardrails.py exactly as a pre-tool hook does. Returns (returncode, decision_or_None)."""
    if tool is None:
        tool = "run_shell_command" if adapter == "gemini" else "Bash"
    payload = {"tool_name": tool, "tool_input": {"command": command}, "cwd": cwd or str(REPO_ROOT)}
    env = dict(os.environ)
    env["BAILIWICK_HOME"] = os.environ["BAILIWICK_HOME"]
    env.pop("CLAUDE_PROJECT_DIR", None)  # let payload cwd drive project_dir deterministically
    if wired:
        env["BAILIWICK_SHADOW"] = "1"
    else:
        env.pop("BAILIWICK_SHADOW", None)
    if break_glass:
        env["BAILIWICK_BREAK_GLASS"] = "1"
    else:
        env.pop("BAILIWICK_BREAK_GLASS", None)
    args = [sys.executable, str(GUARDRAILS)]
    if adapter != "claude":
        args.append(adapter)
    proc = subprocess.run(args, input=json.dumps(payload), capture_output=True, text=True, env=env)
    out = proc.stdout.strip()
    return proc.returncode, (json.loads(out) if out else None)


def decision_of(parsed, adapter="claude"):
    """Pull the decision verb out of whichever contract the adapter uses."""
    if parsed is None:
        return None
    if adapter == "gemini":
        return parsed["decision"]
    return parsed["hookSpecificOutput"]["permissionDecision"]


# ----------------------------------------------------------------------------- ASK-IMPACT (claude)

ASK_IMPACT_COMMANDS = [
    "terraform apply",
    "terraform apply -auto-approve",
    "terraform -chdir=infra apply",
    "terragrunt destroy",
    "kubectl apply -f deploy.yaml",
    "kubectl delete pod nginx",
    "kubectl scale deploy/web --replicas=3",
    "kubectl rollout restart deploy/web",
    "helm upgrade myrel ./chart",
    "helm uninstall myrel",
    "gcloud compute instances delete vm-1",
    "gsutil rm gs://bucket/obj",
    "az group delete --name rg-1",
    "aws ec2 terminate-instances --instance-ids i-123",
    "aws s3 rm s3://bucket/key",
    "rm -rf /tmp/scratch",
    "rm -fr build",
    "rm --recursive node_modules",
    "git merge feature",
    "gh repo delete owner/repo",
]


@pytest.mark.parametrize("cmd", ASK_IMPACT_COMMANDS)
def test_ask_impact_asks(cmd):
    rc, parsed = run_guard(cmd)
    assert rc == 0
    assert decision_of(parsed) == "ask", f"{cmd!r} should ASK, got {parsed!r}"
    assert parsed["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert parsed["hookSpecificOutput"]["permissionDecisionReason"].startswith("[bailiwick guardrail]")


# ----------------------------------------------------------------------------- validation-only pass

PASS_COMMANDS = [
    "terraform plan",
    "terraform validate",
    "terraform fmt",
    "kubectl get pods",
    "kubectl describe pod nginx",
    "kubectl apply -f deploy.yaml --dry-run=client",   # dry-run exempt
    "helm template ./chart",
    "helm upgrade myrel ./chart --dry-run",            # dry-run exempt
    "gcloud compute instances list",
    "aws s3 ls s3://bucket",
    "git status",
    "git diff",
    "git log --oneline",
    "ls -la",
    "echo done && gcloud compute instances list",      # SEG: no mutating verb this segment
    'echo "terraform apply"',                          # verb is quoted -> not a command token
    'gcloud logging read \'protoPayload.methodName:"delete"\'',  # regression: quoted delete
    "gcloud compute instances list && echo delete",    # SEG stops at &&; delete is next segment
]


@pytest.mark.parametrize("cmd", PASS_COMMANDS)
def test_validation_only_passes(cmd):
    rc, parsed = run_guard(cmd)
    assert rc == 0
    assert parsed is None, f"{cmd!r} should PASS untouched, got {parsed!r}"


def test_terraform_apply_dry_run_still_asks():
    # terraform apply is NOT dry-run-exempt (its validation path is `plan`).
    rc, parsed = run_guard("terraform apply --dry-run")
    assert decision_of(parsed) == "ask"


# ----------------------------------------------------------------------------- ASK-GO-AHEAD

@pytest.mark.parametrize("cmd", [
    "git commit -m 'wip'",
    "git push origin main",
    "gh pr create --title x --body y",
    "gh pr merge 42",
])
def test_go_ahead_asks(cmd):
    rc, parsed = run_guard(cmd)
    assert decision_of(parsed) == "ask", f"{cmd!r} should ASK (go-ahead), got {parsed!r}"


# ----------------------------------------------------------------------------- ASK-SIGNATURE

def test_signature_in_commit_message_asks_and_is_labelled():
    cmd = 'git commit -m "feat: x\n\nCo-Authored-By: Claude <noreply@anthropic.com>"'
    rc, parsed = run_guard(cmd)
    assert decision_of(parsed) == "ask"
    assert "signature" in parsed["hookSpecificOutput"]["permissionDecisionReason"].lower()


def test_robot_emoji_signature_asks():
    cmd = 'git commit -m "chore: tidy \U0001F916"'
    rc, parsed = run_guard(cmd)
    assert decision_of(parsed) == "ask"
    assert "signature" in parsed["hookSpecificOutput"]["permissionDecisionReason"].lower()


# ----------------------------------------------------------------------------- EXEMPT plumbing

@pytest.mark.parametrize("cmd", [
    "bash /home/me/toolkit/hooks/capture_backup.sh push",
    "git -C capture-mirror push",
])
def test_capture_plumbing_exempt(cmd):
    rc, parsed = run_guard(cmd)
    assert parsed is None, f"{cmd!r} is dirty-zone plumbing and must never be blocked"


# ----------------------------------------------------------------------------- normalize / evasion

def test_line_continuation_does_not_evade():
    rc, parsed = run_guard("terraform \\\n apply")
    assert decision_of(parsed) == "ask", "backslash-newline split must be folded before matching"


# ----------------------------------------------------------------------------- self-gating

def test_inert_when_not_wired(tmp_path):
    # No shadow env, cwd has no complement marker -> guardrail must stay completely inert.
    rc, parsed = run_guard("terraform apply", wired=False, cwd=str(tmp_path))
    assert rc == 0
    assert parsed is None, "guardrail must not act outside bailiwick-wired repos"


def test_non_bash_tool_ignored():
    rc, parsed = run_guard("terraform apply", tool="Read")
    assert parsed is None


def test_malformed_payload_fails_open():
    env = dict(os.environ)
    env["BAILIWICK_SHADOW"] = "1"
    proc = subprocess.run([sys.executable, str(GUARDRAILS)], input="not json",
                          capture_output=True, text=True, env=env)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


# ----------------------------------------------------------------------------- adapters: gemini

def test_gemini_asks_with_its_own_contract():
    rc, parsed = run_guard("terraform apply", adapter="gemini")
    assert parsed == {"decision": "ask",
                      "reason": parsed["reason"]}  # shape check
    assert parsed["decision"] == "ask"
    assert parsed["reason"].startswith("[bailiwick guardrail]")


def test_gemini_ignores_non_shell_tool():
    rc, parsed = run_guard("terraform apply", adapter="gemini", tool="Bash")
    assert parsed is None  # gemini adapter only acts on run_shell_command


# ----------------------------------------------------------------------------- adapters: codex

def test_codex_denies_with_remedy():
    rc, parsed = run_guard("terraform apply", adapter="codex")
    assert decision_of(parsed) == "deny"  # codex has no ask
    reason = parsed["hookSpecificOutput"]["permissionDecisionReason"]
    assert "BAILIWICK_BREAK_GLASS" in reason, "codex deny must carry an actionable remedy"


def test_codex_break_glass_allows_once():
    rc, parsed = run_guard("terraform apply", adapter="codex", break_glass=True)
    assert rc == 0
    assert parsed is None, "codex break-glass is allow-once: no decision emitted"


# ----------------------------------------------------------------------------- white-box: helpers

@pytest.fixture(scope="module")
def guard_mod():
    spec = importlib.util.spec_from_file_location("guardrails_under_test", GUARDRAILS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_normalize_folds_continuations(guard_mod):
    assert guard_mod.normalize("rm -rf \\\n x") == "rm -rf  x"


def test_strip_quoted_blanks_quotes(guard_mod):
    assert "delete" not in guard_mod.strip_quoted("gcloud logging read 'x delete y'")
    assert "delete" not in guard_mod.strip_quoted('echo "please delete"')


@pytest.mark.parametrize("cmd", [
    "terraform apply", "kubectl delete pod x", "rm -rf x", "gcloud compute instances delete x",
])
def test_danger_prefilter_trips_on_destructive(guard_mod, cmd):
    assert guard_mod.DANGER_PREFILTER.search(cmd), f"prefilter must flag {cmd!r} for fail-closed"


@pytest.mark.parametrize("cmd", ["terraform plan", "kubectl get pods", "ls -la"])
def test_danger_prefilter_ignores_safe(guard_mod, cmd):
    assert not guard_mod.DANGER_PREFILTER.search(cmd)


def test_is_bailiwick_repo_marker_detection(guard_mod, tmp_path):
    assert not guard_mod.is_bailiwick_repo(str(tmp_path))
    (tmp_path / "CLAUDE.local.md").write_text("references $BAILIWICK here")
    assert guard_mod.is_bailiwick_repo(str(tmp_path))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
