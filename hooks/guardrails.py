#!/usr/bin/env python3
"""Runtime guardrails for the bailiwick — one engine, three tool adapters.

Invoked as a pre-execution hook by:
  - Claude Code  (PreToolUse, Bash)            — no argument, or `claude`
  - Codex CLI    (PreToolUse, Bash)            — argument `codex`
  - Antigravity  (PreToolUse, run_command)     — argument `antigravity`
  - Gemini CLI   (BeforeTool, run_shell_command; deprecated) — argument `gemini`

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
  - SIGNED-COMMIT SHAPE (deny): in a repo that signs (commit.gpgsign / user.signingkey), a git
          commit must take the /sign skill's shape — `-S -F .git/COMMIT_MSG_<slug>` — and the
          message file is scanned for the attribution signature. Anything else is denied with
          the /sign route in the reason; break-glass downgrades the deny like the error path.
  - EXEMPT: dirty-zone capture plumbing (capture_backup.sh, the capture-mirror repo)
          always passes — capture exists to guarantee no data loss and is never blocked.
          The /purge asks (sentinel, purge_delete.sh / purge_scrub.py --apply) are evaluated
          on every segment BEFORE the exemption, so an exemption claim cannot swallow them.

Validation-only commands (terraform plan/validate/fmt, kubectl get/describe or --dry-run,
read-only gcloud/aws/az, git status/diff/log, ...) match no pattern and run untouched.
Shell line-continuations (backslash-newline) are folded before matching, so splitting a
verb across continued lines does not evade the patterns. Backslashes are consumed in pairs (`a\\\\`
then a newline is a real newline), and each physical line is ALSO evaluated unjoined, because bash
never continues a comment (`echo x # note \\` then `terraform apply` runs line 2). Shell words are folded (whole-word, partial
and backslash-escaped quoting), so `terraform "apply"`, `terraform ap"ply"` and `kubectl de\\lete` do
not either. Tiers are evaluated PER SEGMENT (`;` `&&` `||` `|`, comments
dropped), so a --dry-run flag or an EXEMPT match in one segment never speaks for a chained one.
A command that is exactly `bash|sh|zsh -c/-lc '<cmd>'` (how a Codex argv call can arrive) is
evaluated as given AND as the inner `<cmd>` it runs.

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
Partial quoting and backslash escapes are folded (`terraform ap"ply"`, `"--a"pply`, `ap\\ply`); the
quoted-argument false positive stays suppressed because a quoted run holding whitespace, a separator
or a nested quote is not a word piece, and a quoted run right after `=` or `:` is treated as a VALUE
and blanked (`--filter="name:delete-me"`, `methodName:"delete"`; `--dry-run="client"` excepted, since
its value decides the exemption). An escaped space/separator (`-chdir=a\\ b`) is rewritten to `_` so it
neither splits a segment nor stops a fold. No normalisation step may CREATE a comment, quote or
separator the shell would not see: unwrapped specials are re-escaped and a blank before `#` leaves a
placeholder (property-tested against a reference lexer). Known residual evasion: `$'..'` ANSI-C
quoting with \\x / octal escapes; variable, command and parameter substitution (`$v`, `$(…)`,
`${x:="delete"}`); brace expansion (`rm -{r,}f x`); aliases/functions and wrapper scripts.

Cost: every matcher is linear (`A + SEG + B` patterns run as staged searches, see _Staged), and the
evaluation runs under a wall-clock budget (EVAL_BUDGET_SECONDS, SIGALRM, POSIX main thread only):
Codex/Antigravity kill a hook at 30 s and a killed hook fails OPEN, so an overrun is cut short and
DENIED unconditionally (break-glass as the error path; audit event `deny-budget`) — an overrun proves
nothing about which tier would have matched. A decision disarms the timer before it is audited or
printed, and at most one decision is ever printed. A command value that is not a str or a list of
str cannot be read by the tiers; the pre-filter runs over its JSON (deny on a match, else health
warn). The pre-filter's vocabulary spans every tier. On an internal evaluation error (including a
tier table that failed to compile at import) it fails CLOSED (deny) for commands that trip the
pre-filter and fails OPEN otherwise (ADR-005) — never wedging the harness on a harmless command. A
malformed payload (nothing to evaluate) still fails open. Treat it as a high-value safety rail for
direct commands, not enforcement under indirection.

ADAPTER MAPPING (the confirmation tiers are identical; only the decision vocabulary differs):
  - claude: every tier -> permissionDecision "ask" (the dialog IS the re-confirmation).
    Break-glass downgrades only the error-path fail-closed deny to ask.
  - antigravity: every tier -> {"decision": "force_ask"} — Antigravity's plain "ask" honours a
    cached "Always Allow", which would silently skip the in-the-moment re-confirmation; force_ask
    always prompts (antigravity.google/docs/hooks). Error path fails closed with
    {"decision": "deny"}; break-glass downgrades that deny to force_ask.
  - gemini: (legacy Gemini CLI BeforeTool, deprecated) every tier -> {"decision": "ask"} —
    source-verified in gemini-cli's scheduler. Same deny / break-glass handling.
  - codex: PreToolUse has NO ask (allow-with-rewrite or deny only, and a deny without a non-empty
    permissionDecisionReason silently fails open — always emit the reason). Every tier -> deny
    with an actionable remedy in the reason. BAILIWICK_BREAK_GLASS=1 = allow-once (no decision
    emitted, audited) — the only in-band override, since no confirmation dialog exists.

Break-glass (deliberate override): with BAILIWICK_BREAK_GLASS=1 set — claude/antigravity/gemini: the
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
    # the backup script invoked as a command word, optionally through an interpreter. The script
    # name must END the path token: `…/capture_backup.sh/../../hooks/mark_purge_session.sh` is a
    # path THROUGH it (the kernel resolves it to the other script), never the backup script.
    r"(?:^|[;&|]\s*)(?:(?:bash|sh|zsh)\s+)?\S*capture_backup\.sh(?=\s|$|[;&|])",
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
_SEG_SPLIT = re.compile(r"[;&|\n]")


class _Staged:
    """`A SEG B SEG C` matched as successive searches inside each separator-free chunk.

    As one regex, every occurrence of A re-scans the rest of the segment hunting for B, which is
    quadratic (cubic with a third stage): `echo ` + `purge_scrub scrub ` * 1700 took 45 s, past the
    Codex/Antigravity hook timeout, which fails open. Within a chunk that holds no separator, SEG
    matches anything, so "some A, then later some B" holds exactly when the leftmost A is followed by
    some B, and so on. Each chunk is therefore scanned once per stage, which is linear.

    RULE for every stage: it must not be able to match a separator (`;&|` or newline). That is,
    no `.`, no `\\s`/`\\S`/`\\W`/`\\D`, no negated class: use `[ \\t]+` for "whitespace". Then a
    stage could never have crossed a separator in the one-regex form either, so the split into
    chunks changes nothing. test_staged_stages_cannot_match_a_separator enforces this."""
    __slots__ = ("stages",)

    def __init__(self, parts, flags):
        self.stages = [re.compile(p, flags) for p in parts]

    def search(self, text):
        for chunk in _SEG_SPLIT.split(text):
            pos = 0
            for stage in self.stages:
                m = stage.search(chunk, pos)
                if m is None:
                    break
                pos = m.end()
            else:
                return True
        return False


def _pattern(pattern, flags=re.IGNORECASE):
    """Compile a tier pattern: a plain regex, or a _Staged matcher when it is built `A + SEG + B`."""
    parts = pattern.split(SEG)
    return re.compile(pattern, flags) if len(parts) == 1 else _Staged(parts, flags)


# The dry-run exemption must be a standalone flag in the SAME segment that matched — a bare
# `"--dry-run" in command` let `kubectl delete ns prod --dry-run=client; kubectl delete ns prod`
# (and a trailing `# --dry-run` comment) suppress the live mutation. `=none` / `=false` are live runs.
DRY_RUN_RE = re.compile(r"(?:^|\s)--dry-run(?:=(?!none\b|false\b)\S+)?(?=\s|$)")

# The /purge sentinel (hooks/mark_purge_session.sh): capture_session.py reads its invocation as
# "this is a /purge session", stops capturing it, deletes its earlier captures and tombstones their
# backup blobs — so it must never run on agent (or prompt-injected) initiative.
MARK_PURGE_WHAT = ("mark_purge_session.sh marks this session as /purge: disables capture and deletes "
                   "this session's captures (and requests their backup retraction)")
# Raw-command companion for quoted paths that strip_quoted() blanks (`bash '/a b/hooks/mark…sh'`):
# the same command position, the script inside a quoted token.
# (Compiled with the tier tables, inside the _TABLE_ERROR guard.)
_MARK_PURGE_RAW = (
    r"(?:^|[;&|\n(])\s*(?:\w+=\S*\s+)*(?:(?:bash|sh|zsh|source|\.|exec|command|env)\s+)*"
    r"(?:\"[^\"\n]*|'[^'\n]*)mark_purge_session\.sh[\"']")
PURGE_DELETE_WHAT = "purge_delete.sh --apply deletes client files irreversibly"
PURGE_SCRUB_WHAT = ("purge_scrub.py --apply rewrites the guardrail audit log / health shards / host "
                    "history in place")
# purge_scrub.py `--apply`: argparse is built with allow_abbrev=False, but match any `--ap…` too
# (belt and braces against a parser that would accept `--ap`/`--app`), and `purge_scrub` without
# `.py` so `python3 -m purge_scrub` is caught.
_SCRUB_APPLY = r"\b(scrub|history)\b" + r"[^;&|\n]*" + r"--ap\w*"
# Raw-command companions for the two --apply asks (same reason as MARK_PURGE_RAW_RE): a quoted
# script path holding a space is blanked by strip_quoted(), taking the script name with it.


class _QuotedHead:
    """A quoted-script-path head, then staged tail patterns confined to the rest of ITS segment
    (up to the next `;&|` or newline). Same matches as `head[^;&|\n]*tail…` as one regex, but linear:
    as one regex every head re-scanned the remainder for the tail (`"purge_scrub.py" scrub ` * 1700
    ran past the hook timeout). A tail window already searched is not searched again for a later head
    whose window lies inside it."""
    __slots__ = ("head", "tail")

    def __init__(self, head, tail_parts):
        self.head = re.compile(head)
        self.tail = _Staged(tail_parts, 0)

    def search(self, text):
        pos, done_from, done_stop = 0, None, None
        while True:
            m = self.head.search(text, pos)
            if m is None:
                return False
            end = m.end()
            sep = _SEG_SPLIT.search(text, end)
            stop = sep.start() if sep else len(text)
            if not (stop == done_stop and end >= done_from):
                if self.tail.search(text[end:stop]):
                    return True
                done_from, done_stop = end, stop
            pos = m.start() + 1


# (head, tail stages) for the two quoted-path --apply companions; built inside the _TABLE_ERROR guard.
_PURGE_DELETE_RAW = (r"""(?:"[^"\n]*|'[^'\n]*)purge_delete\.sh["']""", [r"--apply\b"])
_PURGE_SCRUB_RAW = (r"""(?:"[^"\n]*|'[^'\n]*)purge_scrub(?:\.py)?["']""", _SCRUB_APPLY.split(SEG))

