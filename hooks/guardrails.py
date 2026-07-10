#!/usr/bin/env python3
"""Runtime guardrails for the bailiwick — one engine, three tool adapters.

Invoked as a pre-execution hook by:
  - Claude Code  (PreToolUse, Bash)            — no argument, or `claude`
  - Codex CLI    (PreToolUse, Bash)            — argument `codex`
  - Gemini CLI   (BeforeTool, run_shell_command) — argument `gemini`

All three send a JSON payload on stdin carrying the shell command; the tier evaluation is
identical, only payload parsing and the decision contract differ (see ADAPTER MAPPING below).
BEFORE the command runs, the framework's non-negotiable rules become enforced decisions
instead of mere instructions:

  - ASK-IMPACT (forced reconfirmation — even when the user instructed the agent):
          actions with real-world impact — terraform/terragrunt apply & destroy;
          kubectl apply/delete/patch/replace/scale/drain + mutating rollouts;
          helm install/upgrade/uninstall/rollback; gcloud/gsutil/az
          delete/destroy/update/patch/rm; mutating aws verbs and aws s3 rm/rb/mv;
          recursive/forced shell rm; git merge; gh repo delete. These never run on
          agent initiative alone: the harness surfaces a confirmation so the user
          re-confirms that this specific action really is the intent.
  - ASK-GO-AHEAD (forced confirmation): git commit / git push and PR opening/merging
          (gh pr create|merge|close). Allowed only on a clear user go-ahead — never
          silently, never agent-initiated. A commit/PR message carrying an AI
          attribution signature (Co-Authored-By: Claude / "Generated with ... Claude" /
          the robot emoji) gets its own confirmation so a signature never lands unnoticed.
  - EXEMPT: dirty-zone capture plumbing (capture_backup.sh, the capture-mirror repo)
          always passes — capture exists to guarantee no data loss and is never blocked.

Validation-only commands (terraform plan/validate/fmt, kubectl get/describe or --dry-run,
read-only gcloud/aws/az, git status/diff/log, ...) match no pattern and run untouched.
Shell line-continuations (backslash-newline) are folded before matching, so splitting a
verb across continued lines does not evade the patterns.

Self-gating: the hook is installed once at user level and fires in every project, so it
stays inert unless the repo is bailiwick-wired (a framework complement file carries the
$BAILIWICK marker). It never blocks commands in unrelated repositories.

Decision protocol (Claude Code hooks): print a PreToolUse hookSpecificOutput object with
permissionDecision deny|ask and exit 0. The failure direction is TIERED (ADR-005), not
uniformly open — see "Scope & limits" below: fail CLOSED (deny) when the destructive
pre-filter trips, fail OPEN otherwise, so a bug never wedges the harness on a harmless command.

Scope & limits — NOT a complete security boundary. This is a DIRECT-command guardrail for the
supported patterns only. It does NOT see destructive operations reached via `make apply`, wrapper /
task-runner scripts, shell aliases/functions, or Terraform-MCP tool actions — those bypass it. On an
internal evaluation error it fails CLOSED (deny) for commands that trip the destructive pre-filter and
fails OPEN otherwise (ADR-005) — never wedging the harness on a harmless command. A malformed payload
(nothing to evaluate) still fails open. Treat it as a high-value safety rail for direct commands, not
enforcement under indirection.

ADAPTER MAPPING (the confirmation tiers are identical; only the decision vocabulary differs):
  - claude: every tier -> permissionDecision "ask" (the dialog IS the re-confirmation).
    Break-glass downgrades only the error-path fail-closed deny to ask.
  - gemini: every tier -> {"decision": "ask"} — BeforeTool's ask forces the user confirmation
    dialog (source-verified in gemini-cli's scheduler; the docs only list allow/deny, so pin the
    CLI version if this ever regresses). Error path fails closed with {"decision": "deny"};
    break-glass downgrades that deny to ask.
  - codex: PreToolUse has NO ask (allow-with-rewrite or deny only, and a deny without a non-empty
    permissionDecisionReason silently fails open — always emit the reason). Every tier -> deny
    with an actionable remedy in the reason. BAILIWICK_BREAK_GLASS=1 = allow-once (no decision
    emitted, audited) — the only in-band override, since no confirmation dialog exists.

Break-glass (deliberate override): with BAILIWICK_BREAK_GLASS=1 set — claude/gemini: the
error-path fail-closed DENY is downgraded to ASK (in normal operation there is no hard deny;
both tiers already resolve to a confirmation); codex: any tier decision becomes allow-once
(audited), because Codex has no ask. Every ask / deny / break-glass decision is appended to
$BAILIWICK_HOME/guardrail-audit.log (best-effort) as an audit trail.
"""
import json
import os
import re
import sys

