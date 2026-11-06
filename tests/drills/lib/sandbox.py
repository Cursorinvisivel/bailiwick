#!/usr/bin/env python3
"""Build, describe, and remove a disposable drill sandbox (stdlib + git only).

    sandbox.py create --drill purge|curate [--parent DIR] [--variant new|baseline|no-delegation]
                      [--baseline-ref SHA] [--no-bootstrap] [--no-bash-sandbox]
                                                                    -> prints the sandbox root last
    sandbox.py env <root>                                           -> export lines for the run
    sandbox.py banner <root>                                        -> the operator instructions
    sandbox.py cleanup <root>                                       -> rm -rf, only when marked

Layout of <root> (bailiwick-drill-XXXXXX):
    .drill-sandbox      marker (JSON) — every guard requires it
    framework/          clone of the checkout under test (+ its uncommitted working tree), NO remotes,
                        .bailiwick-sync.json = satellite, capture_backup disabled
    project/            fake project, seeded-wired to framework/, project-scoped hooks/skills/agents
    home-bailiwick/     BAILIWICK_HOME for the run (captures, audit log, health shards)
    home/               fake HOME used ONLY while running bootstrap.sh (it writes user-scope config)
    drill-env.sh        the exports;  launch.sh  starts Claude Code isolated from user settings/MCP
    drill-results/      score JSON (excluded from every residual sweep)

Outside the sandbox: the drill's persistent Claude Code config dir (CLAUDE_CONFIG_DIR for the session,
default ~/.cache/bailiwick-drill-claude, override BW_DRILL_CLAUDE_HOME). It holds the drill login and
every Claude Code state file of drill sessions (transcripts, file-history, history.jsonl), so none of
it lands in the real ~/.claude. guard.check_claude_home refuses the real ~/.claude, anything inside
it, and its ancestors.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import guard  # noqa: E402

SOURCE_REPO = guard.SOURCE_REPO
# The pre-change skill text: the head of feat/lead-by-default, which is this branch's base. Pinned to a
# SHA so the baseline cannot drift; a ref that does not resolve is a hard error (no fallback to HEAD).
DEFAULT_BASELINE_REF = "a5a2feb"
SKILL_FOR = {"purge": "purge", "curate": "curate"}
VARIANTS = ("new", "baseline", "no-delegation")  # no-delegation: curate only (arm D, Step 2a forced off)
# Never copied into a sandbox: the harness holds the answer keys the agent under test must not see.
HARNESS = ("tests/drills/", "tests/test_drills.py")
SKIPPED_SECRETS = []  # untracked secret-looking files the last snapshot refused (reported in the banner)


class SeedError(Exception):
    """The sandbox cannot be built as asked (e.g. the baseline ref does not resolve). Exit 4."""


SEED_ERROR = 4


def log(msg):
    print("[drill] " + msg, file=sys.stderr)


def git(args, cwd, check=True, env=None, input_text=None, hooks_dir=None):
    """git with the user's global hooks and signing neutralised (the sandbox never signs or runs hooks)."""
    pre = ["git"]
    if hooks_dir:
        pre += ["-c", "core.hooksPath=" + hooks_dir]
    pre += ["-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]
    out = subprocess.run(pre + args, cwd=cwd, capture_output=True, text=True, env=env, input=input_text)
    if check and out.returncode != 0:
        raise RuntimeError("git {} failed in {}: {}".format(" ".join(args), cwd, out.stderr.strip()[:400]))
    return out


def mangle(path):
    """Claude Code's per-project transcript dir name: every non-alphanumeric char becomes '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def drill_claude_home():
    """The drill session's Claude Code config dir (persistent, so the operator logs in once)."""
    return guard.drill_claude_home_default()


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")


def update_marker(root, **fields):
    marker = guard.check_root(root)
    marker.update(fields)
    write_json(os.path.join(marker["root"], guard.MARKER), marker)
    return marker


def _local_identity(repo, hooks_dir):
    for k, v in (("user.name", "Drill Operator"), ("user.email", "drill@example.invalid"),
                 ("commit.gpgsign", "false"), ("tag.gpgsign", "false"), ("user.signingkey", ""),
                 ("core.hooksPath", hooks_dir)):
        git(["config", k, v], repo)


def _harness(rel):
    return any(rel == h.rstrip("/") or rel.startswith(h) for h in HARNESS)


SECRET_RX = re.compile(r"(?i)^(\.env.*|.*\.tfvars|.*\.pem|.*\.key|.*credentials.*|.*-key\.json|.*\.p12|id_.*)$")


def _secretish(rel):
    return bool(SECRET_RX.match(os.path.basename(rel)))


def snapshot_worktree(src, fw, hooks_dir):
    """The framework clone, as a HISTORY-FREE snapshot of the checkout's working tree.

    Not `git clone`: (1) the skill drafts under test are uncommitted, so HEAD alone is the wrong
    tree; (2) a clone carries the source's history, and once this harness is committed that history
    holds the answer keys (every planted token) — readable by the agent under test via `git log -S`
    and polluting the history probes; (3) no history means no remotes and no refs to leak.
    Tracked + untracked-not-ignored files are copied as they are on disk; the harness is left out.
    Untracked files with secret-ish names (.env*, *.tfvars, *.pem, *.key, *credentials*, *-key.json,
    *.p12, id_*) are refused, not copied; they are recorded in SKIPPED_SECRETS for the banner."""
    os.makedirs(fw)
    SKIPPED_SECRETS[:] = []
    tracked = {r for r in git(["ls-files", "-z"], src).stdout.split("\0") if r}
    listed = git(["ls-files", "-z", "--cached", "--others", "--exclude-standard"], src).stdout
    copied = 0
    for rel in sorted({r for r in listed.split("\0") if r}):
        s, d = os.path.join(src, rel), os.path.join(fw, rel)
        if _harness(rel) or not os.path.lexists(s):
            continue
        if rel not in tracked and _secretish(rel):
            SKIPPED_SECRETS.append(rel)
            log("WARNING: not copying untracked secret-looking file into the snapshot: " + rel)
            continue
        if os.path.islink(s):
            _check_symlink(rel, os.readlink(s))
        elif os.path.isdir(s):
            continue
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d, follow_symlinks=False)
        copied += 1
    git(["init", "-q"], fw)
    git(["checkout", "-q", "-b", "main"], fw, check=False)
    _local_identity(fw, hooks_dir)
    git(["add", "-A"], fw)
    head = git(["rev-parse", "HEAD"], src).stdout.strip()
    dirty = git(["status", "--porcelain", "--untracked-files=normal"], src).stdout
    git(["commit", "-q", "-m", "drill: snapshot of the framework working tree under test"], fw, hooks_dir=hooks_dir)
    return head, copied, hashlib.sha256(dirty.encode("utf-8", "replace")).hexdigest()[:12]


