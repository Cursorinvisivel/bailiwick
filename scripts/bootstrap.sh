#!/usr/bin/env bash
# bailiwick project bootstrap (bash).
#
# Wire a repository to the framework. DEFAULT = SHADOW MODE (FRAMEWORK.md §7.1): zero-footprint,
# personal — NO files are written into the repo; it is opted in via ~/.bailiwick/allowlist and
# global user-scope MCP. With --seeded, the wiring is written INTO the repo instead — MCP configs
# (Claude Code + VS Code), framework guidance as HIDDEN COMPLEMENT files (CLAUDE.local.md, optional
# .bailiwick.local.md Codex marker / Copilot instructions), and the capture-staging dir. The
# team's own CLAUDE.md / AGENTS.md / copilot-instructions.md are NEVER touched or shadowed — the
# complements load alongside them. Seeded wiring is kept HIDDEN via .git/info/exclude, so it never
# appears in the tracked .gitignore and is never shared with colleagues or clients who clone the
# repo. .bailiwick-outputs/ (unsanitised captures) is always kept local. --with-standards seeds the
# TRACKED team baselines and works in BOTH modes (it is the intentional shared path).
#
# Works for a fresh repo (--init, implies --seeded) or an existing clone. Point it at any path.
set -euo pipefail

BAILIWICK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
CANON_PATH="/path/to/bailiwick"   # path baked into committed templates

usage() {
  cat <<USAGE
bailiwick project bootstrap — wire a repo to the framework, invisible to the shared repo.

Usage: bootstrap.sh [options] <target-repo-path>
       bootstrap.sh --install-tools            (global-only: no target repo needed)

Modes (SHADOW is the DEFAULT):
  (no mode flag)   SHADOW MODE (FRAMEWORK.md §7.1): zero-footprint; personal. Activates the
                   framework for <repo> WITHOUT writing ANY files into it. Adds the repo root to
                   ~/.bailiwick/allowlist and registers global user-scope MCP (Claude Code);
                   captures stage centrally under ~/.bailiwick/captures/. Ideal for a client
                   clone you must leave untouched. With --with-agents / --with-gemini it ALSO
                   injects global Codex / Gemini MCP (~/.codex/config.toml, ~/.gemini/settings.json;
                   bailiwick-* names, idempotent). --with-standards still seeds the TRACKED team
                   baselines (see below) — that is the deliberate shared path; other seeding /
                   exclude flags are ignored. Undo: delete the repo's line from the allowlist.
  --shadow         Explicit alias for the default shadow mode (kept for compatibility; no-op).
  --seeded         In-repo hidden variant: write the wiring INTO the repo (MCP configs, complement
                   files, capture staging), excluded via .git/info/exclude — never the tracked
                   .gitignore. Implied by --visible and --init (they write repo files by design).

Options:
  --init           Create the target dir and 'git init' if it is not a repo. Implies --seeded.
  --with-agents    Also seed .bailiwick.local.md (Codex private marker — read via the global
                   ~/.codex/AGENTS.md layer; the team's own AGENTS.md is never shadowed).
  --with-copilot   Also create .github/instructions/bailiwick.instructions.md (Copilot complement,
                   applyTo:"**" — merges with any team .github/copilot-instructions.md).
  --with-gemini    Also generate .gemini/settings.json (Gemini MCP + advisory excludeTools) and seed
                   the shared .bailiwick.local.md marker. Gemini reads the framework via the global
                   ~/.gemini/GEMINI.md layer (installed by --install-tools); the team's own GEMINI.md
                   is never shadowed. A team-tracked .gemini/settings.json is left untouched.
  --all-tools      Shorthand for --with-agents --with-copilot --with-gemini.
  --with-standards Also seed agnostic, self-contained BASELINE standard files (CLAUDE.md, and
                   AGENTS.md / .github/copilot-instructions.md per the tool flags) with generic
                   engineering best practices. These are TRACKED (shared with the team), contain no
                   framework references, and are written only when absent (an existing team
                   file is never overwritten). Works in BOTH modes: even in (default) shadow mode
                   these team files ARE written into the repo — intentionally shared, so no hidden
                   complements or exclude entries are added for them. Pair with --init for new
                   shared repos. Paired with --update it instead PATCHES IN PLACE only the
                   'Working intelligence' reuse-rule section of whichever baseline files already
                   exist — a non-destructive way to propagate an updated reuse rule to existing
                   repos without clobbering the rest.
  --update         Framework-update mode. With --seeded: regenerate the MANAGED configs (.mcp.json,
                   .vscode/mcp.json, Codex/Gemini MCP) to the current standard and reconcile
                   .git/info/exclude, while PRESERVING seeded, hand-edited
                   complements (CLAUDE.local.md, .bailiwick.local.md, copilot — only their
                   Bailiwick path is corrected if it drifted). In (default) shadow mode it refreshes
                   the allowlist + global MCP wiring idempotently. Safe to run repeatedly.
  --no-gh-auth     Skip the gh CLI probe (no network call): always write the github MCP
                   server in its \${GITHUB_TOKEN} env-var form. Use for offline / CI runs.
  --install-tools  Install the once-per-machine prerequisites when missing: the
                   terraform-mcp-server and github-mcp-server binaries (via 'go install', needs go), the
                   capture/curation + guardrail hooks (merged into ~/.claude/settings.json),
                   the global Claude skill symlinks (~/.claude/skills/: /curate, /enrich, /learn, /metrics, /investigate, /purge), the
                   Codex skill symlinks (~/.codex/skills/: bailiwick-curate, bailiwick-enrich, bailiwick-learn, bailiwick-investigate, bailiwick-purge), and the global
                   Codex + Gemini operator layers (managed blocks in ~/.codex/AGENTS.md and
                   ~/.gemini/GEMINI.md). Idempotent — no-op for anything already present. Off by
                   default (it touches global state + the network). Run with NO <target-repo-path>
                   for a global-only install — nothing per-repo is written (handy after adding a new
                   skill, or as first-time machine setup for shadow mode).
  --visible        Do NOT hide the framework files (team setup: they get tracked). Implies
                   --seeded. .bailiwick-outputs/ is kept local regardless.
  --force          Overwrite ALL framework complement files, including hand-edited
                   CLAUDE.local.md / .bailiwick.local.md (a repo-tracked file is still never touched).
  --clobber        DESTRUCTIVE reset — only takes effect WITH --force (the two-flag combo is the
                   intentionality gate). Removes the two guards that normally protect the team's
                   own files: (1) repo-TRACKED complement files are overwritten instead of left
                   untouched, and (2) existing --with-standards baseline files (CLAUDE.md /
                   AGENTS.md / copilot-instructions.md) are overwritten instead of preserved.
                   Pair with --with-standards to reset the shared baseline files to the generic
                   standard. Tracked files are recoverable via git; untracked ones are not.
  --dry-run        Preview only: print every global-config and repo-file change that would be made
                   (install or uninstall) and write NOTHING. Combine with any other flags.
  --uninstall      Reverse framework wiring. With NO target: the once-per-machine GLOBAL wiring —
                   Bailiwick's hook entries in ~/.claude/settings.json, its Codex/Gemini guardrail +
                   MCP blocks and operator layers, the skill symlinks, user-scope MCP, and the shadow
                   allowlist. With a TARGET repo ('--uninstall <repo>'): un-seeds THAT repo — removes
                   the seeded complement/MCP files (untracked + this clone's), strips the framework's
                   own .git/info/exclude block, and drops the repo's allowlist line. Strictly
                   bailiwick-scoped: tracked team files, --with-standards baselines, a coexisting
                   framework, and captures are never touched. Your captures/health/audit data and the
                   go-installed MCP binaries are left in place. Preview with --dry-run.
  --purge-captures Only with '--uninstall <repo>': also delete that repo's .bailiwick-outputs/
                   INCLUDING any uncurated captures (default is to preserve + warn). Irreversible.
  -h, --help       Show this help.

Default: SHADOW mode — zero-footprint; personal; nothing is written into the repo. With
--seeded, the wiring is excluded via .git/info/exclude (local only) — nothing about the
framework is written to the tracked .gitignore, so a clone shows no trace of it.
USAGE
}

DO_INIT=0; WITH_AGENTS=0; WITH_COPILOT=0; WITH_GEMINI=0; FORCE=0; CLOBBER=0; VISIBLE=0; UPDATE=0; NO_GH_AUTH=0; INSTALL_TOOLS=0; WITH_STANDARDS=0; SHADOW=0; SEEDED=0; DRY_RUN=0; UNINSTALL=0; PURGE_CAPTURES=0; TARGET_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --purge-captures) PURGE_CAPTURES=1 ;;
    --init) DO_INIT=1 ;;
    --with-agents) WITH_AGENTS=1 ;;
    --with-copilot) WITH_COPILOT=1 ;;
    --with-gemini) WITH_GEMINI=1 ;;
    --all-tools) WITH_AGENTS=1; WITH_COPILOT=1; WITH_GEMINI=1 ;;
    --with-standards) WITH_STANDARDS=1 ;;
    --update) UPDATE=1 ;;
    --no-gh-auth) NO_GH_AUTH=1 ;;
    --install-tools) INSTALL_TOOLS=1 ;;
    --visible) VISIBLE=1 ;;
    --shadow) SHADOW=1 ;;
    --seeded) SEEDED=1 ;;
    --force) FORCE=1 ;;
    --clobber) CLOBBER=1 ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "unknown option: $1" >&2; usage; exit 2 ;;
    *) TARGET_ARG="$1" ;;
  esac
  shift
done

# Mode resolution — SHADOW is the DEFAULT (zero-footprint; personal). --seeded selects the in-repo
# hidden wiring; --visible and --init imply seeded (they write repo files by design). --shadow
# stays accepted as an explicit alias for the default.
if [ "$SHADOW" -eq 1 ] && { [ "$SEEDED" -eq 1 ] || [ "$VISIBLE" -eq 1 ] || [ "$DO_INIT" -eq 1 ]; }; then
  echo "error: --shadow conflicts with --seeded/--visible/--init (those write repo files by design; shadow writes none)" >&2
  exit 2
