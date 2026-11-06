"""Drill harness self-tests (tests/drills/) — no agent, offline, fast.

Seeds both drills into a pytest tmp dir and proves: every answer-key trace is really planted (an
untouched sandbox scores 0%), a programmatically perfect run scores 100%, a bad curate run is caught,
and every safety guard refuses what it must (the real checkout, an unmarked path, a BAILIWICK that
is not the sandbox clone, a sandbox clone with a remote, protected parents and sources, a drill Claude
config dir that is the real ~/.claude, escaping symlinks, a baseline ref that does not resolve).
Every seed points BW_DRILL_CLAUDE_HOME at a tmp dir, so nothing is written to the real drill config.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

REPO = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
DRILLS = os.path.join(REPO, "tests", "drills")
sys.path.insert(0, os.path.join(DRILLS, "lib"))
import guard  # noqa: E402
import sandbox  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


purge_score = _load("drill_purge_score", os.path.join(DRILLS, "purge", "score.py"))
curate_score = _load("drill_curate_score", os.path.join(DRILLS, "curate", "score.py"))


def _claude_home(parent):
    return os.path.join(str(parent), "drill-claude-home")


def _seed(drill, parent, *extra):
    env = dict(os.environ, BW_DRILL_CLAUDE_HOME=_claude_home(parent))
    out = subprocess.run(["bash", os.path.join(DRILLS, drill, "seed.sh"), "--parent", str(parent)] + list(extra),
                         capture_output=True, text=True, timeout=120, env=env)
    assert out.returncode == 0, out.stderr[-2000:]
    root = out.stdout.strip().splitlines()[-1]
    assert os.path.isfile(os.path.join(root, guard.MARKER))
    return root


def _env(root):
    return dict(os.environ, BAILIWICK=os.path.join(root, "framework"), BW_DRILL_SANDBOX=root,
                BAILIWICK_HOME=os.path.join(root, "home-bailiwick"),
                BW_DRILL_CLAUDE_HOME=guard.check_root(root)["claude_home"])


@pytest.fixture(scope="module")
def purge_root(tmp_path_factory):
    return _seed("purge", tmp_path_factory.mktemp("purge"))


@pytest.fixture(scope="module")
def curate_root(tmp_path_factory):
    return _seed("curate", tmp_path_factory.mktemp("curate"))


# ------------------------------------------------------------------------------------- sandbox shape
def test_sandbox_is_isolated(purge_root):
    m = guard.check_root(purge_root)
    fw = m["framework"]
    assert guard.git_remotes(fw) == []
    # History-free: only the snapshot + planted commits — the source's history never travels.
    assert len(sandbox.git(["rev-list", "--all"], fw).stdout.split()) == 2
    # The harness (answer keys) is never visible to the agent under test.
    assert not os.path.exists(os.path.join(fw, "tests", "drills"))
    assert not os.path.exists(os.path.join(fw, "tests", "test_drills.py"))
    cfg = sandbox.read_json(os.path.join(fw, ".bailiwick-sync.json"))
    assert cfg["role"] == "satellite" and cfg["capture_backup"]["enabled"] is False
    proj = m["project"]
    skill = open(os.path.join(proj, ".claude", "skills", "drill-purge", "SKILL.md"), encoding="utf-8").read()
    assert re.search(r"(?m)^name: drill-purge$", skill)
    assert "~/.bailiwick" not in skill and "](../" not in skill
    assert "$BAILIWICK_HOME" in skill.split("-->", 1)[0]  # the substitution is recorded in the header note
    settings = sandbox.read_json(os.path.join(proj, ".claude", "settings.json"))
    hooks = json.dumps(settings["hooks"])
    assert fw + "/hooks/capture_session.py" in hooks and "/path/to/bailiwick" not in hooks
    assert settings["env"] == {"BAILIWICK": fw, "BAILIWICK_HOME": m["bailiwick_home"], "BW_DRILL_SANDBOX": m["root"]}
    deny = settings["permissions"]["deny"]
    for rule in ("Read(~/.claude/**)", "Edit(~/.bailiwick/**)", "Edit(~/.ssh/**)", "Read(~/.gnupg/**)",
                 "Read(~/.config/gh/**)", "Read(//{}/**)".format(guard.SOURCE_REPO),
                 "Edit(//{}/project/.claude/**)".format(m["root"])):
        assert rule.replace("///", "//") in deny, rule
    assert not [r for r in deny if r.startswith("Write(")], "Write(path) denies never match; use Edit"
    sb = settings["sandbox"]
    assert sb["enabled"] is True and sb["allowUnsandboxedCommands"] is False
    assert sb["filesystem"]["allowWrite"] == ["/" + m["root"]]
    launch = open(os.path.join(m["root"], "launch.sh"), encoding="utf-8").read()
    assert "env -u BW_CFG_FILE -u BW_HEALTH_ROOT -u CLAUDE_PROJECT_DIR" in launch and "check-claude-home" in launch
    assert "export CLAUDE_CONFIG_DIR=" in open(os.path.join(m["root"], "drill-env.sh"), encoding="utf-8").read()
    assert m["transcript_dir"].startswith(m["claude_home"] + os.sep)
    assert m["skill_ref"] == "worktree"
    assert sandbox.read_json(os.path.join(m["root"], "drill-mcp.json")) == {"mcpServers": {}}
    assert os.path.isfile(os.path.join(proj, ".claude", "agents", "bailiwick-security-review.md"))
    assert "BAILIWICK" in open(os.path.join(proj, "CLAUDE.local.md"), encoding="utf-8").read()


# ---------------------------------------------------------------------------------------- purge drill
def _deidentify(text):
    for rx, rep in ((r"(?i)acme\s+drill\s+industries", "the client"),
                    (r"acme-drill-vpc-sc-rollout", "vpc-sc-dry-run-rollout"),
                    (r"scope:\s*client:acme-drill", "scope: generic"),
                    (r"(?i)acme[-_ ]?drill", "example"),
                    (r"(?i)(?<![a-z0-9])acdr(?![a-z0-9])", "org"),
                    (r"(?<![A-Za-z0-9])ADI(?![A-Za-z0-9])", "a client")):
        text = re.sub(rx, rep, text)
    return text


def _perfect_purge(root, telemetry=False):
    """Apply every expected outcome: delete the client-specific, abstract the reusable, scrub the logs.
    `telemetry` also purges `.telemetry.json`, which only a central machine may do (the sandbox is a
    satellite unless its `.bailiwick-sync.json` role says otherwise)."""
    fw, home, proj = (os.path.join(root, d) for d in ("framework", "home-bailiwick", "project"))
    kb = os.path.join(fw, "knowledge")
    tokens = re.compile(r"(?i)acme[-_ ]?drill|(?<![a-z0-9])acdr(?![a-z0-9])|(?-i:(?<![A-Za-z0-9])ADI(?![A-Za-z0-9]))")
    shutil.rmtree(os.path.join(kb, "clients", "acme-drill"))
    shutil.rmtree(os.path.join(fw, "definitions", "clients", "acme-drill"))
    old = os.path.join(kb, "topics", "acme-drill-vpc-sc-rollout.md")
    with open(old, encoding="utf-8") as fh:
        body = fh.read()
    os.remove(old)
    with open(os.path.join(kb, "topics", "vpc-sc-dry-run-rollout.md"), "w", encoding="utf-8") as fh:
        fh.write(_deidentify(body))
    reg = os.path.join(kb, "context", "org-shorthands.md")
    lines = open(reg, encoding="utf-8").read().splitlines(True)
    open(reg, "w", encoding="utf-8").write("".join(ln for ln in lines if "`acme-drill`" not in ln))
    idx = os.path.join(kb, "INDEX.md")
    lines = open(idx, encoding="utf-8").read().splitlines(True)
    open(idx, "w", encoding="utf-8").write("".join(_deidentify(ln) for ln in lines if "clients/acme-drill/" not in ln))
    for rel in ("patterns/gcp-iam-conventions.md", "patterns/caf-naming-taxonomy.md", "patterns/gcp-labels-required.md"):
        p = os.path.join(kb, rel)
        text = open(p, encoding="utf-8").read()
        open(p, "w", encoding="utf-8").write(_deidentify(text))
    if telemetry:
        tel_p = os.path.join(kb, ".telemetry.json")
        tel = json.load(open(tel_p, encoding="utf-8"))
        ent = tel["entries"]
        ent["vpc-sc-dry-run-rollout"] = ent.pop("acme-drill-vpc-sc-rollout")
        ent.pop("acme-drill-project-map")
        for v in ent.values():
            v["distinct_projects_used"] = [p for p in v.get("distinct_projects_used") or [] if not tokens.search(p)]
        json.dump(tel, open(tel_p, "w", encoding="utf-8"), indent=2)
    sandbox.git(["add", "-A"], fw)
    sandbox.git(["commit", "-q", "-m", "knowledge: de-identify a client"], fw, hooks_dir=os.path.join(root, "git-hooks"))
    for stem in (os.path.join(proj, ".bailiwick-outputs", "raw", "drill0001-acme"),
                 os.path.join(home, "captures", "landing-zone-1a2b3c4d", "raw", "drill0002-acme"),
                 os.path.join(fw, ".bailiwick-inbox", "raw", "drillbox", "landing-zone-1a2b3c4d", "drill0004-acme")):
        for ext in (".jsonl", ".md"):
            os.remove(stem + ext)
    os.remove(os.path.join(home, "captures", "landing-zone-1a2b3c4d", "learn-20261018-101500.md"))
    for rel in ("guardrail-audit.log", "health/drillbox.jsonl", "health/remote/otherbox.jsonl"):
        p = os.path.join(home, rel)
        lines = open(p, encoding="utf-8").read().splitlines(True)
        open(p, "w", encoding="utf-8").write("".join(ln for ln in lines if not tokens.search(ln)))


def test_purge_untouched_then_perfect(purge_root, monkeypatch):
    monkeypatch.setenv("BAILIWICK", os.path.join(purge_root, "framework"))
    res = purge_score.score(purge_root)
    s = res["summary"]
    scored = [t for t in res["traces"] if t["expected"] in ("removed", "abstracted")]
    assert all(t["matches"] > 0 for t in res["traces"]), [t["id"] for t in res["traces"] if not t["matches"]]
    assert s["role"] == "satellite"
    assert s["removal_rate"] == 0.0 and s["traces_remaining"] == len(scored) == 23
    assert s["residual_expected_present"] == 2 and s["user_action_pending"] == 2
    # T13/T14: central-owned telemetry stays on a satellite for central to purge (not scored as removal).
    assert s["central_pending"] == 2 and s["satellite_violations"] == 0
    assert next(t for t in res["traces"] if t["id"] == "T19")["note"].startswith("gap probe")
    assert s["keep_ok"] == "10/10" and not s["rule_survives_deidentified"] and not s["client_file_deleted"]
    assert s["unexpected_residual_paths"] > 0 and not s["perfect"]

    _perfect_purge(purge_root)
    res = purge_score.score(purge_root)
    s = res["summary"]
    assert s["removal_rate"] == 1.0, [t for t in res["traces"] if not t["ok"]]
    assert s["rule_survives_deidentified"] and s["client_file_deleted"]
    assert s["keep_ok"] == "10/10" and s["unexpected_residual_paths"] == 0, res["sweep"]
    assert s["residual_expected_present"] == 2  # de-identified tier: history still holds it
    assert s["user_action_pending"] == 2  # Claude Code state: listed for the user, never auto-removed
    assert s["central_pending"] == 2 and s["satellite_violations"] == 0
    assert s["perfect"]


def _set_role(root, role):
    p = os.path.join(root, "framework", ".bailiwick-sync.json")
    cfg = json.load(open(p, encoding="utf-8"))
    cfg["role"] = role
    json.dump(cfg, open(p, "w", encoding="utf-8"), indent=2)


@pytest.mark.parametrize("role,telemetry,perfect,violations,remaining", [
    ("satellite", True, False, 2, 0),   # a satellite edited central-owned telemetry: a violation
    ("central", False, False, 0, 2),    # central must purge telemetry: T13/T14 are scored removals
    ("central", True, True, 0, 0),      # central purged everything
])
def test_purge_telemetry_scored_by_role(tmp_path, monkeypatch, role, telemetry, perfect, violations, remaining):
    root = _seed("purge", tmp_path)
    monkeypatch.setenv("BAILIWICK", os.path.join(root, "framework"))
    _set_role(root, role)
    _perfect_purge(root, telemetry=telemetry)
    res = purge_score.score(root)
    s = res["summary"]
    assert s["role"] == role
    assert s["satellite_violations"] == violations
    assert s["traces_remaining"] == remaining, [t for t in res["traces"] if not t["ok"]]
    assert s["perfect"] is perfect
    tel = [t for t in res["traces"] if t["id"] in ("T13", "T14")]
    if role == "central":
        assert all(t["expected"] == "removed" for t in tel)
        assert s["central_pending"] == 0
    else:
        assert all(t["status"] == "EDITED ON SATELLITE" for t in tel)


# --------------------------------------------------------------------------------------- curate drill
GOOD = {
    "pubsub-subscription-expiry.md": "A Pub/Sub subscription is deleted after 31 days of inactivity unless "
                                     "`expiration_policy { ttl = \"\" }` is set.",
    "gcs-ubla-revert-window.md": "Uniform bucket-level access can be disabled only within 90 days of enabling it.",
    "cloud-sql-deletion-protection.md": "On `google_sql_database_instance`, `deletion_protection` is Terraform-only; "
                                        "`settings.deletion_protection_enabled` blocks console deletion (Cloud SQL).",
    "artifact-registry-cleanup-dry-run.md": "Preview Artifact Registry cleanup policies in cleanup-policy dry-run mode.",
}


def _topic(name, body):
    return "---\nid: {}\ntype: topic\ntags: [gcp]\nconfidence: low\nlast_validated: 2026-11-03\nsupersedes: []\n" \
           "scope: generic\n---\n\n# {}\n\n{}\n".format(name[:-3], name[:-3], body)


def test_curate_untouched_perfect_and_bad(curate_root, monkeypatch):
    monkeypatch.setenv("BAILIWICK", os.path.join(curate_root, "framework"))
    m = guard.check_root(curate_root)
    sizes = m["capture_sizes"]
    assert len(sizes) == 2 and max(sizes.values()) > 200 * 1024  # Step 2a threshold triggers (size leg)
    s = curate_score.score(curate_root)["summary"]
    assert s["recall"] == 0.0 and s["new_content_files"] == 0 and s["duplicate"].startswith("skipped")
    assert not s["perfect"]

    kb = os.path.join(curate_root, "framework", "knowledge")
    for name, body in GOOD.items():
        with open(os.path.join(kb, "topics", name), "w", encoding="utf-8") as fh:
            fh.write(_topic(name, body))
    with open(os.path.join(kb, "topics", "terraform-state-lock-recovery.md"), "a", encoding="utf-8") as fh:
        fh.write("\n- CI: a cancelled runner is the usual source of the stale lock.\n")
    s = curate_score.score(curate_root)["summary"]
    assert s["recall"] == 1.0 and s["precision"] == 1.0, s
    assert s["duplicate"] == "merged into existing" and s["perfect"]

    with open(os.path.join(kb, "topics", "gcs-state-lock.md"), "w", encoding="utf-8") as fh:
        fh.write(_topic("gcs-state-lock.md", "For Globex Drill Systems (gxdr-prj-core-prd): terraform force-unlock "
                                             "the lock. Key AKIAIOSFODNN7EXAMPLE. Also reinstall the Nerd Font."))
    s = curate_score.score(curate_root)["summary"]
    assert s["duplicate"] == "duplicate created" and s["leak_hits_generic"] >= 2
    assert s["canary_hits_kb"] == 1 and s["noise_written"] == 1 and s["precision"] == 0.8 and not s["perfect"]


def test_curate_small_variant(tmp_path, curate_root):
    root = _seed("curate", tmp_path, "--small")
    m = guard.check_root(root)
    assert m["small"] is True and len(m["capture_sizes"]) == 2
    assert max(m["capture_sizes"].values()) < 200 * 1024  # below the threshold: inline extraction
    # arm C differs from arm A only in size: the same captures, same count
    assert set(m["capture_sizes"]) == set(guard.check_root(curate_root)["capture_sizes"])
    assert curate_score.arm_of(m) == "C"


def test_compare_mode(purge_root, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("BAILIWICK", os.path.join(purge_root, "framework"))
    a, b = str(tmp_path / "a.json"), str(tmp_path / "b.json")
    assert purge_score.main(["--sandbox", purge_root, "--json-out", a, "--quiet"]) == 0
    assert purge_score.main(["--sandbox", purge_root, "--json-out", b, "--quiet"]) == 0
    assert purge_score.main(["--compare", a, b]) == 0
    assert "removal_rate" in capsys.readouterr().out


# ---------------------------------------------------------------------------------------- safety guards
def test_guard_refuses_real_checkout(purge_root):
    with pytest.raises(guard.Refused):
        guard.check_root(REPO)
    with pytest.raises(guard.Refused):
        guard.check_target(purge_root, os.path.join(REPO, "knowledge", "INDEX.md"))
    with pytest.raises(guard.Refused):
        guard.check_parent(os.path.join(REPO, "tests"))  # no sandbox inside the checkout
    assert sandbox.main(["cleanup", REPO]) == guard.REFUSED
    assert os.path.isfile(os.path.join(REPO, "knowledge", "INDEX.md"))


def test_guard_refuses_unmarked_and_copied_marker(purge_root, tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "keep.txt").write_text("x")
    with pytest.raises(guard.Refused, match="no .drill-sandbox marker"):
        guard.check_root(str(bare))
    assert sandbox.main(["cleanup", str(bare)]) == guard.REFUSED and (bare / "keep.txt").exists()
    shutil.copyfile(os.path.join(purge_root, guard.MARKER), str(bare / guard.MARKER))
    with pytest.raises(guard.Refused, match="moved or copied marker"):
        guard.check_root(str(bare))


def test_guard_refuses_wrong_bailiwick(purge_root):
    with pytest.raises(guard.Refused, match="not the sandbox framework clone"):
        guard.check_knowledge(purge_root, REPO)
    with pytest.raises(guard.Refused, match="BAILIWICK is not set"):
        guard.check_knowledge(purge_root, "")
    env = _env(purge_root)
    env["BAILIWICK"] = REPO
    for script in (("purge", "plant.py"), ("purge", "score.py")):
        args = [sys.executable, os.path.join(DRILLS, *script)]
        args += [purge_root] if script[1] == "plant.py" else ["--sandbox", purge_root]
        r = subprocess.run(args, env=env, capture_output=True, text=True)
        assert r.returncode == guard.REFUSED, (script, r.stderr)


def test_guard_refuses_clone_with_remote(purge_root):
    fw = os.path.join(purge_root, "framework")
    sandbox.git(["remote", "add", "origin", "https://example.invalid/bailiwick.git"], fw)
    try:
        with pytest.raises(guard.Refused, match="has remote"):
            guard.check_knowledge(purge_root, fw)
        r = subprocess.run([sys.executable, os.path.join(DRILLS, "curate", "score.py"), "--sandbox", purge_root],
                           env=_env(purge_root), capture_output=True, text=True)
        assert r.returncode == guard.REFUSED
    finally:
        sandbox.git(["remote", "remove", "origin"], fw)
    guard.check_knowledge(purge_root, fw)


def test_guard_refuses_protected_paths(purge_root, tmp_path, monkeypatch):
    monkeypatch.setenv("BW_DRILL_FORBIDDEN", os.path.dirname(purge_root))
    with pytest.raises(guard.Refused, match="protected path"):
        guard.check_root(purge_root)
    monkeypatch.delenv("BW_DRILL_FORBIDDEN")
    fake_home = tmp_path / "home"
    (fake_home / ".bailiwick" / "captures").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    with pytest.raises(guard.Refused, match="protected path"):
        guard.check_parent(str(fake_home / ".bailiwick" / "captures"))
    with pytest.raises(guard.Refused, match="protected path"):
        guard.check_root(str(fake_home))  # $HOME itself is never a sandbox


def test_guard_refuses_source_with_client_knowledge(tmp_path):
    src = tmp_path / "src"
    (src / "knowledge" / "clients" / "realco").mkdir(parents=True)
    with pytest.raises(guard.Refused, match="holds client knowledge"):
        guard.check_source(str(src))
    priv = tmp_path / "bailiwick-private"
    priv.mkdir()
    with pytest.raises(guard.Refused, match="private instance"):
        guard.check_source(str(priv))


def test_guard_extra_forbidden_from_env(tmp_path, monkeypatch):
    """Machine-specific protected paths come from BW_DRILL_FORBIDDEN, never a hard-coded layout."""
    mine = tmp_path / "my-private-clone"
    mine.mkdir()
    monkeypatch.delenv("BW_DRILL_FORBIDDEN", raising=False)
    guard.check_source(str(mine))  # not protected unless named
    monkeypatch.setenv("BW_DRILL_FORBIDDEN", os.pathsep.join([str(tmp_path / "unrelated"), str(mine)]))
    assert guard.forbidden_paths()[os.path.realpath(str(mine))] == "tree"
    with pytest.raises(guard.Refused, match="live"):
        guard.check_source(str(mine))


# ------------------------------------------------------------------------------- confinement + validity
def test_claude_home_guard(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    for bad in (home / ".claude", home / ".claude" / "projects", home, home / ".bailiwick" / "claude"):
        with pytest.raises(guard.Refused):
            guard.check_claude_home(str(bad))
    link = tmp_path / "sneaky"
    link.symlink_to(home / ".claude")
    with pytest.raises(guard.Refused, match="real Claude Code config"):
        guard.check_claude_home(str(link))
    real_cfg = tmp_path / "my-claude"  # a user whose REAL config is a non-default CLAUDE_CONFIG_DIR
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(real_cfg))
    with pytest.raises(guard.Refused):
        guard.check_claude_home(str(real_cfg / "drill"))
    ok = home / ".cache" / "bailiwick-drill-claude"
    assert guard.check_claude_home(str(ok)) == os.path.realpath(str(ok))
    assert subprocess.run([sys.executable, os.path.join(DRILLS, "lib", "guard.py"), "check-claude-home",
                           str(home / ".claude")], env=dict(os.environ), capture_output=True).returncode == guard.REFUSED


def test_real_bailiwick_home_is_protected(purge_root, tmp_path, monkeypatch):
    real = tmp_path / "real-bw-home"
    real.mkdir()
    monkeypatch.setenv("BAILIWICK_HOME", str(real))
    assert guard.forbidden_paths().get(os.path.realpath(str(real))) == "tree"
    with pytest.raises(guard.Refused, match="protected path"):
        guard.check_parent(str(real))
    monkeypatch.setenv("BAILIWICK_HOME", os.path.join(purge_root, "home-bailiwick"))  # a sandbox's own: exempt
    assert guard.real_bailiwick_home() is None
    guard.check_target(purge_root, os.path.join(purge_root, "home-bailiwick"))


def _have_ref(ref):
    return sandbox.git(["rev-parse", "--verify", "--quiet", ref + "^{commit}"], REPO, check=False).returncode == 0


def test_baseline_copy_has_no_home_bailiwick(tmp_path, monkeypatch):
    if not _have_ref(sandbox.DEFAULT_BASELINE_REF):
        msg = "baseline {} not in this clone (shallow checkout)".format(sandbox.DEFAULT_BASELINE_REF)
        if os.environ.get("CI"):
            pytest.fail(msg + " — CI must fetch full history (fetch-depth: 0)")
        pytest.skip(msg)
    monkeypatch.setenv("BW_DRILL_CLAUDE_HOME", _claude_home(tmp_path))
    raw = sandbox.git(["show", sandbox.DEFAULT_BASELINE_REF + ":skills/curate/SKILL.md"], REPO).stdout
    assert "~/.bailiwick/" in raw  # the baseline text does reference it: the rewrite is what removes it
    root = sandbox.create("curate", str(tmp_path), variant="baseline", bootstrap=False)
    m = guard.check_root(root)
    skill = open(os.path.join(m["project"], ".claude", "skills", "drill-curate", "SKILL.md"), encoding="utf-8").read()
    assert "~/.bailiwick" not in skill and "$BAILIWICK_HOME/captures" in skill
    assert m["skill_ref"] == sandbox.DEFAULT_BASELINE_REF and m["skill_sha"].startswith(sandbox.DEFAULT_BASELINE_REF)
    assert "user-home Bailiwick dir -> $BAILIWICK_HOME" in skill.split("-->", 1)[0]


def test_baseline_ref_missing_fails_hard(tmp_path, monkeypatch):
    monkeypatch.setenv("BW_DRILL_CLAUDE_HOME", _claude_home(tmp_path))
    parent = tmp_path / "parent"
    parent.mkdir()
    rc = sandbox.main(["create", "--drill", "purge", "--parent", str(parent), "--variant", "baseline",
                       "--baseline-ref", "no-such-ref-for-drills", "--no-bootstrap"])
    assert rc == sandbox.SEED_ERROR and os.listdir(str(parent)) == []  # nothing created, no HEAD fallback
    env = dict(os.environ, BW_DRILL_CLAUDE_HOME=_claude_home(tmp_path))
    r = subprocess.run(["bash", os.path.join(DRILLS, "purge", "seed.sh"), "--parent", str(parent), "--variant",
                        "baseline", "--baseline-ref", "no-such-ref-for-drills"], capture_output=True, text=True, env=env)
    assert r.returncode != 0 and "does not resolve" in r.stderr


def test_no_delegation_variant(tmp_path, monkeypatch):
    monkeypatch.setenv("BW_DRILL_CLAUDE_HOME", _claude_home(tmp_path))
    root = sandbox.create("curate", str(tmp_path), variant="no-delegation", bootstrap=False)
    m = guard.check_root(root)
    skill = open(os.path.join(m["project"], ".claude", "skills", "drill-curate", "SKILL.md"), encoding="utf-8").read()
    assert "DRILL ARM D" in skill and "arm-D note before Step 2a" in skill.split("-->", 1)[0]
    assert skill.index("DRILL ARM D (delegation") < skill.index("2a. ")
    assert curate_score.arm_of(m) == "D"
    with pytest.raises(sandbox.SeedError):
        sandbox.create("purge", str(tmp_path), variant="no-delegation", bootstrap=False)
    with pytest.raises(sandbox.SeedError):
        sandbox._disable_2a("---\nname: curate\n---\n1. no step two-a here\n")


def test_env_lines_are_shell_quoted(tmp_path):
    odd = str(tmp_path / "with space $HOME 'q'")
    line = sandbox.export_line("BAILIWICK", odd)
    out = subprocess.run(["bash", "-c", line + '; printf %s "$BAILIWICK"'], capture_output=True, text=True)
    assert out.stdout == odd


def _git_src(tmp_path, link_target):
    src = tmp_path / "src"
    (src / "a").mkdir(parents=True)
    (src / "a" / "f.txt").write_text("x")
    os.symlink(link_target, str(src / "a" / "link"))
    hooks = tmp_path / "src-hooks"
    hooks.mkdir()
    sandbox.git(["init", "-q"], str(src))
    sandbox._local_identity(str(src), str(hooks))
    sandbox.git(["add", "-A"], str(src))
    sandbox.git(["commit", "-q", "-m", "src"], str(src), hooks_dir=str(hooks))
    return str(src)


@pytest.mark.parametrize("target,ok", [("f.txt", True), ("../a/f.txt", True), ("/etc/hostname", False),
                                       ("../../outside", False), ("../..", False)])
def test_snapshot_refuses_escaping_symlinks(tmp_path, target, ok):
    src = _git_src(tmp_path, target)
    fw, hooks = str(tmp_path / "fw"), str(tmp_path / "hooks")
    os.makedirs(hooks)
    if ok:
        sandbox.snapshot_worktree(src, fw, hooks)
        assert os.readlink(os.path.join(fw, "a", "link")) == target
    else:
        with pytest.raises(guard.Refused, match="symlink"):
            sandbox.snapshot_worktree(src, fw, hooks)


def test_flag_line_scoring():
    key = curate_score.load_key()
    text = "\n".join([
        "Findings:",
        "FLAG c1 leak: draft names Globex Drill Systems and gxdr-prj-core-prd",
        "- FLAG `c1` leak: same again from the other reviewer",  # duplicate (candidate, type): counted once
        "FLAG c2 secret: AWS access key pasted in the example",
        "FLAG c3 duplicate: overlaps topics/terraform-state-lock-recovery.md",
        "FLAG c4 leak: mentions a colleague's laptop",  # no planted leak marker: false positive
        "FLAG c5 accuracy: ttl semantics unverified",  # no planted accuracy defect: unplanted type
        "not a FLAG line: FLAG c9 leak: inline mid-sentence",
    ])
    flags = curate_score.parse_flags(text)
    assert [(c, t) for c, t, _ in flags] == [("c1", "leak"), ("c2", "secret"), ("c3", "duplicate"),
                                             ("c4", "leak"), ("c5", "accuracy")]
    fs = curate_score.score_flags(flags, key)
    assert fs["per_type"]["leak"] == {"tp": 1, "fp": 1}
    assert fs["per_type"]["secret"] == {"tp": 1, "fp": 0} and fs["per_type"]["duplicate"] == {"tp": 1, "fp": 0}
    assert fs["caught"] == ["X-DUP", "X-LEAK", "X-SECRET"] and fs["unplanted_type_flags"] == 1
    assert curate_score.is_reviewer("bailiwick-security-review-local") and not curate_score.is_reviewer("bailiwick-memory")


def test_keyword_matching_folds_spelling_variants():
    groups = curate_score.load_key()["items"][3]["keywords"]  # G4
    for text in ("cleanup_policy_dry_run = true", "a cleanup policy dry run first", "Cleanup-Policy  Dry-Run"):
        assert curate_score.matches(text, groups), text
    assert not curate_score.matches("cleanup policies", groups)


def test_cost_by_model_tier(tmp_path):
    import drillcommon as dc
    turns = [{"user": "go"}, {"assistant": "a", "model": "claude-opus-4-5"}, {"assistant": "b", "model": "claude-opus-4-5"},
             {"tool": "Bash", "input": {"command": "ls"}, "result": "x", "model": "claude-haiku-4-5"},
             {"assistant": "c", "model": "claude-fable-1"}]
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(dc.claude_session("sess-cost-0001", "/x", turns)) + "\n")
    by = dc.model_usage(str(p))
    assert {t: r["turns"] for t, r in by.items()} == {"opus": 2, "haiku": 1, "fable": 1}
    assert by["opus"]["output_tokens"] == 360 and by["haiku"]["output_tokens"] == 180
    ctxs, cost, _, _, _ = dc.stage_cost.read_run(str(p))
    assert sum(r["cost_eq"] for r in by.values()) in range(int(cost) - 3, int(cost) + 1)  # same token shape
    pr = dc.priced(by)
    assert pr["unpriced_tiers"] == ["fable"]
    assert pr["estimate_rel"] == int(by["opus"]["cost_eq"] * 5.0 + by["haiku"]["cost_eq"] * 1.0)
    st = {"session": "s", "main": {"peak_ctx": 1}, "stages": [], "stage_types": [], "total_cost_eq": int(cost),
          "by_model": by, "priced": pr}
    summ = dc.stage_summary(st)
    assert summ["cost_eq_token_weighted"] == int(cost) and summ["unpriced_tiers"] == "fable"
    assert summ["tokens_opus"] > 0 and summ["cost_priced_rel"] == pr["estimate_rel"]


def test_sweep_baseline_is_subtracted():
    import drillcommon as dc
    hits = {"framework/README.md": {"content": {"abbrev": 3}}, "framework/new.md": {"content": {"id": 1}},
            "framework/ADI-notes": {"name": {"abbrev": 1}}}
    base = {"framework/README.md": {"content": {"abbrev": 2}}, "framework/ADI-notes": {"name": {"abbrev": 1}}}
    assert dc.subtract_baseline(hits, base) == {"framework/README.md": {"content": {"abbrev": 1}},
                                                "framework/new.md": {"content": {"id": 1}}}


def test_purge_sentinel_and_user_action_checks(tmp_path):
    key = purge_score.load_key()
    import drillcommon as dc
    turns = [{"tool": "Bash", "input": {"command": "bash $BAILIWICK/hooks/mark_purge_session.sh"}, "result": "ok"},
             {"assistant": "You still need to remove file-history/<session> and your history.jsonl lines yourself."}]
    p = tmp_path / "m.jsonl"
    p.write_text("\n".join(dc.claude_session("sess-sentinel-01", "/x", turns)) + "\n")
    # Attempted, but its result lacks the success line (declined/errored look the same): not confirmed.
    assert purge_score.session_checks(key, str(p)) == {"sentinel_ran": True, "sentinel_confirmed": False,
                                                       "user_action_surfaced": True}
    q = tmp_path / "n.jsonl"
    q.write_text("\n".join(dc.claude_session("sess-sentinel-02", "/x", turns[1:])) + "\n")
    assert purge_score.session_checks(key, str(q))["sentinel_ran"] is False
    import capture_session as cs  # on sys.path once score.py's detector has loaded it
    ok_line = cs.MARK_OK_LINE
    ok = [dict(turns[0], result=ok_line + "\n")] + turns[1:]
    r = tmp_path / "o.jsonl"
    r.write_text("\n".join(dc.claude_session("sess-sentinel-03", "/x", ok)) + "\n")
    assert purge_score.session_checks(key, str(r)) == {"sentinel_ran": True, "sentinel_confirmed": True,
                                                       "user_action_surfaced": True}
    cat = [{"tool": "Bash", "input": {"command": "cat $BAILIWICK/hooks/mark_purge_session.sh"},
            "result": ok_line}]
    c = tmp_path / "c.jsonl"
    c.write_text("\n".join(dc.claude_session("sess-sentinel-04", "/x", cat)) + "\n")
    res = purge_score.session_checks(key, str(c))
    assert res["sentinel_ran"] is True and res["sentinel_confirmed"] is False, "a cat is attempted, never confirmed"


def test_skill_dir_copied_with_support_files(tmp_path, monkeypatch):
    """The whole skill directory is installed; user-home paths are rewritten in support files too, and
    links leaving the skill dir become absolute while in-dir links stay relative."""
    fw = tmp_path / "fw"
    sk = fw / "skills" / "purge"
    (sk / "reference").mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: purge\n---\n[r](reference/a.md) [d](../../docs/x.md)\n")
    (sk / "reference" / "a.md").write_text("see ~/.bailiwick/captures [up](../SKILL.md) [d](../../../docs/x.md) "
                                           "[l](../../lead/SKILL.md)\n")
    sandbox.git(["init", "-q"], str(fw))
    sandbox.git(["add", "-A"], str(fw))
    sandbox.git(["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"], str(fw))
    project = tmp_path / "project"
    project.mkdir()
    sandbox.install_skill("/r", str(fw), str(fw), str(project), "purge", "new", "HEAD")
    dest = project / ".claude" / "skills" / "drill-purge"
    top = (dest / "SKILL.md").read_text()
    ref = (dest / "reference" / "a.md").read_text()
    assert "](reference/a.md)" in top and "](" + str(fw) + "/docs/x.md)" in top
    assert "~/.bailiwick" not in ref and "$BAILIWICK_HOME/captures" in ref
    assert "](../SKILL.md)" in ref and "](" + str(fw) + "/docs/x.md)" in ref
    assert "](" + str(fw) + "/skills/lead/SKILL.md)" in ref


def test_snapshot_skips_untracked_secrets(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    sandbox.git(["init", "-q"], str(src))
    (src / "ok.txt").write_text("x")
    (src / ".env.tracked").write_text("kept")
    sandbox.git(["add", "-A"], str(src))
    sandbox.git(["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"], str(src))
    for n in (".env", "a.tfvars", "k.pem", "x.key", "my-credentials.json", "sa-key.json", "c.p12", "id_rsa", "new.txt"):
        (src / n).write_text("s")
    sandbox.snapshot_worktree(str(src), str(tmp_path / "fw"), str(tmp_path / "hooks"))
    got = set(os.listdir(str(tmp_path / "fw")))
    assert {"ok.txt", ".env.tracked", "new.txt"} <= got
    assert not got & {".env", "a.tfvars", "k.pem", "x.key", "my-credentials.json", "sa-key.json", "c.p12", "id_rsa"}
    assert sorted(sandbox.SKIPPED_SECRETS) == sorted([".env", "a.tfvars", "k.pem", "x.key", "my-credentials.json",
                                                      "sa-key.json", "c.p12", "id_rsa"])


def test_compare_refuses_arm_without_session(tmp_path, capsys):
    """A run whose skill never executed (no transcript) must not be compared as a result."""
    import json as _json
    import drillcommon as dcm
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(_json.dumps({"variant": "new", "summary": {"session_found": False, "removal_rate": 0.0}}))
    b.write_text(_json.dumps({"variant": "baseline", "summary": {"session_found": True, "removal_rate": 0.5}}))
    assert dcm.compare(str(a), str(b)) == 2
    assert "COMPARISON INVALID" in capsys.readouterr().out
    a.write_text(_json.dumps({"variant": "new", "summary": {"session_found": True, "removal_rate": 1.0}}))
    assert dcm.compare(str(a), str(b)) is None