def _check_symlink(rel, target):
    """A symlink in the snapshot must stay inside it: no absolute target, no `..` escape. A link into
    the live checkout (or anywhere else) would hand the agent a path out of the sandbox."""
    if os.path.isabs(target):
        raise guard.Refused("snapshot symlink {} -> {} is absolute (would point out of the sandbox)".format(rel, target))
    resolved = os.path.normpath(os.path.join(os.path.dirname(rel), target))
    if resolved == ".." or resolved.startswith("../") or os.path.isabs(resolved):
        raise guard.Refused("snapshot symlink {} -> {} escapes the snapshot".format(rel, target))


def _bootstrap(root, fw, project):
    """Seed-wire the project with the SANDBOX's own bootstrap.sh under a fake HOME: bootstrap
    writes user-scope config (~/.claude.json MCP, ~/.bailiwick/allowlist, …), which must land in
    the sandbox. Returns (ok, files written under the fake HOME)."""
    home = os.path.join(root, "home")
    os.makedirs(home, exist_ok=True)
    env = dict(os.environ)
    env.update(HOME=home, BAILIWICK_HOME=os.path.join(root, "home-bailiwick"),
               XDG_CACHE_HOME=os.path.join(root, "cache"), XDG_CONFIG_HOME=os.path.join(home, ".config"),
               GIT_CONFIG_GLOBAL=os.path.join(home, ".gitconfig"), CODEX_HOME=os.path.join(home, ".codex"),
               GEMINI_HOME=os.path.join(home, ".gemini"), CLAUDE_CONFIG_DIR=os.path.join(home, ".claude"))
    env.pop("BAILIWICK", None)
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    with open(os.path.join(root, "logs", "bootstrap.log"), "w", encoding="utf-8") as fh:
        try:
            rc = subprocess.run(["bash", os.path.join(fw, "scripts", "bootstrap.sh"), "--seeded", "--no-gh-auth",
                                 project], cwd=project, env=env, stdout=fh, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, timeout=120).returncode
        except subprocess.TimeoutExpired:
            rc = 124
    written = []
    for dp, dn, fn in os.walk(home):
        written += [os.path.relpath(os.path.join(dp, f), root) for f in fn]
    return rc == 0, sorted(written)


