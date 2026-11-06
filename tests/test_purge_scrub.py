"""Contract tests for scripts/purge_scrub.py — the one token matcher /purge uses everywhere.

Pinned: short tokens match on alphanumeric boundaries only (`adi` never hits "loading"/"radius"),
redaction keeps every line (count and structure), the rewrite is atomic and keeps the file mode, a
dry run changes nothing (and is the default), no token or matched line ever reaches stdout, targets
are confined to the documented surfaces (no symlinks), and tokens under 3 chars are refused.
"""
import os
import re
import stat
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "purge_scrub.py")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import purge_scrub as ps  # noqa: E402

TOKENS = ["acme-drill", "ADI", "Acme Drill Ltd"]


def run(*args):
    return subprocess.run([sys.executable, "-I", SCRIPT] + list(args), capture_output=True, text=True)


@pytest.fixture(autouse=True)
def surfaces(tmp_path, monkeypatch):
    """$BAILIWICK_HOME and ${CLAUDE_CONFIG_DIR} both point at tmp_path (inherited by `run`)."""
    monkeypatch.setenv("BAILIWICK_HOME", str(tmp_path))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))


@pytest.fixture
def tokfile(tmp_path):
    p = tmp_path / "tokens"
    p.write_text("\n".join(TOKENS) + "\n\n", encoding="utf-8")
    return str(p)


def _assert_no_token(out):
    low = out.lower()
    assert "acme-drill" not in low and "acme drill" not in low
    assert not re.search(r"(?<![a-z0-9])adi(?![a-z0-9])", low)


# ---- matcher -------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,hits", [
    ("loading the radius module", 0),       # short token inside words: no match
    ("ADI rollout", 1), ("team adi.", 1), ("x/adi-prod/y", 1), ("adi_prod", 1), ("(Adi)", 1),
    ("adix", 0), ("1adi", 0),
    ("ACME-DRILL bucket", 1), ("prefix-acme-drillsuffix", 1),  # long token: substring
    ("for Acme Drill Ltd's", 1),
])
def test_boundary_rule(text, hits):
    rx, gt = ps.matcher(TOKENS)
    counts = [0] * len(TOKENS)
    ps.redact(text, rx, gt, counts)
    assert sum(counts) == hits


def test_longest_form_wins_and_single_pass():
    rx, gt = ps.matcher(["acme", "acme-drill"])
    counts = [0, 0]
    out = ps.redact("acme-drill and acme", rx, gt, counts)
    assert out == "[redacted] and [redacted]" and counts == [1, 1]


def test_non_ascii_token_matches_json_escaped_form():
    rx, gt = ps.matcher(["Müller"])
    counts = [0]
    out = ps.redact('{"display":"ask M\\u00fcller","p":"MÜLLER"}', rx, gt, counts)
    assert counts == [2] and "ller" not in out


def test_ere_lines_agree_with_python_matcher(tmp_path):
    grep = subprocess.run(["sh", "-c", "command -v grep"], capture_output=True, text=True).stdout.strip()
    if not grep:
        pytest.skip("grep unavailable")
    pat = tmp_path / "t.ere"
    ps.write_private(str(pat), ps.ere_lines(TOKENS))
    assert stat.S_IMODE(os.stat(pat).st_mode) == 0o600
    sample = ["loading the radius module", "ADI rollout", "x/adi-prod/y", "adix", "ACME-DRILL bucket",
              "for Acme Drill Ltd's", "nothing here"]
    data = tmp_path / "data"
    data.write_text("\n".join(sample) + "\n", encoding="utf-8")
    got = subprocess.run([grep, "-inE", "-f", str(pat), str(data)], capture_output=True, text=True).stdout
    grep_lines = {int(l.split(":", 1)[0]) for l in got.splitlines()}
    rx, _ = ps.matcher(TOKENS)
    py_lines = {i for i, l in enumerate(sample, 1) if rx.search(l)}
    assert grep_lines == py_lines == {2, 3, 5, 6}