# The /purge asks run on EVERY segment BEFORE the EXEMPT filter (see main): an exemption claim
# must never be able to swallow them (`…/capture_backup.sh/../../hooks/mark_purge_session.sh`).
PURGE_ASK_PATTERNS = [
    (r"\bpurge_delete\.sh\b" + SEG + r"--apply\b", False, PURGE_DELETE_WHAT),
    (r"\bpurge_scrub(?:\.py)?\b" + SEG + _SCRUB_APPLY, False, PURGE_SCRUB_WHAT),
    # The /purge sentinel, in command position (optionally behind env assignments or a shell).
    # Read/grep/cat of it stay quiet. A quoted path holding a space is blanked by strip_quoted(),
    # so MARK_PURGE_RAW_RE above covers that form on the raw command.
    (r"^\s*(?:\w+=\S*\s+)*(?:(?:bash|sh|zsh|source|\.|exec|command|env)\s+)*\S*"
     r"mark_purge_session\.sh(?=\s|$)", False, MARK_PURGE_WHAT),
]

# ASK-IMPACT: real-world impact — forced reconfirmation even when the user instructed the action.
# Tuples: (pattern, dry_run_exempt, what). dry_run_exempt=True lets a --dry-run form pass as
# validation-only (kubectl/helm support it; terraform's validation path is `plan`, which the
# subcommand-anchored pattern already leaves alone).
ASK_IMPACT_PATTERNS = [
    (r"\b(terraform|terragrunt)\b(\s+-\S+)*\s+(apply|destroy)\b", False,
     "terraform/terragrunt apply|destroy changes real infrastructure"),
    (r"\bkubectl\b" + SEG + r"\b(apply|delete|patch|replace|scale|drain|cordon|uncordon)\b", True,
     "kubectl mutation changes live cluster state"),
    (r"\bkubectl\b" + SEG + r"\brollout[ \t]+(restart|undo|pause|resume)\b", True,
     "kubectl rollout mutation changes live cluster state"),
    (r"\bhelm\b" + SEG + r"\b(install|upgrade|uninstall|delete|rollback)\b", True,
     "helm release mutation changes live cluster state"),
    (r"\b(gcloud|gsutil|az)\b" + SEG + r"\b(delete|destroy|update|patch|rm)\b", False,
     "cloud CLI mutation (delete/destroy/update/patch/rm) changes real resources"),
    (r"\baws\b" + SEG + r"\b(delete-|terminate-|remove-|update-)", False,
     "mutating AWS CLI verb (delete-/terminate-/remove-/update-) changes real resources"),
    (r"\baws[ \t]+s3\b" + SEG + r"\b(rm|rb|mv)\b", False,
     "aws s3 rm/rb/mv changes real storage"),
    # /purge tooling (also evaluated ahead of EXEMPT — see PURGE_ASK_PATTERNS).
    *PURGE_ASK_PATTERNS,
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


class _AnyOf:
    """`.search()` over several tier patterns (an alternation of _Staged matchers)."""
    __slots__ = ("patterns",)

    def __init__(self, *patterns):
        self.patterns = [_pattern(p) for p in patterns]

    def search(self, text):
        return any(p.search(text) for p in self.patterns)


_GIT_MESSAGE_PARTS = (r"\bgit\b" + SEG + r"\bcommit\b", r"\bgh\b" + SEG + r"\bpr\b")

# ASK-GO-AHEAD: permitted, but only on a clear user go-ahead — never silent, never agent-initiated.
ASK_GOAHEAD_PATTERNS = [
    (r"\bgit\b" + SEG + r"\b(commit|push)\b",
     "git commit/push requires a clear user go-ahead (framework non-negotiable) — never agent initiative; confirm to proceed."),
    (r"\bgh\b" + SEG + r"\bpr\b" + SEG + r"\b(create|merge|close|ready)\b",
     "opening/merging a PR requires a clear user go-ahead — never agent initiative; confirm to proceed."),
]

# Compile every tier pattern once; `A + SEG + B` patterns become linear _Staged matchers (ReDoS).
# Guarded: a malformed pattern raising here would abort the import OUTSIDE __main__'s try — a
# non-zero exit the harness treats as no decision, i.e. a silent fail-open on every command. Instead
# the error is kept and main() routes every evaluation to the fail-closed path (ADR-005).
_TABLE_ERROR = None
try:
    PURGE_ASK_PATTERNS = [(_pattern(p), dry, what) for p, dry, what in PURGE_ASK_PATTERNS]
    ASK_IMPACT_PATTERNS = [(_pattern(p), dry, what) for p, dry, what in ASK_IMPACT_PATTERNS]
    ASK_GOAHEAD_PATTERNS = [(_pattern(p), reason) for p, reason in ASK_GOAHEAD_PATTERNS]
    EXEMPT_PATTERNS = [_pattern(p) for p in EXEMPT_PATTERNS]
    GIT_MESSAGE_RE = _AnyOf(*_GIT_MESSAGE_PARTS)
    MARK_PURGE_RAW_RE = re.compile(_MARK_PURGE_RAW)
    PURGE_DELETE_RAW_RE = _QuotedHead(*_PURGE_DELETE_RAW)
    PURGE_SCRUB_RAW_RE = _QuotedHead(*_PURGE_SCRUB_RAW)
    PURGE_RAW_ASKS = [(MARK_PURGE_RAW_RE, MARK_PURGE_WHAT), (PURGE_DELETE_RAW_RE, PURGE_DELETE_WHAT),
                      (PURGE_SCRUB_RAW_RE, PURGE_SCRUB_WHAT)]
except Exception as _e:  # exercised by test_import_time_compile_failure_fails_closed
    _TABLE_ERROR = _e

# SIGNED-COMMIT SHAPE: in a repo that signs (commit.gpgsign=true or user.signingkey set), a commit
# must take the /sign skill's shape — `-S` plus `-F <gitdir>/COMMIT_MSG_<slug>`. That shape is the
# skill's output: the message was drafted to a file and pre-flighted against SIGNATURE_RE, and the
# signature is requested explicitly instead of trusting config. An inline `-m` commit skipped both,
# so it is DENIED (not asked): an ask would let one click approve the step the skill exists to force.
# The subcommand is found past git's global options, so `git log --grep commit` never matches.
# A token scan, not a regex: an option-repetition regex here backtracked exponentially (ReDoS).
GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                       "--super-prefix", "--config-env"}


