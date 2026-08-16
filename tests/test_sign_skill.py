#!/usr/bin/env python3
"""Contract tests for skills/sign/check_message.py — the /sign attribution pre-flight.

What CI proves here is the property the skill actually leans on: the helper does NOT own the
attribution pattern. It imports SIGNATURE_RE from hooks/guardrails.py, the same regex the
PreToolUse guardrail enforces, so the pre-flight and the runtime block can never disagree. A
second copy of the pattern would drift, and the copy that drifts is always the one that isn't
enforcing anything — so the test that matters most is the one asserting the import, not the
one asserting a hardcoded string.

The exit codes are a contract too, and a load-bearing one: a caller cannot tell "your message
is dirty" from "your install is broken" if both return 1. 0 clean · 1 signature · 2 unreachable.
"""
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKER = REPO_ROOT / "skills" / "sign" / "check_message.py"


def run(arg, stdin=None, checker=None):
    """Invoke the helper as the skill does — a subprocess, not an import."""
    return subprocess.run(
        [sys.executable, str(checker or CHECKER), arg],
        input=stdin,
        capture_output=True,
        text=True,
    )


def msg(tmp_path, text, name="COMMIT_MSG"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


# --- the pattern comes from the guardrail, not from here -------------------------------------

def test_pattern_is_imported_from_the_guardrail_not_redefined():
    """The helper must not carry its own copy of the pattern — that is the whole design."""
    src = CHECKER.read_text(encoding="utf-8")
    assert "SIGNATURE_RE" in src, "helper no longer references the guardrail's pattern name"
    assert "guardrails.py" in src, "helper no longer resolves hooks/guardrails.py"
    # A literal re.compile of an attribution pattern here would mean a second source of truth.
    assert "re.compile" not in src, "helper defines its own pattern — it must import the guardrail's"


def test_guardrail_still_exposes_the_contract():
    """If hooks/guardrails.py drops SIGNATURE_RE, the skill breaks — fail here, loudly, first."""
    sys.path.insert(0, str(REPO_ROOT / "hooks"))
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_bw_guardrails_probe", REPO_ROOT / "hooks" / "guardrails.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "SIGNATURE_RE"), "guardrails.py no longer defines SIGNATURE_RE"
    assert mod.SIGNATURE_RE.search("Co-Authored-By: Claude <noreply@anthropic.com>")


# --- exit code 0: clean ------------------------------------------------------------------------

def test_clean_conventional_message_passes(tmp_path):
    r = run(msg(tmp_path, "fix(mcp): install the fetch runner and pin its SDK\n\nWhy, not what.\n"))
    assert r.returncode == 0, r.stderr
    assert "no AI attribution signature" in r.stdout


def test_message_merely_discussing_the_rule_is_not_a_hit(tmp_path):
    """Docs and this repo's own commits talk ABOUT attribution; that must not trip the check."""
    r = run(msg(tmp_path, "docs: explain why we strip attribution trailers from commits\n"))
    assert r.returncode == 0, r.stdout + r.stderr


# --- exit code 1: each attribution form the framework bans -------------------------------------

def test_co_authored_by_is_caught(tmp_path):
    r = run(msg(tmp_path, "feat: x\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n"))
    assert r.returncode == 1
    assert "signature found" in r.stdout
    assert "line 3" in r.stdout, "the offending line number must be reported"


def test_generated_with_is_caught(tmp_path):
    r = run(msg(tmp_path, "feat: x\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)\n"))
    assert r.returncode == 1


def test_robot_emoji_is_caught(tmp_path):
    r = run(msg(tmp_path, "feat: x\n\n🤖\n"))
    assert r.returncode == 1


def test_every_hit_line_is_listed(tmp_path):
    body = "feat: x\n\nCo-Authored-By: Claude <a@b>\nsome text\nCo-Authored-By: Claude <c@d>\n"
    r = run(msg(tmp_path, body))
    assert r.returncode == 1
    assert "line 3" in r.stdout and "line 5" in r.stdout


# --- stdin ------------------------------------------------------------------------------------

def test_reads_stdin_when_arg_is_dash():
    assert run("-", stdin="fix: clean\n").returncode == 0
    assert run("-", stdin="feat: x\n\nCo-Authored-By: Claude <a@b>\n").returncode == 1


# --- exit code 2: a broken install must never read as a dirty message --------------------------

def test_no_arguments_exits_2_not_1():
    r = subprocess.run([sys.executable, str(CHECKER)], capture_output=True, text=True)
    assert r.returncode == 2, "misuse must be distinguishable from a signature hit"


def test_unreachable_guardrail_exits_2_not_1(tmp_path):
    """Transplanted out of the framework clone, the helper must say so — not report 'clean',
    and not report '1' as though the message were dirty."""
    orphan_dir = tmp_path / "elsewhere" / "skills" / "sign"
    orphan_dir.mkdir(parents=True)
    orphan = orphan_dir / "check_message.py"
    shutil.copy(CHECKER, orphan)
    r = run(msg(tmp_path, "fix: clean\n"), checker=orphan)
    assert r.returncode == 2, f"expected 2 (unreachable), got {r.returncode}"
    assert "cannot find" in r.stderr