fi
if [ "$SEEDED" -eq 1 ] || [ "$VISIBLE" -eq 1 ] || [ "$DO_INIT" -eq 1 ]; then
  SEEDED=1; SHADOW=0
else
  SHADOW=1
fi

# --install-tools with NO target = global-only: install/validate the once-per-machine prerequisites
# (hooks, skills, Codex skills, operator layers, terraform-mcp) and skip ALL per-repo wiring. Shadow
# mode makes this global-first setup the norm — no throwaway repo needed just to run --install-tools.
GLOBAL_ONLY=0
if [ "$INSTALL_TOOLS" -eq 1 ] && [ -z "$TARGET_ARG" ]; then GLOBAL_ONLY=1; fi
if [ "$GLOBAL_ONLY" -ne 1 ] && [ "$UNINSTALL" -ne 1 ] && [ -z "$TARGET_ARG" ]; then
  echo "error: target repo path required (or run '--install-tools' with no target for a global-only install, or '--uninstall' to remove the global wiring)" >&2
  usage; exit 2
fi
[ "$GLOBAL_ONLY" -eq 1 ] && echo "• bailiwick : $BAILIWICK_ROOT (global-only install — no target repo)"

# --clobber is the destructive reset; it is inert unless paired with --force (intentionality gate).
if [ "$CLOBBER" -eq 1 ] && [ "$FORCE" -ne 1 ]; then
  echo "error: --clobber requires --force (the two-flag combo is the intentionality gate for a destructive reset)" >&2
  exit 2
fi

# ================================ dry-run + uninstall ===========================================
DRY() { [ "$DRY_RUN" -eq 1 ]; }
plan() { printf '  [dry-run] would %s\n' "$1"; }

# Remove a marker-delimited BEGIN..END block from a text file, in place. Only ever matches
# `bailiwick` markers, so a coexisting framework's blocks are never touched. Best-effort.
rm_block() {  # <file> <begin-substr> <end-substr> <label>
  local file="$1" begin="$2" end="$3" label="$4"
  [ -f "$file" ] && grep -qF "$begin" "$file" 2>/dev/null || return 0
  if DRY; then plan "remove the $label block from $file"; return 0; fi
  if python3 - "$file" "$begin" "$end" <<'PY'; then echo "  removed: $label block from $file"; fi
import re, sys
f, b, e = sys.argv[1], sys.argv[2], sys.argv[3]
t = open(f, encoding="utf-8").read()
open(f, "w", encoding="utf-8").write(
    re.sub(r"\n*" + re.escape(b) + r".*?" + re.escape(e) + r"[^\n]*\n?", "\n", t, count=1, flags=re.DOTALL))
PY
}

rm_claude_hooks() {  # drop only hook entries whose command points into THIS clone (path-scoped)
  local f="$HOME/.claude/settings.json"
  [ -f "$f" ] && grep -qF "$BAILIWICK_ROOT" "$f" 2>/dev/null || return 0
  if DRY; then plan "remove this clone's guardrail + capture hook entries from $f"; return 0; fi
  if python3 - "$f" "$BAILIWICK_ROOT" <<'PY'; then echo "  removed: bailiwick hooks from $f"; fi
import json, sys
f, root = sys.argv[1], sys.argv[2]
try: d = json.load(open(f, encoding="utf-8"))
except Exception: sys.exit(1)
hooks = d.get("hooks")
if not isinstance(hooks, dict): sys.exit(1)
ours = lambda h: isinstance(h, dict) and root in (h.get("command") or "")
for ev, groups in list(hooks.items()):
    if not isinstance(groups, list): continue
    ng = []
    for g in groups:
        kept = [h for h in (g.get("hooks", []) if isinstance(g, dict) else []) if not ours(h)]
        if kept: g["hooks"] = kept; ng.append(g)
    if ng: hooks[ev] = ng
    else: del hooks[ev]
if not hooks: d.pop("hooks", None)
json.dump(d, open(f, "w", encoding="utf-8"), indent=2); open(f, "a").write("\n")
PY
}

rm_gemini_json() {
  local f="${GEMINI_HOME:-$HOME/.gemini}/settings.json"
  [ -f "$f" ] && grep -qF "bailiwick-" "$f" 2>/dev/null || return 0
  if DRY; then plan "remove bailiwick-guardrail hook + bailiwick-* MCP servers from $f"; return 0; fi
  if python3 - "$f" <<'PY'; then echo "  cleaned: bailiwick entries from $f"; fi
import json, sys
f = sys.argv[1]
try: d = json.load(open(f, encoding="utf-8"))
except Exception: sys.exit(1)
if not isinstance(d, dict): sys.exit(1)
srv = d.get("mcpServers")
if isinstance(srv, dict):
    for k in [k for k in srv if k.startswith("bailiwick-")]: del srv[k]
    if not srv: d.pop("mcpServers", None)
hooks = d.get("hooks")
if isinstance(hooks, dict):
    bt = hooks.get("BeforeTool")
    if isinstance(bt, list):
        nb = []
        for g in bt:
            kept = [h for h in (g.get("hooks", []) if isinstance(g, dict) else [])
                    if not (isinstance(h, dict) and h.get("name") == "bailiwick-guardrail")]
            if kept: g["hooks"] = kept; nb.append(g)
        if nb: hooks["BeforeTool"] = nb
        else: hooks.pop("BeforeTool", None)
    if not hooks: d.pop("hooks", None)
json.dump(d, open(f, "w", encoding="utf-8"), indent=2); open(f, "a").write("\n")
PY
}

