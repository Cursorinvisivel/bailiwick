#!/usr/bin/env python3
"""Safely merge the bailiwick hooks block into a Claude Code settings.json.

Usage: install_hooks.py <settings.json> <settings.template.json>

Idempotent and non-destructive: only adds hook commands not already present, and
preserves every other key plus any pre-existing (non-Bailiwick) hooks. Shared by
bootstrap.sh and bootstrap.ps1 so the merge logic lives in one place.

Path portability: the committed template bakes the CANONICAL Bailiwick path. On a
machine where the framework lives elsewhere (satellites), every template command is
rewritten to the real Bailiwick root — derived from the template's own location —
before merging. Without this, all hooks (including the guardrail) would silently
point at a path that only exists on the central machine.

Adoption: an existing install whose Bailiwick-owned hook commands run from ANOTHER
root — the baked canonical path, the pre-dissolve <root>/claude-code/hooks/ layout,
or an entirely different clone (a renamed/retired predecessor) — is migrated in
place to this clone rather than left beside a freshly appended duplicate. One clone
is live at a time: doctor.sh calls a foreign hook root broken and says "re-run
bootstrap.sh --install-tools from here", so that re-run has to actually take
ownership. A command is only touched when rewriting its root makes it exactly one
of this template's own hook commands — a user's own hooks are never rewritten,
even one reusing an owned filename under a hooks/ directory.

Prints MIGRATED: <old> -> <new> lines for any adoption, then exactly one of:
INSTALLED | PRESENT | ERROR: <msg>
Exit 0 on INSTALLED/PRESENT; non-zero on ERROR (existing file left untouched).
"""
import json
import os
import re
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


def _owned_basenames(tmpl_hooks):
    """Hook script filenames the framework owns, taken from the template itself."""
    names = set()
    for groups in tmpl_hooks.values():
        if not isinstance(groups, list):
            continue
        for grp in groups:
            for h in grp.get("hooks", []) if isinstance(grp, dict) else []:
                for tok in (h.get("command") or "").split():
                    base = os.path.basename(tok.strip("'\""))
                    if base.endswith((".py", ".sh")):
                        names.add(base)
    return names


def _adopt_foreign(group_list, owned, hooks_dir, tmpl_cmds):
    """Re-point Bailiwick-owned hook commands that run from another root at hooks_dir.

    Candidate matching is '<somewhere>/hooks/<owned script>' (covers the old
    '<root>/claude-code/hooks/' layout, which also ends in /hooks/), but a rewrite is
    committed ONLY when the result lands exactly on one of this template's own
    commands — the stale install must be the framework's own invocation modulo its
    root. That guard is what keeps a user's hook safe even when it reuses an owned
    filename under a hooks/ directory (extra args won't match the template), and it
    refuses splice-corrupt rewrites of quoted paths containing spaces (the \\S*
    match starts mid-path there, so the result never equals a template command).
    Returns a list of (old, new) directory pairs actually migrated.
    """
    if not owned:
        return []
    pat = re.compile(r"\S*/hooks/(" + "|".join(re.escape(n) for n in sorted(owned)) + r")\b")
    migrated = []
    for grp in group_list:
        if not isinstance(grp, dict):
            continue
        for h in grp.get("hooks", []):
            cmd = h.get("command") if isinstance(h, dict) else None
            if not cmd or cmd in tmpl_cmds:
                continue
            pairs = []

            def _sub(m):
                old_dir = os.path.dirname(m.group(0))
                if os.path.realpath(old_dir) == os.path.realpath(hooks_dir):
                    return m.group(0)
                pairs.append((old_dir, hooks_dir))
                return os.path.join(hooks_dir, m.group(1))

            new_cmd = pat.sub(_sub, cmd)
            if new_cmd != cmd and new_cmd in tmpl_cmds:
                h["command"] = new_cmd
                migrated.extend(pairs)
    return migrated


def _dedupe_owned(group_list, hooks_dir):
    """Drop repeat occurrences of a command running out of hooks_dir; returns True if any went."""
    seen, changed = set(), False
    for grp in group_list:
        if not isinstance(grp, dict):
            continue
        kept = []
        for h in grp.get("hooks", []):
            cmd = h.get("command") if isinstance(h, dict) else None
            key = (grp.get("matcher"), cmd)
            if cmd and hooks_dir + os.sep in cmd:
                if key in seen:
                    changed = True
                    continue
                seen.add(key)
            kept.append(h)
        if "hooks" in grp:
            grp["hooks"] = kept
    # Drop groups left empty by the pass; a group with no hooks is dead weight in settings.json.
    if changed:
        group_list[:] = [g for g in group_list
                         if not (isinstance(g, dict) and g.get("hooks") == [])]
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
    # Adopt any previous install of the framework's own hooks — the baked canonical path, the
    # pre-dissolve <root>/claude-code/hooks/ layout, or a differently-named clone — so this clone
    # becomes the live one. Without this the stale command differs from the fresh template command
    # and would be left running as a DEAD (or, for a surviving old clone, a SECOND) hook beside the
    # newly appended one, with captures landing where this clone's /curate cannot see them.
    hooks_dir = os.path.join(bailiwick_root, "hooks")
    owned = _owned_basenames(tmpl_hooks)
    tmpl_cmds = set()
    for groups in tmpl_hooks.values():
        if isinstance(groups, list):
            tmpl_cmds |= _existing_commands(groups)
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for old_dir, new_dir in _adopt_foreign(groups, owned, hooks_dir, tmpl_cmds):
            print(f"MIGRATED: {old_dir} -> {new_dir}")
            changed = True
        # Two stale installs (e.g. canonical + old-layout) can collapse onto the same command;
        # drop the copies so capture/guardrail hooks never fire twice per event.
        if _dedupe_owned(groups, hooks_dir):
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