def test_exprs_lines_are_filter_repo_regex_with_boundaries():
    lines = ps.exprs_lines(["adi", "a.b-corp"])
    assert lines[0] == r"regex:(?i)a\.b\-corp==>[redacted]"     # longest first
    assert lines[1] == r"regex:(?i)(?<![a-z0-9])adi(?![a-z0-9])==>[redacted]"
    body = re.compile(lines[0][len("regex:"):].split("==>")[0])
    assert body.search("A.B-CORP") and not body.search("aXb-corp")


def test_exprs_overlapping_tokens_redact_whole_in_file_order():
    """filter-repo applies the lines in order; the longer token must come first."""
    lines = ps.exprs_lines(["contoso", "contoso-payments"])
    text = "deploy contoso-payments and contoso"
    for line in lines:  # replay filter-repo's sequential application
        pat, repl = line[len("regex:"):].split("==>")
        text = re.sub(pat, repl, text)
    assert text == "deploy [redacted] and [redacted]"


# ---- scrub mode ----------------------------------------------------------------------------------

def _log(tmp_path):
    p = tmp_path / "guardrail-audit.log"
    lines = ['2026-11-01 ask /home/u/code/acme-drill-infra rm -r x\n',
             '2026-11-01 ask /home/u/code/other-repo loading radius\n',
             '{"ts":"t","detail":"push to Acme Drill Ltd / ADI"}\r\n',
             'tail line without newline acme-drill']
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write("".join(lines))
    os.chmod(p, 0o640)
    return p, lines


def test_scrub_redacts_in_place_keeping_lines(tmp_path, tokfile):
    p, before = _log(tmp_path)
    r = run("scrub", "--tokens", tokfile, "--apply", str(p))
    assert r.returncode == 0, r.stderr
    with open(p, encoding="utf-8", newline="") as fh:
        after = fh.read().splitlines(True)
    assert len(after) == len(before)
    assert after[1] == before[1]                       # unrelated line untouched
    assert after[0] == "2026-11-01 ask /home/u/code/[redacted]-infra rm -r x\n"
    assert after[2].endswith("\r\n") and after[2].count("[redacted]") == 2
    assert not after[3].endswith("\n")
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o640
    assert "token #1: 2 match(es)" in r.stdout and "token #2: 1 match(es)" in r.stdout
    assert "token #3: 1 match(es)" in r.stdout
    _assert_no_token(r.stdout + r.stderr)
    assert not [f for f in os.listdir(tmp_path) if f.startswith(".purge-scrub.")]  # no temp left


@pytest.mark.parametrize("flags", [[], ["--dry-run"]], ids=["default", "explicit-alias"])
def test_scrub_dry_run_is_the_default_and_a_no_op(tmp_path, tokfile, flags):
    p, _ = _log(tmp_path)
    raw, st = p.read_bytes(), os.stat(p)
    r = run("scrub", "--tokens", tokfile, *flags, str(p))
    assert r.returncode == 0 and "dry run: nothing rewritten (1 file(s) would change)" in r.stdout
    assert "--apply" in r.stdout
    assert p.read_bytes() == raw and os.stat(p).st_ino == st.st_ino
    _assert_no_token(r.stdout)


def test_scrub_apply_and_dry_run_are_exclusive(tmp_path, tokfile):
    p, _ = _log(tmp_path)
    r = run("scrub", "--tokens", tokfile, "--apply", "--dry-run", str(p))
    assert r.returncode == 2


@pytest.mark.parametrize("flag", ["--ap", "--app", "--appl", "--dry", "--tok"])
def test_scrub_refuses_abbreviated_options_and_writes_nothing(tmp_path, tokfile, flag):
    """An abbreviation of --apply would slip past the guardrail's `--apply` ask (allow_abbrev=False)."""
    p, _ = _log(tmp_path)
    raw, st = p.read_bytes(), os.stat(p)
    args = ["scrub", flag, tokfile, str(p)] if flag == "--tok" else ["scrub", "--tokens", tokfile, flag, str(p)]
    r = run(*args)
    assert r.returncode == 2, (flag, r.stdout, r.stderr)
    assert p.read_bytes() == raw and os.stat(p).st_ino == st.st_ino, "nothing rewritten"