rm_symlinks() {  # only symlinks that resolve INTO this clone
  local d link tgt
  for d in "$HOME/.claude/skills" "${CODEX_HOME:-$HOME/.codex}/skills"; do
    [ -d "$d" ] || continue
    for link in "$d"/*; do
      [ -L "$link" ] || continue
      tgt="$(readlink -f "$link" 2>/dev/null || readlink "$link" 2>/dev/null || echo '')"
      case "$tgt/" in "$BAILIWICK_ROOT"/*)
        if DRY; then plan "remove skill symlink $link"; else rm -f "$link" && echo "  removed symlink: $link"; fi ;;
      esac
    done
  done
}

rm_claude_mcp() {
  command -v claude >/dev/null 2>&1 || return 0
  local n
  for n in bailiwick-filesystem bailiwick-fetch bailiwick-terraform bailiwick-github; do
    if DRY; then plan "claude mcp remove --scope user $n"
    else claude mcp remove "$n" --scope user >/dev/null 2>&1 && echo "  removed: user MCP $n" || true; fi
  done
}

rm_allowlist() {
  local f="${BAILIWICK_HOME:-$HOME/.bailiwick}/allowlist"
  [ -f "$f" ] || return 0
  if DRY; then plan "remove the shadow allowlist $f (deactivates every shadow repo)"
  else rm -f "$f" && echo "  removed: shadow allowlist $f"; fi
}

uninstall_global() {
  local codex="${CODEX_HOME:-$HOME/.codex}" gem="${GEMINI_HOME:-$HOME/.gemini}"
  echo
  if DRY; then echo "▶ bailiwick --uninstall (DRY RUN — nothing will be changed)"
  else echo "▶ bailiwick --uninstall — removing global wiring (bailiwick-scoped; a coexisting framework is never touched)"; fi
  echo "  clone: $BAILIWICK_ROOT"
  rm_claude_hooks
  rm_claude_mcp
  rm_block "$codex/config.toml" "# BEGIN bailiwick hooks" "# END bailiwick hooks" "Codex guardrail hook"
  rm_block "$codex/config.toml" "# BEGIN bailiwick mcp"   "# END bailiwick mcp"   "Codex MCP"
  rm_block "$codex/AGENTS.md"   "<!-- BEGIN bailiwick"    "<!-- END bailiwick -->" "Codex operator layer"
  rm_block "$gem/GEMINI.md"     "<!-- BEGIN bailiwick"    "<!-- END bailiwick -->" "Gemini operator layer"
  rm_gemini_json
  rm_symlinks
  rm_allowlist
  echo
  echo "  Left intact by design: this clone (delete the directory to remove it fully); your captures,"
  echo "  health shards, and guardrail-audit.log under ${BAILIWICK_HOME:-$HOME/.bailiwick}/ (your data);"
  echo "  the go-installed terraform-mcp-server / github-mcp-server binaries; and any per-repo seeded"
  echo "  files (un-seed a repo with '$0 --uninstall <repo>')."
  DRY && echo "  (dry run — re-run without --dry-run to apply.)"
  return 0
}

# ---- per-repo un-seed (reverse SEEDED wiring in one target repo) -------------------------------
# Safe + bailiwick-scoped: removes a seeded file only when it is UNTRACKED *and* carries this clone's
# path (so a team file, or an untracked file that isn't ours, is never deleted); strips only the
# framework's own .git/info/exclude block (your rules preserved); removes just this repo's allowlist
# line; and PRESERVES uncurated captures (delete them explicitly with --purge-captures).
rm_seeded_file() {  # <repo-abs> <relpath> <fingerprint-or-empty>
  local abs="$1" rel="$2" fp="$3" f="$1/$2"
  [ -e "$f" ] || return 0
  if git -C "$abs" ls-files --error-unmatch "$rel" >/dev/null 2>&1; then
    echo "  keep (tracked by repo — not ours to remove): $rel"; return 0
  fi
  if [ -n "$fp" ] && ! grep -qF "$fp" "$f" 2>/dev/null; then
    echo "  keep (untracked, no bailiwick fingerprint — left as-is): $rel"; return 0
  fi
  if DRY; then plan "remove seeded $rel"; else rm -f "$f" && echo "  removed: $rel"; fi
}

strip_repo_exclude() {  # <repo-abs> — remove only the framework's own lines from .git/info/exclude
  local abs="$1" gitdir excl
  gitdir="$(git -C "$abs" rev-parse --git-dir 2>/dev/null || echo "$abs/.git")"
  case "$gitdir" in /*) : ;; *) gitdir="$abs/$gitdir" ;; esac
  excl="$gitdir/info/exclude"
  [ -f "$excl" ] && grep -qF "bailiwick framework wiring" "$excl" 2>/dev/null || return 0
  if DRY; then plan "strip the framework block from $excl (your own exclude rules preserved)"; return 0; fi
  python3 - "$excl" <<'PY'
import sys
f = sys.argv[1]
mark = "# bailiwick framework wiring (local-only — never shared)"
ours = {".bailiwick-outputs/", ".mcp.json", ".vscode/mcp.json", "CLAUDE.local.md",
        ".bailiwick.local.md", ".codex/config.toml", ".gemini/settings.json",
        ".github/instructions/bailiwick.instructions.md"}
lines = open(f, encoding="utf-8").read().splitlines()
out = [ln for ln in lines if ln.strip() != mark and ln.strip() not in ours]
while out and out[-1].strip() == "":  # drop a trailing blank the block left behind
    out.pop()
open(f, "w", encoding="utf-8").write("\n".join(out) + ("\n" if out else ""))
PY
  echo "  removed: framework block from $excl (your own exclude rules preserved)"
}

rm_allowlist_entry() {  # <repo-abs> — remove just this repo's shadow-allowlist line
  local abs="$1" f="${BAILIWICK_HOME:-$HOME/.bailiwick}/allowlist"
  [ -f "$f" ] && grep -qxF "$abs" "$f" 2>/dev/null || return 0
  if DRY; then plan "remove this repo's allowlist entry ($abs)"; return 0; fi
  python3 - "$f" "$abs" <<'PY'
import sys
f, entry = sys.argv[1], sys.argv[2]
lines = [l for l in open(f, encoding="utf-8").read().splitlines() if l.strip() != entry]
open(f, "w", encoding="utf-8").write("\n".join(lines) + ("\n" if lines else ""))
PY
  echo "  removed: this repo's shadow-allowlist entry"
}

warn_repo_captures() {  # <repo-abs>
  local abs="$1" out="$1/.bailiwick-outputs" n
  [ -d "$out" ] || return 0
  if [ "$PURGE_CAPTURES" -eq 1 ]; then
    if DRY; then plan "delete $out INCLUDING any captures (--purge-captures)"
    else rm -rf "$out" && echo "  removed: .bailiwick-outputs/ (--purge-captures — captures deleted)"; fi
    return 0
  fi
  n="$(find "$out/raw" -type f \( -name '*.jsonl' -o -name '*.md' \) 2>/dev/null | grep -vc '/\.curated/' || true)"
  if [ "${n:-0}" -gt 0 ]; then
    echo "  PRESERVED: .bailiwick-outputs/ holds ~$n uncurated capture file(s) — left in place."
    echo "             Promote them with /curate, or delete via: --uninstall --purge-captures '$abs'"
  else
    echo "  note: .bailiwick-outputs/ left in place (no uncurated captures) — remove by hand if unwanted."
  fi
}

uninstall_repo() {  # <target>
  local repo="$1" abs d
  [ -d "$repo" ] || { echo "error: not a directory: $repo" >&2; return 1; }
  abs="$(cd "$repo" && pwd -P)"
  echo
  if DRY; then echo "▶ bailiwick --uninstall '$abs' (DRY RUN — nothing will be changed)"
  else echo "▶ bailiwick --uninstall '$abs' — removing per-repo seeded wiring"; fi
  echo "  (tracked team files, --with-standards baselines, and captures are preserved)"
  rm_seeded_file "$abs" "CLAUDE.local.md"                               "$BAILIWICK_ROOT"
  rm_seeded_file "$abs" ".bailiwick.local.md"                           ""
  rm_seeded_file "$abs" ".mcp.json"                                     "$BAILIWICK_ROOT"
  rm_seeded_file "$abs" ".vscode/mcp.json"                              "$BAILIWICK_ROOT"
  rm_seeded_file "$abs" ".codex/config.toml"                            "$BAILIWICK_ROOT"
  rm_seeded_file "$abs" ".gemini/settings.json"                         "$BAILIWICK_ROOT"
  rm_seeded_file "$abs" ".github/instructions/bailiwick.instructions.md" ""
  if ! DRY; then  # prune dirs we may have emptied (never forced; ignored if non-empty or absent)
    for d in ".vscode" ".codex" ".github/instructions" ".github"; do rmdir "$abs/$d" 2>/dev/null || true; done
  fi
  strip_repo_exclude "$abs"
  rm_allowlist_entry "$abs"
  warn_repo_captures "$abs"
  echo
  echo "  This only un-wires the repo. The once-per-machine GLOBAL wiring (hooks, operator layers,"
  echo "  skills, user MCP) stays — remove that with '--uninstall' (no target). The clone and your"
  echo "  ~/.bailiwick/ data remain."
  DRY && echo "  (dry run — re-run without --dry-run to apply.)"
  return 0
}

# --uninstall reverses framework wiring and exits. With a target repo it un-seeds THAT repo;
# with no target it reverses the once-per-machine global wiring.
if [ "$UNINSTALL" -eq 1 ]; then
  if [ -n "$TARGET_ARG" ]; then uninstall_repo "$TARGET_ARG"; else uninstall_global; fi
  exit 0
fi

[ "$DRY_RUN" -eq 1 ] && echo "▶ bailiwick --dry-run — previewing changes; nothing will be written."

# ===== per-repo wiring — skipped entirely in global-only mode (matching `fi` before §prerequisites) =====
if [ "$GLOBAL_ONLY" -ne 1 ]; then

if [ ! -d "$TARGET_ARG" ]; then
  if [ "$DO_INIT" -eq 1 ]; then mkdir -p "$TARGET_ARG"; else
    echo "error: '$TARGET_ARG' does not exist (use --init to create it)" >&2; exit 2
  fi
fi
TARGET="$(cd "$TARGET_ARG" && pwd)"
REPO_NAME="$(basename "$TARGET")"

if [ ! -e "$TARGET/.git" ]; then
  if [ "$DO_INIT" -eq 1 ]; then git -C "$TARGET" init -q && echo "• git init: $TARGET"; else
    echo "error: '$TARGET' is not a git repo (use --init to create one)" >&2; exit 2
  fi
fi

echo "• bailiwick : $BAILIWICK_ROOT"
echo "• target  : $TARGET ($REPO_NAME)"
if [ "$CLOBBER" -eq 1 ]; then
  echo "⚠ CLOBBER+FORCE: tracked complement files and existing baseline standards WILL be overwritten."
  echo "  Tracked files are recoverable via 'git checkout -- <file>'; untracked overwrites are not."
fi

# True if a path is already tracked by the target repo. Tracked files are PROJECT-OWNED:
# the hidden-wiring model (.git/info/exclude) cannot hide them, and seeding would clobber
# real project content. So we never touch a tracked file.
is_tracked() { git -C "$TARGET" ls-files --error-unmatch "$1" >/dev/null 2>&1; }

write_managed() {  # $1 rel-path ; content on stdin — generated config, refreshed on --update/--force
  local dest="$TARGET/$1"
  if DRY; then plan "write managed config $1"; cat >/dev/null; return 0; fi
  if [ -e "$dest" ] && [ "$FORCE" -ne 1 ] && [ "$UPDATE" -ne 1 ]; then
    echo "  skip (exists): $1"; cat >/dev/null; return 0
  fi
  local existed=0; [ -e "$dest" ] && existed=1
  mkdir -p "$(dirname "$dest")"; cat > "$dest"
  if [ "$existed" -eq 1 ]; then echo "  updated: $1"; else echo "  wrote: $1"; fi
}

copy_seeded() {  # $1 src-abs ; $2 rel-dest — seeded once, then hand-edited. Never auto-clobbered.
  local dest="$TARGET/$2"
  if DRY; then plan "seed complement file $2"; return 0; fi
  if is_tracked "$2"; then
    if [ "$CLOBBER" -eq 1 ]; then
      # Destructive reset explicitly requested (--clobber --force): overwrite the project-owned
      # file. It stays tracked & visible; recover with 'git checkout -- <file>' if unintended.
      sed -e "s#${CANON_PATH}#${BAILIWICK_ROOT}#g" -e "s#\[Project / Repo Name\]#${REPO_NAME}#g" "$1" > "$dest"
      echo "  CLOBBERED (tracked file overwritten — recover via git): $2"; return 0
    fi
    # Project already owns this file — do NOT seed/overwrite (even with --force) and do NOT
    # pretend to hide it. Framework guidance must be merged in deliberately and is shared.
    echo "  skip (tracked by repo — left untouched; can't be hidden, won't clobber): $2"
    return 0
  fi
  if [ -e "$dest" ]; then
    if [ "$FORCE" -eq 1 ]; then
      sed -e "s#${CANON_PATH}#${BAILIWICK_ROOT}#g" -e "s#\[Project / Repo Name\]#${REPO_NAME}#g" "$1" > "$dest"
      echo "  overwrote: $2"; return 0
    fi
    # --update (or any re-run): preserve edits; only correct a drifted Bailiwick path.
    if [ "$CANON_PATH" != "$BAILIWICK_ROOT" ] && grep -qF "$CANON_PATH" "$dest" 2>/dev/null; then
      sed -i "s#${CANON_PATH}#${BAILIWICK_ROOT}#g" "$dest"; echo "  path-fixed: $2"
    else
      echo "  keep (edited): $2"
    fi
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  sed -e "s#${CANON_PATH}#${BAILIWICK_ROOT}#g" -e "s#\[Project / Repo Name\]#${REPO_NAME}#g" "$1" > "$dest"
  echo "  wrote: $2"
}

copy_standard() {  # $1 src-abs ; $2 rel-dest — agnostic baseline, TRACKED (shared). Preserved unless --clobber --force.
  local dest="$TARGET/$2"
  local existed=0; [ -e "$dest" ] && existed=1
  if [ "$existed" -eq 1 ] && [ "$CLOBBER" -ne 1 ]; then echo "  keep (exists, not overwritten): $2"; return 0; fi
  mkdir -p "$(dirname "$dest")"
  sed -e "s#\[Project / Repo Name\]#${REPO_NAME}#g" "$1" > "$dest"
  if [ "$existed" -eq 1 ]; then echo "  CLOBBERED (baseline reset — recover via git): $2";
  else echo "  wrote (tracked baseline): $2"; fi
}

# Canonical "Working intelligence" reuse block, read live from the template (single source of truth):
# the section header through the line *before* "- **Read before you write.**".
STD_SECTION_HDR="## Working intelligence — before writing anything"
extract_reuse_block() {  # prints the canonical block from $1 (a baseline file)
  awk -v hdr="$STD_SECTION_HDR" '
    $0==hdr{f=1} f && /^- \*\*Read before you write\.\*\*/{exit} f{print}' "$1"
}
refresh_standard_section() {  # $1 rel-dest ; $2 canonical-block-file — patch ONLY the reuse section, in place
  local dest="$TARGET/$1"
  [ -e "$dest" ] || return 0
  if ! grep -qxF "$STD_SECTION_HDR" "$dest" 2>/dev/null; then
    echo "  note: no '$STD_SECTION_HDR' section in $1 — left untouched (hand-edited?)"; return 0; fi
  if ! grep -qE '^- \*\*Read before you write\.\*\*' "$dest" 2>/dev/null; then
    echo "  note: reuse-section end anchor missing in $1 — left untouched"; return 0; fi
  # Idempotency: skip when the target's section already matches the canonical block.
  if [ "$(extract_reuse_block "$dest")" = "$(cat "$2")" ]; then
    echo "  reuse rule already current: $1"; return 0; fi
  local tmp; tmp="$(mktemp)"
  awk -v hdr="$STD_SECTION_HDR" -v blockfile="$2" '
    BEGIN{ while((getline l < blockfile)>0) blk[++n]=l }
    $0==hdr{ inms=1; for(i=1;i<=n;i++) print blk[i]; next }
    inms && /^- \*\*Read before you write\.\*\*/{ inms=0 }
    !inms{ print }
  ' "$dest" > "$tmp" && mv "$tmp" "$dest"
  echo "  refreshed reuse rule: $1 (prior version recoverable via git)"
}

