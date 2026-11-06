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

  check   --tokens <file> <file>...
      READ-ONLY outbound-text gate (the Advisor brief, commit message, branch/slug, PR title and
      body files). Writes nothing and has no --apply. Counts token hits over several views of each
      file, so an encoded or re-separated identifier cannot slip past the plain `grep -ciE` check:
        raw         the text as-is, with the matching rule above (JSON-escaped forms included);
        separators  token and text are FOLDED alike (NFKD, so fullwidth and NBSP forms collapse;
                    combining marks dropped, so `conceicao` hits a token spelled with cedilla and
                    tilde; o-slash, ae, sharp s, stroke letters, oe, thorn, eth, dotless i spelled
                    out in Latin; Unicode dashes -> `-`; Unicode spaces and format characters
                    such as a zero-width space -> a space). Then `-`, `_`, `.`, `/` and whitespace are
                    equivalent to each other and to nothing: the token's separators are dropped and
                    `[-_./\\s]*` is allowed between every remaining character, so `acme-drill` also
                    hits `acme_drill`, `ACME.Drill`, `acme/drill`, `acme drill`, `acmedrill`, an
                    en-dash or zero-width-space spelling, `acme-\\n  drill`, `ac-me-drill`. The text
                    is not stripped of separators, so a short token keeps its alphanumeric
                    boundaries (`adi` hits `a.d.i` standalone, never inside `radius` or `a-dim`);
        url         percent-decoded (`+` is a space), repeated until stable, at most 3 rounds;
        html        html.unescape, repeated until stable, at most 3 rounds;
        base64      every `[A-Za-z0-9+/_-]{8,}={0,2}` run, standard and URL-safe alphabets, decoded
                    as-is and with its first 1-3 characters dropped (realigns a run glued to a
                    preceding word: the 4-character groups then line up again);
        hex         every run of 8+ hex digits, decoded at offsets 0 and 1.
      Decoded bytes are read as UTF-8; only printable stretches of 4+ characters are searched, so
      binary noise does not invent hits. Every view except raw/separators is searched only when the
      decoding changed something, with the raw matcher and with the separators matcher on its fold.
      The count is therefore a HIT COUNT ACROSS VIEWS, not a number of distinct traces: one plain
      mention shows as 2 (raw + separators). It is a must-be-zero gate.
      NOT covered (a human still reads the text): `\\xNN` escapes, quoted-printable, base64 wrapped
      across lines, UTF-16, homoglyphs NFKD does not fold (Cyrillic `a`, Greek `o`), layered
      encodings (base64 of URL-encoded text), and base64 of a bare token too short for an 8-character
      run (a 3-5 character token on its own).
      Prints only counts (per file, per view, and a total); never a token, an excerpt, or a
      token-bearing file name. Each file is read up to 5 MB; a larger file is an error, never a
      silently truncated scan. Exit 0 total 0; 1 any hit; 2 an error (unreadable, missing or empty
      tokens file, refused short token, missing/oversized/non-regular file); never a false 0.

Tokens shorter than 3 characters are refused (they would redact unrelated text) unless
--allow-short is given.

