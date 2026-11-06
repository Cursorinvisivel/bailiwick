#!/usr/bin/env python3
"""bailiwick — token redaction and token matching for /purge (stdlib only; run with `python3 -I`).

One matcher, four consumers, so every scrub, count, and history rewrite agrees on what "a token
matched" means (skills/purge/SKILL.md, Step 1.4):

  - a token of 4 characters or fewer matches only on alphanumeric boundaries, case-insensitively:
    `(?<![a-z0-9])tok(?![a-z0-9])`. A short abbreviation such as `adi` must not hit "loading" or
    "radius";
  - a longer token matches as a case-insensitive substring;
  - a non-ASCII token also matches its JSON `\\uXXXX`-escaped forms (lower, upper, as given).

Modes:

  scrub   --tokens <file> [--apply] <file>...
      Redact every match IN PLACE with `[redacted]`, for the guardrail audit log and the health
      shards. DRY RUN unless --apply (`--dry-run` is still accepted as an explicit no-op alias).
      Lines are never dropped: line count and structure stay intact. Counts are printed per
      token INDEX (1-based, order of the tokens file) and per file before anything is rewritten.
      Each rewrite is atomic (temp file in the same directory, same mode, os.replace), and a file
      that changed while it was being scrubbed is left alone and reported (exit 1).
      Targets are restricted to the documented surfaces: $BAILIWICK_HOME/guardrail-audit.log and
      files under $BAILIWICK_HOME/health/ ($BAILIWICK_HOME defaults to ~/.bailiwick).

  history --tokens <file> [--apply] <history.jsonl>
      The same redaction for Claude Code's prompt history, for the user-run block AFTER every
      Claude Code session has ended. Dry run unless --apply. The only accepted target is
      ${CLAUDE_CONFIG_DIR:-~/.claude}/history.jsonl.

  scrub/history refuse (exit 2, nothing read or written) any target outside those surfaces, and any
  target that is itself a symlink: the audit log is the guardrail's record, so the tool must not be
  a general in-place rewriter. The guardrail asks before any `scrub|history … --apply`.

  ere     --tokens <file> --out <file>
      Write one POSIX ERE per line, for `grep -iE -f <out>` and `git grep -iE -f <out>`, encoding the
      same boundary rule (grep -F cannot express it).

  exprs   --tokens <file> --out <file>
      Write a git-filter-repo expressions file (`regex:(?i)<pattern>==>[redacted]` per line) for
      `--replace-text` and `--replace-message` (docs/history-purge.md §1).

Tokens shorter than 3 characters are refused (they would redact unrelated text) unless
--allow-short is given.

Never prints a token, a matched line, or a path that matches a token. Output files are mode 0600.
Exit: 0 ok (a dry run that finds matches is still 0), 1 a file was not rewritten, 2 usage error or
a refused target.
"""
import argparse
import json
import os
import re
import stat
import sys
import tempfile

REDACTION = "[redacted]"
SHORT = 4  # tokens this long or shorter match on alphanumeric boundaries only
MIN_LEN = 3  # shorter tokens are refused unless --allow-short
_ERE_SPECIAL = set("\\.[]()*+?{}|^$")


def read_tokens(path, allow_short=False):
    """Non-blank lines, stripped, de-duplicated case-insensitively, in file order. A token shorter
    than MIN_LEN is refused (by index, never echoed) unless allow_short."""
    seen, out = set(), []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            tok = line.strip()
            if tok and tok.lower() not in seen:
                seen.add(tok.lower())
                out.append(tok)
    if not out:
        raise SystemExit("purge_scrub: no tokens in the tokens file — refusing (an empty scrub reports a false clean)")
    short = [str(i) for i, tok in enumerate(out, 1) if len(tok) < MIN_LEN]
    if short and not allow_short:
        raise SystemExit("purge_scrub: token #{} shorter than {} characters — refusing (it would redact "
                         "unrelated text); fix the tokens file or pass --allow-short deliberately"
                         .format(", #".join(short), MIN_LEN))
    return out