def is_git_commit(seg):
    """True when a segment runs `git [global options] commit`."""
    tokens = seg.split()
    for i, tok in enumerate(tokens):
        if tok != "git" and not tok.endswith("/git"):
            continue
        j = i + 1
        while j < len(tokens) and tokens[j].startswith("-"):
            j += 2 if tokens[j] in GIT_OPTS_WITH_VALUE else 1
        if j < len(tokens) and tokens[j] == "commit":
            return True
    return False
COMMIT_SIGN_FLAG_RE = re.compile(r"(?:^|\s)(?:-S\S*|--gpg-sign(?:=\S+)?)(?=\s|$)")
COMMIT_NO_SIGN_RE = re.compile(r"(?:^|\s)--no-gpg-sign(?=\s|$)")
COMMIT_MSG_FILE_RE = re.compile(r"(?:^|\s)(?:-F\s*|--file(?:=|\s+))(\S+)")
SIGN_MSG_PATH_RE = re.compile(r"(?:^|/)\.git/(?:worktrees/[^/]+/)?COMMIT_MSG_[\w.-]+$")
UNSIGNED_SHAPE_REASON = (
    "this repo signs commits, so commits go through the /sign skill (Codex: $bailiwick-sign; "
    "other hosts: follow $BAILIWICK/skills/sign/SKILL.md): "
    "draft the message to .git/COMMIT_MSG_<slug>, pre-flight it with check_message.py, then "
    "`git commit -S -F .git/COMMIT_MSG_<slug>`. Inline -m, unsigned, and amend-without-file "
    "commits are denied.")


