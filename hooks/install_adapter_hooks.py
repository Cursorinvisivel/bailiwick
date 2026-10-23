#!/usr/bin/env python3
"""Install the bailiwick hooks into Codex + Antigravity (global, per machine).

Usage: install_adapter_hooks.py                # install/refresh both adapters (codex + antigravity)
       install_adapter_hooks.py codex          # just codex
       install_adapter_hooks.py antigravity    # just antigravity
       install_adapter_hooks.py gemini         # deprecated: routes to antigravity with warning

Wires the same scripts Claude Code runs into:
  - Codex CLI:  a managed block in ~/.codex/config.toml ->
                  * [[hooks.PreToolUse]] matcher "^Bash$"  -> guardrails.py (ADR-006 tiers)
                  * [[hooks.Stop]] / [[hooks.SessionEnd]]  -> capture_session.py, then
                    capture_backup.sh push (codex-cli >= 0.147, which added those events)
                (Codex requires a one-time interactive trust PER hook definition — it prompts on
                 the hook's first fire in a trusted project, in the `codex` CLI (`/hooks` manages
                 trust); until trusted, a hook is configured but does not run.)
  - Antigravity: ~/.gemini/config/hooks.json ->
                   * bailiwick-guardrail (PreToolUse, matcher "run_command", decision "ask" / "deny")
                   * bailiwick-capture   (Stop, capture_session.py + capture_backup.sh push)
                 Also cleans up legacy Gemini CLI hooks in ~/.gemini/settings.json (sunset June 2026).

Idempotent and non-destructive: the Codex block is marker-delimited and replaced in place;
the Antigravity hooks are managed entries in hooks.json.
Refuses to touch malformed JSON or TOML. Both hooks self-gate (wired/shadow repos only),
so installing globally is safe.

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
CAPTURE = os.path.join(BAILIWICK_ROOT, "hooks", "capture_session.py")
CAPTURE_BACKUP = os.path.join(BAILIWICK_ROOT, "hooks", "capture_backup.sh")

CODEX_BEGIN = "# BEGIN bailiwick hooks (managed - do not edit inside; reinstall via bootstrap --install-tools)"
CODEX_END = "# END bailiwick hooks"
GEMINI_HOOK_NAME = "bailiwick-guardrail"

def codex_block():
    # TOML: forward slashes work on Windows too; commandWindows covers a python3-less PATH.
    # ORDER IS LOAD-BEARING: Codex keys hook trust by `<event>:<group>:<index>` (observed:
    # `[hooks.state."<config path>:pre_tool_use:0:0"]`), so PreToolUse stays first and
    # byte-identical — its trust entry keeps addressing the same hook. Whether the stored
    # `trusted_hash` also survives depends on what Codex hashes, which is NOT verified here (two
    # candidate preimages for a live entry did not reproduce it); if it re-prompts once for the
    # guardrail after this change, that is the reason.
    guard = GUARDRAIL.replace("\\", "/")
    capture = CAPTURE.replace("\\", "/")
    backup = CAPTURE_BACKUP.replace("\\", "/")
    return """{begin}
[[hooks.PreToolUse]]
matcher = "^Bash$"

[[hooks.PreToolUse.hooks]]
type = "command"
command = 'python3 "{guard}" codex'
commandWindows = 'python "{guard}" codex'
timeout = 30
statusMessage = "bailiwick guardrail"
{capture_events}{end}
""".format(begin=CODEX_BEGIN, guard=guard, end=CODEX_END,
           capture_events="".join(codex_capture_event(ev, capture, backup)
                                  for ev in ("Stop", "SessionEnd")))


def codex_capture_event(event, capture, backup):
    """Capture pair for one Codex lifecycle event (codex-cli >= 0.147 added Stop/SessionEnd).

    Same two commands, same order, as the Claude Code template: copy the transcript into the
    dirty zone, then push the encrypted off-machine copy. Both hooks self-gate to wired repos
    and both CLIs pass the same payload fields (`session_id`/`transcript_path`/`cwd`/
    `hook_event_name`), so the scripts need no per-CLI argument. Kept synchronous — the backup
    push must observe the capture the line above it just wrote.
    """
    return """
[[hooks.{event}]]

[[hooks.{event}.hooks]]
type = "command"
command = 'python3 "{capture}"'
commandWindows = 'python "{capture}"'
timeout = 60
statusMessage = "bailiwick capture"