# --- agnostic baseline STANDARD files (TRACKED/shared, no framework refs) — only with --with-standards ---
# Seeded only when absent (an existing team file is never overwritten) and NOT added to .git/info/exclude:
# these are meant to be committed and shared. Runs in BOTH modes — in (default) shadow mode they are
# the ONLY files written into the repo (no hidden complements, no exclude entries for them).
seed_standards() {
  local STD="$BAILIWICK_ROOT/knowledge/templates/agnostic-standards-baseline.md"
  if [ "$UPDATE" -eq 1 ]; then
    # Non-destructive refresh: patch ONLY the reuse-rule section of an EXISTING committed baseline,
    # leaving the rest of the team's hand-edited file intact. Seeds nothing new; touches whichever of
    # the three baseline files already exist. Recover a prior section via git if needed.
    local BLOCKFILE; BLOCKFILE="$(mktemp)"; extract_reuse_block "$STD" > "$BLOCKFILE"
    local f
    for f in CLAUDE.md AGENTS.md .github/copilot-instructions.md; do
      refresh_standard_section "$f" "$BLOCKFILE"
    done
    rm -f "$BLOCKFILE"
  else
    copy_standard "$STD" "CLAUDE.md"
    if [ "$WITH_AGENTS" -eq 1 ];  then copy_standard "$STD" "AGENTS.md"; fi
    if [ "$WITH_COPILOT" -eq 1 ]; then copy_standard "$STD" ".github/copilot-instructions.md"; fi
  fi
}

# --- federation: enabled external read-only roots from the framework registry ---
# These become additional MCP filesystem roots so the Federation Agent can CONSULT them
# (read-only is a policy rule — see agents/federation.md). No-op while none enabled.
ext_roots_arr=()
SRC_REG="$BAILIWICK_ROOT/.bailiwick-sources.json"
if [ -f "$SRC_REG" ] && command -v python3 >/dev/null 2>&1; then
  while IFS= read -r r; do [ -n "$r" ] && ext_roots_arr+=("$r"); done < <(python3 -c '
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: sys.exit(0)
for s in d.get("sources", []):
    if s.get("enabled") and s.get("kind","filesystem")=="filesystem" and s.get("location"):
        print(s["location"])
' "$SRC_REG")
fi
MCP_ROOTS="\"${TARGET}\", \"${BAILIWICK_ROOT}\""
VSC_ROOTS="\"\${workspaceFolder}\", \"${BAILIWICK_ROOT}\""
if [ "${#ext_roots_arr[@]}" -gt 0 ]; then
  for r in "${ext_roots_arr[@]}"; do
    MCP_ROOTS="$MCP_ROOTS, \"$r\""
    VSC_ROOTS="$VSC_ROOTS, \"$r\""
  done
  echo "  federation: ${#ext_roots_arr[@]} external read-only root(s) wired into MCP"
fi

# The github MCP server needs an API token for the account that owns the FRAMEWORK
# (this Bailiwick's own git remote) — NOT necessarily gh's *active* account, which on a
# company-managed laptop is usually the company identity and cannot see your personal
# repos. We derive the owner from the framework remote, find a logged-in gh account that
# can actually reach it, and pin the MCP server to THAT account's token via
# `gh auth token --user`. The token is resolved lazily at spawn (read from gh's keychain
# each launch), so it never lands in a dotfile or the exported environment, and the pin
# survives `gh auth switch` back to the company account for daily work.
# Falls back to the ${GITHUB_TOKEN} env var when gh can't provide a usable token
# (CI / token-only setups, or the personal account simply isn't logged into gh yet).
# Wrapped as a function so BOTH paths use it: the shadow block (global bailiwick-github MCP) and the
# seeded path (per-repo github MCP). Sets globals: GH_USER/GH_HOST/gh_decided/gh_warn.
resolve_gh_account() {
  GH_USER=""; GH_HOST=""; gh_owner_repo=""; gh_real_host=""; gh_alias=""
  bailiwick_remote="$(git -C "$BAILIWICK_ROOT" remote get-url origin 2>/dev/null || true)"
  if [ "$NO_GH_AUTH" -ne 1 ] && [ -n "$bailiwick_remote" ]; then
    _u="${bailiwick_remote%.git}"
    case "$_u" in
      *://*)  _hp="${_u#*://}"; _hp="${_hp##*@}"; gh_alias="${_hp%%/*}"; gh_owner_repo="${_hp#*/}" ;;
      *@*:*)  _rest="${_u#*@}"; gh_alias="${_rest%%:*}"; gh_owner_repo="${_rest#*:}" ;;
    esac
    # An SSH host alias (e.g. github-personal) is not a real hostname — resolve it for the API.
    [ -n "$gh_alias" ] && gh_real_host="$(ssh -G "$gh_alias" 2>/dev/null | awk '/^hostname /{print $2; exit}' || true)"
    case "$gh_real_host" in *.*) : ;; *) gh_real_host="github.com" ;; esac
  fi

  # Account selection (priority): (1) explicit override in $BAILIWICK_ROOT/.bailiwick-sync.json
  # ("github_account" + optional "github_host"); (2) owner->account map ("github_account_map") —
  # the deterministic, machine-readable form of the gitconfig rewrite-rule intent (gitconfig maps an
  # owner to an SSH *alias*, not a gh *login*, so the bridge is declared here); (3) the access probe.
  # The probe collects ALL logged-in accounts that can read the repo: exactly one wins silently;
  # more than one is AMBIGUOUS — it defaults to the active account, warns, and points at
  # github_account_map. Disambiguation only bites on multi-account machines (client laptops / VMs).
  _cfg="$BAILIWICK_ROOT/.bailiwick-sync.json"
  _cfg_get() {  # top-level string value for key $1, or empty
    [ -f "$_cfg" ] || return 0
    if command -v python3 >/dev/null 2>&1; then
      python3 -c 'import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
v=d.get(sys.argv[2]); print(v if isinstance(v,str) else "")' "$_cfg" "$1" 2>/dev/null
    else
      grep -oE "\"$1\"[[:space:]]*:[[:space:]]*\"[^\"]+\"" "$_cfg" 2>/dev/null | head -1 | sed -E 's/.*"([^"]+)"$/\1/'
    fi
  }
  _cfg_map_get() {  # github_account_map[$1] (python only; degrades to the probe without python3)
    [ -f "$_cfg" ] || return 0
    command -v python3 >/dev/null 2>&1 || return 0
    python3 -c 'import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
m=d.get("github_account_map") or {}
v=m.get(sys.argv[2]) if isinstance(m,dict) else None
print(v if isinstance(v,str) else "")' "$_cfg" "$1" 2>/dev/null
  }

  gh_owner="${gh_owner_repo%%/*}"; gh_decided=""; gh_warn=""
  if command -v gh >/dev/null 2>&1 && [ -n "$gh_owner_repo" ]; then
    _ovr_acct="$(_cfg_get github_account)"; _ovr_host="$(_cfg_get github_host)"
    _map_acct="$(_cfg_map_get "$gh_owner")"
    _pick=""; _pick_host="$gh_real_host"
    if [ -n "$_ovr_acct" ]; then
      _pick="$_ovr_acct"; [ -n "$_ovr_host" ] && _pick_host="$_ovr_host"; gh_decided="override"
    elif [ -n "$_map_acct" ]; then
      _pick="$_map_acct"; gh_decided="account-map"
    fi
    if [ -n "$_pick" ]; then
      # Honour the declared choice — it only needs a usable token (no access probe).
      if [ -n "$(gh auth token --hostname "$_pick_host" --user "$_pick" 2>/dev/null || true)" ]; then
        GH_USER="$_pick"; GH_HOST="$_pick_host"
      else
        gh_warn="configured gh account '$_pick' has no token on $_pick_host (run 'gh auth login' for it) — fell back to the access probe"
        gh_decided=""
      fi
    fi
    if [ -z "$GH_USER" ]; then
      # Access probe — collect EVERY account that can read the repo, not just the first.
      # Access test (not name match) — the owner may be an org whose login differs from your handle.
      _cands="$(gh auth status 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="account") print $(i+1)}' || true)"
      _active_tok="$(gh auth token --hostname "$gh_real_host" 2>/dev/null || true)"
      _matches=""; _active_match=""
      for _acct in $_cands; do
        _tok="$(gh auth token --hostname "$gh_real_host" --user "$_acct" 2>/dev/null || true)"
        [ -n "$_tok" ] || continue
        if GH_TOKEN="$_tok" gh api --hostname "$gh_real_host" "repos/$gh_owner_repo" >/dev/null 2>&1; then
          _matches="${_matches:+$_matches }$_acct"
          [ -n "$_active_tok" ] && [ "$_tok" = "$_active_tok" ] && _active_match="$_acct"
        fi
      done
      _n=0; for _m in $_matches; do _n=$((_n+1)); done
      if [ "$_n" -eq 1 ]; then
        GH_USER="$_matches"; GH_HOST="$gh_real_host"; gh_decided="probe"
      elif [ "$_n" -gt 1 ]; then
        GH_USER="${_active_match:-${_matches%% *}}"; GH_HOST="$gh_real_host"; gh_decided="ambiguous"
        gh_warn="multiple gh accounts can read ${gh_owner_repo} (${_matches}) — defaulted to '${GH_USER}' (remote uses SSH profile '${gh_alias:-n/a}'). Pin it deterministically by adding to ${_cfg}: \"github_account_map\": { \"${gh_owner}\": \"<account>\" }"
      fi
    fi
  fi
}