# EXEMPT: dirty-zone capture plumbing — always passes, ahead of every other tier. Capture exists
# to guarantee no data loss; blocking its commits/pushes would defeat the framework's own backstop.
EXEMPT_PATTERNS = [
    r"capture_backup\.sh",
    r"capture-mirror",
]

# Segment separator: patterns must not read a verb from the NEXT chained command as belonging to
# this tool ("terraform plan && kubectl apply" is not "terraform ... apply").
SEG = r"[^;&|\n]*"

# ASK-IMPACT: real-world impact — forced reconfirmation even when the user instructed the action.
# Tuples: (pattern, dry_run_exempt, what). dry_run_exempt=True lets a --dry-run form pass as
# validation-only (kubectl/helm support it; terraform's validation path is `plan`, which the
# subcommand-anchored pattern already leaves alone).
ASK_IMPACT_PATTERNS = [
    (r"\b(terraform|terragrunt)\b(\s+-\S+)*\s+(apply|destroy)\b", False,
     "terraform/terragrunt apply|destroy changes real infrastructure"),
    (r"\bkubectl\b" + SEG + r"\b(apply|delete|patch|replace|scale|drain|cordon|uncordon)\b", True,
     "kubectl mutation changes live cluster state"),
    (r"\bkubectl\b" + SEG + r"\brollout\s+(restart|undo|pause|resume)\b", True,
     "kubectl rollout mutation changes live cluster state"),
    (r"\bhelm\b" + SEG + r"\b(install|upgrade|uninstall|delete|rollback)\b", True,
     "helm release mutation changes live cluster state"),
    (r"\b(gcloud|gsutil|az)\b" + SEG + r"\b(delete|destroy|update|patch|rm)\b", False,
     "cloud CLI mutation (delete/destroy/update/patch/rm) changes real resources"),
    (r"\baws\b" + SEG + r"\b(delete-|terminate-|remove-|update-)", False,
     "mutating AWS CLI verb (delete-/terminate-/remove-/update-) changes real resources"),
    (r"\baws\s+s3\b" + SEG + r"\b(rm|rb|mv)\b", False,
     "aws s3 rm/rb/mv changes real storage"),
    (r"(^|[;&|]\s*|\s)rm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\b|--recursive\b|--force\b)", False,
     "recursive/forced rm is irreversible"),
    (r"\bgit\b" + SEG + r"\bmerge\b", False,
     "git merge rewrites branch state"),
    (r"\bgh\b" + SEG + r"\brepo\b" + SEG + r"\b(delete|archive)\b", False,
     "gh repo delete/archive is repository-level and hard to reverse"),
]

# ASK-SIGNATURE: an AI attribution trailer inside a commit/PR message — its own confirmation, so a
# signature never lands by agent initiative (checked only on message-carrying git/gh commands).
SIGNATURE_RE = re.compile(
    r"co-authored-by:\s*claude|generated with .{0,20}claude|\U0001F916", re.IGNORECASE)
GIT_MESSAGE_RE = re.compile(
    r"\bgit\b" + SEG + r"\bcommit\b|\bgh\b" + SEG + r"\bpr\b", re.IGNORECASE)

