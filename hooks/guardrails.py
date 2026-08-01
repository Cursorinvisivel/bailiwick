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
          kubectl apply/delete/patch/replace/scale/drain/cordon/uncordon +
          mutating rollouts;
          helm install/upgrade/uninstall/rollback; gcloud/gsutil/az
          delete/destroy/update/patch/rm; mutating aws verbs and aws s3 rm/rb/mv;
          recursive/forced shell rm; git merge; gh repo delete. These never run on
          agent initiative alone: the harness surfaces a confirmation so the user
          re-confirms that this specific action really is the intent.
  - ASK-GO-AHEAD (forced confirmation): git commit / git push and PR opening/merging
          (gh pr create|merge|close|ready). Allowed only on a clear user go-ahead — never
          silently, never agent-initiated. A commit/PR message carrying an AI
          attribution signature (Co-Authored-By: Claude / "Generated with ... Claude" /
          the robot emoji) gets its own confirmation so a signature never lands unnoticed.
  - EXEMPT: dirty-zone capture plumbing (capture_backup.sh, the capture-mirror repo)
          always passes — capture exists to guarantee no data loss and is never blocked.

Validation-only commands (terraform plan/validate/fmt, kubectl get/describe or --dry-run,
read-only gcloud/aws/az, git status/diff/log, ...) match no pattern and run untouched.
Shell line-continuations (backslash-newline) are folded before matching, so splitting a
verb across continued lines does not evade the patterns; whole-token quoting is unwrapped, so
`terraform "apply"` does not either. Tiers are evaluated PER SEGMENT (`;` `&&` `||` `|`, comments
dropped), so a --dry-run flag or an EXEMPT match in one segment never speaks for a chained one.

Self-gating: the hook is installed once at user level and fires in every project, so it
stays inert unless the repo is bailiwick-wired (a framework complement file carries the
$BAILIWICK marker). It never blocks commands in unrelated repositories.

Decision protocol (Claude Code hooks): print a PreToolUse hookSpecificOutput object with
permissionDecision deny|ask and exit 0. The failure direction is TIERED (ADR-005), not
uniformly open — see "Scope & limits" below: fail CLOSED (deny) when the destructive
pre-filter trips, fail OPEN otherwise, so a bug never wedges the harness on a harmless command.

Scope & limits — NOT a complete security boundary. This is a DIRECT-command guardrail for the
supported patterns only. It does NOT see destructive operations reached via `make apply`, wrapper /
task-runner scripts, shell aliases/functions, or Terraform-MCP tool actions — those bypass it.
Known residual evasion: quoting only PART of a token (`terraform ap"ply"`) still slips the patterns —
the transformation that would catch it is indistinguishable from the quoted-argument false positive
(`gcloud logging read 'methodName:"delete"'`) the tiers deliberately ignore. On an
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
# Anchored to COMMAND position, never free text: an unanchored substring meant that any command
# merely mentioning the mirror (a `# capture-mirror` comment, a capture-mirror.tfvars argument,
# a chained `echo capture_backup.sh`) disarmed every tier. Exemption is also evaluated per segment
# (see segments()), so `capture_backup.sh push && terraform destroy` cannot ride it.
EXEMPT_PATTERNS = [
    # the backup script invoked as a command word, optionally through an interpreter
    r"(?:^|[;&|]\s*)(?:(?:bash|sh|zsh)\s+)?\S*capture_backup\.sh\b",
    # git against the CANONICAL mirror only (capture_backup.sh: $XDG_CACHE_HOME|~/.cache/bailiwick/
    # capture-mirror), with -C immediately after `git` and the path ending the token. Matching any
    # path merely containing "capture-mirror" turned the exemption into an unconfirmed push channel:
    # an agent-created /tmp/capture-mirror, or a decoy -C path while --git-dir pointed git at the
    # client repo, both rode it to `git push <arbitrary-url>` with no confirmation.
    r"(?:^|[;&|]\s*)git\s+-C\s+\S*/bailiwick/capture-mirror/?(?=\s|$)",
]

# An exemption claim is void if the segment redirects git at another repository (--git-dir and
# --work-tree override -C) or names an explicit remote URL — the mirror only ever pushes to the
# `origin` its own plumbing configured, never to a URL spelled out on the command line.
EXEMPT_DISQUALIFIERS = re.compile(r"--git-dir|--work-tree|--exec-path|://|\S+@\S+:")

# Segment separator: patterns must not read a verb from the NEXT chained command as belonging to
# this tool ("terraform plan && kubectl apply" is not "terraform ... apply").
SEG = r"[^;&|\n]*"