[[hooks.{event}.hooks]]
type = "command"
command = 'bash "{backup}" push'
timeout = 60
statusMessage = "bailiwick capture backup"
""".format(event=event, capture=capture, backup=backup)


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


def install_antigravity(gemini_alias=False):
    home = os.environ.get("GEMINI_HOME") or os.path.join(os.path.expanduser("~"), ".gemini")
    config_dir = os.environ.get("ANTIGRAVITY_CONFIG_DIR") or os.path.join(home, "config")
    cfg = os.path.join(config_dir, "hooks.json")
    os.makedirs(config_dir, exist_ok=True)

    if gemini_alias:
        print("gemini: WARNING: 'gemini' adapter is DEPRECATED (Gemini CLI sunset June 2026) "
              "and will be removed in April 2027 (in 6 months). Routing to 'antigravity'...")

    data = {}
    if os.path.exists(cfg):
        try:
            with open(cfg, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            print("antigravity: ERROR: existing hooks.json is invalid JSON ({}); not modifying".format(e))
            return 3
        if not isinstance(data, dict):
            print("antigravity: ERROR: hooks.json is not a JSON object; not modifying")
            return 3

    guardrail_entry = {
        "PreToolUse": [
            {
                "matcher": "run_command",
                "hooks": [{
                    "type": "command",
                    "command": 'python3 "{}" antigravity'.format(GUARDRAIL),
                    "timeout": 30,
                    "description": "bailiwick guardrail (ADR-006 confirmation tiers; self-gates to wired repos)",
                }],
            }
        ]
    }

    capture_entry = {
        "Stop": [
            {
                "type": "command",
                "command": 'python3 "{}"'.format(CAPTURE),
                "timeout": 60,
                "description": "bailiwick capture (automatic raw session capture for /curate)",
            },
            {
                "type": "command",
                "command": 'bash "{}" push'.format(CAPTURE_BACKUP),
                "timeout": 60,
                "description": "bailiwick capture backup (encrypted off-machine copy)",
            },
        ]
    }

    had_guardrail = "bailiwick-guardrail" in data
    had_capture = "bailiwick-capture" in data
    same_guardrail = data.get("bailiwick-guardrail") == guardrail_entry
    same_capture = data.get("bailiwick-capture") == capture_entry

    if not had_guardrail and not had_capture:
        status = "INSTALLED"
    elif same_guardrail and same_capture:
        status = "PRESENT"
    else:
        status = "UPDATED"

    data["bailiwick-guardrail"] = guardrail_entry
    data["bailiwick-capture"] = capture_entry

    if status != "PRESENT":
        with open(cfg + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(cfg + ".tmp", cfg)

    # Legacy cleanup: safely remove BeforeTool hook from ~/.gemini/settings.json
    gemini_cfg = os.path.join(home, "settings.json")
    if os.path.exists(gemini_cfg):
        try:
            with open(gemini_cfg, encoding="utf-8") as fh:
                gdata = json.load(fh)
            if isinstance(gdata, dict):
                ghooks = gdata.get("hooks")
                if isinstance(ghooks, dict):
                    before = ghooks.get("BeforeTool")
                    if isinstance(before, list):
                        new_before = []
                        removed = False
                        for grp in before:
                            if isinstance(grp, dict):
                                kept = [h for h in grp.get("hooks", [])
                                        if not (isinstance(h, dict) and h.get("name") == "bailiwick-guardrail")]
                                if len(kept) != len(grp.get("hooks", [])):
                                    removed = True
                                if kept:
                                    grp["hooks"] = kept
                                    new_before.append(grp)
                            else:
                                new_before.append(grp)
                        if removed:
                            if new_before:
                                ghooks["BeforeTool"] = new_before
                            else:
                                del ghooks["BeforeTool"]
                            if not ghooks:
                                del gdata["hooks"]
                            with open(gemini_cfg + ".tmp", "w", encoding="utf-8") as fh:
                                json.dump(gdata, fh, indent=2)
                                fh.write("\n")
                            os.replace(gemini_cfg + ".tmp", gemini_cfg)
                            print("antigravity: NOTE — Removed legacy Gemini CLI 'bailiwick-guardrail' hook from "
                                  "{} (Gemini CLI was sunset in June 2026; hooks now active in {})".format(gemini_cfg, cfg))
        except Exception:
            pass  # Do not block Antigravity hook installation if legacy settings.json is unreadable

    print("antigravity: {} ({})".format(status, cfg))
    return 0


def install_gemini():
    return install_antigravity(gemini_alias=True)


def main():
    raw_targets = sys.argv[1:]
    if not raw_targets:
        targets = ["codex", "antigravity"]
    else:
        targets = []
        for a in raw_targets:
            if a in ("codex", "antigravity", "gemini") and a not in targets:
                targets.append(a)
        if not targets:
            targets = ["codex", "antigravity"]

    rc = 0
    for t in targets:
        if t == "codex":
            rc = max(rc, install_codex())
        elif t == "antigravity":
            rc = max(rc, install_antigravity(gemini_alias=False))
        elif t == "gemini":
            rc = max(rc, install_gemini())
    return rc


if __name__ == "__main__":
    sys.exit(main())
