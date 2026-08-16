#!/usr/bin/env python3
"""Pre-flight a commit/PR message for an AI attribution signature.

The pattern is NOT redefined here. It is imported from hooks/guardrails.py, which is the
runtime enforcement point (PreToolUse) for the same rule — two copies would drift, and the
copy that drifts is always the one that isn't enforcing anything. This check exists only to
catch the signature BEFORE the commit is attempted, so the guardrail's confirmation prompt
never has to fire.

guardrails.py is import-safe: everything executable sits behind `if __name__ == "__main__"`.

Usage:  python3 check_message.py <msgfile>      # or: … - , to read stdin
Exit:   0 clean · 1 signature found · 2 could not reach the guardrail pattern
"""
import importlib.util
import pathlib
import sys

# Resolve via THIS file, never $BAILIWICK: the skill is reached through a symlink in
# ~/.claude/skills/, and .resolve() follows it back into the framework clone, so the
# hooks/ dir is always adjacent whether or not the env var is set or correct.
GUARDRAILS = pathlib.Path(__file__).resolve().parents[2] / "hooks" / "guardrails.py"


UNREACHABLE = 2  # distinct from 1: a broken install must never read as a dirty message


def _unreachable(msg):
    """Exit 2, not 1. sys.exit(str) would print and exit 1 — indistinguishable from a hit."""
    print(f"check_message: {msg}", file=sys.stderr)
    sys.exit(UNREACHABLE)


def signature_re():
    if not GUARDRAILS.is_file():
        _unreachable(f"cannot find {GUARDRAILS} — is this skill still inside the framework clone?")
    spec = importlib.util.spec_from_file_location("_bw_guardrails", GUARDRAILS)
    mod = importlib.util.module_from_spec(spec)
    # guardrails.py imports siblings (bw_common); its own dir has to be importable.
    sys.path.insert(0, str(GUARDRAILS.parent))
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001 — any failure here must be loud, not silent
        _unreachable(f"could not load {GUARDRAILS}: {exc}")
    try:
        return mod.SIGNATURE_RE
    except AttributeError:
        _unreachable(f"{GUARDRAILS} defines no SIGNATURE_RE — the guardrail contract moved")


def main():
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return UNREACHABLE
    src = sys.argv[1]
    text = sys.stdin.read() if src == "-" else pathlib.Path(src).read_text(encoding="utf-8")

    rx = signature_re()
    hits = [(i, ln) for i, ln in enumerate(text.splitlines(), 1) if rx.search(ln)]
    if not hits:
        print("✓ no AI attribution signature (checked against hooks/guardrails.py SIGNATURE_RE)")
        return 0
    print("✗ AI attribution signature found — strip it before committing:")
    for i, ln in hits:
        print(f"    line {i}: {ln.strip()}")
    print("\nThe framework's non-negotiable: a signature never lands by agent initiative.")
    print("Keep it ONLY if the user explicitly asked for it — then expect the guardrail to confirm.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