# --- Shadow mode (FRAMEWORK.md §7.1, the DEFAULT): activate globally, write NOTHING into the -----
# repo (except the TRACKED --with-standards baselines, which are the deliberate shared path).
# Bypasses ALL repo-file seeding / MCP-file / .git-exclude logic below.
if [ "$SHADOW" -eq 1 ]; then
  BW_HOME="${BAILIWICK_HOME:-$HOME/.bailiwick}"
  ALLOW="$BW_HOME/allowlist"
  HERE="$(cd "$TARGET" && pwd -P)"
  mkdir -p "$BW_HOME"

  # 1. Allowlist entry (idempotent) — the gate (hooks + tool layers) activates on this.
  if [ ! -f "$ALLOW" ]; then
    printf '# bailiwick shadow allowlist — one absolute repo root per line (# comments).\n# Listed repos activate the framework with NO files written into them (FRAMEWORK.md §7.1).\n' > "$ALLOW"
  fi
  if grep -qxF "$HERE" "$ALLOW" 2>/dev/null; then
    echo "  allowlist: already present — $HERE"
  else
    printf '%s\n' "$HERE" >> "$ALLOW"
    echo "  allowlist: added — $HERE"
  fi

  # 2. Global user-scope MCP for Claude Code (filesystem root = Bailiwick + federation; the working
  #    repo is read natively). Applies to all repos; activation stays gated by the allowlist above.
  SH_ROOTS=("$BAILIWICK_ROOT")
  if [ "${#ext_roots_arr[@]}" -gt 0 ]; then for r in "${ext_roots_arr[@]}"; do SH_ROOTS+=("$r"); done; fi
  SH_ROOTS_JSON=""; for r in "${SH_ROOTS[@]}"; do SH_ROOTS_JSON="$SH_ROOTS_JSON, \"$r\""; done; SH_ROOTS_JSON="${SH_ROOTS_JSON#, }"
  # Account-aware github MCP for the GLOBAL scope: resolve the account that owns the framework
  # (override > account-map > access probe — same rules as the per-repo flow) and build the
  # lazy spawn-time token wrapper. Empty GH_USER (no gh, probe failed, --no-gh-auth) => skipped.
  resolve_gh_account
  GH_SHADOW_SH=""
  if [ -n "$GH_USER" ]; then
    GH_SHADOW_SH="GITHUB_PERSONAL_ACCESS_TOKEN=\$(gh auth token --hostname ${GH_HOST} --user ${GH_USER}) exec github-mcp-server stdio"
    echo "  gh: global bailiwick-github pinned to '${GH_USER}' on ${GH_HOST} (${gh_decided})"
    [ -n "$gh_warn" ] && echo "  ⚠ gh: $gh_warn"
  fi

  if command -v claude >/dev/null 2>&1; then
    sh_mcp() {  # $1=name; shift; command…  — idempotent, non-fatal (never breaks the run)
      local n="$1"; shift
      if DRY; then plan "register user MCP '$n' (claude mcp add --scope user)"; return 0; fi
      if claude mcp list 2>/dev/null | grep -qE "(^|[[:space:]])$n([[:space:]]|:|$)"; then
        echo "  mcp(user): $n already registered"; return 0
      fi
      if claude mcp add --scope user "$n" -- "$@" >/dev/null 2>&1; then
        echo "  mcp(user): registered $n"
      else
        echo "  mcp(user): could not register $n — add manually: claude mcp add --scope user $n -- $*"
      fi
    }
    sh_mcp bailiwick-filesystem npx -y @modelcontextprotocol/server-filesystem "${SH_ROOTS[@]}"
    sh_mcp bailiwick-fetch uvx mcp-server-fetch
    sh_mcp bailiwick-terraform terraform-mcp-server stdio
    if [ -n "$GH_USER" ]; then
      sh_mcp bailiwick-github sh -c "$GH_SHADOW_SH"
    else
      echo "  mcp(user): bailiwick-github not registered (no usable gh account — see gh notes) — add manually if wanted"
    fi
  else
    echo "  ✗ 'claude' CLI not found — register the framework MCP root manually:"
    echo "      claude mcp add --scope user bailiwick-filesystem -- npx -y @modelcontextprotocol/server-filesystem \"$BAILIWICK_ROOT\""
  fi

  # Optional GLOBAL MCP for Codex / Gemini, opted in per tool via --with-agents / --with-gemini.
  # Uses bailiwick-* server names (never collides with your own) and github is omitted (per-repo token).
  if [ "$WITH_GEMINI" -eq 1 ] && command -v python3 >/dev/null 2>&1; then
    GEM="${GEMINI_HOME:-$HOME/.gemini}/settings.json"
    if DRY; then plan "merge bailiwick-* MCP servers into $GEM"; else mkdir -p "$(dirname "$GEM")"
    if python3 - "$GEM" "$SH_ROOTS_JSON" "$GH_SHADOW_SH" <<'PY'
import json, os, sys
dest, frag, gh = sys.argv[1], sys.argv[2], sys.argv[3]
roots = json.loads("[" + frag + "]")
try:
    d = json.load(open(dest)) if os.path.exists(dest) and os.path.getsize(dest) > 0 else {}
except Exception:
    d = {}
srv = d.setdefault("mcpServers", {})
# Drop stale servers from the framework's former name (arch-toolkit -> bailiwick); exact old keys only.
for _k in ("arch-filesystem", "arch-fetch", "arch-terraform", "arch-github"):
    srv.pop(_k, None)