def test_guardrail_without_signature_re_exits_2(tmp_path):
    """The contract moving (SIGNATURE_RE renamed/removed) is a distinct, named failure."""
    fake_root = tmp_path / "fakeclone"
    (fake_root / "hooks").mkdir(parents=True)
    (fake_root / "hooks" / "guardrails.py").write_text("# no SIGNATURE_RE here\n", encoding="utf-8")
    skill_dir = fake_root / "skills" / "sign"
    skill_dir.mkdir(parents=True)
    orphan = skill_dir / "check_message.py"
    shutil.copy(CHECKER, orphan)
    r = run(msg(tmp_path, "fix: clean\n"), checker=orphan)
    assert r.returncode == 2
    assert "SIGNATURE_RE" in r.stderr


# --- the skill file itself ----------------------------------------------------------------------

def test_skill_md_has_frontmatter_and_never_pushes():
    """/sign's stated boundary is load-bearing: publishing is a separate authorised step."""
    src = (REPO_ROOT / "skills" / "sign" / "SKILL.md").read_text(encoding="utf-8")
    assert src.startswith("---\n"), "SKILL.md needs YAML frontmatter to be discovered"
    assert "\nname: sign\n" in src
    assert "Never pushes" in src, "the no-push boundary must stay stated in the skill"
    assert "--pinentry-mode error" in src, "the non-hanging probe is the skill's core mechanic"


# --- Codex wrapper parity -----------------------------------------------------------------------
#
# The wrapper is a SECOND copy of the procedure's rules, which is exactly the drift risk the helper
# itself was designed to avoid. It is allowed to differ on one axis only — how the user is asked to
# unlock the key, since Codex has no `!` prefix — and must agree on every safety boundary. These
# tests are the thing that notices when it stops agreeing.

CODEX_WRAPPER = REPO_ROOT / "codex-skills" / "bailiwick-sign" / "SKILL.md"


def test_codex_wrapper_exists_with_discoverable_frontmatter():
    assert CODEX_WRAPPER.is_file(), "Codex wrapper missing — /sign is unreachable from Codex"
    src = CODEX_WRAPPER.read_text(encoding="utf-8")
    assert src.startswith("---\n"), "wrapper needs YAML frontmatter to be discovered"
    assert "\nname: bailiwick-sign\n" in src, "wrapper name must match its directory"
    yaml = CODEX_WRAPPER.parent / "agents" / "openai.yaml"
    assert yaml.is_file(), "wrapper needs agents/openai.yaml, like the other Codex skills"
    assert "display_name:" in yaml.read_text(encoding="utf-8")


def test_codex_wrapper_defers_to_the_canonical_procedure():
    """A wrapper that stops pointing at the canonical file has become a fork."""
    src = CODEX_WRAPPER.read_text(encoding="utf-8")
    assert "skills/sign/SKILL.md" in src, "wrapper no longer points at the canonical procedure"
    assert "thin Codex wrapper" in src, "wrapper must state that it is not the source of truth"


def test_codex_wrapper_keeps_every_safety_boundary():
    """These are the rules that must never differ between the two copies."""
    src = CODEX_WRAPPER.read_text(encoding="utf-8")
    for rule, why in [
        ("Never pushes", "the no-push boundary"),
        ("--pinentry-mode error", "the non-hanging probe"),
        ("Co-Authored-By", "the attribution rule"),
        ("check_message.py", "the pre-flight step"),
        ("loopback", "the ban on sidestepping pinentry"),
    ]:
        assert rule in src, f"Codex wrapper dropped {why} ({rule!r})"


def test_codex_wrapper_documents_all_three_exit_codes():
    """Exit 2 is the one that matters: a broken install must not read as a dirty message."""
    src = CODEX_WRAPPER.read_text(encoding="utf-8")
    assert "`2`" in src and "`1`" in src and "`0`" in src, "wrapper must document 0/1/2"


def test_both_copies_document_the_handover_fallback():
    """A re-probe that keeps failing must terminate in a handover, not an unlock loop.

    Observed in practice: on some machines a successful unlock leaves no usable cache for the
    agent's process (keyinfo reads '-' immediately after), so re-probing never succeeds while the
    user's own terminal signs fine. Both copies must say so, and must still require verification.
    """
    for path in (REPO_ROOT / "skills" / "sign" / "SKILL.md", CODEX_WRAPPER):
        src = path.read_text(encoding="utf-8")
        assert "keyinfo" in src, f"{path.name} does not show how to confirm the cache is absent"
        assert "do not loop" in src.lower(), f"{path.name} does not forbid the unlock loop"
        assert "verify" in src.lower(), f"{path.name} dropped the verification requirement"


def test_both_copies_chain_the_probe_to_the_commit():
    """The probe must be fresh at execution, not left over from an earlier call.

    default-cache-ttl is an IDLE timer and approval latency counts against it, so a probe that
    passed in a previous tool call proves nothing by the time `git commit -S` re-signs. Both copies
    must chain them with && so the approval precedes both and a cold key short-circuits.
    """
    for path in (REPO_ROOT / "skills" / "sign" / "SKILL.md", CODEX_WRAPPER):
        src = path.read_text(encoding="utf-8")
        assert "&& git commit -S" in src, f"{path.name} does not chain the probe to the commit"
        assert "idle" in src.lower(), f"{path.name} does not explain the idle-TTL mechanism"


def test_codex_wrapper_does_not_instruct_the_claude_only_unlock():
    """The one permitted divergence, asserted in the right direction: Codex has no `!` prefix, so
    the wrapper must tell the user to unlock in their own terminal instead of copying Claude's."""
    src = CODEX_WRAPPER.read_text(encoding="utf-8")
    assert "own terminal" in src, "wrapper must give Codex users a workable unlock route"
    assert "`!` prefix runs it in the session shell" not in src, (
        "wrapper copied Claude Code's `!` unlock, which does not exist in Codex"
    )