def _minimal_wiring(fw, project):
    with open(os.path.join(project, "CLAUDE.local.md"), "w", encoding="utf-8") as fh:
        fh.write("# Bailiwick drill wiring (minimal)\n\n$BAILIWICK = `{}`\n\n"
                 "Framework guidance: read `$BAILIWICK/CLAUDE.md` and `$BAILIWICK/knowledge/INDEX.md`.\n".format(fw))


# Home-relative paths the agent under test must never read or write (permission-rule syntax: `~/`
# is the user's home, `//` an absolute path). Read denies also feed the Bash sandbox's denyRead.
DENY_HOME = ("~/.bailiwick/**", "~/.cache/bailiwick/**",
             "~/.gnupg/**", "~/.config/gh/**", "~/.ssh/**", "~/.claude/**", "~/.claude.json",
             "~/.config/gcloud/**", "~/.aws/**", "~/.kube/**", "~/.azure/**", "~/.docker/config.json",
             "~/.git-credentials", "~/.netrc")
# Sandbox files the agent must not rewrite (its own confinement, the marker, the launcher, the scores).
DENY_WRITE_IN_ROOT = (".drill-sandbox", "drill-env.sh", "launch.sh", "drill-mcp.json", "drill-results/**",
                      "project/.claude/**")


def _abs_rule(path):
    return "/" + path if path.startswith("/") else path  # "/x" -> "//x": absolute in permission rules


def deny_rules(root):
    """permissions.deny for the drill project: the protected set as Read/Edit denies, plus Edit denies
    on the sandbox's own control files. No Write(...) rules: Claude Code matches file-edit denies only
    as Edit(path), which covers every file-editing tool (2.1.317 warns that Write(path) never matches)."""
    paths = list(DENY_HOME)
    protected = {guard.SOURCE_REPO} | set(guard.installed_frameworks()) | guard.extra_forbidden()
    rbh = guard.real_bailiwick_home()
    if rbh:
        protected.add(rbh)
    paths += [_abs_rule(p) + "/**" for p in sorted(protected)]
    rules = ["{}({})".format(tool, p) for p in paths for tool in ("Read", "Edit")]
    rules += ["Edit({})".format(_abs_rule(os.path.join(root, p))) for p in DENY_WRITE_IN_ROOT]
    return rules


def _project_settings(root, fw, project, bash_sandbox=True):
    """Project-scoped config for the drill session: hooks from the SANDBOX clone (the branch under test),
    the drill env (so even a plain `claude` gets the hooks' drill self-defence), permission denies on
    every protected path, and Claude Code's Bash sandbox with writes limited to the sandbox root.
    Schema checked against the strings of Claude Code 2.1.317 (sandbox.enabled, failIfUnavailable,
    allowUnsandboxedCommands, filesystem.allowWrite); verify after a Claude Code upgrade."""
    tmpl = read_json(os.path.join(fw, "hooks", "settings.template.json"), {}) or {}
    hooks = json.loads(json.dumps(tmpl.get("hooks", {})).replace("/path/to/bailiwick", fw))
    settings = {
        "//": "bailiwick drill sandbox — hooks run from the sandbox clone; launch with ../launch.sh so "
              "user-scope settings (and their real hooks) are NOT loaded and Claude Code state goes to "
              "the drill config dir, not ~/.claude.",
        "hooks": hooks,
        "env": {"BAILIWICK": fw, "BAILIWICK_HOME": os.path.join(root, "home-bailiwick"),
                "BW_DRILL_SANDBOX": root},
        "permissions": {"deny": deny_rules(root)},
        "sandbox": {
            "enabled": bool(bash_sandbox),
            "failIfUnavailable": bool(bash_sandbox),
            "allowUnsandboxedCommands": False,
            "filesystem": {"allowWrite": [_abs_rule(root)]},
        },
    }
    write_json(os.path.join(project, ".claude", "settings.json"), settings)