def repo_signs(cwd):
    """True when git in `cwd` is configured to sign (commit.gpgsign=true or a user.signingkey).
    Any failure reads as not signing — the go-ahead tier still confirms the commit."""
    import subprocess
    try:
        def get(key):
            out = subprocess.run(["git", "-C", cwd, "config", "--get", key],
                                 capture_output=True, text=True, timeout=3)
            return out.stdout.strip() if out.returncode == 0 else ""
        return get("commit.gpgsign").lower() == "true" or bool(get("user.signingkey"))
    except Exception:
        return False


def commit_msg_file(seg):
    """The -F/--file path of a /sign-shaped commit segment, or None when the shape is wrong."""
    if not COMMIT_SIGN_FLAG_RE.search(seg) or COMMIT_NO_SIGN_RE.search(seg):
        return None
    m = COMMIT_MSG_FILE_RE.search(seg)
    if not m or not SIGN_MSG_PATH_RE.search(m.group(1)):
        return None
    return m.group(1)


def file_has_signature(path, cwd):
    """SIGNATURE_RE over a -F message file. With -F the message never appears in the command, so
    without this read the signature tier would be blind to every /sign commit. Unreadable -> False."""
    try:
        full = path if os.path.isabs(path) else os.path.join(cwd, path)
        with open(os.path.expanduser(full), encoding="utf-8", errors="replace") as fh:
            return SIGNATURE_RE.search(fh.read()) is not None
    except Exception:
        return False


# DANGER pre-filter (ADR-005): a broad, cheap match on the raw command, used to pick the fail
# direction when the main pattern engine errors (deny when this trips, else fail open) and to judge
# a command value of an unsupported shape. Its vocabulary spans EVERY tier (impact, go-ahead, the
# /purge asks), so neither fallback lets through a whole tier the engine would have asked about.
# Kept tiny (near-zero failure surface) and LINEAR: as one regex, `tool[^\n]*verb` re-scanned the
# line for every tool word — each (tool, verb) pair here is two left-to-right scans per line.
class _Prefilter:
    _PAIRS = [
        (r"\b(terraform|terragrunt|gcloud|gsutil|az|aws|kubectl|helm)\b",
         r"\b(apply|destroy|delete|terminate|remove|update|patch|rm|drain|scale|uninstall|rollback)\b"),
        (r"\bkubectl\b", r"\b(replace|cordon|uncordon|rollout)\b"),
        (r"\bhelm\b", r"\b(install|upgrade)\b"),
        (r"\baws\b", r"\b(rb|mv)\b|\b(delete|terminate|remove|update)-"),
        (r"\bgit\b", r"\b(commit|push|merge)\b"),
        (r"\bgh\b", r"\b(create|merge|close|ready|delete|archive)\b"),
    ]
    _DIRECT = (r"(^|[;&|]\s*|\s)rm\s+(-[a-zA-Z]*[rf]|--recursive\b|--force\b)|"
               r"purge_delete\.sh|purge_scrub|mark_purge_session\.sh")

    def __init__(self):
        flags = re.IGNORECASE
        self.pairs = [(re.compile(t, flags), re.compile(v, flags)) for t, v in self._PAIRS]
        self.direct = re.compile(self._DIRECT, flags)

    def search(self, text):
        if self.direct.search(text):
            return True
        for line in text.split("\n"):
            for tool, verb in self.pairs:
                m = tool.search(line)
                if m and verb.search(line, m.end()):
                    return True
        return False


class _DenyAll:
    """Stand-in when the pre-filter itself failed to compile: every fallback decision is deny."""

    def search(self, text):
        return True


# Built under a guard, like the tier tables. The pre-filter IS the fallback, so a failure here
# cannot route to it: every path that relies on it (error, unsupported shape) then denies anything.
# The tiers themselves are unaffected and still decide normally.
_PREFILTER_ERROR = None
try:
    DANGER_PREFILTER = _Prefilter()
except Exception as _e:  # exercised by test_import_time_compile_failure_fails_closed
    _PREFILTER_ERROR = _e
    DANGER_PREFILTER = _DenyAll()


def normalize(command):
    """Fold shell line-continuations (backslash-newline) so a verb split across continued
    lines cannot evade the patterns. The shell removes `\\<newline>` entirely (joining with
    nothing), so we replace it with the empty string — otherwise a mid-token split like
    `terraform app\\<newline>ly` would normalize to `app ly` and slip past `apply`. Plain
    newlines stay — separate lines are separate commands.

    Backslashes are consumed in PAIRS, left to right (linear, one pass): `a\\\\<newline>` is an
    escaped backslash followed by a REAL newline, not a continuation. Folding its second backslash
    with the newline glued the next line onto this one (`a\\terraform apply` -> the fold read `\\t` as
    `t`), and the command on the next line vanished."""
    return _CONTINUATION.sub(_fold_continuation, command)


# A backslash pair (kept) or a backslash-newline continuation, scanned left to right.
_CONTINUATION = re.compile(r"\\(\\|\r?\n)")


def _fold_continuation(m):
    return m.group(0) if m.group(1) == "\\" else ""


def unjoin(command):
    """The command with every continuation turned into a plain newline: each physical line on its own.
    bash does NOT continue a COMMENT — in `echo x # note \\<newline>terraform apply` the backslash is
    part of the comment and line 2 runs — so normalize() alone hid line 2 inside the comment. main()
    evaluates this form as an extra layer after the joined one (extra layers only add decisions)."""
    return _CONTINUATION.sub(lambda m: m.group(0) if m.group(1) == "\\" else "\n", command)


def _needs_unjoin(command):
    """True when some physical line other than the last holds a `#`. A comment that swallows a
    continuation is the only case where bash differs from the joined form, so only then is the
    unjoined form evaluated. A deliberate over-approximation (no quote tracking). Unconditionally,
    it made multi-line validation commands ask: `kubectl delete ns x \\<newline> --dry-run=client`
    split the dry-run flag off its segment."""
    return "#" in command[:command.rfind("\n") + 1]