# The dry-run exemption must be a standalone flag in the SAME segment that matched — a bare
# `"--dry-run" in command` let `kubectl delete ns prod --dry-run=client; kubectl delete ns prod`
# (and a trailing `# --dry-run` comment) suppress the live mutation.
DRY_RUN_RE = re.compile(r"(?:^|\s)--dry-run(?:=\S+)?(?=\s|$)")

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
    lines cannot evade the patterns. The shell removes `\\<newline>` entirely (joining with
    nothing), so we replace it with the empty string — otherwise a mid-token split like
    `terraform app\\<newline>ly` would normalize to `app ly` and slip past `apply`. Plain
    newlines stay — separate lines are separate commands."""
    return re.sub(r"\\\r?\n", "", command)


# A quoted run that spans a WHOLE token and holds no whitespace, separator, or nested quote:
# `terraform "apply"`, `rm '-rf'`, `kubectl "delete"`. The shell executes these exactly as the
# unquoted form, so they are command tokens and must be unwrapped before quoted ARGUMENTS are
# blanked — otherwise quoting the verb erased it from the string the tiers match against.
_QUOTED_TOKEN = re.compile(r"(?<![^\s;&|])(['\"])([^'\"\s;&|]*)\1(?![^\s;&|])")


def unwrap_token_quotes(command):
    """Unquote whole-token quoted words, leaving genuine quoted arguments intact for strip_quoted().
    The two cases are distinguished by content: `echo "terraform apply"` holds whitespace and
    `'protoPayload.methodName:"delete"'` holds a nested quote, so neither is unwrapped."""
    return _QUOTED_TOKEN.sub(lambda m: m.group(2), command)


def strip_quoted(command):
    """Blank out single/double-quoted substrings that survive unwrap_token_quotes() — i.e. genuine
    quoted ARGUMENTS. A verb inside one (e.g. `gcloud logging read '... methodName:"delete" ...'`,
    a read-only query) is a false positive; matching the command-token tiers against the stripped
    form removes that class. Observed live: a `gcloud logging read` with "delete" in the filter was
    flagged ask-impact under the Codex adapter. Order matters — unwrap first, blank second: blanking
    alone treated `terraform "apply"` as a quoted argument and let it through. The SIGNATURE tier is
    the exception (its match lives inside the quoted commit message) and keeps the raw command."""
    return re.sub(r"'[^']*'|\"[^\"]*\"", " ", command)


def segments(command):
    """Split a quote-blanked command into the segments the shell executes separately, dropping
    `#` comments. Tier decisions are made per segment: a --dry-run flag, or an EXEMPT match, in
    one segment must never speak for another (`kubectl delete x --dry-run=client; kubectl delete x`).
    Safe to run after strip_quoted only — a `#`, `;` or `&&` inside quotes is already blanked, so it
    can never be misread here as a comment or a separator."""
    no_comments = re.sub(r"(?:^|\s)#[^\n]*", " ", command)
    return [seg for seg in re.split(r"[;&|\n]+", no_comments) if seg.strip()]

# Self-gating, shadow gate, home resolution, and health logging live in the shared
# hooks/bw_common.py substrate (one implementation for this hook and capture_session.py).
from bw_common import is_bailiwick_repo, is_shadow_repo  # noqa: F401
from bw_common import bw_home as _bw_home
import bw_common


def _health(event, detail):
    """Health line for this component (shared writer — see bw_common.health)."""
    bw_common.health("guardrails", event, detail)


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
    # a quoted argument isn't a false positive — but whole-token quoting is unwrapped first, since
    # `terraform "apply"` is a command token the shell runs verbatim. The signature tier keeps
    # `command` (needs the quotes).
    cmd_tokens = strip_quoted(unwrap_token_quotes(command))

    # Gemini exports CLAUDE_PROJECT_DIR as a compat alias; Codex carries only payload cwd.
    project_dir = bw_common.resolve_project_dir(payload)
    if not (is_bailiwick_repo(project_dir) or is_shadow_repo(project_dir)):
        return 0  # Inert outside bailiwick-wired repos (seeded or shadow-activated).

    # Evaluate tiers in order: EXEMPT → ASK-IMPACT → ASK-SIGNATURE → ASK-GO-AHEAD. On ANY engine
    # failure, fail CLOSED if the command trips the destructive pre-filter, else fail open — never
    # wedge the harness on a harmless command (ADR-005).
    try:
        # Per-segment evaluation (ADR-006 amendment): EXEMPT clears only its own segment, and the
        # dry-run exemption only the segment that matched — neither speaks for a chained command.
        segs = [seg for seg in segments(cmd_tokens)
                if not (any(re.search(p, seg, re.IGNORECASE) for p in EXEMPT_PATTERNS)
                        and not EXEMPT_DISQUALIFIERS.search(seg))]
        if not segs:
            return 0  # dirty-zone capture plumbing only — never blocked (data-loss prevention)
        for seg in segs:
            seg_dry_run = DRY_RUN_RE.search(seg) is not None
            for pattern, dry_exempt, what in ASK_IMPACT_PATTERNS:
                if dry_exempt and seg_dry_run:
                    continue  # validation-only form in THIS segment — no real impact
                if re.search(pattern, seg, re.IGNORECASE):
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
        for seg in segs:
            for pattern, reason in ASK_GOAHEAD_PATTERNS:
                if re.search(pattern, seg, re.IGNORECASE):
                    _respond(adapter, "goahead", reason, raw_command, project_dir)
                    return 0
    except Exception as e:
        _health("error", "pattern engine failure ({}): {!r}".format(adapter, e)[:200])
        try:
            # ADR-005: the pre-filter runs on the RAW command. Feeding it the quote-stripped form
            # let the same quoting trick that evades the tiers also blind the fail-closed path.
            if DANGER_PREFILTER.search(normalize(raw_command)):
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
