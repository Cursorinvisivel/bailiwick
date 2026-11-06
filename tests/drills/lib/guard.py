#!/usr/bin/env python3
"""Drill safety guards: the ONE implementation every drill script calls (bash via the CLI below,
Python by import). A drill runs a destructive skill (/purge) and a library-writing skill (/curate),
so every seed, score, and cleanup step proves it is pointed at a disposable sandbox first.

A path passes only when ALL hold:
  - the sandbox root carries a `.drill-sandbox` marker (kind "bailiwick-drill") whose recorded
    root equals the root's resolved path (a copied marker does not authorise another directory);
  - the target resolves inside that root (symlinks resolved);
  - neither the root nor the target is inside, or an ancestor of, a FORBIDDEN path: the checkout
    running the drill, every framework clone the user's Claude Code install points at (skill and
    agent symlink targets, hook command paths in ~/.claude/settings.json), ~/.bailiwick, $HOME
    itself, and every path in BW_DRILL_FORBIDDEN (os.pathsep-separated: e.g. your private clone);
  - for anything that touches knowledge/: $BAILIWICK resolves to <root>/framework, which is its own
    git repository with NO remotes.

The drill's Claude Code config dir (CLAUDE_CONFIG_DIR for the drill session; persistent, outside the
sandbox) must never be the user's real ~/.claude, inside it, or an ancestor of it (check_claude_home).

These guards protect the HARNESS scripts. They do not confine the agent under test: that comes from
the drill config dir, the project permission denies, and Claude Code's Bash sandbox (sandbox.py).

Stdlib only. Exit 0 = allowed, 3 = refused (reason on stderr), 2 = usage.
"""
import json
import os
import re
import subprocess
import sys

MARKER = ".drill-sandbox"
KIND = "bailiwick-drill"
REFUSED = 3

# tests/drills/lib/guard.py -> the checkout that ships these scripts (the branch under test).
SOURCE_REPO = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))


class Refused(Exception):
    """A guard refused. The message says which rule and which path."""


def _real(path):
    return os.path.realpath(os.path.expanduser(path))


def is_within(path, parent):
    """True when `path` equals `parent` or sits below it (both already resolved)."""
    try:
        return os.path.commonpath([path, parent]) == parent
    except ValueError:  # different drives (Windows) — never within
        return False


def _repo_root_of(path):
    """The framework root a skill/agent/hook path belongs to: walk up to a dir holding hooks/ + knowledge/."""
    cur = _real(path)
    for _ in range(6):
        if os.path.isdir(os.path.join(cur, "hooks")) and os.path.isdir(os.path.join(cur, "knowledge")):
            return cur
        nxt = os.path.dirname(cur)
        if nxt == cur:
            break
        cur = nxt
    return None


def installed_frameworks(home=None):
    """Framework clones the user's real Claude Code install points at (read-only discovery)."""
    home = home or os.path.expanduser("~")
    found = set()
    for sub in ("skills", "agents"):
        d = os.path.join(home, ".claude", sub)
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            p = os.path.join(d, n)
            if os.path.islink(p):
                root = _repo_root_of(p)
                if root:
                    found.add(root)
    try:
        with open(os.path.join(home, ".claude", "settings.json"), encoding="utf-8") as fh:
            text = fh.read()
        for m in re.finditer(r"(/[^\s\"']+)/hooks/[\w.-]+\.(?:py|sh)", text):
            root = _repo_root_of(m.group(1))
            if root:
                found.add(root)
    except OSError:
        pass
    return found


def _sandbox_owning(path):
    """The drill sandbox root whose marker records `path` as its bailiwick_home, else None."""
    cur = path
    for _ in range(4):
        cur = os.path.dirname(cur)
        m = os.path.join(cur, MARKER)
        if os.path.isfile(m):
            try:
                with open(m, encoding="utf-8") as fh:
                    marker = json.load(fh)
            except (OSError, ValueError):
                return None
            if isinstance(marker, dict) and marker.get("kind") == KIND and marker.get("bailiwick_home") == path:
                return cur
            return None
    return None