# The user-home Bailiwick dir in skill text (`~/.bailiwick`, `$HOME/.bailiwick`, `${HOME}/.bailiwick`):
# rewritten to $BAILIWICK_HOME in BOTH variants, so the baseline text cannot steer the agent at the real
# one (the sandbox exports BAILIWICK_HOME=<root>/home-bailiwick).
HOME_BW_RX = re.compile(r"(?:~|\$HOME|\$\{HOME\})/\.bailiwick(?![\w.-])")
# Arm D: the Step 2a delegation threshold, replaced so 2a never applies.
THRESHOLD_RX = re.compile(r"(?i)use 2a when there are more than 2 raw captures,? or any capture over ~?200\s*KB")
STEP_2A_RX = re.compile(r"(?m)^(\s*)2a\.\s")
ARM_D_NOTE = ("**DRILL ARM D (delegation forced off).** In this run Step 2a never applies: always extract "
              "inline as in Step 2, whatever the input count or size. Everything else in Step 2a that "
              "also covers the inline path (inbox cleanup, fallback reporting) still applies.")


def _disable_2a(text):
    """Arm D: force Step 2a's delegation off. Returns (text, what was edited). Raises SeedError when
    the skill has no Step 2a at all (the arm would not measure anything)."""
    m = STEP_2A_RX.search(text)
    if not m:
        raise SeedError("no-delegation variant: the curate skill has no `2a.` step to disable")
    edits = []
    text, n = THRESHOLD_RX.subn("never use 2a in this drill run (arm D; the original threshold was more "
                                "than 2 raw captures, or any capture over ~200 KB)", text)
    if n:
        edits.append("Step 2a threshold disabled")
    m = STEP_2A_RX.search(text)
    text = text[:m.start()] + m.group(1) + ARM_D_NOTE + "\n\n" + text[m.start():]
    edits.append("arm-D note before Step 2a")
    return text, edits


def _absolutize_links(text, rel_dir, skill, fw):
    """Markdown links that leave the skill's own directory are made absolute against the sandbox clone;
    links that stay inside it (SKILL.md <-> reference/*.md) are left relative, so they resolve in the
    drill copy. rel_dir is the file's directory relative to skills/<skill>/ ('' or 'reference')."""
    base = "skills/" + skill + ("/" + rel_dir if rel_dir else "")

    def fix(m):
        target = m.group(1)
        if not target.startswith("."):
            return m.group(0)
        res = os.path.normpath(os.path.join(base, target))
        if res == "skills/" + skill or res.startswith("skills/" + skill + "/"):
            return m.group(0)
        return "](" + fw + "/" + res
    return re.sub(r"\]\((\.\.?/[^)\s#]*)", fix, text)


def _rewrite_skill(text, skill, fw, note_head, no_delegation=False):
    """The drill copy of a skill. Every edit is listed in the header note."""
    edits = ["name"]
    text = re.sub(r"(?m)^name:\s*{}\s*$".format(re.escape(skill)), "name: drill-" + skill, text, count=1)
    text = _absolutize_links(text, "", skill, fw)
    edits.append("links leaving the skill dir made absolute")
    text, n = HOME_BW_RX.subn("$BAILIWICK_HOME", text)
    edits.append("user-home Bailiwick dir -> $BAILIWICK_HOME ({}x)".format(n))
    if no_delegation:
        text, more = _disable_2a(text)
        edits += more
    note = "{}; edits vs the original: {}".format(note_head, ", ".join(edits))
    m = re.match(r"(?s)(---\n.*?\n---\n)", text)
    if m:
        return m.group(1) + "\n<!-- " + note + " -->\n" + text[m.end():]
    return "<!-- " + note + " -->\n" + text


def _rewrite_support(dest, skill, fw):
    """Every other text file in the skill dir (reference/*.md, scripts, ...): the same user-home rewrite
    in BOTH variants, plus absolute links for markdown that leaves the skill dir. Binary files are left."""
    n_files = 0
    for dp, dn, fn in os.walk(dest):
        for f in fn:
            p = os.path.join(dp, f)
            if os.path.relpath(p, dest) == "SKILL.md":
                continue
            try:
                with open(p, encoding="utf-8") as fh:
                    text = fh.read()
            except (UnicodeDecodeError, OSError):
                continue
            new = HOME_BW_RX.sub("$BAILIWICK_HOME", text)
            if f.endswith(".md"):
                new = _absolutize_links(new, ("" if dp == dest else os.path.relpath(dp, dest).replace(os.sep, "/")), skill, fw)
            if new != text:
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(new)
                n_files += 1
    return n_files


