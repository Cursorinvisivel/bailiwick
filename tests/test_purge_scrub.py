"""Contract tests for scripts/purge_scrub.py — the one token matcher /purge uses everywhere.

Pinned: short tokens match on alphanumeric boundaries only (`adi` never hits "loading"/"radius"),
redaction keeps every line (count and structure), the rewrite is atomic and keeps the file mode, a
dry run changes nothing (and is the default), no token or matched line ever reaches stdout, targets
are confined to the documented surfaces (no symlinks), and tokens under 3 chars are refused.
`check` (the read-only outbound-text gate) also sees separator, URL, HTML, base64 and hex variants,
prints counts only, and never reports a false 0 (missing/empty tokens, unreadable or oversized file).
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
    assert len(seen) == 6 and not any(seen), \
        "top-level + scrub/history/ere/exprs/check, all allow_abbrev=False"


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


# ---- check mode (read-only outbound-text gate) ---------------------------------------------------

CHECK_TOKENS = ["acme-drill", "Wombat Payments", "abc"]


@pytest.fixture
def chk_tokens(tmp_path):
    p = tmp_path / "chk-tokens"
    p.write_text("\n".join(CHECK_TOKENS) + "\n", encoding="utf-8")
    return str(p)


def _b64(s, alt=None):
    import base64
    return (base64.urlsafe_b64encode if alt else base64.b64encode)(s.encode()).decode()


def _forbidden(tok):
    """The token and the encodings `check` decodes; none may ever reach the output."""
    import base64
    import urllib.parse
    out = {tok.lower(), tok.encode().hex(), urllib.parse.quote(tok).lower()}
    for drop in range(3):  # every alignment of the base64 body
        raw = base64.b64encode(("x" * drop + tok).encode()).decode().rstrip("=")
        out.add(raw[4:-4].lower())
    return out


def _check(tmp_path, tokens, body, name="brief.md"):
    f = tmp_path / name
    f.write_text(body, encoding="utf-8")
    r = run("check", "--tokens", tokens, str(f))
    blob = (r.stdout + r.stderr).lower()
    for tok in CHECK_TOKENS[:2]:
        for form in _forbidden(tok):
            assert form not in blob, "check echoed a token or one of its encodings"
    return r


def _view(r, name):
    m = re.search(r"\b" + name + r" (\d+)", r.stdout)
    assert m, r.stdout
    return int(m.group(1))


def test_check_clean_file_exits_0_and_prints_counts_only(tmp_path, chk_tokens):
    r = _check(tmp_path, chk_tokens, "Plan: abstract <ID> under <ORG_NAME>.\nfabcd radius 0xdeadbeefcafe\n"
               "Wombat paying, acme drives; acme dri11 and the ab cd test.\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "file #1 brief.md: 0 (" in r.stdout and "total: 0" in r.stdout


@pytest.mark.parametrize("body,view", [
    ("raw acme-drill here", "raw"),
    ("ACME_DRILL", "separators"), ("acme.drill", "separators"), ("Acme Drill", "separators"),
    ("acmedrill", "separators"), ("wombat-payments", "separators"), ("WombatPayments", "separators"),
    ("Wombat\n   Payments wraps a line", "separators"), ("ac-me-drill", "separators"),
    ("see %61cme-drill", "url"), ("q=Wombat+Payments", "url"),
    ("double %2561%2563%256d%2565-drill", "url"),
    ("&#97;cme-drill", "html"), ("Wombat&nbsp;Payments", "html"), ("&amp;#97;cme-drill", "html"),
    ("blob " + _b64("acme-drill") + " end", "base64"),
    ("blob " + _b64("for Wombat Payments ltd") + " end", "base64"),
    ("u=" + _b64("acme-drill??>>", alt=True), "base64"),
    ("id=" + "acme-drill".encode().hex(), "hex"),
    ("idd" + "Wombat Payments".encode().hex().upper(), "hex"),  # odd hex prefix: offset 1
])
def test_check_detects_each_view(tmp_path, chk_tokens, body, view):
    r = _check(tmp_path, chk_tokens, body + "\n")
    assert r.returncode == 1, r.stdout + r.stderr
    assert _view(r, view) >= 1


@pytest.mark.parametrize("prefix", ["", "Z", "Zq", "Zq9", "Zq9x", "prefixZq"])
@pytest.mark.parametrize("pad", [True, False])
def test_check_base64_embedded_mid_string_at_every_alignment(tmp_path, chk_tokens, prefix, pad):
    body = _b64("acme-drill")
    body = body if pad else body.rstrip("=")
    r = _check(tmp_path, chk_tokens, "key:" + prefix + body + ("" if pad else "Tail9") + "\n")
    assert r.returncode == 1 and _view(r, "base64") >= 1, r.stdout


@pytest.mark.parametrize("lead", ["", "x", "xy"])
def test_check_base64_of_token_inside_longer_text_any_byte_offset(tmp_path, chk_tokens, lead):
    r = _check(tmp_path, chk_tokens, _b64(lead + "Wombat Payments") + "\n")
    assert r.returncode == 1 and _view(r, "base64") >= 1


@pytest.mark.parametrize("text,hit", [
    ("fabcd", False), ("abcd", False), ("xabc", False), ("abc", True), ("(ABC)", True),
    ("a.b.c", True), ("a-b c", True), ("ab-cd", False),
])
def test_check_short_token_keeps_alphanumeric_boundaries(tmp_path, text, hit):
    t = tmp_path / "t"
    t.write_text("abc\n", encoding="utf-8")
    f = tmp_path / "f"
    f.write_text(text + "\n", encoding="utf-8")
    r = run("check", "--tokens", str(t), str(f))
    assert r.returncode == (1 if hit else 0), r.stdout


def test_check_total_and_exit_over_several_files(tmp_path, chk_tokens):
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text("clean\n", encoding="utf-8")
    b.write_text("acme-drill\n", encoding="utf-8")
    r = run("check", "--tokens", chk_tokens, str(a), str(b))
    assert r.returncode == 1
    assert "file #1 a.md: 0" in r.stdout and "file #2 b.md: 2" in r.stdout and "total: 2" in r.stdout


def test_check_withholds_a_token_bearing_file_name(tmp_path, chk_tokens):
    r = _check(tmp_path, chk_tokens, "clean\n", name="acme_drill-brief.md")
    assert r.returncode == 0 and "file #1 (name withheld" in r.stdout


@pytest.mark.parametrize("content", [None, "", "\n   \n"])
def test_check_missing_or_empty_tokens_is_an_error_not_a_clean(tmp_path, content):
    t = tmp_path / "tokens"
    if content is not None:
        t.write_text(content, encoding="utf-8")
    f = tmp_path / "f"
    f.write_text("acme-drill\n", encoding="utf-8")
    r = run("check", "--tokens", str(t), str(f))
    assert r.returncode == 2 and "refusing" in r.stderr and "Traceback" not in r.stderr


def test_check_refuses_short_tokens_unless_allow_short(tmp_path):
    t = tmp_path / "tokens"
    t.write_text("acme-drill\nab\n", encoding="utf-8")
    f = tmp_path / "f"
    f.write_text("clean\n", encoding="utf-8")
    r = run("check", "--tokens", str(t), str(f))
    assert r.returncode == 2 and "token #2 shorter than 3" in r.stderr
    assert run("check", "--tokens", str(t), "--allow-short", str(f)).returncode == 0


def test_check_missing_and_oversized_files_are_errors(tmp_path, chk_tokens, monkeypatch):
    big = tmp_path / "big.md"
    big.write_bytes(b"a" * (ps.CHECK_MAX_BYTES + 1))
    r = run("check", "--tokens", chk_tokens, str(tmp_path / "nope.md"), str(big))
    assert r.returncode == 2
    assert "file #1 nope.md: error" in r.stderr and "file #2 big.md: error: larger than" in r.stderr
    d = tmp_path / "dir"
    d.mkdir()
    assert run("check", "--tokens", chk_tokens, str(d)).returncode == 2


def test_check_is_read_only_and_has_no_apply(tmp_path, chk_tokens):
    f = tmp_path / "brief.md"
    f.write_text("acme-drill\n", encoding="utf-8")
    raw, mtime = f.read_bytes(), f.stat().st_mtime_ns
    before = sorted(os.listdir(tmp_path))
    r = run("check", "--tokens", chk_tokens, "--apply", str(f))
    assert r.returncode == 2 and "unrecognized arguments" in r.stderr
    r = run("check", "--tokens", chk_tokens, str(f))
    assert r.returncode == 1
    assert f.read_bytes() == raw and f.stat().st_mtime_ns == mtime and sorted(os.listdir(tmp_path)) == before


def test_check_random_binary_noise_does_not_invent_hits(tmp_path, chk_tokens):
    import base64
    import random
    rnd = random.Random(7)
    blob = bytes(rnd.getrandbits(8) for _ in range(60000))
    f = tmp_path / "noise.md"
    f.write_text(base64.b64encode(blob).decode() + "\n" + blob.hex() + "\n", encoding="utf-8")
    r = run("check", "--tokens", chk_tokens, str(f))
    assert r.returncode == 0, r.stdout


def test_tokens_file_refusal_is_exit_2_in_every_mode(tmp_path):
    t = tmp_path / "tokens"
    t.write_text("\n", encoding="utf-8")
    r = run("ere", "--tokens", str(t), "--out", str(tmp_path / "o"))
    assert r.returncode == 2 and "refusing" in r.stderr and not (tmp_path / "o").exists()


# Non-ASCII test text is built with chr() so this file stays ASCII-only.
CEDILLA_TOKEN = "concei" + chr(0xE7) + chr(0xE3) + "o-labs"


def _fullwidth(s):
    return "".join(chr(0xFF21 + ord(c) - ord("A")) if "A" <= c <= "Z" else c for c in s)


@pytest.mark.parametrize("body", [
    "conceicao-labs",                                            # accents dropped
    "CONCEI" + chr(0xC7) + chr(0xC3) + "O_Labs",                 # precomposed, other case/separator
    "concei" + "c" + chr(0x327) + "a" + chr(0x303) + "o labs",   # decomposed (combining marks)
    "acme/drill",
    "acme" + chr(0x2011) + "drill",                              # non-breaking hyphen
    "acme&#8209;drill",                                          # ... as an HTML entity
    "acme" + chr(0x2013) + "drill",                              # en dash
    "acme" + chr(0xA0) + "drill",                                # no-break space
    "acme" + chr(0x200B) + "drill",                              # zero-width space inside
    "ac" + chr(0xAD) + "me-drill",                               # soft hyphen inside
    _fullwidth("ACME") + "-drill",                               # fullwidth letters
    "%EF%BC%A1CME-drill",                                        # URL-encoded fullwidth A
])
def test_check_folds_unicode_and_slash_variants(tmp_path, body):
    t = tmp_path / "tokens"
    t.write_text("acme-drill\n" + CEDILLA_TOKEN + "\n", encoding="utf-8")
    f = tmp_path / "f.md"
    f.write_text("see " + body + " here\n", encoding="utf-8")
    r = run("check", "--tokens", str(t), str(f))
    assert r.returncode == 1, r.stdout
    out = (r.stdout + r.stderr).lower()
    assert "concei" not in out and "acme" not in out


@pytest.mark.parametrize("text,hit", [
    ("x" + chr(0x200B) + "adi y", True),       # a zero-width char is a boundary, not glue
    ("a" + chr(0x200B) + "di", True),          # ... and is ignored inside the token
    (_fullwidth("ADI") + "x", False),          # fold keeps the boundary rule
    ("r" + _fullwidth("ADI") + "us", False),
    ("ad" + chr(0x301) + "i", True),           # combining accent dropped
    ("radi" + chr(0x2013) + "us", False),
])
def test_check_fold_keeps_short_token_boundaries(tmp_path, text, hit):
    t = tmp_path / "t"
    t.write_text("adi\n", encoding="utf-8")
    f = tmp_path / "f"
    f.write_text(text + "\n", encoding="utf-8")
    r = run("check", "--tokens", str(t), str(f))
    assert r.returncode == (1 if hit else 0), r.stdout


def test_fold_and_sep_matcher_unit():
    assert ps.fold("plain ascii") == "plain ascii"
    assert ps.fold(_fullwidth("AB") + chr(0x2013) + chr(0x200B) + "e" + chr(0x301)) == "AB- e"
    srx = ps.sep_matcher([CEDILLA_TOKEN])
    assert srx.search(ps.fold("Conceicao / Labs")) and not srx.search(ps.fold("concession labs"))


def test_check_stays_fast_on_adversarial_input(tmp_path, chk_tokens):
    import time
    f = tmp_path / "adv.md"
    body = ("a" + "-" * 997 + "c") * 1000 + (_fullwidth("ACM") + chr(0x200B) * 50) * 10000 \
        + chr(0xFDFA) * 100000  # separator runs after a first char, Cf runs, a 18x NFKD expander
    f.write_text(body, encoding="utf-8")
    t0 = time.time()
    r = run("check", "--tokens", chk_tokens, str(f))
    assert r.returncode == 0, r.stdout
    assert time.time() - t0 < 20  # about 0.5 s locally; generous for CI


O_SLASH, O_SLASH_UP = chr(0xF8), chr(0xD8)


@pytest.mark.parametrize("token,text,hit", [
    ("orsted", O_SLASH_UP + "rsted A/S", True),                 # ASCII token, special-letter text
    (O_SLASH_UP + "rsted", "orsted a/s", True),                 # special-letter token, ASCII text
    (O_SLASH_UP + "rsted", O_SLASH + "rsted", True),            # ... and the original spelling
    ("aerospace-labs", chr(0xC6) + "rospace Labs", True),       # ae ligature
    ("strasse-tech", "Stra" + chr(0xDF) + "e_Tech", True),      # sharp s
    ("strasse-tech", "STRA" + chr(0x1E9E) + "E-TECH", True),    # capital sharp s
    ("lodz-works", chr(0x141) + "od" + chr(0x17A) + " works", True),   # l with stroke + acute z
    ("djuro-co", chr(0x110) + "juro.co", True),                 # d with stroke
    ("oeuvre-x", chr(0x152) + "uvre x", True),                  # oe ligature
    ("thorsen-ab", chr(0xDE) + "orsen AB", True),               # thorn
    ("istanbul-co", chr(0x131) + "stanbul co", True),           # dotless i
    ("hamrun-ltd", chr(0x126) + "amrun Ltd", True),             # h with stroke
    ("orsted", "worsted wool", True),                           # long token: substring, as everywhere
])
def test_check_folds_letters_nfkd_leaves_whole(tmp_path, token, text, hit):
    t = tmp_path / "t"
    t.write_text(token + "\n", encoding="utf-8")
    f = tmp_path / "f"
    f.write_text(text + "\n", encoding="utf-8")
    r = run("check", "--tokens", str(t), str(f))
    assert r.returncode == (1 if hit else 0), r.stdout
    assert "rsted" not in (r.stdout + r.stderr).lower()


@pytest.mark.parametrize("text,hit", [
    (O_SLASH + "le", True), ("ole", True), ("(" + O_SLASH_UP + "LE)", True),
    ("x" + O_SLASH + "le", False),              # folded letter is a letter, not a boundary
    (O_SLASH + "lex", False), ("c" + O_SLASH + "le", False),
])
def test_check_letter_fold_keeps_short_token_boundaries(tmp_path, text, hit):
    t = tmp_path / "t"
    t.write_text("ole\n", encoding="utf-8")
    f = tmp_path / "f"
    f.write_text(text + "\n", encoding="utf-8")
    assert run("check", "--tokens", str(t), str(f)).returncode == (1 if hit else 0)


def test_check_label_withholds_a_folded_token_bearing_name(tmp_path):
    t = tmp_path / "t"
    t.write_text("orsted\n", encoding="utf-8")
    f = tmp_path / (O_SLASH_UP + "rsted-brief.md")
    f.write_text("clean\n", encoding="utf-8")
    r = run("check", "--tokens", str(t), str(f))
    assert r.returncode == 0 and "file #1 (name withheld" in r.stdout
    assert ps.fold(O_SLASH_UP + "rsted " + chr(0xE6) + chr(0xDF)) == "Orsted aess"