def command_forms(raw_command):
    """The forms main() evaluates, in order: the joined (normalized) command, then the unjoined one
    (see unjoin) when a comment could have swallowed a continuation (see _needs_unjoin)."""
    joined = normalize(raw_command)
    if not _needs_unjoin(raw_command):
        return [joined]
    split = unjoin(raw_command)
    return [joined] if split == joined else [joined, split]


# One shell word built from concatenated pieces, none of which holds whitespace or a separator:
#   unquoted char  [^\s;&|'"\\]      backslash escape  \\[^\s;&|]
#   single-quoted  '[^'\s;&|"]*'     double-quoted     "[^"\s;&|'\\]*"
# The shell executes `terraform "apply"`, `terraform ap"ply"`, `rm -r"f"` and `kubectl de\lete`
# exactly as the unquoted word, so such a word is folded before quoted ARGUMENTS are blanked —
# otherwise quoting (part of) the verb erased it from the string the tiers match against.
# Linear by construction (ReDoS guard — this module already had one): every alternative starts with
# a distinct character and no piece can cross whitespace or `;&|`, so no position inside a match is
# itself a word start, and each piece's length is fixed by its first character. That is also why the
# escape piece is `\\[^\s;&|]`, not `\\[^\n]`: an escaped space/separator would let a word span the
# next word's start and turn a failing scan quadratic. _blank_escaped_splits() removes those first.
_WORD_PIECES = r"""[^\s;&|'"\\]|\\[^\s;&|]|'[^'\s;&|"]*'|"[^"\s;&|'\\]*\""""
_SHELL_WORD = re.compile(r"(?<![^\s;&|])(?:" + _WORD_PIECES + r")+(?![^\s;&|])")
_WORD_PIECE = re.compile(r"""[^\s;&|'"\\]+|\\[^\s;&|]|'[^'\s;&|"]*'|"[^"\s;&|'\\]*\"""")
# Escaped characters kept WITH their backslash when a word is folded: emitted bare, a `\"` / `\'`
# would open a quote strip_quoted() then blanks across real commands, a `\#` at a word start would
# read as a comment to segments(), and `\\` would start a new escape. The same characters are
# re-escaped inside an unwrapped quoted run (`'#'`, `'\'`), for the same reasons.
_ESCAPE_KEEP = frozenset("'\"\\#")
_REESCAPE = re.compile(r"""([\\'"#])""")
# An escaped space or separator (`a\ b`, `a\;b`) is part of a word, not a split. It is rewritten to
# `_` BEFORE folding, so `terraform -chdir=a\ b apply` stays one segment with one `-chdir` word.
# Escapes are consumed pairwise left to right, so `\\;` (escaped backslash, then a REAL `;`) keeps
# its separator. `_` is a word character, so it never forms a new `\b` boundary around a verb.
_ESCAPED_SPLIT = re.compile(r"\\([\s;&|])|\\.", re.DOTALL)


def _blank_escaped_splits(command):
    return _ESCAPED_SPLIT.sub(lambda m: "_" if m.group(1) is not None else m.group(0), command)


def _fold_word(word, keep_values=True):
    """Rebuild one shell word for matching: unquoted characters kept, `\\c` -> `c`, quoted runs
    unwrapped — EXCEPT (keep_values) a quoted run right after `=` or `:` (or right after such a kept
    run), which is a VALUE (`--filter="name:delete-me"`, `--format="value(name)"`,
    `methodName:"delete"`) and is kept quoted so strip_quoted() blanks it as an argument.
    `--dry-run="client"` is the exception: its value decides the dry-run exemption, so it is unwrapped.

    The output must never create a separator, quote or comment the shell would not see: specials in
    an unwrapped run are re-escaped, and a `#` that would land at the start of the rebuilt word
    (`""#x`, which the shell reads as one word, not a comment) is escaped too."""
    out = []
    last = ""         # last character emitted so far in this word
    tail = ""         # the last few characters emitted (bounded: no quadratic re-join)
    in_value = False  # the previous piece was a kept (still-quoted) value run
    for piece in _WORD_PIECE.findall(word):
        head = piece[0]
        if head == "\\":
            text = piece if piece[1] in _ESCAPE_KEEP else piece[1]
            in_value = False
        elif head in "'\"":
            if keep_values and (in_value or (last in ("=", ":") and not tail.endswith("--dry-run="))):
                text, in_value = piece, True
            else:
                text, in_value = _REESCAPE.sub(r"\\\1", piece[1:-1]), False
        else:
            text, in_value = piece, False
        if text.startswith("#") and out and not last:
            text = "\\" + text  # mid-word `#` after an empty run: not a comment in the shell
        out.append(text)
        if text:
            last = text[-1]
            tail = (tail + text)[-10:]
    return "".join(out)


def unwrap_token_quotes(command, keep_values=True):
    """Fold shell words whose quoting the shell removes, leaving genuine quoted ARGUMENTS intact for
    strip_quoted(). Whole-word (`terraform "apply"`), partial (`terraform ap"ply"`, `"--a"pply`) and
    backslash-escaped (`terraform ap\\ply`) forms all fold to the bare word. Quoted runs holding
    whitespace, a separator, a nested quote or a backslash are not word pieces, so they stay quoted:
    `echo "terraform apply"`, `'protoPayload.methodName:"delete"'`. A quoted run directly after `=`
    or `:` is a value and stays quoted too (see _fold_word) — unless keep_values=False, the form the
    /purge asks also read so a value-shaped quote cannot hide a purge script path. A word with an
    unbalanced quote is not folded at all. Escaped spaces/separators are first blanked to `_`
    (_blank_escaped_splits) so they can neither split a segment nor stop a word from folding."""
    command = _blank_escaped_splits(command)
    return _SHELL_WORD.sub(lambda m: _fold_word(m.group(0), keep_values), command)


# Quoted runs as the shell reads them: a backslash escape OUTSIDE quotes is consumed first, so `\"`
# never opens a quote, and a double-quoted run honours `\"` inside it. Each alternative starts with a
# distinct character -> linear.
_QUOTED_RUN = re.compile(r"""\\.|'[^']*'|"(?:[^"\\]|\\.)*\"""", re.DOTALL)