def _baseline_tree(src, sha, skill, dest):
    """The baseline's whole skills/<skill>/ directory (not the worktree's), so the A/B arm carries the
    baseline's own supporting files and none of the new ones."""
    shutil.rmtree(dest)
    names = git(["ls-tree", "-r", "-z", "--name-only", sha, "skills/" + skill + "/"], src).stdout.split("\0")
    for name in filter(None, names):
        target = os.path.join(dest, os.path.relpath(name, "skills/" + skill))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(git(["show", "{}:{}".format(sha, name)], src).stdout)


def resolve_baseline(src, ref, skill):
    """The baseline commit SHA holding skills/<skill>/SKILL.md. Hard error when it does not resolve."""
    r = git(["rev-parse", "--verify", "--quiet", ref + "^{commit}"], src, check=False)
    if r.returncode != 0 or not r.stdout.strip():
        raise SeedError("baseline ref {!r} does not resolve to a commit in {} — fetch it or pass "
                        "--baseline-ref <sha> (no fallback: a wrong baseline invalidates the A/B)".format(ref, src))
    sha = r.stdout.strip()
    if git(["cat-file", "-e", "{}:skills/{}/SKILL.md".format(sha, skill)], src, check=False).returncode != 0:
        raise SeedError("baseline {} ({}) has no skills/{}/SKILL.md".format(ref, sha[:12], skill))
    return sha