Never prints a token, a matched line, or a path that matches a token. Output files are mode 0600.
Exit: 0 ok (a dry run that finds matches is still 0), 1 a file was not rewritten (check: a hit), 2
usage error, an unreadable/empty tokens file, or a refused target.
"""
import argparse
import base64
import binascii
import html
import json
import os
import re
import stat
import sys
import tempfile
import unicodedata
import urllib.parse

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


# ---- check: read-only, encoding-aware outbound-text gate -----------------------------------------

CHECK_MAX_BYTES = 5 * 1024 * 1024
_SEP_CHARS = "-_./"  # plus any whitespace; fold() maps Unicode dashes, spaces and format chars here
# Possessive (3.11+) where available: the class never overlaps a token character, so giving back a
# separator can never help a match; possessive just skips the futile backtracking.
_SEP_CLASS = r"[-_./\s]*+" if sys.version_info >= (3, 11) else r"[-_./\s]*"
_B64_RUN = re.compile(r"[A-Za-z0-9+/_-]{8,}={0,2}")
_HEX_RUN = re.compile(r"[0-9A-Fa-f]{8,}")
_B64URL = str.maketrans("-_", "+/")
_DECODE_ROUNDS = 3
_MIN_SEGMENT = 4  # printable stretch a decoded blob must contain to be searched
_NONPRINT = re.compile("[\x00-\x08\x0a-\x1f\x7f-\x9f\ufffd\u2028\u2029]+")
CHECK_VIEWS = ("raw", "separators", "url", "html", "base64", "hex")
# Letters NFKD leaves whole (no combining-mark decomposition): o-slash, ae, sharp s (and capital),
# l/d with stroke, oe, thorn, eth, dotless i, h with stroke. Mapped to their usual Latin spellings.
_FOLD_LETTERS = {
    0x00D8: "O", 0x00F8: "o", 0x00C6: "AE", 0x00E6: "ae", 0x00DF: "ss", 0x1E9E: "SS",
    0x0141: "L", 0x0142: "l", 0x0110: "D", 0x0111: "d", 0x0152: "OE", 0x0153: "oe",
    0x00DE: "TH", 0x00FE: "th", 0x00D0: "D", 0x00F0: "d", 0x0131: "i", 0x0126: "H", 0x0127: "h",
}


def fold(text):
    """Compatibility fold for the separators matcher, applied to tokens and text alike: NFKD
    (fullwidth `\uff21` -> `A`, ligatures, NBSP -> space), combining marks (Mn) dropped
    (`conceicao` == `conceic\u0327a\u0303o`), Unicode dashes (Pd) -> `-`, and spaces (Zs/Zl/Zp)
    and format characters (Cf: zero-width space, soft hyphen, bidi controls) -> a space. A Cf is
    mapped to a separator rather than deleted: separators are equivalent to nothing, so
    `acme\u200bdrill` still hits, and a zero-width character next to a short token stays a boundary.
    Letters NFKD leaves whole (o-slash, ae, sharp s, l/d/h with stroke, oe, thorn, eth, dotless i)
    map to their Latin spellings (_FOLD_LETTERS), so a token `orsted` and a token spelled with
    o-slash both hit either spelling.
    ASCII text is returned untouched; the table is built from the text's distinct characters only."""
    if text.isascii():
        return text
    text = unicodedata.normalize("NFKD", text)
    table = {}
    for ch in set(text):
        if ord(ch) < 128:
            continue
        if ord(ch) in _FOLD_LETTERS:
            table[ord(ch)] = _FOLD_LETTERS[ord(ch)]
            continue
        cat = unicodedata.category(ch)
        if cat == "Mn":
            table[ord(ch)] = None
        elif cat == "Pd":
            table[ord(ch)] = "-"
        elif cat in ("Zs", "Zl", "Zp", "Cf"):
            table[ord(ch)] = " "
    return text.translate(table) if table else text


def _sep_core(tok):
    return "".join(c for c in fold(tok) if c not in _SEP_CHARS and not c.isspace())


def sep_matcher(tokens):
    """Separator-tolerant matcher over FOLDED text (search `fold(text)`): the folded token with its
    separators dropped, `[-_./\\s]*` allowed between every remaining character, the short-token
    boundary rule kept. Equivalent to normalising both sides, without destroying the boundaries a
    short token needs. The class never overlaps the token's own characters, so matching stays
    linear."""
    alts = []
    for tok in tokens:
        core = _sep_core(tok)
        if not core:
            continue
        body = _SEP_CLASS.join(re.escape(c) for c in core)
        alts.append(r"(?<![a-z0-9])" + body + r"(?![a-z0-9])" if is_short(core) else body)
    return re.compile("|".join(alts), re.IGNORECASE) if alts else None


def _repeat(fn, text):
    out = text
    for _ in range(_DECODE_ROUNDS):
        nxt = fn(out)
        if nxt == out:
            break
        out = nxt
    return out


def _printable(data):
    """Printable stretches (>= _MIN_SEGMENT chars) of bytes read as UTF-8, newline-joined. Control
    characters, line breaks and U+FFFD (an invalid byte) split stretches; space and tab do not."""
    parts = _NONPRINT.split(data.decode("utf-8", errors="replace"))
    return "\n".join(s for s in parts if len(s) >= _MIN_SEGMENT)


def _b64_decode(run):
    s = run.rstrip("=").translate(_B64URL)
    if len(s) % 4 == 1:  # one dangling character cannot encode a byte
        s = s[:-1]
    try:
        return base64.b64decode(s + "=" * (-len(s) % 4), validate=True)
    except (binascii.Error, ValueError):
        return b""


def _b64_view(text):
    out = []
    for m in _B64_RUN.finditer(text):
        run = m.group(0)
        for drop in range(4):
            if len(run) - drop >= 8:
                seg = _printable(_b64_decode(run[drop:]))
                if seg:
                    out.append(seg)
    return "\n".join(out)


