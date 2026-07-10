#!/usr/bin/env python3
"""Safely merge the bailiwick hooks block into a Claude Code settings.json.

Usage: install_hooks.py <settings.json> <settings.template.json>

Idempotent and non-destructive: only adds hook commands not already present, and
preserves every other key plus any pre-existing (non-Bailiwick) hooks. Shared by
bootstrap.sh and bootstrap.ps1 so the merge logic lives in one place.

Path portability: the committed template bakes the CANONICAL Bailiwick path. On a
machine where the framework lives elsewhere (satellites), every template command is
rewritten to the real Bailiwick root — derived from the template's own location —
before merging, and any previously installed command still pointing at the
canonical path is migrated in place. Without this, all hooks (including the
guardrail) would silently point at a non-existent path on satellites.

Prints exactly one of: INSTALLED | PRESENT | ERROR: <msg>
Exit 0 on INSTALLED/PRESENT; non-zero on ERROR (existing file left untouched).
"""
import json
import os
import sys

# Path baked into the committed settings.template.json (mirrors bootstrap.sh CANON_PATH).
CANON_PATH = "/path/to/bailiwick"


def _bailiwick_root(template_path):
    """$BAILIWICK/hooks/settings.template.json -> <bailiwick>."""
    return os.path.dirname(os.path.dirname(os.path.abspath(template_path)))


def _rewrite_commands(group_list, old, new):
    """Replace old->new in every hook command; returns True if anything changed."""
    changed = False
    for grp in group_list:
        if not isinstance(grp, dict):
            continue
        for h in grp.get("hooks", []):
            if isinstance(h, dict) and h.get("command") and old in h["command"]:
                h["command"] = h["command"].replace(old, new)
                changed = True
    return changed


def _existing_commands(group_list):
    cmds = set()
    for grp in group_list:
        if isinstance(grp, dict):
            for h in grp.get("hooks", []):
                if isinstance(h, dict) and h.get("command"):
                    cmds.add(h["command"])
    return cmds


def main():
    if len(sys.argv) != 3:
        print("ERROR: usage: install_hooks.py <settings.json> <template.json>")
        return 2
    settings_path, template_path = sys.argv[1], sys.argv[2]

    try:
        tmpl_hooks = json.load(open(template_path)).get("hooks", {})
    except Exception as e:
        print(f"ERROR: cannot read template: {e}")
        return 2
    if not tmpl_hooks:
        print("ERROR: template has no hooks block")
        return 2

    # Rewrite the baked canonical path to this machine's real Bailiwick root (no-op on the
    # canonical machine). Applied to the template before merging so satellites never
    # install hook commands pointing at a path that only exists on the central machine.
    bailiwick_root = _bailiwick_root(template_path)
    if bailiwick_root != CANON_PATH:
        for groups in tmpl_hooks.values():
            if isinstance(groups, list):
                _rewrite_commands(groups, CANON_PATH, bailiwick_root)

    if os.path.exists(settings_path):
        try:
            cfg = json.load(open(settings_path))
        except Exception as e:
            print(f"ERROR: existing settings.json is invalid JSON ({e}); not modifying")
            return 3
        if not isinstance(cfg, dict):
            print("ERROR: settings.json is not a JSON object; not modifying")
            return 3
    else:
        cfg = {}

    hooks = cfg.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        print("ERROR: settings.json 'hooks' is not an object; not modifying")
        return 3

    changed = False
    # Migrate a previous install that baked the canonical path (broken satellite state):
    # rewrite Bailiwick commands in place — CANON_PATH is unique to the framework, so this can
    # never touch a user's own hooks.
    if bailiwick_root != CANON_PATH:
        for groups in hooks.values():
            if isinstance(groups, list) and _rewrite_commands(groups, CANON_PATH, bailiwick_root):
                changed = True

    # Migrate the pre-dissolve layout: hooks used to live under <root>/claude-code/hooks/. After
    # promoting them to <root>/hooks/, an existing install still points at the old, now-nonexistent
    # path — the command differs from the fresh template command, so without this it would be left
    # as a DEAD hook beside the newly appended one. Rewrite it in place. Scoped to THIS clone's root
    # (bailiwick_root is the leading segment), so a coexisting framework at another path is untouched.
    old_layout = os.path.join(bailiwick_root, "claude-code", "hooks") + os.sep
    new_layout = os.path.join(bailiwick_root, "hooks") + os.sep
    if old_layout != new_layout:
        for groups in hooks.values():
            if isinstance(groups, list) and _rewrite_commands(groups, old_layout, new_layout):
                changed = True

    for event, groups in tmpl_hooks.items():
        existing = hooks.setdefault(event, [])
        if not isinstance(existing, list):
            print(f"ERROR: settings hooks['{event}'] is not a list; not modifying")
            return 3
        have = _existing_commands(existing)
        for grp in groups:
            matcher = grp.get("matcher")  # preserve (e.g. PreToolUse "Bash"); None for unmatched events
            for h in grp.get("hooks", []):
                cmd = h.get("command")
                if cmd and cmd not in have:
                    new_grp = {"hooks": [h]}
                    if matcher is not None:
                        new_grp["matcher"] = matcher
                    existing.append(new_grp)
                    have.add(cmd)
                    changed = True

    if not changed:
        print("PRESENT")
        return 0

    os.makedirs(os.path.dirname(settings_path) or ".", exist_ok=True)
    tmp = settings_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, settings_path)
    print("INSTALLED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