@pytest.mark.parametrize("flag", ["--ap", "--appl"])
def test_history_refuses_abbreviated_apply(tmp_path, tokfile, flag):
    h = tmp_path / "history.jsonl"
    h.write_text('{"display":"purge acme-drill"}\n', encoding="utf-8")
    raw = h.read_bytes()
    r = run("history", "--tokens", tokfile, flag, str(h))
    assert r.returncode == 2 and h.read_bytes() == raw


def test_every_parser_refuses_abbreviations():
    import argparse
    seen = []
    real = argparse.ArgumentParser.__init__

    def spy(self, *a, **kw):
        seen.append(kw.get("allow_abbrev", True))
        real(self, *a, **kw)
    argparse.ArgumentParser.__init__ = spy
    try:
        with pytest.raises(SystemExit):
            ps.main(["--help"])
    finally:
        argparse.ArgumentParser.__init__ = real
    assert len(seen) == 5 and not any(seen), "top-level + scrub/history/ere/exprs, all allow_abbrev=False"


@pytest.mark.parametrize("where", ["outside", "sibling-of-home", "bailiwick-knowledge"])
def test_scrub_refuses_targets_off_the_documented_surfaces(tmp_path, tokfile, where):
    target = {"outside": tmp_path.parent / (tmp_path.name + "-x") / "notes.md",
              "sibling-of-home": tmp_path / "allowlist",
              "bailiwick-knowledge": tmp_path / "knowledge" / "INDEX.md"}[where]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("acme-drill\n", encoding="utf-8")
    raw = target.read_bytes()
    r = run("scrub", "--tokens", tokfile, "--apply", str(target))
    assert r.returncode == 2 and "refused" in r.stderr and "nothing read or written" in r.stderr
    assert target.read_bytes() == raw and r.stdout == ""


def test_scrub_refuses_symlinks_even_inside_the_surfaces(tmp_path, tokfile):
    victim = tmp_path / "victim.txt"
    victim.write_text("acme-drill\n", encoding="utf-8")
    (tmp_path / "health").mkdir()
    link = tmp_path / "health" / "shard.jsonl"
    link.symlink_to(victim)                           # final component a symlink
    sub = tmp_path / "health" / "remote"
    sub.symlink_to(tmp_path.parent)                   # a symlinked dir leading out of the surface
    for target in (link, sub / tmp_path.name / "victim.txt"):
        r = run("scrub", "--tokens", tokfile, "--apply", str(target))
        assert r.returncode == 2 and "refused" in r.stderr, target
    assert victim.read_text(encoding="utf-8") == "acme-drill\n"


def test_scrub_refusal_withholds_token_bearing_paths(tmp_path, tokfile):
    d = tmp_path / "acme-drill"
    d.mkdir()
    r = run("scrub", "--tokens", tokfile, str(d / "x.log"))
    assert r.returncode == 2 and "path withheld" in r.stderr
    _assert_no_token(r.stdout + r.stderr)


def test_scrub_accepts_health_shards_and_the_audit_log(tmp_path, tokfile):
    _log(tmp_path)
    (tmp_path / "health" / "remote").mkdir(parents=True)
    (tmp_path / "health" / "m.jsonl").write_text("ADI\n", encoding="utf-8")
    (tmp_path / "health" / "remote" / "n.jsonl").write_text("acme-drill\n", encoding="utf-8")
    r = run("scrub", "--tokens", tokfile, "--apply", str(tmp_path / "guardrail-audit.log"),
            str(tmp_path / "health" / "m.jsonl"), str(tmp_path / "health" / "remote" / "n.jsonl"),
            str(tmp_path / "health" / "remote" / "*"))  # an unmatched glob stays literal: skipped
    assert r.returncode == 0, r.stderr
    assert "rewritten: 3 file(s)" in r.stdout
    assert (tmp_path / "health" / "m.jsonl").read_text(encoding="utf-8") == "[redacted]\n"


def test_scrub_is_atomic_replace(tmp_path, tokfile, monkeypatch):
    p, _ = _log(tmp_path)
    ino = os.stat(p).st_ino
    assert ps.scrub(TOKENS, [str(p)], write=True) == 0
    assert os.stat(p).st_ino != ino                     # replaced via a new file, not truncated