def variants(tok):
    """The token plus, when non-ASCII, its JSON-escaped forms (JSON writers may store `\\u00fc`)."""
    forms = [tok]
    if any(ord(c) > 127 for c in tok):
        for v in (tok, tok.lower(), tok.upper()):
            esc = json.dumps(v)[1:-1]
            if esc not in forms:
                forms.append(esc)
    return forms


def is_short(tok):
    return len(tok) <= SHORT


def _py_piece(tok, form):
    body = re.escape(form)
    return r"(?<![a-z0-9])" + body + r"(?![a-z0-9])" if is_short(tok) else body


def matcher(tokens):
    """One compiled alternation; group `t<i>` identifies the token. Longest forms first, so a
    token that contains another (`acme-drill` / `acme`) is redacted whole, in a single pass that
    never re-scans its own `[redacted]` output."""
    pieces = []
    for i, tok in enumerate(tokens):
        for form in variants(tok):
            pieces.append((len(form), i, _py_piece(tok, form)))
    pieces.sort(key=lambda p: -p[0])
    # Named groups must be unique: wrap each form in its own group and map it back to the token.
    group_tok, alts = {}, []
    for n, (_, i, piece) in enumerate(pieces):
        group_tok["g{}".format(n)] = i
        alts.append("(?P<g{}>{})".format(n, piece))
    return re.compile("|".join(alts), re.IGNORECASE), group_tok


def redact(text, rx, group_tok, counts):
    def sub(m):
        counts[group_tok[m.lastgroup]] += 1
        return REDACTION
    return rx.sub(sub, text)


def _label(path, k, rx):
    return path if not rx.search(path) else "file #{} (path withheld: it matches a token)".format(k)


def _sig(path):
    st = os.stat(path)
    return (st.st_size, st.st_mtime_ns, st.st_ino)


