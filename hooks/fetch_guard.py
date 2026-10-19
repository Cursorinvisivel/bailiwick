#!/usr/bin/env python3
"""Fetch-time URL allowlist for the /curate freshness research agent (Claude Code PreToolUse, WebFetch).

The freshness variant (agents/cloud-research-freshness.md) holds untrusted web content and an
outbound fetch; its prompt asks it to stay inside the source registry, but a prompt is not a
control. This hook enforces the registry before each fetch, using the same policy code the
orchestrator runs afterwards (skills/curate/scripts/check_source.py), so the two cannot drift.

Scope: only WebFetch calls made by the `bailiwick-cloud-research-freshness` subagent, identified
by the payload's `agent_type`. Every other caller passes untouched — general research keeps the
Cloud Research stage's broader source policy. Inside scope the hook fails CLOSED on errors it can
see: an unreadable registry, an unusable URL or an internal error denies the fetch, because an
unchecked fetch here is exactly the exfiltration path the hook exists to close. It fails OPEN when
it never runs or cannot tell the caller: no python3 on PATH, a crash before main(), a timeout, or a
payload without `agent_type`. A MISSING script is different: python3 exits 2, which Claude Code
treats as blocking, so a moved clone blocks every WebFetch until --install-tools is re-run
(scripts/doctor.sh flags hook paths that no longer exist).

Limits: this checks the URL the agent asks for. Redirects the fetch tool follows are not visible
here; the orchestrator's post-hoc check of reported destinations still applies. Under Gemini,
Codex and Copilot the generated adapters drop `tools:` and this hook does not run.
"""
import json
import os
import sys

AGENT = "bailiwick-cloud-research-freshness"
ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
# Appended, never prepended: run as `python3 -I`, the stdlib resolves first and the script
# directory is not implicitly on the path.
sys.path.append(os.path.join(ROOT, "skills", "curate", "scripts"))
sys.path.append(os.path.join(ROOT, "hooks"))


def emit(decision, reason):
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": "[bailiwick fetch guard] " + reason,
        }
    }, sys.stdout)
    sys.stdout.write("\n")


def _redact(url):
    """Host plus a short unsalted URL hash: a denied URL may carry claim text, so it is not logged
    raw. The hash is a correlation aid, not secrecy — a guessable value can be recovered."""
    if url is None:
        return "-"
    try:
        import hashlib
        from urllib.parse import urlsplit
        parts = urlsplit(str(url))
        digest = hashlib.sha256(str(url).encode("utf-8", "replace")).hexdigest()[:16]
        return "{}://{} sha256:{}".format(parts.scheme, parts.hostname or "?", digest)
    except Exception:
        return "unparseable"


def _audit(event, url):
    """Best-effort audit line in the guardrail log (never raises). The third column names the
    agent where guardrails.py writes a project path."""
    try:
        import datetime
        import bw_common
        home = bw_common.bw_home()
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "guardrail-audit.log"), "a", encoding="utf-8") as fh:
            fh.write("{}\t{}\t{}\t{}\n".format(
                datetime.datetime.now().isoformat(timespec="seconds"),
                event, AGENT, _redact(url)))
    except Exception:
        pass


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        # Cannot tell who is calling. Deny only if the freshness agent is plausibly the caller.
        if AGENT in raw:
            _audit("fetch-deny-malformed", None)
            emit("deny", "unreadable hook payload for the freshness agent — fetch denied (fail-closed).")
        return 0
    if payload.get("agent_type") != AGENT or payload.get("tool_name") != "WebFetch":
        return 0

    url = (payload.get("tool_input") or {}).get("url")
    try:
        import check_source
        sources = check_source.load_registry(check_source.REGISTRY)
        matches = check_source.matching_sources(url, sources)
        reason = "outside the freshness source registry's allowed prefixes"
    except Exception as exc:
        matches, reason = [], "URL rejected by the freshness policy: {}".format(exc)
    if matches:
        return 0
    _audit("fetch-deny", url)
    emit("deny", reason + " — fetch only registry URLs; report the gap instead of working around it.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        _audit("fetch-deny-error", None)
        emit("deny", "fetch guard internal error — fetch denied (fail-closed).")
        sys.exit(0)
