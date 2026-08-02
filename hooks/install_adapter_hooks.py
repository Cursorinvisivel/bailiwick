#!/usr/bin/env python3
"""Install the bailiwick guardrail as Codex + Gemini pre-execution hooks (global, per machine).

Usage: install_adapter_hooks.py            # install/refresh both adapters
       install_adapter_hooks.py codex      # just one
       install_adapter_hooks.py gemini

Wires guardrails.py (the same engine Claude Code runs) into:
  - Codex CLI:  a managed block in ~/.codex/config.toml  -> [[hooks.PreToolUse]] matcher "^Bash$"
                (Codex requires a one-time interactive trust of new hooks — TUI `/hooks`;
                 until trusted, the hook is configured but does not run.)
  - Gemini CLI: a named entry in ~/.gemini/settings.json -> hooks.BeforeTool
                (matcher "run_shell_command"; decision "ask" mirrors the Claude Code tiers).

Idempotent and non-destructive: the Codex block is marker-delimited and replaced in place;
the Gemini entry is identified by hook name "bailiwick-guardrail" and updated in place.
Everything else in both files is preserved. Refuses to touch a malformed settings.json.
Both hooks self-gate (wired/shadow repos only), so installing globally is safe.

Prints one line per adapter: INSTALLED | UPDATED | PRESENT | ERROR: <msg>
Exit 0 unless an ERROR occurred.

Path portability: like install_hooks.py, the command paths are built from THIS file's real
location, so satellites get their own Bailiwick path automatically.
"""
import json
import os
import re
import sys

BAILIWICK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARDRAIL = os.path.join(BAILIWICK_ROOT, "hooks", "guardrails.py")

CODEX_BEGIN = "# BEGIN bailiwick hooks (managed - do not edit inside; reinstall via bootstrap --install-tools)"
CODEX_END = "# END bailiwick hooks"
GEMINI_HOOK_NAME = "bailiwick-guardrail"

def codex_block():
    # TOML: forward slashes work on Windows too; commandWindows covers a python3-less PATH.
    posix = GUARDRAIL.replace("\\", "/")
    return """{begin}
[[hooks.PreToolUse]]
matcher = "^Bash$"

[[hooks.PreToolUse.hooks]]
type = "command"
command = 'python3 "{path}" codex'
commandWindows = 'python "{path}" codex'
timeout = 30
statusMessage = "bailiwick guardrail"
{end}
""".format(begin=CODEX_BEGIN, path=posix, end=CODEX_END)


def install_codex():
    home = os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
    cfg = os.path.join(home, "config.toml")
    os.makedirs(home, exist_ok=True)
    text = ""
    if os.path.exists(cfg):
        with open(cfg, encoding="utf-8") as fh:
            text = fh.read()
    orig = text
    block = codex_block()
    pattern = re.compile(re.escape(CODEX_BEGIN) + r"(.*?)" + re.escape(CODEX_END) + r"\n?", re.S)
    m = pattern.search(text)
    if m:
        # Codex persists its hook TRUST as a `[hooks.state."..."]` table that it writes ADJACENT to
        # the hook — observed landing INSIDE our managed markers. A naive block replace would wipe
        # the trust, forcing a re-trust after every reinstall. So carry any `[hooks.state...]` tables
        # from the old block into the new one (before END). The trust hash is over the hook's own
        # definition, so if the command actually changed the hash simply won't match and Codex
        # re-prompts once — correct — but an idempotent reinstall keeps trust intact.
        preserved = "".join(re.findall(r"(\[hooks\.state[^\n]*\][^\[]*)", m.group(1)))
        new_block = block
        if preserved.strip():
            new_block = block.replace(CODEX_END, preserved.rstrip("\n") + "\n" + CODEX_END)
        new = pattern.sub(lambda _: new_block, text, count=1)
        status = "PRESENT" if new == text else "UPDATED"
    else:
        new = text + ("\n" if text and not text.endswith("\n") else "") + block
        status = "INSTALLED"
    if new != orig:
        with open(cfg + ".tmp", "w", encoding="utf-8") as fh:
            fh.write(new)
        os.replace(cfg + ".tmp", cfg)
    print("codex: {} ({})".format(status, cfg))
    if status == "INSTALLED":
        print("codex: NOTE — Codex asks to TRUST a new hook the first time it fires in a trusted "
              "project (an interactive prompt in the `codex` CLI; the VS Code extension does NOT "
              "surface it). Trust persists in ~/.codex/config.toml; this installer preserves it on "
              "reinstall.")
    return 0


def install_gemini():
    home = os.environ.get("GEMINI_HOME") or os.path.join(os.path.expanduser("~"), ".gemini")
    cfg = os.path.join(home, "settings.json")
    os.makedirs(home, exist_ok=True)
    data = {}
    if os.path.exists(cfg):
        try:
            with open(cfg, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            print("gemini: ERROR: existing settings.json is invalid JSON ({}); not modifying".format(e))
            return 3
        if not isinstance(data, dict):
            print("gemini: ERROR: settings.json is not a JSON object; not modifying")
            return 3
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        print("gemini: ERROR: settings 'hooks' is not an object; not modifying")
        return 3
    before = hooks.setdefault("BeforeTool", [])
    if not isinstance(before, list):
        print("gemini: ERROR: hooks.BeforeTool is not a list; not modifying")
        return 3

    entry = {
        "matcher": "run_shell_command",
        "hooks": [{
            "name": GEMINI_HOOK_NAME,
            "type": "command",
            "command": 'python3 "{}" gemini'.format(GUARDRAIL),
            "timeout": 10000,
            "description": "bailiwick guardrail (ADR-006 confirmation tiers; self-gates to wired repos)",
        }],
    }
    status = "INSTALLED"
    for i, grp in enumerate(before):
        if isinstance(grp, dict) and any(
                isinstance(h, dict) and h.get("name") == GEMINI_HOOK_NAME for h in grp.get("hooks", [])):
            status = "PRESENT" if grp == entry else "UPDATED"
            before[i] = entry
            break
    else:
        before.append(entry)
    if status != "PRESENT":
        with open(cfg + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(cfg + ".tmp", cfg)
    print("gemini: {} ({})".format(status, cfg))
    return 0


def main():
    targets = [a for a in sys.argv[1:] if a in ("codex", "gemini")] or ["codex", "gemini"]
    rc = 0
    for t in targets:
        rc = max(rc, install_codex() if t == "codex" else install_gemini())
    return rc


if __name__ == "__main__":
    sys.exit(main())