# ASK-GO-AHEAD: permitted, but only on a clear user go-ahead — never silent, never agent-initiated.
ASK_GOAHEAD_PATTERNS = [
    (r"\bgit\b" + SEG + r"\b(commit|push)\b",
     "git commit/push requires a clear user go-ahead (framework non-negotiable) — never agent initiative; confirm to proceed."),
    (r"\bgh\b" + SEG + r"\bpr\b" + SEG + r"\b(create|merge|close|ready)\b",
     "opening/merging a PR requires a clear user go-ahead — never agent initiative; confirm to proceed."),
]

# DANGER pre-filter (ADR-005): a broad, cheap match on the raw command, used ONLY to pick the fail
# direction if the main pattern engine errors — fail CLOSED (deny) when this trips, else fail open.
# Aligned with the ASK-IMPACT tool/verb space; kept a single compiled regex (near-zero failure surface).
DANGER_PREFILTER = re.compile(
    r"\b(terraform|terragrunt|gcloud|gsutil|az|aws|kubectl|helm)\b[^\n]*"
    r"\b(apply|destroy|delete|terminate|remove|update|patch|rm|drain|scale|uninstall|rollback)\b"
    r"|(^|[;&|]\s*|\s)rm\s+-[a-zA-Z]*[rf]",
    re.IGNORECASE)


def normalize(command):
    """Fold shell line-continuations (backslash-newline) so a verb split across continued
    lines cannot evade the patterns. Plain newlines stay — separate lines are separate commands."""
    return re.sub(r"\\\r?\n", " ", command)


def strip_quoted(command):
    """Blank out single/double-quoted substrings. The destructive verbs in ASK-IMPACT and the
    commit/push verbs in ASK-GO-AHEAD are always shell *command tokens*, never inside quotes — so a
    verb appearing inside a quoted ARGUMENT (e.g. `gcloud logging read '... methodName:"delete" ...'`,
    a read-only query) is a false positive. Matching those tiers against the quote-stripped command
    removes that class. The SIGNATURE tier is the exception (its match lives inside the quoted commit
    message), so it keeps the raw command. Observed live: a `gcloud logging read` with "delete" in the
    filter was flagged ask-impact under the Codex adapter."""
    return re.sub(r"'[^']*'|\"[^\"]*\"", " ", command)

COMPLEMENT_FILES = (
    ".bailiwick.local.md",
    "CLAUDE.local.md",
    ".github/instructions/bailiwick.instructions.md",
)


def is_bailiwick_repo(project_dir):
    """Only act in bailiwick-wired repos (mirrors capture_session.py)."""
    for name in COMPLEMENT_FILES:
        try:
            with open(os.path.join(project_dir, name), "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
            if "BAILIWICK" in text:
                return True
        except Exception:
            continue
    return False


def _bw_home():
    return os.environ.get("BAILIWICK_HOME") or os.path.join(os.path.expanduser("~"), ".bailiwick")


def _health(event, detail):
    """Append a framework-health line to this machine's per-source shard (best-effort, never
    raises). Aggregated fleet-wide by /metrics; transported by capture_backup.sh (encrypted)."""
    try:
        import datetime
        import socket
        machine = ""
        try:
            bailiwick_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            with open(os.path.join(bailiwick_root, ".bailiwick-sync.json"), encoding="utf-8") as fh:
                machine = (json.load(fh).get("machine") or "").strip()
        except Exception:
            pass
        machine = re.sub(r"[^a-z0-9._-]", "-", (machine or socket.gethostname()).lower())
        hdir = os.path.join(_bw_home(), "health")
        os.makedirs(hdir, exist_ok=True)
        with open(os.path.join(hdir, machine + ".jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "machine": machine, "component": "guardrails", "event": event,
                "detail": str(detail)[:300]}) + "\n")
    except Exception:
        pass