def _blank_run(m):
    """A quoted run becomes a space; before a `#` it becomes ` _`, so the blank cannot turn a
    mid-word `#` (`'a b'#x`, one shell word) into a comment that hides the rest of the line."""
    run = m.group(0)
    if run[0] == "\\":
        return run
    return " _" if m.string.startswith("#", m.end()) else " "


def strip_quoted(command):
    """Blank out single/double-quoted substrings that survive unwrap_token_quotes() — i.e. genuine
    quoted ARGUMENTS. A verb inside one (e.g. `gcloud logging read '... methodName:"delete" ...'`,
    a read-only query) is a false positive; matching the command-token tiers against the stripped
    form removes that class. Observed live: a `gcloud logging read` with "delete" in the filter was
    flagged ask-impact under the Codex adapter. Order matters — unwrap first, blank second: blanking
    alone treated `terraform "apply"` as a quoted argument and let it through. Escapes are honoured:
    `echo \\" ; terraform apply ; echo \\"` holds no quoted run (the naive `"[^"]*"` blanked the
    whole middle command). The SIGNATURE tier is the exception (its match lives inside the quoted
    commit message) and keeps the raw command."""
    return _QUOTED_RUN.sub(_blank_run, command)


def segments(command):
    """Split a quote-blanked command into the segments the shell executes separately, dropping
    `#` comments. Tier decisions are made per segment: a --dry-run flag, or an EXEMPT match, in
    one segment must never speak for another (`kubectl delete x --dry-run=client; kubectl delete x`).
    Safe to run after strip_quoted only — a `#`, `;` or `&&` inside quotes is already blanked, so it
    can never be misread here as a comment or a separator."""
    no_comments = re.sub(r"(?:^|\s)#[^\n]*", " ", command)
    return [seg for seg in re.split(r"[;&|\n]+", no_comments) if seg.strip()]


_SHELL_LONG_OPTS = ("--norc", "--noprofile", "--login")
_SHELL_C_RE = re.compile(r"^\s*(?:\S*/)?(?:bash|sh|zsh)\s+(?:(?:--norc|--noprofile|--login)\s+)*"
                         r"-[A-Za-z]*c[A-Za-z]*\s")
_SHELL_C_FLAG = re.compile(r"-[A-Za-z]*c[A-Za-z]*")


def shell_c_layers(command, depth=3):
    """Yield command, inner, …: the command plus the script each `bash|sh|zsh -c/-lc '<cmd>'` wrapper
    runs. A Codex argv-style call (`["bash", "-lc", "<cmd>"]`) can reach this hook joined as one
    string; strip_quoted() would blank the whole inner command, so every tier would miss it while
    capture_session.py's detector unwraps it. Accepted shapes: `<shell> [--norc|--noprofile|--login]…
    -<flags with c> '<cmd>' [arg0 args…]` — the inner layer is the word after the -c flag. The outer
    layer (anything chained or trailing included) is always evaluated FIRST, and _evaluate() only
    ever emits ask/deny, so an extra inner layer can add a decision, never remove one.

    A GENERATOR: the outer command is yielded before any inner layer is parsed, so main() has fully
    evaluated it before shlex ever runs — a parser fault on an inner layer can no longer demote the
    outer command from the full tiers to the DANGER_PREFILTER fallback."""
    yield command
    import shlex
    for _ in range(depth):
        if not _SHELL_C_RE.match(command):
            break
        try:
            argv = shlex.split(command)
        except ValueError:
            break
        i = 1
        while i < len(argv) and argv[i] in _SHELL_LONG_OPTS:
            i += 1
        if not (len(argv) > i + 1 and os.path.basename(argv[0]) in ("bash", "sh", "zsh")
                and _SHELL_C_FLAG.fullmatch(argv[i])):
            break
        inner = argv[i + 1]
        command = normalize(inner)
        yield command
        split = unjoin(inner) if _needs_unjoin(inner) else command
        if split != command:
            yield split  # each physical line of the inner script too (comment-continuation, see unjoin)

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


def emit_antigravity(decision, reason):
    """Antigravity PreToolUse / Gemini BeforeTool contract: {"decision": ..., "reason": ...} on stdout (JSON only)."""
    json.dump({"decision": decision,
               "reason": "[bailiwick guardrail] " + reason}, sys.stdout)
    sys.stdout.write("\n")


emit_gemini = emit_antigravity

# Antigravity's "ask" respects cached grants; only force_ask guarantees the re-confirmation.
ASK_VERB = {"antigravity": "force_ask", "gemini": "ask"}


# Audit-event label per tier (adapter-prefixed for codex/gemini/antigravity at the call site).
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


# Per-invocation decision state. `decided`: a decision (including Codex's break-glass allow-once)
# was reached, so no fallback may emit a second one. `budget_armed`: the evaluation timer is live.
_STATE = {"decided": False, "budget_armed": False}


def _settle():
    """First step of every decision: disarm the evaluation budget BEFORE auditing/emitting (an alarm
    inside _audit would otherwise abort the ask before it is printed), and record that a decision
    exists so main()'s fallback never prints a second JSON object."""
    if _STATE["budget_armed"]:
        import signal
        signal.setitimer(signal.ITIMER_REAL, 0)
        _STATE["budget_armed"] = False
    _STATE["decided"] = True


def _respond(adapter, tier, reason, command, project_dir):
    """Map a tier decision onto the adapter's decision contract (see ADAPTER MAPPING)."""
    _settle()
    if adapter in ("antigravity", "gemini"):
        prefix = "antigravity:" if adapter == "antigravity" else "gemini:"
        _audit(prefix + AUDIT_EVENT[tier], command, project_dir)
        emit_antigravity(ASK_VERB[adapter], reason)
    elif adapter == "codex":
        if os.environ.get("BAILIWICK_BREAK_GLASS") == "1":
            _audit("codex:break-glass-allow", command, project_dir)
            return  # allow-once: no decision emitted; the override is the audit trail
        _audit("codex:" + AUDIT_EVENT[tier], command, project_dir)
        emit("deny", reason + " " + CODEX_REMEDY[tier])
    else:
        _audit(AUDIT_EVENT[tier], command, project_dir)
        emit("ask", reason)