srv["bailiwick-filesystem"] = {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"] + roots}
srv["bailiwick-fetch"] = {"command": "uvx", "args": ["mcp-server-fetch"]}
srv["bailiwick-terraform"] = {"command": "terraform-mcp-server", "args": ["stdio"]}
if gh:
    srv["bailiwick-github"] = {"command": "sh", "args": ["-c", gh]}
json.dump(d, open(dest, "w"), indent=2); open(dest, "a").write("\n")
PY
    then echo "  mcp(gemini): merged bailiwick-* servers into $GEM"; else echo "  mcp(gemini): could not update $GEM — edit by hand"; fi
    fi
  fi
  if [ "$WITH_AGENTS" -eq 1 ]; then
    CODEX="${CODEX_HOME:-$HOME/.codex}/config.toml"
    if DRY; then plan "inject the bailiwick-* MCP block into $CODEX"; else mkdir -p "$(dirname "$CODEX")"
    _tb="$(mktemp)"
    {
      echo "# BEGIN bailiwick mcp (managed — refreshed by bootstrap.sh --with-agents in shadow mode)"
      echo "[mcp_servers.bailiwick-filesystem]"; echo "command = \"npx\""
      printf 'args = ["-y", "@modelcontextprotocol/server-filesystem"%s]\n' "$(for r in "${SH_ROOTS[@]}"; do printf ', "%s"' "$r"; done)"
      echo "[mcp_servers.bailiwick-fetch]"; echo "command = \"uvx\""; echo "args = [\"mcp-server-fetch\"]"
      echo "[mcp_servers.bailiwick-terraform]"; echo "command = \"terraform-mcp-server\""; echo "args = [\"stdio\"]"
      if [ -n "$GH_SHADOW_SH" ]; then
        echo "[mcp_servers.bailiwick-github]"; echo "command = \"sh\""
        printf 'args = ["-c", "%s"]\n' "$(printf '%s' "$GH_SHADOW_SH" | sed 's/"/\\"/g')"
      fi
      echo "# END bailiwick mcp"
    } > "$_tb"
    # Sweep a stale block from the framework's FORMER name (arch-toolkit -> bailiwick); the current
    # marker won't match it, so it would otherwise be orphaned beside the fresh bailiwick-* block.
    if [ -f "$CODEX" ] && grep -qF "# BEGIN arch-toolkit mcp" "$CODEX"; then
      python3 - "$CODEX" <<'PY'
import re, sys
d = sys.argv[1]; t = open(d).read()
t2 = re.sub(r"\n?# BEGIN arch-toolkit mcp.*?# END arch-toolkit mcp\n?", "\n", t, flags=re.S)
if t2 != t: open(d, "w").write(t2)
PY
      echo "  mcp(codex): removed a stale arch-toolkit MCP block from $CODEX (renamed to bailiwick)"
    fi
    if [ -f "$CODEX" ] && grep -qF "# BEGIN bailiwick mcp" "$CODEX"; then
      if python3 - "$CODEX" "$_tb" <<'PY'
import re, sys
dest, blockf = sys.argv[1], sys.argv[2]
block = open(blockf).read().rstrip("\n")
text = open(dest).read()
open(dest, "w").write(re.sub(r"# BEGIN bailiwick mcp.*?# END bailiwick mcp", lambda _: block, text, count=1, flags=re.DOTALL))
PY
      then echo "  mcp(codex): refreshed bailiwick-* block in $CODEX"; else echo "  mcp(codex): could not update $CODEX — edit by hand"; fi
    else
      { [ -s "$CODEX" ] && printf '\n'; cat "$_tb"; printf '\n'; } >> "$CODEX"
      echo "  mcp(codex): added bailiwick-* block to $CODEX"
    fi
    rm -f "$_tb"
    fi
  fi
  [ "$WITH_COPILOT" -eq 1 ] && echo "  mcp(copilot): user-scope MCP is set via VS Code → 'MCP: Open User Configuration' (not scriptable here)"

  # --with-standards works in shadow mode too: the baselines are TRACKED team files, seeded
  # deliberately and shared — so no hidden complements and no exclude entries are added for them.
  if [ "$WITH_STANDARDS" -eq 1 ]; then
    echo "  standards: seeding TRACKED team baselines (--with-standards; shadow adds no hidden wiring)"
    seed_standards
  fi

  if [ "$WITH_STANDARDS" -eq 1 ]; then
    printf '\n✓ Shadow-wired '\''%s'\'' — no hidden wiring written (only the TRACKED --with-standards baselines above).\n' "$REPO_NAME"
  else
    printf '\n✓ Shadow-wired '\''%s'\'' — NO files written into the repo (repo tree untouched).\n' "$REPO_NAME"
  fi
  cat <<SHADOW_DONE
This repo is opted in via the allowlist; activation is otherwise global.
Next:
  • Claude Code : hooks must be installed once globally — run '$0 --install-tools' (global-only,
      no target needed; or merge settings.template.json). SessionStart now activates on the
      allowlist; captures stage centrally under ${BW_HOME}/captures/<repo>/ — the repo stays clean.
  • Codex/Gemini: install/refresh the global operator layers (--install-tools) — they now activate on
      ~/.bailiwick/allowlist (or BAILIWICK_SHADOW=1), no marker needed, and read the framework by
      path natively. Global filesystem/fetch/terraform MCP servers are injected by --with-agents /
      --with-gemini (above), plus account-aware bailiwick-github when a usable gh account resolved
      (override > github_account_map > access probe; skipped with --no-gh-auth).
  • Copilot (VS Code): user-scope MCP via "MCP: Open User Configuration"; user instructions are
      build-dependent (VS Code #304101). See FRAMEWORK.md §7.1.
  • one-off (any tool): 'export BAILIWICK_SHADOW=1' force-activates the current shell.
SHADOW_DONE
  # --install-tools alongside a shadow run: continue to the once-per-machine global install below
  # (the seeded per-repo wiring stays skipped — shadow writes no wiring files into the repo).
  if [ "$INSTALL_TOOLS" -ne 1 ]; then exit 0; fi
  echo "  --install-tools: continuing to the global prerequisites install…"
fi

# ===== seeded-mode wiring — skipped entirely in shadow mode (matching `fi` after exclude pruning) =====
if [ "$SHADOW" -ne 1 ]; then

# --- github MCP auth resolution -------------------------------------------------
# github MCP account resolution — see resolve_gh_account() above the shadow block.
resolve_gh_account

if [ -n "$GH_USER" ]; then
  _gh_sh="GITHUB_PERSONAL_ACCESS_TOKEN=\$(gh auth token --hostname ${GH_HOST} --user ${GH_USER}) exec github-mcp-server stdio"
  GH_BLOCK_MCP="\"command\": \"sh\",
      \"args\": [\"-c\", \"${_gh_sh}\"]"
  GH_BLOCK_VSC="$GH_BLOCK_MCP"
  # Codex config.toml form (TOML). Reuses the same spawn-time gh-auth command.
  GH_BLOCK_TOML="command = \"sh\"
args = [\"-c\", \"${_gh_sh}\"]"
  case "$gh_decided" in
    override)    _via=" via .bailiwick-sync.json github_account" ;;
    account-map) _via=" via .bailiwick-sync.json github_account_map[$gh_owner]" ;;
    ambiguous)   _via=" via access probe (AMBIGUOUS — see warning)" ;;
    *)           _via="" ;;
  esac
  GH_STATUS_MSG="github MCP -> gh account '${GH_USER}' on ${GH_HOST}${_via} (token resolved at spawn; no env var needed)"
else
  GH_BLOCK_MCP="\"command\": \"github-mcp-server\",
      \"args\": [\"stdio\"],
      \"env\": { \"GITHUB_PERSONAL_ACCESS_TOKEN\": \"\${GITHUB_TOKEN}\" }"
  GH_BLOCK_VSC="\"command\": \"github-mcp-server\",
      \"args\": [\"stdio\"],
      \"env\": { \"GITHUB_PERSONAL_ACCESS_TOKEN\": \"\${env:GITHUB_TOKEN}\" }"
  # Codex form maps GITHUB_TOKEN via a spawn shell (robust regardless of Codex env expansion).
  GH_BLOCK_TOML="command = \"sh\"
args = [\"-c\", \"GITHUB_PERSONAL_ACCESS_TOKEN=\${GITHUB_TOKEN} exec github-mcp-server stdio\"]"
  if [ "$NO_GH_AUTH" -eq 1 ]; then
    GH_STATUS_MSG="export GITHUB_TOKEN with a personal PAT (gh probe skipped via --no-gh-auth)"
  elif command -v gh >/dev/null 2>&1 && [ -n "$gh_owner_repo" ]; then
    GH_STATUS_MSG="no logged-in gh account can reach ${gh_owner_repo} on ${gh_real_host} — run 'gh auth login' for that account, or export GITHUB_TOKEN with a personal PAT"
  else
    GH_STATUS_MSG="export GITHUB_TOKEN with a personal PAT (gh CLI not detected, or no Bailiwick remote to derive the account)"
  fi
fi
echo "  $GH_STATUS_MSG"
[ -n "$gh_warn" ] && echo "  ⚠ $gh_warn"

# --- .mcp.json (Claude Code) ---
write_managed ".mcp.json" <<EOF
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", ${MCP_ROOTS}]
    },
    "fetch": {
      "command": "uvx",
      "args": ["mcp-server-fetch"]
    },
    "github": {
      ${GH_BLOCK_MCP}
    },
    "terraform": {
      "command": "terraform-mcp-server",
      "args": ["stdio"]
    }
  }
}
EOF

# --- .vscode/mcp.json (VS Code) ---
write_managed ".vscode/mcp.json" <<EOF
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", ${VSC_ROOTS}]
    },
    "fetch": {
      "command": "uvx",
      "args": ["mcp-server-fetch"]
    },
    "github": {
      ${GH_BLOCK_VSC}
    },
    "terraform": {
      "command": "terraform-mcp-server",
      "args": ["stdio"]
    }
  }
}
EOF

# --- framework guidance as HIDDEN COMPLEMENT files (never the team's shared standard files) ---
# Each tool loads its complement alongside (not replacing) any team CLAUDE.md / AGENTS.md /
# copilot-instructions.md. All are gitignored via .git/info/exclude below, and all still load
# (the tools discover instruction files by filesystem, regardless of git tracking). Per-tool adapter:
#   Claude Code : CLAUDE.local.md  — native personal memory; loads after CLAUDE.md (merges).
#   Codex       : .bailiwick.local.md  — a private MARKER read via the global ~/.codex/AGENTS.md
#                 layer (installed by --install-tools). A repo-root instruction file would suppress
#                 the team's AGENTS.md (Codex loads one file per directory), so a neutral marker is
#                 used instead — it never shadows; the team AGENTS.md stays authoritative.
#   Copilot     : .github/instructions/bailiwick.instructions.md (applyTo:"**") — loads in LOCAL
#                 VS Code only; the GitHub-hosted Copilot cloud agent cannot see untracked files.
copy_seeded "$BAILIWICK_ROOT/knowledge/templates/project-claude-md-template.md" "CLAUDE.local.md"
# On --update, refresh whatever complement/config already exists (detect per tool).
SEED_MARKER=0; GEMINI_GENERATED=0
if [ "$UPDATE" -eq 1 ] && [ -e "$TARGET/.bailiwick.local.md" ]; then SEED_MARKER=1; fi
if [ "$UPDATE" -eq 1 ] && [ -e "$TARGET/.codex/config.toml" ]; then WITH_AGENTS=1; fi
if [ "$UPDATE" -eq 1 ] && [ -e "$TARGET/.gemini/settings.json" ] && ! is_tracked ".gemini/settings.json"; then WITH_GEMINI=1; fi
if [ "$UPDATE" -eq 1 ] && [ -e "$TARGET/.github/instructions/bailiwick.instructions.md" ]; then WITH_COPILOT=1; fi

# Shared private marker — read by BOTH Codex (via ~/.codex/AGENTS.md) and Gemini (via ~/.gemini/GEMINI.md).
if [ "$WITH_AGENTS" -eq 1 ] || [ "$WITH_GEMINI" -eq 1 ] || [ "$SEED_MARKER" -eq 1 ]; then
  copy_seeded "$BAILIWICK_ROOT/knowledge/templates/project-agents-md-template.md" ".bailiwick.local.md"