def real_bailiwick_home():
    """A non-default BAILIWICK_HOME from the environment that is NOT a drill sandbox's own
    home-bailiwick (drill-env.sh exports that one) — the user's real one, so protected. None otherwise."""
    bh = (os.environ.get("BAILIWICK_HOME") or "").strip()
    if not bh:
        return None
    r = _real(bh)
    return None if _sandbox_owning(r) else r


def forbidden_paths():
    """Resolved paths a drill must never touch or contain. Value "tree": nothing inside it either;
    "node": the path itself and its ancestors only ($HOME and / may hold a sandbox below them)."""
    home = os.path.expanduser("~")
    paths = {
        SOURCE_REPO: "tree",
        _real(os.path.join(home, ".bailiwick")): "tree",
        _real(home): "node",
        "/": "node",
    }
    for p in installed_frameworks(home):
        paths[p] = "tree"
    rbh = real_bailiwick_home()
    if rbh:
        paths[rbh] = "tree"
    for extra in extra_forbidden():
        paths[extra] = "tree"
    return paths


def extra_forbidden():
    """Resolved BW_DRILL_FORBIDDEN entries (os.pathsep-separated): machine-specific protected paths,
    such as a private framework clone, kept out of this shared file."""
    return {_real(e.strip()) for e in (os.environ.get("BW_DRILL_FORBIDDEN") or "").split(os.pathsep) if e.strip()}


def _check_not_forbidden(path, what):
    for f, mode in sorted(forbidden_paths().items()):
        if mode == "tree" and is_within(path, f):
            raise Refused("{} {} is inside a protected path ({})".format(what, path, f))
        if is_within(f, path):
            raise Refused("{} {} is, or contains, a protected path ({})".format(what, path, f))


def read_marker(root):
    r = _real(root)
    mpath = os.path.join(r, MARKER)
    if not os.path.isfile(mpath):
        raise Refused("no {} marker in {} — not a drill sandbox".format(MARKER, r))
    try:
        with open(mpath, encoding="utf-8") as fh:
            marker = json.load(fh)
    except (OSError, ValueError) as e:
        raise Refused("unreadable {} marker in {} ({})".format(MARKER, r, type(e).__name__))
    if not isinstance(marker, dict) or marker.get("kind") != KIND:
        raise Refused("marker in {} is not a {} marker".format(r, KIND))
    if marker.get("root") != r:
        raise Refused("marker records root {!r}, but it sits in {} (moved or copied marker)".format(
            marker.get("root"), r))
    return marker


def check_root(root):
    """The sandbox root is real, marked, and clear of every protected path. Returns the marker."""
    if not root:
        raise Refused("no sandbox root given (pass --sandbox or export BW_DRILL_SANDBOX)")
    r = _real(root)
    if not os.path.isdir(r):
        raise Refused("sandbox root {} is not a directory".format(r))
    _check_not_forbidden(r, "sandbox root")
    return read_marker(r)


def check_target(root, target):
    """`target` resolves inside a valid sandbox root."""
    check_root(root)
    r, t = _real(root), _real(target)
    if not is_within(t, r):
        raise Refused("target {} is outside the sandbox {}".format(t, r))
    _check_not_forbidden(t, "target")
    return t


def real_claude_dirs():
    """The user's real Claude Code config dirs: ~/.claude always, plus a non-drill CLAUDE_CONFIG_DIR."""
    out = {_real(os.path.join(os.path.expanduser("~"), ".claude"))}
    cc = (os.environ.get("CLAUDE_CONFIG_DIR") or "").strip()
    if cc and _real(cc) != _real(drill_claude_home_default()):
        out.add(_real(cc))
    return out


def drill_claude_home_default():
    """Where the drill's persistent Claude Code config dir lives unless BW_DRILL_CLAUDE_HOME says otherwise."""
    return (os.environ.get("BW_DRILL_CLAUDE_HOME") or "").strip() or os.path.join(
        os.path.expanduser("~"), ".cache", "bailiwick-drill-claude")