def _decide_deny(adapter, reason, command, project_dir, event="deny"):
    """Hard deny — the error-path fail-closed deny and the signed-commit shape tier. Break-glass
    downgrades it to ask (claude/antigravity/gemini) or allow-once (codex, which has no ask).
    Audits every outcome; `event` labels the non-break-glass audit line."""
    _settle()
    bg = os.environ.get("BAILIWICK_BREAK_GLASS") == "1"
    if adapter in ("antigravity", "gemini"):
        prefix = "antigravity:" if adapter == "antigravity" else "gemini:"
        if bg:
            _audit(prefix + "break-glass", command, project_dir)
            emit_antigravity(ASK_VERB[adapter], "BREAK-GLASS override active — " + reason + " Confirm deliberately; logged.")
        else:
            _audit(prefix + event, command, project_dir)
            emit_antigravity("deny", reason)
    elif adapter == "codex":
        if bg:
            _audit("codex:break-glass-allow", command, project_dir)
        else:
            _audit("codex:" + event, command, project_dir)
            emit("deny", reason)
    else:
        if bg:
            _audit("break-glass", command, project_dir)
            emit("ask", "BREAK-GLASS override active (BAILIWICK_BREAK_GLASS) — " + reason
                 + " Confirm deliberately; this override is logged.")
        else:
            _audit(event, command, project_dir)
            emit("deny", reason)


def _evaluate(command, adapter, payload, raw_command, project_dir):
    """Run the tiers on one command layer; True when a decision was emitted. Raises on an engine
    fault (main() applies the fail-closed pre-filter)."""
    # Command-token tiers (impact / go-ahead) match against the quote-stripped form so a verb inside
    # a quoted argument isn't a false positive — but shell words are folded first (whole-word,
    # partial and backslash-escaped quoting), since `terraform "apply"` / `terraform ap"ply"` run as
    # `terraform apply`. The signature tier keeps `command` (needs the quotes).
    cmd_tokens = strip_quoted(unwrap_token_quotes(command))

    # Evaluate tiers in order: /PURGE ASKS → EXEMPT → ASK-IMPACT → SIGNED-COMMIT SHAPE →
    # ASK-SIGNATURE → ASK-GO-AHEAD.
    all_segs = segments(cmd_tokens)
    # /purge asks FIRST, on every segment and on the raw command: an EXEMPT claim can never swallow
    # them, and a command that is ONLY a quoted path blanks to nothing (hence the raw companions).
    # They also read the form with value-shaped quotes unwrapped (`bash d=x"/…/mark_purge_session.sh"`
    # would otherwise blank the script path): the script names are distinctive, so this costs no
    # false positives, unlike the generic verbs.
    for raw_re, what in PURGE_RAW_ASKS:
        if raw_re.search(command):
            _respond(adapter, "impact", "HIGH-IMPACT: " + what
                     + " — blocked from agent initiative; re-confirm this is really the intent.",
                     raw_command, project_dir)
            return True
    purge_segs = list(all_segs)
    full_tokens = strip_quoted(unwrap_token_quotes(command, keep_values=False))
    if full_tokens != cmd_tokens:  # only the segments a value-unwrap changed are re-checked
        seen = set(all_segs)
        purge_segs += [seg for seg in segments(full_tokens) if seg not in seen]
    for seg in purge_segs:
        for pattern, _dry_exempt, what in PURGE_ASK_PATTERNS:
            if pattern.search(seg):
                _respond(adapter, "impact", "HIGH-IMPACT: " + what
                         + " — blocked from agent initiative; re-confirm this is really the intent.",
                         raw_command, project_dir)
                return True
    # Per-segment evaluation (ADR-006 amendment): EXEMPT clears only its own segment, and the
    # dry-run exemption only the segment that matched — neither speaks for a chained command.
    segs = [seg for seg in all_segs
            if not (any(p.search(seg) for p in EXEMPT_PATTERNS)
                    and not EXEMPT_DISQUALIFIERS.search(seg))]
    if not segs:
        return False  # dirty-zone capture plumbing only — never blocked (data-loss prevention)
    for seg in segs:
        seg_dry_run = DRY_RUN_RE.search(seg) is not None
        for pattern, dry_exempt, what in ASK_IMPACT_PATTERNS:
            if dry_exempt and seg_dry_run:
                continue  # validation-only form in THIS segment — no real impact
            if pattern.search(seg):
                _respond(adapter, "impact", "HIGH-IMPACT: " + what
                         + " — blocked from agent initiative; re-confirm this is really the intent.",
                         raw_command, project_dir)
                return True
    # SIGNED-COMMIT SHAPE: deny a commit that skipped /sign in a repo that signs; for a
    # /sign-shaped commit, scan the -F message file, which the command text never shows.
    commit_segs = [seg for seg in segs if is_git_commit(seg)]
    file_signature = False
    if commit_segs:
        shell_cwd = (payload.get("cwd") if isinstance(payload, dict) else None) or project_dir
        if repo_signs(shell_cwd):
            for seg in commit_segs:
                msg_file = commit_msg_file(seg)
                if msg_file is None:
                    _decide_deny(adapter, UNSIGNED_SHAPE_REASON, raw_command, project_dir,
                                 event="deny-unsigned-shape")
                    return True
                file_signature = file_signature or file_has_signature(msg_file, shell_cwd)
    if file_signature or (GIT_MESSAGE_RE.search(command) and SIGNATURE_RE.search(command)):
        _respond(adapter, "signature",
                 "the commit/PR message carries an AI attribution signature "
                 "(Co-Authored-By / 'Generated with' / robot emoji) — confirm it is wanted, "
                 "or strip it before proceeding.",
                 raw_command, project_dir)
        return True
    for seg in segs:
        for pattern, reason in ASK_GOAHEAD_PATTERNS:
            if pattern.search(seg):
                _respond(adapter, "goahead", reason, raw_command, project_dir)
                return True
    return False


def _field(obj, key):
    """obj[key] when obj is a dict, else None — payload sub-objects are never trusted to be dicts."""
    return obj.get(key) if isinstance(obj, dict) else None