def _audit(event, command, project_dir):
    """Best-effort audit line for every deny / ask / break-glass decision (never raises)."""
    try:
        import datetime
        home = _bw_home()
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "guardrail-audit.log"), "a", encoding="utf-8") as fh:
            fh.write("{}\t{}\t{}\t{}\n".format(
                datetime.datetime.now().isoformat(timespec="seconds"),
                event, project_dir, " ".join(command.split())[:500]))
    except Exception:
        pass


def is_shadow_repo(project_dir):
    """Shadow activation — no in-repo marker (FRAMEWORK.md §7.1): BAILIWICK_SHADOW=1 or an
    allowlist match. Enforcement must apply in shadow repos exactly as in seeded ones."""
    if os.environ.get("BAILIWICK_SHADOW") == "1":
        return True
    try:
        here = os.path.realpath(project_dir)
        with open(os.path.join(_bw_home(), "allowlist"), "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                entry = line.split("#", 1)[0].strip().rstrip("/")
                if entry and os.path.realpath(entry) == here:
                    return True
    except Exception:
        pass
    return False


def emit(decision, reason):
    """Claude Code / Codex shared shape (both use the PreToolUse hookSpecificOutput contract)."""
    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": "[bailiwick guardrail] " + reason,
        }
    }, sys.stdout)
    sys.stdout.write("\n")


def emit_gemini(decision, reason):
    """Gemini CLI BeforeTool contract: {"decision": ..., "reason": ...} on stdout (JSON only)."""
    json.dump({"decision": decision,
               "reason": "[bailiwick guardrail] " + reason}, sys.stdout)
    sys.stdout.write("\n")


# Audit-event label per tier (adapter-prefixed for codex/gemini at the call site).
AUDIT_EVENT = {"impact": "ask-impact", "signature": "ask-signature", "goahead": "ask"}

# Codex has no confirmation dialog, so every deny reason must carry its remedy.
CODEX_REMEDY = {
    "impact": ("Codex has no confirmation dialog: the user runs this out-of-band, or relaunches "
               "Codex with BAILIWICK_BREAK_GLASS=1 to permit once (logged)."),
    "goahead": ("Codex has no confirmation dialog: after an explicit user go-ahead, relaunch "
                "Codex with BAILIWICK_BREAK_GLASS=1 to permit once (logged)."),
    "signature": ("Strip the AI attribution signature and retry, or get an explicit user "
                  "go-ahead and use BAILIWICK_BREAK_GLASS=1 (logged)."),
}


def _respond(adapter, tier, reason, command, project_dir):
    """Map a tier decision onto the adapter's decision contract (see ADAPTER MAPPING)."""
    if adapter == "gemini":
        _audit("gemini:" + AUDIT_EVENT[tier], command, project_dir)
        emit_gemini("ask", reason)
    elif adapter == "codex":
        if os.environ.get("BAILIWICK_BREAK_GLASS") == "1":
            _audit("codex:break-glass-allow", command, project_dir)
            return  # allow-once: no decision emitted; the override is the audit trail
        _audit("codex:" + AUDIT_EVENT[tier], command, project_dir)
        emit("deny", reason + " " + CODEX_REMEDY[tier])
    else:
        _audit(AUDIT_EVENT[tier], command, project_dir)
        emit("ask", reason)


def _decide_deny(adapter, reason, command, project_dir):
    """Error-path fail-closed deny — break-glass downgrades to ask (claude/gemini) or
    allow-once (codex, which has no ask). Audits every outcome."""
    bg = os.environ.get("BAILIWICK_BREAK_GLASS") == "1"
    if adapter == "gemini":
        if bg:
            _audit("gemini:break-glass", command, project_dir)
            emit_gemini("ask", "BREAK-GLASS override active — " + reason + " Confirm deliberately; logged.")
        else:
            _audit("gemini:deny", command, project_dir)
            emit_gemini("deny", reason)
    elif adapter == "codex":
        if bg:
            _audit("codex:break-glass-allow", command, project_dir)
        else:
            _audit("codex:deny", command, project_dir)
            emit("deny", reason)
    else:
        if bg:
            _audit("break-glass", command, project_dir)
            emit("ask", "BREAK-GLASS override active (BAILIWICK_BREAK_GLASS) — " + reason
                 + " Confirm deliberately; this override is logged.")
        else:
            _audit("deny", command, project_dir)
            emit("deny", reason)