def install_skill(root, src, fw, project, skill, variant, baseline_ref):
    """Install the skill under test as project-scoped `drill-<skill>` — the user's own `/<skill>` is a
    symlink into another clone, and a distinct name removes any precedence ambiguity. Every variant
    installs under the SAME name so the operator types the same command in every arm."""
    dest = os.path.join(project, ".claude", "skills", "drill-" + skill)
    shutil.copytree(os.path.join(fw, "skills", skill), dest,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    ref_used, sha = "worktree", git(["rev-parse", "HEAD"], fw).stdout.strip()
    if variant == "baseline":
        ref_used = baseline_ref
        sha = resolve_baseline(src, baseline_ref, skill)
        _baseline_tree(src, sha, skill, dest)
        with open(os.path.join(dest, "SKILL.md"), encoding="utf-8") as fh:
            text = fh.read()
    else:
        with open(os.path.join(dest, "SKILL.md"), encoding="utf-8") as fh:
            text = fh.read()
    note_head = ("bailiwick drill copy of skills/{}/SKILL.md — variant {} ({}@{}); sandbox {}; $BAILIWICK = {}"
                 ).format(skill, variant, ref_used, sha[:12], root, fw)
    with open(os.path.join(dest, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write(_rewrite_skill(text, skill, fw, note_head, no_delegation=(variant == "no-delegation")))
    _rewrite_support(dest, skill, fw)
    return {"skill_name": "drill-" + skill, "skill_ref": ref_used, "skill_sha": sha}


def install_agents(fw, project):
    """Stage agents from the sandbox clone as project-scoped agents (project wins over user scope
    on a name clash), so the stages a drill dispatches are the branch's, not the installed clone's."""
    dest = os.path.join(project, ".claude", "agents")
    os.makedirs(dest, exist_ok=True)
    names = []
    for f in sorted(os.listdir(os.path.join(fw, "agents"))):
        if not f.endswith(".md"):
            continue
        with open(os.path.join(fw, "agents", f), encoding="utf-8") as fh:
            text = fh.read()
        m = re.search(r"(?m)^name:\s*(bailiwick-[\w-]+)\s*$", text[:2000])
        if m and text.startswith("---"):
            shutil.copyfile(os.path.join(fw, "agents", f), os.path.join(dest, m.group(1) + ".md"))
            names.append(m.group(1))
    return names


def _exclude(repo, entries):
    path = os.path.join(repo, ".git", "info", "exclude")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cur = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    with open(path, "a", encoding="utf-8") as fh:
        for e in entries:
            if e not in cur.split("\n"):
                fh.write(e + "\n")


def snapshot(fw):
    """sha256 of every file under knowledge/ — the before-state scorers diff against."""
    out = {}
    base = os.path.join(fw, "knowledge")
    for dp, dn, fn in os.walk(base):
        for f in fn:
            p = os.path.join(dp, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, fw)] = hashlib.sha256(fh.read()).hexdigest()
    return out


def create(drill, parent=None, variant="new", baseline_ref=DEFAULT_BASELINE_REF, bootstrap=True, source=None,
           bash_sandbox=True):
    src = guard.check_source(source or SOURCE_REPO)
    if variant not in VARIANTS:
        raise SeedError("unknown variant {!r}".format(variant))
    if variant == "no-delegation" and drill != "curate":
        raise SeedError("variant no-delegation (arm D) exists for the curate drill only")
    if variant == "baseline":  # fail before anything is created
        resolve_baseline(src, baseline_ref, SKILL_FOR[drill])
    claude_home = guard.check_claude_home(drill_claude_home())
    parent = guard.check_parent(parent or os.environ.get("TMPDIR") or tempfile.gettempdir())
    root = os.path.realpath(tempfile.mkdtemp(prefix="bailiwick-drill-", dir=parent))
    now = datetime.datetime.now(datetime.timezone.utc)
    marker = {"kind": guard.KIND, "root": root, "created": now.isoformat(timespec="seconds"),
              "created_epoch": now.timestamp(), "drill": drill, "variant": variant, "source": src,
              "framework": os.path.join(root, "framework"), "project": os.path.join(root, "project"),
              "bailiwick_home": os.path.join(root, "home-bailiwick"), "claude_home": claude_home,
              "protected_bailiwick_home": guard.real_bailiwick_home(), "bash_sandbox": bool(bash_sandbox)}
    write_json(os.path.join(root, guard.MARKER), marker)
    guard.check_root(root)  # the root itself must pass before anything is written into it
    fw, project, hooks_dir = marker["framework"], marker["project"], os.path.join(root, "git-hooks")
    for d in (hooks_dir, marker["bailiwick_home"], os.path.join(root, "cache"), os.path.join(root, "drill-results")):
        os.makedirs(d, exist_ok=True)

    log("snapshotting {} (working tree, harness excluded) -> {}".format(src, fw))
    source_head, copied, status_id = snapshot_worktree(src, fw, hooks_dir)
    write_json(os.path.join(fw, ".bailiwick-sync.json"), {
        "role": "satellite", "machine": "drillbox",
        "capture_backup": {"enabled": False, "confidentiality_ack": False},
        # the capture hook skips sessions of exactly these skills; drill-purge is the renamed copy
        "capture": {"include_subagents": True, "skip_skills": ["purge", "drill-purge"]}, "curate": {"deidentify": False}})
    guard.check_knowledge(root, fw)  # clone resolved, its own repo, zero remotes

    os.makedirs(project)
    git(["init", "-q"], project)
    git(["checkout", "-q", "-b", "main"], project, check=False)
    _local_identity(project, hooks_dir)
    with open(os.path.join(project, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("# drill-ops\n\nDisposable fake project for a Bailiwick skill drill. No real data.\n")
    git(["add", "README.md"], project)
    git(["commit", "-q", "-m", "init drill project"], project, hooks_dir=hooks_dir)

    boot_ok, home_writes = (False, [])
    if bootstrap:
        boot_ok, home_writes = _bootstrap(root, fw, project)
    wired = os.path.isfile(os.path.join(project, "CLAUDE.local.md"))
    if not wired:
        log("bootstrap {} — writing minimal seeded wiring by hand".format("skipped" if not bootstrap else "failed"))
        _minimal_wiring(fw, project)
    _exclude(project, [".claude/", "CLAUDE.local.md", ".bailiwick.local.md", ".mcp.json", ".vscode/",
                       ".bailiwick-outputs/", ".github/instructions/"])
    _project_settings(root, fw, project, bash_sandbox)
    skill = install_skill(root, src, fw, project, SKILL_FOR[drill], variant, baseline_ref)
    agents = install_agents(fw, project)
    write_json(os.path.join(root, "drill-mcp.json"), {"mcpServers": {}})
    _write_scripts(root)

    return update_marker(root, source_head=source_head, files_copied=copied, worktree_status_id=status_id,
                         framework_base=git(["rev-parse", "HEAD"], fw).stdout.strip(),
                         skipped_secrets=list(SKIPPED_SECRETS), bootstrap_ok=boot_ok, bootstrap_home_writes=home_writes, agents=agents,
                         transcript_dir=os.path.join(claude_home, "projects", mangle(project)),
                         **skill)["root"]


def export_line(name, value):
    return "export {}={}".format(name, shlex.quote(value))


def env_lines(root):
    """The run environment, shell-quoted. CLAUDE_CONFIG_DIR is the drill's own config dir: source this
    in a subshell, not your login shell, or later `claude` runs in that shell use the drill config."""
    m = guard.check_root(root)
    lines = [export_line("BW_DRILL_SANDBOX", m["root"]),
             export_line("BAILIWICK", m["framework"]),
             export_line("BAILIWICK_HOME", m["bailiwick_home"])]
    if m.get("claude_home"):
        lines += [export_line("BW_DRILL_CLAUDE_HOME", m["claude_home"]),
                  export_line("CLAUDE_CONFIG_DIR", m["claude_home"])]
    return lines


def _write_scripts(root):
    with open(os.path.join(root, "drill-env.sh"), "w", encoding="utf-8") as fh:
        fh.write("# source me: the environment for this drill sandbox\n" + "\n".join(env_lines(root)) + "\n")
    launch = os.path.join(root, "launch.sh")
    with open(launch, "w", encoding="utf-8") as fh:
        fh.write("""#!/usr/bin/env bash
# Start Claude Code for this drill, isolated from the user's real Bailiwick install:
#  CLAUDE_CONFIG_DIR = drill config dir  user skills, agents, memory, settings and hooks are invisible, and
#                                    transcripts / file-history / history.jsonl stay out of ~/.claude
#                                    (persistent: the first launch asks you to log in, later ones do not)
#  --setting-sources project,local   belt and braces: no user settings file either
#  --strict-mcp-config + empty set   no user-scope MCP servers (the user's filesystem MCP roots the
#                                    live library; the github MCP reaches real repos)
#  env -u / unset BW_*               no inherited hook overrides (config file, event, cwd, backup sync)
#  unset cloud credentials           GOOGLE_APPLICATION_CREDENTIALS, CLOUDSDK_*, AWS_*, AZURE_*, KUBECONFIG,
#                                    GH_TOKEN, GITHUB_TOKEN
set -euo pipefail
here="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd -P)"
. "$here/drill-env.sh"
python3 {guard} check-knowledge "$BW_DRILL_SANDBOX" || {{ echo "launch refused by the drill guard" >&2; exit 3; }}
python3 {guard} check-claude-home "$CLAUDE_CONFIG_DIR" >/dev/null || {{ echo "launch refused: drill config dir" >&2; exit 3; }}
mkdir -p "$CLAUDE_CONFIG_DIR" && chmod 700 "$CLAUDE_CONFIG_DIR"
for v in $(compgen -e); do
  case "$v" in
    BW_DRILL_SANDBOX|BW_DRILL_CLAUDE_HOME) ;;
    BW_*|CLOUDSDK_*|AWS_*|AZURE_*) unset "$v" ;;
  esac
done
unset GOOGLE_APPLICATION_CREDENTIALS KUBECONFIG GH_TOKEN GITHUB_TOKEN  # no cloud/VCS credentials in the drill
if [ "$(uname -s)" = Linux ] && python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("bash_sandbox", True) else 1)' "$BW_DRILL_SANDBOX/.drill-sandbox"; then
  miss=""; for t in bwrap socat; do command -v "$t" >/dev/null 2>&1 || miss="$miss $t"; done
  if [ -n "$miss" ]; then
    echo "launch refused: the drill's Bash sandbox needs:$miss (install: sudo apt install bubblewrap socat)," >&2
    echo "  or re-seed with --no-bash-sandbox. Claude Code would otherwise exit at startup." >&2
    exit 4
  fi
fi
cd "$BW_DRILL_SANDBOX/project"
exec env -u BW_CFG_FILE -u BW_HEALTH_ROOT -u CLAUDE_PROJECT_DIR \\
  claude --setting-sources project,local --strict-mcp-config --mcp-config "$BW_DRILL_SANDBOX/drill-mcp.json" "$@"
""".format(guard=shlex.quote(os.path.join(HERE, "guard.py"))))
    os.chmod(launch, 0o755)


def banner(root):
    m = guard.check_root(root)
    cmd = {"purge": "/{} acme-drill".format(m.get("skill_name", "drill-purge")),
           "curate": "/{}".format(m.get("skill_name", "drill-curate"))}[m["drill"]]
    lines = [
        "", "Drill sandbox ready ({} drill, variant {}{}).".format(
            m["drill"], m["variant"], ", small input" if m.get("small") else ""),
        "  root:       " + m["root"],
        "  skill:      {} ({}@{})".format(m.get("skill_name"), m.get("skill_ref"), (m.get("skill_sha") or "")[:12]),
        "  bootstrap:  " + ("ok (seeded, fake HOME)" if m.get("bootstrap_ok") else "minimal wiring by hand"),
        "  claude cfg: {} (drill-only; first launch asks you to log in)".format(m.get("claude_home")),
        "  bash sbx:   " + ("on (writes limited to the sandbox root)" if m.get("bash_sandbox", True)
                            else "OFF (--no-bash-sandbox): agent Bash is confined by denies only"),
        ] + (["  SKIPPED (secret-looking, untracked, not in the snapshot): " + ", ".join(m["skipped_secrets"])]
             if m.get("skipped_secrets") else []) + [
        "", "1. Start the session (isolated from your real settings, hooks, MCP servers, and ~/.claude):",
        "     {}/launch.sh".format(shlex.quote(m["root"])),
        "2. In the session, check /hooks shows only {}/hooks/* commands, then run:".format(m["framework"]),
        "     " + cmd,
        "3. Answer per the README operator protocol, then /exit.",
        "4. Score (in a subshell, so drill-env.sh does not stay in your shell):",
        "     ( source {}/drill-env.sh; python3 {}/{}/score.py --transcript-session latest )".format(
            shlex.quote(m["root"]), shlex.quote(os.path.dirname(HERE)), m["drill"]),
        "Cleanup:   bash {}/sandbox.sh cleanup {}".format(shlex.quote(HERE), shlex.quote(m["root"])),
    ]
    return "\n".join(lines)


def cleanup(root):
    m = guard.check_root(root)
    shutil.rmtree(m["root"])
    log("removed " + m["root"])
    ch = m.get("claude_home")
    left = [p for p in (m.get("transcript_dir"),
                        os.path.join(ch, "file-history", m["planted_claude_session"])
                        if ch and m.get("planted_claude_session") else None) if p and os.path.exists(p)]
    if ch:
        log("drill Claude Code state for this sandbox stays in the drill config dir {} (not ~/.claude): {}; "
            "history.jsonl lines with project {}. Delete by hand if wanted; removing the whole dir means "
            "logging in again.".format(ch, ", ".join(left) or "no per-sandbox dirs", m["project"]))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sandbox.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--drill", choices=sorted(SKILL_FOR), required=True)
    c.add_argument("--parent")
    c.add_argument("--variant", choices=VARIANTS, default="new")
    c.add_argument("--baseline-ref", default=DEFAULT_BASELINE_REF)
    c.add_argument("--no-bootstrap", action="store_true")
    c.add_argument("--no-bash-sandbox", action="store_true",
                   help="leave Claude Code's Bash sandbox off (when it cannot start on this host)")
    for name in ("env", "banner", "cleanup"):
        sub.add_parser(name).add_argument("root")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "create":
            print(create(a.drill, a.parent, a.variant, a.baseline_ref, not a.no_bootstrap,
                         bash_sandbox=not a.no_bash_sandbox))
        elif a.cmd == "env":
            print("\n".join(env_lines(a.root)))
        elif a.cmd == "banner":
            print(banner(a.root))
        elif a.cmd == "cleanup":
            cleanup(a.root)
    except guard.Refused as e:
        print("drill guard REFUSED: {}".format(e), file=sys.stderr)
        return guard.REFUSED
    except SeedError as e:
        print("drill seed FAILED: {}".format(e), file=sys.stderr)
        return SEED_ERROR
    return 0


if __name__ == "__main__":
    sys.exit(main())