def command_text(value, adapter="claude"):
    """Normalise a hook payload's command value to the one string the tiers read. A str stays; an
    argv list/tuple of str is shell-joined (`["bash", "-lc", "terraform apply"]` ->
    `bash -lc 'terraform apply'`, which shell_c_layers() then unwraps). Before this, a list reached
    `.strip()` outside main()'s try, raised, and __main__'s catch-all exited 0 — a silent fail-open.
    None/empty -> "" (nothing to evaluate). Any other shape (dict, number, a list holding a non-str)
    -> None, with a health warning: main() then runs the fail-closed pre-filter over its JSON."""
    if value is None or isinstance(value, str):
        return value or ""
    if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        import shlex
        return shlex.join(value)
    _health("warn", "unsupported command value ({}): {} — pre-filter only".format(
        adapter, type(value).__name__))
    return None


# Wall-clock budget for the tier evaluation. Codex and Antigravity kill a hook at 30 s, and a killed
# hook FAILS OPEN — so a pathological command that out-ran the matcher would run unconfirmed. On
# expiry the command is DENIED unconditionally (break-glass semantics as the error path): an overrun
# says nothing about which tier would have matched, and the pre-filter cannot stand in for the full
# tiers (a 24 MB `echo …; git push` once overran and was allowed). POSIX only (SIGALRM, main thread);
# elsewhere a no-op, leaving the linear matchers as the only guard.
EVAL_BUDGET_SECONDS = 10.0


class EvaluationBudgetExceeded(BaseException):
    """Raised by the SIGALRM handler when the tier evaluation overruns EVAL_BUDGET_SECONDS. A
    BaseException on purpose: the `except Exception` guards in repo_signs()/file_has_signature()/
    _audit() must not swallow it (the timer fires once — a swallowed expiry ran the rest unbudgeted)."""


def _run_with_budget(fn, seconds):
    """fn() under a SIGALRM interval timer; the timer and the previous handler are always restored
    before returning or raising. A decision disarms the timer itself (see _settle)."""
    import signal
    import threading
    if not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        return fn()

    def _expired(signum, frame):
        _STATE["budget_armed"] = False
        raise EvaluationBudgetExceeded("evaluation exceeded {}s".format(seconds))

    previous = signal.signal(signal.SIGALRM, _expired)
    _STATE["budget_armed"] = True
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        _STATE["budget_armed"] = False
        signal.signal(signal.SIGALRM, previous)


def _evaluate_layers(raw_command, adapter, payload, project_dir):
    """Every layer of every form, as-given first: the joined command, the script inside each
    `bash -c '<cmd>'` wrapper (see shell_c_layers), then the unjoined form's layers (see unjoin).
    The first layer that draws a decision ends the evaluation; layers already seen are skipped. The
    generators yield the outer command before parsing any inner layer, so the outer command always
    gets the full tiers even if inner parsing faults."""
    seen = set()
    for form in command_forms(raw_command):
        for layer in shell_c_layers(form):
            if layer in seen:
                continue
            seen.add(layer)
            if _evaluate(layer, adapter, payload, raw_command, project_dir):
                return True
    return False


def main(adapter="claude"):
    _STATE["decided"] = False
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # Fail open — never wedge the harness on a malformed payload.
    if not isinstance(payload, dict):
        return 0  # Same: nothing to evaluate.

    tool_call = payload.get("toolCall")
    if adapter in ("antigravity", "gemini"):
        # Antigravity sends toolCall: {name: "run_command", args: {CommandLine: "..."}}
        # Legacy Gemini CLI sends tool_name: "run_shell_command", tool_input: {command: "..."}
        if isinstance(tool_call, dict):
            tool = tool_call.get("name") or ""
            if tool != "run_command":
                return 0
            value = _field(tool_call.get("args"), "CommandLine")
        else:
            tool = payload.get("tool_name") or ""
            if tool not in ("run_shell_command", "run_command"):
                return 0
            value = _field(payload.get("tool_input"), "command")
    else:
        tool = payload.get("tool_name") or ""
        if tool != "Bash":  # claude and codex both use the canonical "Bash" tool name
            return 0
        value = _field(payload.get("tool_input"), "command")

    raw_command = command_text(value, adapter)
    if raw_command is not None and not raw_command.strip():
        return 0
    # Antigravity carries workspacePaths / cwd; Gemini exports CLAUDE_PROJECT_DIR; Codex cwd.
    project_dir = bw_common.resolve_project_dir(payload)
    if not (is_bailiwick_repo(project_dir) or is_shadow_repo(project_dir)):
        return 0  # Inert outside bailiwick-wired repos (seeded or shadow-activated).
    if _PREFILTER_ERROR is not None:
        _health("error", "pre-filter failed to compile — fallbacks deny everything: {!r}".format(
            _PREFILTER_ERROR)[:200])

    if raw_command is None:
        # A command shape no adapter documents: the tiers cannot read it, but it must not be a plain
        # fail-open either — the error path's pre-filter decides over its JSON text.
        try:
            blob = json.dumps(value, ensure_ascii=False, default=str)
            if DANGER_PREFILTER.search(blob):
                _decide_deny(adapter, "unsupported command shape that looks destructive — denied "
                             "(fail-closed, ADR-005). Set BAILIWICK_BREAK_GLASS=1 to override "
                             "deliberately.", blob, project_dir, event="deny-unsupported-shape")
        except Exception:
            pass
        return 0

    try:
        if _TABLE_ERROR is not None:
            raise RuntimeError("tier tables failed to compile: {!r}".format(_TABLE_ERROR))
        if _run_with_budget(lambda: _evaluate_layers(raw_command, adapter, payload, project_dir),
                            EVAL_BUDGET_SECONDS):
            return 0
    except EvaluationBudgetExceeded as e:
        _health("error", "evaluation budget exceeded ({}): {}".format(adapter, e)[:200])
        if not _STATE["decided"]:
            try:
                _decide_deny(
                    adapter,
                    "guardrail evaluation exceeded its time budget — denied (fail-closed, ADR-005); "
                    "the command could not be checked. Set BAILIWICK_BREAK_GLASS=1 to override "
                    "deliberately.", raw_command, project_dir, event="deny-budget")
            except Exception:
                pass
    except Exception as e:
        _health("error", "pattern engine failure ({}): {!r}".format(adapter, e)[:200])
        if _STATE["decided"]:
            return 0  # a decision is already out — never print a second one
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
            if _arg in ("claude", "codex", "gemini", "antigravity"):
                _adapter = _arg
        sys.exit(main(_adapter))
    except Exception:
        sys.exit(0)  # Never wedge the harness on an unexpected error.