fi
if [ "$WITH_AGENTS" -eq 1 ]; then
  # Codex MCP lives in config.toml (NOT .mcp.json). Current Codex CLI loads user-scope
  # ~/.codex/config.toml for MCP; this repo-local file is retained as a generated draft/reference
  # until Codex supports project-local config loading in this environment. Shadow mode injects the
  # working user-scope bailiwick-* MCP block into ~/.codex/config.toml.
  write_managed ".codex/config.toml" <<EOF
# bailiwick — Codex MCP servers (repo-local draft/reference). Managed: regenerated on --update/--force.
# Current Codex CLI loads MCP from ~/.codex/config.toml, not this project-local file.
# Use bootstrap.sh --with-agents (shadow mode, the default) for working user-scope Codex MCP injection.

[mcp_servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", ${MCP_ROOTS}]

[mcp_servers.fetch]
command = "uvx"
args = ["mcp-server-fetch"]

[mcp_servers.github]
${GH_BLOCK_TOML}

[mcp_servers.terraform]
command = "terraform-mcp-server"
args = ["stdio"]
EOF
fi
if [ "$WITH_GEMINI" -eq 1 ]; then
  # Gemini MCP lives in .gemini/settings.json (one file for Gemini CLI + Code Assist VS Code agent).
  # Google documents it as committable/shared, so a TEAM-TRACKED settings.json is LEFT UNTOUCHED
  # (skip + warn) — we never clobber it. excludeTools is ADVISORY ONLY: Google calls command-specific
  # shell restriction "simple string matching", "easily bypassed", "not a security mechanism". The
  # real control is NOT enabling geminicodeassist.agentYoloMode (keep the approval dialog).
  if is_tracked ".gemini/settings.json"; then
    echo "  skip (tracked by repo — left untouched; merge framework MCP by hand): .gemini/settings.json"
  else
    write_managed ".gemini/settings.json" <<EOF
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", ${MCP_ROOTS}]
    },
    "fetch": {
      "command": "uvx",
      "args": ["mcp-server-fetch"]
    },
    "github": {
      ${GH_BLOCK_MCP}
    },
    "terraform": {
      "command": "terraform-mcp-server",
      "args": ["stdio"]
    }
  },
  "excludeTools": [
    "run_shell_command(terraform apply)",
    "run_shell_command(terraform destroy)",
    "run_shell_command(terragrunt apply)",
    "run_shell_command(terragrunt destroy)"
  ]
}
EOF
    GEMINI_GENERATED=1
  fi
fi
if [ "$WITH_COPILOT" -eq 1 ]; then
  copy_seeded "$BAILIWICK_ROOT/knowledge/templates/copilot-bailiwick-instructions-template.md" ".github/instructions/bailiwick.instructions.md"
fi

# --- agnostic baseline STANDARD files (TRACKED/shared) — see seed_standards() above. They coexist
# with the hidden complements in seeded mode (and are the only repo writes in shadow mode).
if [ "$WITH_STANDARDS" -eq 1 ]; then
  seed_standards
fi

# --- capture staging ---
if DRY; then plan "create capture staging .bailiwick-outputs/raw/"; else mkdir -p "$TARGET/.bailiwick-outputs/raw"; fi

# --- hide locally via .git/info/exclude (never the tracked .gitignore) ---
GITDIR="$(git -C "$TARGET" rev-parse --git-dir 2>/dev/null || echo .git)"
case "$GITDIR" in /*) : ;; *) GITDIR="$TARGET/$GITDIR" ;; esac
EXCLUDE="$GITDIR/info/exclude"
DRY || { mkdir -p "$(dirname "$EXCLUDE")"; touch "$EXCLUDE"; }
MARK="# bailiwick framework wiring (local-only — never shared)"
add_excl() {
  if DRY; then plan "exclude $1 via .git/info/exclude"; return 0; fi
  if is_tracked "$1"; then
    echo "  note: '$1' is tracked by the repo — left visible (exclude cannot hide a tracked file)"; return 0
  fi
  grep -qxF "$1" "$EXCLUDE" 2>/dev/null || echo "$1" >> "$EXCLUDE"
}
DRY || grep -qF "$MARK" "$EXCLUDE" 2>/dev/null || printf '\n%s\n' "$MARK" >> "$EXCLUDE"
add_excl ".bailiwick-outputs/"
if [ "$VISIBLE" -ne 1 ]; then
  add_excl ".mcp.json"
  add_excl ".vscode/mcp.json"
  add_excl "CLAUDE.local.md"
  if [ "$WITH_AGENTS" -eq 1 ] || [ "$WITH_GEMINI" -eq 1 ]; then add_excl ".bailiwick.local.md"; fi
  if [ "$WITH_AGENTS" -eq 1 ]; then add_excl ".codex/config.toml"; fi
  if [ "$GEMINI_GENERATED" -eq 1 ]; then add_excl ".gemini/settings.json"; fi
  if [ "$WITH_COPILOT" -eq 1 ]; then add_excl ".github/instructions/bailiwick.instructions.md"; fi
  echo "  hidden: framework complement files excluded via .git/info/exclude (team's standard files untouched)"
else
  echo "  visible: framework files left tracked (.bailiwick-outputs/ still local-only)"
fi


fi  # ===== end seeded-mode wiring (shadow mode with --install-tools resumes here) =====

fi  # ===== end per-repo wiring (global-only mode resumes here) =====

# --- validate (and with --install-tools, install) the once-per-machine prerequisites ---
# Under --dry-run, describe what --install-tools would mutate globally, then neutralize it so the
# status block below reports CURRENT state without touching anything.
if [ "$DRY_RUN" -eq 1 ] && [ "$INSTALL_TOOLS" -eq 1 ]; then
  echo
  echo "  [dry-run] --install-tools would, when a piece is missing:"
  echo "    • go install terraform-mcp-server + github-mcp-server (needs 'go')"
  echo "    • merge capture + guardrail hooks into ~/.claude/settings.json (install_hooks.py)"
  echo "    • wire the guardrail into ~/.codex/config.toml + ~/.gemini/settings.json (install_adapter_hooks.py)"
  echo "    • symlink skills into ~/.claude/skills/ and ~/.codex/skills/"
  echo "    • install operator layers into ~/.codex/AGENTS.md + ~/.gemini/GEMINI.md"
  echo "  [dry-run] nothing installed; the status lines below reflect the CURRENT state."
  INSTALL_TOOLS=0
fi
# terraform MCP server is wired into .mcp.json on EVERY run (not just --all-tools).
if ! command -v terraform-mcp-server >/dev/null 2>&1 && [ "$INSTALL_TOOLS" -eq 1 ] && command -v go >/dev/null 2>&1; then
  echo "  --install-tools: installing terraform-mcp-server (go install)…"
  go install github.com/hashicorp/terraform-mcp-server/cmd/terraform-mcp-server@latest 2>&1 | sed 's/^/    /' || true
  hash -r 2>/dev/null || true
fi
if command -v terraform-mcp-server >/dev/null 2>&1; then
  TF_STATUS="✓ terraform-mcp-server on PATH ($(command -v terraform-mcp-server))"
elif command -v go >/dev/null 2>&1; then
  _gobin="$(go env GOPATH 2>/dev/null)/bin"
  if [ -x "$_gobin/terraform-mcp-server" ]; then
    TF_STATUS="✓ terraform-mcp-server installed to $_gobin — add that dir to PATH"
  else
    TF_STATUS="✗ terraform-mcp-server NOT on PATH — run: go install github.com/hashicorp/terraform-mcp-server/cmd/terraform-mcp-server@latest  (or re-run with --install-tools; then add \$(go env GOPATH)/bin to PATH)"
  fi
else
  TF_STATUS="✗ terraform-mcp-server NOT on PATH and 'go' is missing — install golang-go, then re-run with --install-tools (see docs/getting-started.md)"
fi

# github MCP server is GitHub's official local Go binary (stdio), wired the same Docker-free way.
if ! command -v github-mcp-server >/dev/null 2>&1 && [ "$INSTALL_TOOLS" -eq 1 ] && command -v go >/dev/null 2>&1; then
  echo "  --install-tools: installing github-mcp-server (go install)…"
  go install github.com/github/github-mcp-server/cmd/github-mcp-server@latest 2>&1 | sed 's/^/    /' || true
  hash -r 2>/dev/null || true
fi
if command -v github-mcp-server >/dev/null 2>&1; then
  GH_MCP_STATUS="✓ github-mcp-server on PATH ($(command -v github-mcp-server))"
elif command -v go >/dev/null 2>&1; then
  _gobin="$(go env GOPATH 2>/dev/null)/bin"
  if [ -x "$_gobin/github-mcp-server" ]; then
    GH_MCP_STATUS="✓ github-mcp-server installed to $_gobin — add that dir to PATH"
  else
    GH_MCP_STATUS="✗ github-mcp-server NOT on PATH — run: go install github.com/github/github-mcp-server/cmd/github-mcp-server@latest  (or re-run with --install-tools; then add \$(go env GOPATH)/bin to PATH)"
  fi
else
  GH_MCP_STATUS="✗ github-mcp-server NOT on PATH and 'go' is missing — install golang-go, then re-run with --install-tools (see docs/getting-started.md)"
fi

# capture/curation hooks are installed once-globally; detect/merge in ~/.claude/settings.json.
USER_SETTINGS="${HOME}/.claude/settings.json"
HOOK_TMPL="$BAILIWICK_ROOT/hooks/settings.template.json"
hooks_present() { [ -f "$USER_SETTINGS" ] && grep -q "capture_session.py" "$USER_SETTINGS" 2>/dev/null; }
if ! hooks_present && [ "$INSTALL_TOOLS" -eq 1 ] && command -v python3 >/dev/null 2>&1 && [ -f "$HOOK_TMPL" ]; then
  echo "  --install-tools: merging capture/curation hooks into ~/.claude/settings.json…"
  python3 "$BAILIWICK_ROOT/hooks/install_hooks.py" "$USER_SETTINGS" "$HOOK_TMPL" 2>&1 | sed 's/^/    /' || true
fi
# Codex + Gemini guardrail adapters (same engine as the Claude Code guardrail; deny/ask contract
# per tool, self-gating to wired/shadow repos — see hooks/install_adapter_hooks.py).
if [ "$INSTALL_TOOLS" -eq 1 ] && command -v python3 >/dev/null 2>&1; then
  echo "  --install-tools: wiring the guardrail into Codex (PreToolUse) + Gemini (BeforeTool)…"
  python3 "$BAILIWICK_ROOT/hooks/install_adapter_hooks.py" 2>&1 | sed 's/^/    /' || true
fi
if hooks_present; then
  HOOKS_STATUS="✓ capture/curation hooks present in ~/.claude/settings.json"
elif [ -f "$USER_SETTINGS" ]; then
  HOOKS_STATUS="✗ ~/.claude/settings.json exists but has no bailiwick hooks — merge the 'hooks' block from \$BAILIWICK/hooks/settings.template.json (or re-run with --install-tools)"
else
  HOOKS_STATUS="✗ ~/.claude/settings.json not found — install hooks once: merge from \$BAILIWICK/hooks/settings.template.json (or re-run with --install-tools)"
fi

# Skills are GLOBAL (once per machine), like the hooks — user-level symlinks to the framework. Every
# skill directory under skills/ is linked into ~/.claude/skills/ (curate, enrich, …).
SKILLS_DIR="$BAILIWICK_ROOT/skills"
_skill_missing=0; _skill_total=0
for _s in "$SKILLS_DIR"/*/; do
  [ -d "$_s" ] || continue
  _name="$(basename "$_s")"; _link="${HOME}/.claude/skills/${_name}"
  _skill_total=$((_skill_total+1))
  if [ ! -e "$_link" ] && [ "$INSTALL_TOOLS" -eq 1 ]; then
    echo "  --install-tools: linking /${_name} skill globally (~/.claude/skills/${_name})…"
    mkdir -p "$(dirname "$_link")"; ln -s "${_s%/}" "$_link" 2>/dev/null || true
  fi
  [ -e "$_link" ] || _skill_missing=$((_skill_missing+1))