def _hex_view(text):
    out = []
    for m in _HEX_RUN.finditer(text):
        run = m.group(0)
        for off in (0, 1):
            part = run[off:]
            part = part[:len(part) - len(part) % 2]
            if len(part) >= 8:
                seg = _printable(bytes.fromhex(part))
                if seg:
                    out.append(seg)
    return "\n".join(out)


def check_views(text):
    """(view name, text) pairs to search. raw is always searched; a decoded view only when the
    decoding changed or produced something (otherwise it would only re-count raw)."""
    url = _repeat(urllib.parse.unquote_plus, text)
    htm = _repeat(html.unescape, text)
    return [("raw", text), ("url", url if url != text else ""), ("html", htm if htm != text else ""),
            ("base64", _b64_view(text)), ("hex", _hex_view(text))]


def check_counts(text, rx, srx):
    """Hits per CHECK_VIEWS name. `separators` is the separator-tolerant matcher over the folded
    raw text; each decoded view adds the raw matcher's hits on it and the separators matcher's
    hits on its fold (so `acme&#8209;drill` hits once html-decoded and folded)."""
    def hits(r, t):
        return sum(1 for _ in r.finditer(t)) if r is not None and t else 0
    counts = dict.fromkeys(CHECK_VIEWS, 0)
    for name, view in check_views(text):
        if name == "raw":
            counts["raw"] = hits(rx, view)
            counts["separators"] = hits(srx, fold(view))
        else:
            counts[name] = hits(rx, view) + hits(srx, fold(view))
    return counts


def _check_label(given, k, rx, srx):
    base = os.path.basename(given)
    if (rx.search(given) if rx is not None else None) or (srx is not None and srx.search(fold(given))):
        return "file #{} (name withheld: it matches a token)".format(k)
    return "file #{} {}".format(k, base)


def check(tokens, files):
    rx, _ = matcher(tokens)
    srx = sep_matcher(tokens)
    total, errors = 0, 0
    for k, given in enumerate(files, 1):
        label = _check_label(given, k, rx, srx)
        try:
            if not os.path.isfile(given):
                raise ValueError("missing or not a regular file")
            with open(given, "rb") as fh:
                data = fh.read(CHECK_MAX_BYTES + 1)
            if len(data) > CHECK_MAX_BYTES:
                raise ValueError("larger than {} bytes: split it; a truncated scan is refused"
                                 .format(CHECK_MAX_BYTES))
        except (OSError, ValueError) as exc:
            # Never echo an OSError's own text: it carries the path, which may bear a token.
            why = exc if isinstance(exc, ValueError) else "unreadable ({})".format(type(exc).__name__)
            print("{}: error: {}".format(label, why), file=sys.stderr)
            errors += 1
            continue
        counts = check_counts(data.decode("utf-8", errors="replace"), rx, srx)
        n = sum(counts.values())
        total += n
        print("{}: {} ({})".format(label, n, ", ".join("{} {}".format(v, counts[v]) for v in CHECK_VIEWS)))
    print("total: {} hit(s) across views{}".format(total, "; {} file error(s)".format(errors) if errors else ""))
    if errors:
        return 2
    return 1 if total else 0


def load_tokens(path, allow_short):
    """read_tokens for main(): an unreadable, empty or refused tokens file is a usage error (exit 2),
    never a traceback and never a false clean. The messages never echo a token."""
    try:
        return read_tokens(path, allow_short=allow_short), 0
    except SystemExit as exc:
        if not isinstance(exc.code, str):
            raise
        print(exc.code, file=sys.stderr)
    except (OSError, UnicodeDecodeError) as exc:
        print("purge_scrub: cannot read the tokens file ({}); refusing".format(type(exc).__name__),
              file=sys.stderr)
    return None, 2


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
    c = sub.add_parser("check", allow_abbrev=False,
                       help="read-only: count token hits, encoded variants included (no --apply)")
    c.add_argument("--tokens", required=True)
    c.add_argument("files", nargs="+")
    for p in (s, h, c) + tuple(sub.choices[n] for n in ("ere", "exprs")):
        p.add_argument("--allow-short", action="store_true",
                       help="accept tokens shorter than {} characters".format(MIN_LEN))
    a = ap.parse_args(argv)
    tokens, rc = load_tokens(a.tokens, a.allow_short)
    if rc:
        return rc
    if a.mode == "check":
        return check(tokens, a.files)
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