def main(adapter="claude"):
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # Fail open — never wedge the harness on a malformed payload.

    tool = payload.get("tool_name") or ""
    if adapter == "gemini":
        if tool != "run_shell_command":
            return 0
    elif tool != "Bash":  # claude and codex both use the canonical "Bash" tool name
        return 0

    raw_command = ((payload.get("tool_input") or {}).get("command") or "")
    if not raw_command.strip():
        return 0
    command = normalize(raw_command)
    # Command-token tiers (impact / go-ahead) match against the quote-stripped form so a verb inside
    # a quoted argument isn't a false positive; the signature tier keeps `command` (needs the quotes).
    cmd_tokens = strip_quoted(command)

    # Gemini exports CLAUDE_PROJECT_DIR as a compat alias; Codex carries only payload cwd.
    project_dir = (
        os.environ.get("CLAUDE_PROJECT_DIR")
        or payload.get("cwd")
        or os.getcwd()
    )
    if not (is_bailiwick_repo(project_dir) or is_shadow_repo(project_dir)):
        return 0  # Inert outside bailiwick-wired repos (seeded or shadow-activated).

    # Evaluate tiers in order: EXEMPT → ASK-IMPACT → ASK-SIGNATURE → ASK-GO-AHEAD. On ANY engine
    # failure, fail CLOSED if the command trips the destructive pre-filter, else fail open — never
    # wedge the harness on a harmless command (ADR-005).
    try:
        for pattern in EXEMPT_PATTERNS:
            if re.search(pattern, cmd_tokens, re.IGNORECASE):
                return 0  # dirty-zone capture plumbing — never blocked (data-loss prevention)
        dry_run = "--dry-run" in command
        for pattern, dry_exempt, what in ASK_IMPACT_PATTERNS:
            if dry_exempt and dry_run:
                continue  # validation-only form — no real impact
            if re.search(pattern, cmd_tokens, re.IGNORECASE):
                _respond(adapter, "impact", "HIGH-IMPACT: " + what
                         + " — blocked from agent initiative; re-confirm this is really the intent.",
                         raw_command, project_dir)
                return 0
        if GIT_MESSAGE_RE.search(command) and SIGNATURE_RE.search(command):
            _respond(adapter, "signature",
                     "the commit/PR message carries an AI attribution signature "
                     "(Co-Authored-By / 'Generated with' / robot emoji) — confirm it is wanted, "
                     "or strip it before proceeding.",
                     raw_command, project_dir)
            return 0
        for pattern, reason in ASK_GOAHEAD_PATTERNS:
            if re.search(pattern, cmd_tokens, re.IGNORECASE):
                _respond(adapter, "goahead", reason, raw_command, project_dir)
                return 0
    except Exception as e:
        _health("error", "pattern engine failure ({}): {!r}".format(adapter, e)[:200])
        try:
            if DANGER_PREFILTER.search(strip_quoted(normalize(raw_command))):
                _decide_deny(
                    adapter,
                    "guardrail evaluation failed on a potentially destructive command — denied "
                    "(fail-closed, ADR-005). Set BAILIWICK_BREAK_GLASS=1 to override deliberately.",
                    raw_command, project_dir)
        except Exception:
            pass
    return 0  # No decision — normal permission flow proceeds.


if __name__ == "__main__":
    try:
        _adapter = "claude"
        for _arg in sys.argv[1:]:
            if _arg in ("claude", "codex", "gemini"):
                _adapter = _arg
        sys.exit(main(_adapter))
    except Exception:
        sys.exit(0)  # Never wedge the harness on an unexpected error.