def test_scrub_failed_write_leaves_original_and_no_temp(tmp_path, monkeypatch):
    p, _ = _log(tmp_path)
    raw = p.read_bytes()

    def boom(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(ps.os, "replace", boom)
    with pytest.raises(OSError):
        ps.scrub(TOKENS, [str(p)], write=True)
    assert p.read_bytes() == raw
    assert not [f for f in os.listdir(tmp_path) if f.startswith(".purge-scrub.")]


def test_scrub_skips_a_file_changed_mid_run(tmp_path, monkeypatch, capsys):
    p, _ = _log(tmp_path)
    real = ps._sig
    calls = {"n": 0}

    def drifting(path):
        calls["n"] += 1
        s = real(path)
        return s if calls["n"] == 1 else (s[0] + 1,) + s[1:]
    monkeypatch.setattr(ps, "_sig", drifting)
    raw = p.read_bytes()
    assert ps.scrub(TOKENS, [str(p)], write=True) == 1
    assert p.read_bytes() == raw and "NOT rewritten" in capsys.readouterr().out


def test_token_bearing_path_is_withheld_and_missing_file_skipped(tmp_path, tokfile):
    d = tmp_path / "health" / "acme-drill"
    d.mkdir(parents=True)
    f = d / "shard.jsonl"
    f.write_text("ADI\n", encoding="utf-8")
    r = run("scrub", "--tokens", tokfile, str(f), str(tmp_path / "health" / "nope.jsonl"))
    assert r.returncode == 0
    assert "file #1 (path withheld" in r.stdout and "skip (missing" in r.stdout
    _assert_no_token(r.stdout)


def test_empty_tokens_file_refuses(tmp_path):
    t = tmp_path / "tokens"
    t.write_text("\n  \n", encoding="utf-8")
    r = run("scrub", "--tokens", str(t), str(t))
    assert r.returncode != 0 and "refusing" in r.stderr


@pytest.mark.parametrize("mode", ["scrub", "history", "ere"])
def test_short_tokens_refused_unless_allow_short(tmp_path, mode):
    t = tmp_path / "tokens"
    t.write_text("acme-drill\nab\n", encoding="utf-8")
    target = {"scrub": [str(tmp_path / "guardrail-audit.log")],
              "history": [str(tmp_path / "history.jsonl")],
              "ere": ["--out", str(tmp_path / "t.ere")]}[mode]
    r = run(mode, "--tokens", str(t), *target)
    assert r.returncode != 0 and "token #2 shorter than 3" in r.stderr
    assert " ab" not in r.stderr and "acme" not in r.stderr.lower()  # reported by index only
    r = run(mode, "--tokens", str(t), "--allow-short", *target)
    assert r.returncode == 0, r.stderr


# ---- history mode --------------------------------------------------------------------------------

def test_history_is_dry_run_unless_apply(tmp_path, tokfile):
    h = tmp_path / "history.jsonl"
    h.write_text('{"display":"purge acme-drill","project":"/home/u/code/x"}\n{"display":"loading"}\n',
                 encoding="utf-8")
    raw = h.read_bytes()
    r = run("history", "--tokens", tokfile, str(h))
    assert r.returncode == 0 and h.read_bytes() == raw and "--apply" in r.stdout
    r = run("history", "--tokens", tokfile, "--apply", str(h))
    assert r.returncode == 0
    lines = h.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and lines[0] == '{"display":"purge [redacted]","project":"/home/u/code/x"}'
    _assert_no_token(r.stdout)


def test_history_refuses_any_file_but_the_claude_history(tmp_path, tokfile):
    other = tmp_path / "projects" / "history.jsonl"
    other.parent.mkdir()
    other.write_text("acme-drill\n", encoding="utf-8")
    r = run("history", "--tokens", tokfile, "--apply", str(other))
    assert r.returncode == 2 and "refused" in r.stderr
    assert other.read_text(encoding="utf-8") == "acme-drill\n"