done
if [ "$_skill_missing" -eq 0 ] && [ "$_skill_total" -gt 0 ]; then
  SKILL_STATUS="✓ ${_skill_total} skill(s) linked globally (~/.claude/skills/: curate, enrich, …)"
else
  SKILL_STATUS="✗ ${_skill_missing}/${_skill_total} skills not linked — re-run with --install-tools, or symlink each dir under \$BAILIWICK/skills/ into ~/.claude/skills/"
fi

# Codex skills are thin wrappers around the canonical Claude Code skill procedures. They live in
# the framework and are symlinked into ~/.codex/skills so Codex can discover them without copying.
CODEX_SKILLS_DIR="$BAILIWICK_ROOT/codex-skills"
CODEX_SKILLS_HOME="${CODEX_HOME:-$HOME/.codex}/skills"
_codex_skill_missing=0; _codex_skill_total=0
for _s in "$CODEX_SKILLS_DIR"/*/; do
  [ -d "$_s" ] || continue
  _name="$(basename "$_s")"; _link="${CODEX_SKILLS_HOME}/${_name}"
  _codex_skill_total=$((_codex_skill_total+1))
  if [ ! -e "$_link" ] && [ "$INSTALL_TOOLS" -eq 1 ]; then
    echo "  --install-tools: linking \$${_name} Codex skill globally (${_link})…"
    mkdir -p "$(dirname "$_link")"; ln -s "${_s%/}" "$_link" 2>/dev/null || true
  fi
  [ -e "$_link" ] || _codex_skill_missing=$((_codex_skill_missing+1))
done
if [ "$_codex_skill_total" -eq 0 ]; then
  CODEX_SKILL_STATUS="✗ no Codex skills found in \$BAILIWICK/codex-skills"
elif [ "$_codex_skill_missing" -eq 0 ]; then
  CODEX_SKILL_STATUS="✓ ${_codex_skill_total} Codex skill(s) linked globally (~/.codex/skills/: bailiwick-curate, bailiwick-enrich, …)"
else
  CODEX_SKILL_STATUS="✗ ${_codex_skill_missing}/${_codex_skill_total} Codex skills not linked — re-run with --install-tools, or symlink each dir under \$BAILIWICK/codex-skills/ into ~/.codex/skills/"
fi

# Codex & Gemini private operator layers are GLOBAL (once per machine): a managed block in
# ~/.codex/AGENTS.md and ~/.gemini/GEMINI.md that activates per-repo when a repo carries the untracked
# .bailiwick.local.md marker. Each loads BEFORE the repo's own file (so the team file keeps
# precedence) and never shadows it. One generic installer (install_global_layer.sh) serves both.
GLOBAL_INSTALLER="$BAILIWICK_ROOT/hooks/install_global_layer.sh"
CODEX_AGENTS="${CODEX_HOME:-$HOME/.codex}/AGENTS.md"
GEMINI_AGENTS="${GEMINI_HOME:-$HOME/.gemini}/GEMINI.md"
layer_present() { [ -f "$1" ] && grep -qF "BEGIN bailiwick" "$1" 2>/dev/null; }
if [ "$INSTALL_TOOLS" -eq 1 ] && [ -f "$GLOBAL_INSTALLER" ] && command -v python3 >/dev/null 2>&1; then
  echo "  --install-tools: installing/refreshing the Codex operator layer in ~/.codex/AGENTS.md…"
  bash "$GLOBAL_INSTALLER" "$BAILIWICK_ROOT" "$BAILIWICK_ROOT/hooks/codex-global-agents.tmpl.md" "$CODEX_AGENTS" "codex layer" 2>&1 | sed 's/^/    /' || true
  echo "  --install-tools: installing/refreshing the Gemini operator layer in ~/.gemini/GEMINI.md…"
  bash "$GLOBAL_INSTALLER" "$BAILIWICK_ROOT" "$BAILIWICK_ROOT/hooks/gemini-global.tmpl.md" "$GEMINI_AGENTS" "gemini layer" 2>&1 | sed 's/^/    /' || true
fi
if layer_present "$CODEX_AGENTS"; then
  CODEX_STATUS="✓ Codex operator layer present (~/.codex/AGENTS.md) — activates on .bailiwick.local.md"
else
  CODEX_STATUS="✗ Codex operator layer not installed — re-run with --install-tools. Only needed if you use Codex."
fi
if [ "$WITH_AGENTS" -eq 1 ] && [ "$SHADOW" -ne 1 ]; then
  CODEX_MCP_STATUS="⚠ Codex MCP: .codex/config.toml was generated as a repo-local draft, but current Codex CLI reports MCP from ~/.codex/config.toml only. Run '--with-agents' in shadow mode (the default, without --seeded) to inject working user-scope bailiwick-* MCP."
else
  CODEX_MCP_STATUS=""
fi
if layer_present "$GEMINI_AGENTS"; then
  GEMINI_STATUS="✓ Gemini operator layer present (~/.gemini/GEMINI.md) — activates on .bailiwick.local.md"
else
  GEMINI_STATUS="✗ Gemini operator layer not installed — re-run with --install-tools. Only needed if you use Gemini."
fi

if [ "$GLOBAL_ONLY" -eq 1 ]; then
  printf '\n✓ Global bailiwick prerequisites installed/validated (no repo wired).\n'
  printf 'Next:\n'
  printf '  • %s\n' "$TF_STATUS"
  printf '  • %s\n' "$GH_MCP_STATUS"
  printf '  • %s\n' "$HOOKS_STATUS"
  printf '  • %s\n' "$SKILL_STATUS"
  printf '  • %s\n' "$CODEX_SKILL_STATUS"
  printf '  • %s\n' "$CODEX_STATUS"
  printf '  • %s\n' "$GEMINI_STATUS"
  printf '  • wire a repo:  %s <repo>   (shadow/zero-footprint by default; --seeded for in-repo hidden wiring)\n' "$0"
elif [ "$SHADOW" -eq 1 ]; then
  # Reached only on a shadow run WITH --install-tools (plain shadow runs exit in the shadow block).
  printf '\n✓ Global bailiwick prerequisites installed/validated (%q shadow-wired above — no repo files).\n' "$REPO_NAME"
  printf 'Next:\n'
  printf '  • %s\n' "$TF_STATUS"
  printf '  • %s\n' "$GH_MCP_STATUS"
  printf '  • %s\n' "$HOOKS_STATUS"
  printf '  • %s\n' "$SKILL_STATUS"
  printf '  • %s\n' "$CODEX_SKILL_STATUS"
  printf '  • %s\n' "$CODEX_STATUS"
  printf '  • %s\n' "$GEMINI_STATUS"
else
  printf '\n✓ Bootstrapped %q.\n' "$REPO_NAME"
  printf 'Next:\n'
  printf '  • %s\n' "$GH_STATUS_MSG"
  printf '  • %s\n' "$TF_STATUS"
  printf '  • %s\n' "$GH_MCP_STATUS"
  printf '  • %s\n' "$HOOKS_STATUS"
  printf '  • %s\n' "$SKILL_STATUS"
  printf '  • %s\n' "$CODEX_SKILL_STATUS"
  printf '  • %s\n' "$CODEX_STATUS"
  [ -n "$CODEX_MCP_STATUS" ] && printf '  • %s\n' "$CODEX_MCP_STATUS"
  printf '  • %s\n' "$GEMINI_STATUS"
  printf '  • edit CLAUDE.local.md project-specific sections   (stack, environments, backend, CI/CD)\n'
fi