def _atomic_write(path, text, mode):
    fd, tmp = tempfile.mkstemp(prefix=".purge-scrub.", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _home():
    return os.environ.get("BAILIWICK_HOME") or os.path.join(os.path.expanduser("~"), ".bailiwick")


def _claude_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def target_error(mode, given):
    """Why `given` is not an accepted scrub/history target, or None when it is (see module doc)."""
    if os.path.islink(given):
        return "is a symlink"
    real = os.path.realpath(given)
    if mode == "history":
        ok = real == os.path.realpath(os.path.join(_claude_dir(), "history.jsonl"))
        return None if ok else "is not ${CLAUDE_CONFIG_DIR:-~/.claude}/history.jsonl"
    home = os.path.realpath(_home())
    health = os.path.join(home, "health")
    if real == os.path.join(home, "guardrail-audit.log") or real.startswith(health + os.sep):
        return None
    return "is outside $BAILIWICK_HOME/guardrail-audit.log and $BAILIWICK_HOME/health/"


def check_targets(mode, tokens, files):
    """Refuse the whole run (exit 2) when any target is off the documented surfaces."""
    rx, _ = matcher(tokens)
    bad = [(k, given, why) for k, given in enumerate(files, 1)
           for why in [target_error(mode, given)] if why]
    for k, given, why in bad:
        print("purge_scrub: refused: {} {} (no symlinks; only the documented surfaces)".format(
            _label(given, k, rx), why), file=sys.stderr)
    if bad:
        print("purge_scrub: nothing read or written", file=sys.stderr)
        return 2
    return 0


def scrub(tokens, files, write):
    rx, group_tok = matcher(tokens)
    plans, failed = [], 0
    totals = [0] * len(tokens)
    for k, given in enumerate(files, 1):
        label = _label(given, k, rx)
        path = os.path.realpath(given)
        if not os.path.isfile(path):
            print("{}: skip (missing or not a regular file)".format(label))
            continue
        sig = _sig(path)
        with open(path, encoding="utf-8", errors="surrogateescape", newline="") as fh:
            text = fh.read()
        counts = [0] * len(tokens)
        new = redact(text, rx, group_tok, counts)
        lines = sum(1 for a, b in zip(text.splitlines(), new.splitlines()) if a != b)
        for i, c in enumerate(counts):
            totals[i] += c
        print("{}: {} match(es) on {} line(s)".format(label, sum(counts), lines))
        if new != text:
            plans.append((label, path, sig, new))
    for i, c in enumerate(totals):
        print("token #{}: {} match(es)".format(i + 1, c))
    if not write:
        print("dry run: nothing rewritten ({} file(s) would change); re-run with --apply to redact"
              .format(len(plans)))
        return 0
    for label, path, sig, new in plans:
        if _sig(path) != sig:
            print("{}: NOT rewritten — it changed during the scrub (another session running?); re-run".format(label))
            failed += 1
            continue
        _atomic_write(path, new, stat.S_IMODE(os.stat(path).st_mode))
        print("{}: redacted in place".format(label))
    print("rewritten: {} file(s); failed: {}".format(len(plans) - failed, failed))
    return 1 if failed else 0


def _ere_escape(s):
    return "".join("\\" + c if c in _ERE_SPECIAL else c for c in s)


def ere_lines(tokens):
    out = []
    for tok in tokens:
        for form in variants(tok):
            body = _ere_escape(form)
            out.append("(^|[^A-Za-z0-9])" + body + "([^A-Za-z0-9]|$)" if is_short(tok) else body)
    return out


def exprs_lines(tokens):
    """filter-repo applies these to BYTES, where (?i) folds ASCII only: emit case variants of a
    non-ASCII token explicitly. filter-repo applies the lines IN FILE ORDER, so the longest form
    comes first: `contoso` before `contoso-payments` would leave `[redacted]-payments`."""
    pieces = []
    for tok in tokens:
        forms = variants(tok)
        if any(ord(c) > 127 for c in tok):
            forms += [f for f in (tok.lower(), tok.upper()) if f not in forms]
        for form in forms:
            pieces.append((len(form), "regex:(?i)" + _py_piece(tok, form) + "==>" + REDACTION))
    out = []
    for _, line in sorted(pieces, key=lambda p: -p[0]):  # stable: ties keep token order
        if line not in out:
            out.append(line)
    return out


def write_private(path, lines):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("wrote {} pattern line(s) (mode 0600)".format(len(lines)))


def main(argv=None):
    # allow_abbrev=False on EVERY parser: argparse would otherwise accept `--ap`/`--app`/`--appl` for
    # `--apply`, which the guardrail's `--apply` ask never sees (an unconfirmed in-place rewrite).
    ap = argparse.ArgumentParser(prog="purge_scrub.py", description=__doc__.split("\n", 1)[0],
                                 allow_abbrev=False)
    sub = ap.add_subparsers(dest="mode", required=True)
    s = sub.add_parser("scrub", allow_abbrev=False)
    s.add_argument("--tokens", required=True)
    g = s.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="rewrite in place (default: dry run)")
    g.add_argument("--dry-run", action="store_true", help="the default; accepted for compatibility")
    s.add_argument("files", nargs="+")
    h = sub.add_parser("history", allow_abbrev=False)
    h.add_argument("--tokens", required=True)
    h.add_argument("--apply", action="store_true")
    h.add_argument("file")
    for name in ("ere", "exprs"):
        p = sub.add_parser(name, allow_abbrev=False)
        p.add_argument("--tokens", required=True)
        p.add_argument("--out", required=True)
    for p in (s, h) + tuple(sub.choices[n] for n in ("ere", "exprs")):
        p.add_argument("--allow-short", action="store_true",
                       help="accept tokens shorter than {} characters".format(MIN_LEN))
    a = ap.parse_args(argv)
    tokens = read_tokens(a.tokens, allow_short=a.allow_short)
    if a.mode == "scrub":
        return check_targets("scrub", tokens, a.files) or scrub(tokens, a.files, write=a.apply)
    if a.mode == "history":
        rc = check_targets("history", tokens, [a.file])
        if rc:
            return rc
        print("history.jsonl: end EVERY Claude Code session first — each one appends to this file")
        return scrub(tokens, [a.file], write=a.apply)
    write_private(a.out, ere_lines(tokens) if a.mode == "ere" else exprs_lines(tokens))
    return 0


if __name__ == "__main__":
    sys.exit(main())