def check_claude_home(path):
    """The drill session's CLAUDE_CONFIG_DIR: never the real ~/.claude (or a non-drill CLAUDE_CONFIG_DIR),
    never inside one, never an ancestor of one, never inside or containing a protected path."""
    if not path or not str(path).strip():
        raise Refused("no drill Claude Code config dir given")
    c = _real(path)
    for real in sorted(real_claude_dirs()):
        if is_within(c, real):
            raise Refused("drill Claude config dir {} is, or is inside, the real Claude Code config {}".format(c, real))
        if is_within(real, c):
            raise Refused("drill Claude config dir {} contains the real Claude Code config {}".format(c, real))
    _check_not_forbidden(c, "drill Claude config dir")
    return c


def git_remotes(repo):
    out = subprocess.run(["git", "-C", repo, "remote"], capture_output=True, text=True)
    if out.returncode != 0:
        raise Refused("{} is not a git repository".format(repo))
    return [x for x in out.stdout.split() if x]


def check_knowledge(root, bailiwick=None):
    """For anything touching knowledge/: $BAILIWICK is the sandbox clone, which has no remotes."""
    check_root(root)
    fw = os.path.join(_real(root), "framework")
    bw = bailiwick if bailiwick is not None else os.environ.get("BAILIWICK", "")
    if not bw:
        raise Refused("BAILIWICK is not set — export it to {}".format(fw))
    if _real(bw) != fw:
        raise Refused("BAILIWICK={} is not the sandbox framework clone {}".format(_real(bw), fw))
    top = subprocess.run(["git", "-C", fw, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if top.returncode != 0 or _real(top.stdout.strip()) != fw:
        raise Refused("{} is not its own git repository".format(fw))
    remotes = git_remotes(fw)
    if remotes:
        raise Refused("sandbox clone {} has remote(s) {} — a drill clone must have none".format(fw, remotes))
    return fw


def check_parent(parent):
    """Where a NEW sandbox may be created: an existing dir clear of every protected path."""
    p = _real(parent)
    if not os.path.isdir(p):
        raise Refused("parent {} is not a directory".format(p))
    for f, mode in sorted(forbidden_paths().items()):
        if mode == "tree" and is_within(p, f):
            raise Refused("parent {} is inside a protected path ({})".format(p, f))
    return p


def check_source(src):
    """The checkout cloned into a sandbox: a git repo that is not the user's live instance and
    carries no client knowledge (drills use synthetic clients only)."""
    s = _real(src)
    installed = installed_frameworks() | extra_forbidden()
    if s in installed and s != SOURCE_REPO:
        raise Refused("source {} is the installed (live) framework instance".format(s))
    if s.rstrip("/").endswith("bailiwick-private"):
        raise Refused("source {} is the private instance — drills clone the public branch under test".format(s))
    clients = os.path.join(s, "knowledge", "clients")
    if os.path.isdir(clients):
        real = [n for n in os.listdir(clients) if not n.startswith(".") and n.lower() != "readme.md"]
        if real:
            raise Refused("source {} holds client knowledge ({}) — refusing to copy it into a drill".format(
                s, ", ".join(sorted(real))))
    return s


def _main(argv):
    usage = ("usage: guard.py check-root <root> | check-target <root> <path> | check-knowledge <root> "
             "| check-parent <dir> | check-source <src> | check-claude-home <dir> | forbidden")
    if len(argv) < 2:
        print(usage, file=sys.stderr)
        return 2
    cmd, args = argv[1], argv[2:]
    try:
        if cmd == "check-root" and len(args) == 1:
            check_root(args[0])
        elif cmd == "check-target" and len(args) == 2:
            print(check_target(args[0], args[1]))
        elif cmd == "check-knowledge" and len(args) == 1:
            check_knowledge(args[0])
        elif cmd == "check-parent" and len(args) == 1:
            print(check_parent(args[0]))
        elif cmd == "check-source" and len(args) == 1:
            print(check_source(args[0]))
        elif cmd == "check-claude-home" and len(args) == 1:
            print(check_claude_home(args[0]))
        elif cmd == "forbidden" and not args:
            print("\n".join("{}\t{}".format(m, p) for p, m in sorted(forbidden_paths().items())))
        else:
            print(usage, file=sys.stderr)
            return 2
    except Refused as e:
        print("drill guard REFUSED: {}".format(e), file=sys.stderr)
        return REFUSED
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
