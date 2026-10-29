"""MkDocs hooks for the Bailiwick docs site (wired in mkdocs.yml).

docs/ is written to be read on GitHub, so it links freely to files outside docs/ (../README.md,
../hooks/README.md, ../scripts/bootstrap.sh). The site only contains docs/, so those links are
rewritten to their GitHub URL instead of 404ing. The docs themselves are never modified.
"""

import posixpath
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BLOB = "https://github.com/Cursorinvisivel/bailiwick/blob/main/"
TREE = "https://github.com/Cursorinvisivel/bailiwick/tree/main/"

FENCE = re.compile(r"^(```|~~~).*?^\1", re.DOTALL | re.MULTILINE)
INLINE_CODE = re.compile(r"`[^`\n]*`")
LINK = re.compile(r"(\]\()([^)\s]+)(\))")


def _rewrite(target: str, page_dir: str) -> str:
    if target.startswith(("http://", "https://", "mailto:", "#", "/")):
        return target
    path, _, anchor = target.partition("#")
    resolved = posixpath.normpath(posixpath.join("docs", page_dir, path))
    if resolved.startswith("docs/") or resolved.startswith("../"):
        return target
    base = TREE if (REPO_ROOT / resolved).is_dir() else BLOB
    return base + resolved + ("#" + anchor if anchor else "")


def on_page_markdown(markdown, page, config, files):
    if page.is_homepage:
        page.meta.setdefault("template", "home.html")
    # ADR front matter has `status: accepted`; Material would render it as a page-status icon.
    if "status" in page.meta:
        page.meta["adr_status"] = page.meta.pop("status")
    page_dir = posixpath.dirname(page.file.src_uri)

    def fix_links(text: str) -> str:
        return LINK.sub(lambda m: m.group(1) + _rewrite(m.group(2), page_dir) + m.group(3), text)

    # Rewrite only outside code, which holds link-syntax examples.
    out, pos = [], 0
    for block in FENCE.finditer(markdown):
        out.append(_outside_inline_code(markdown[pos:block.start()], fix_links))
        out.append(block.group(0))
        pos = block.end()
    out.append(_outside_inline_code(markdown[pos:], fix_links))
    return "".join(out)


def _outside_inline_code(text, fix):
    out, pos = [], 0
    for code in INLINE_CODE.finditer(text):
        out.append(fix(text[pos:code.start()]))
        out.append(code.group(0))
        pos = code.end()
    out.append(fix(text[pos:]))
    return "".join(out)
