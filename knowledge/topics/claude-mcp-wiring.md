---
id: claude-mcp-wiring
type: topic
tags: [claude-code, codex, mcp, tooling, bootstrap, capture, hooks, skills]
confidence: low
last_validated: 2026-07-01
supersedes: []
scope: generic
---

# Topic: Claude Code MCP Wiring in Multi-Tool Repos

> Maintained by Memory Agent. Last updated: 2026-07-01
> Telemetry (load_count, useful_count, source_sessions, open_contradictions) lives in knowledge/.telemetry.json

## Core Concepts
- VS Code MCP and Claude Code MCP are separate config surfaces.
- VS Code uses `.vscode/mcp.json`.
- Claude Code uses repo `.mcp.json` and/or user-scope MCP registration.
- Capture hooks are separate from MCP; hooks control transcript staging, MCP controls file/tool reachability.
- Enforcement must live in **hooks** (harness-executed), not in CLAUDE.md/prompts (model-discretionary). MCP provides **access**, not **action** — the model still chooses to read; only a hook fires by itself.
- A `SessionStart` hook's **stdout is injected into the session context** — the reliable channel for delivering the framework directive and the knowledge INDEX every session.

## Patterns in Use
- Keep dual config when using both tools:
  - `.vscode/mcp.json` for VS Code integration.
  - `.mcp.json` for Claude Code in-repo portability.
- Install hooks once globally from the hooks template into user settings; rely on self-gating in wired repos.
- Self-gating guard: global user-level hooks stay inert unless a repo marker references `$BAILIWICK` — checked across the hidden complements (`CLAUDE.local.md`, `.bailiwick.local.md`, `.github/instructions/bailiwick.instructions.md`). Global install, zero per-repo setup, no leakage into unrelated repos; the team's shared files needn't carry the marker.
- Capture fires only on substantive sessions (file mutations or ≥3 tool calls); harness-run, so it cannot be forgotten.
- Terraform MCP runs Docker-free: `terraform-mcp-server stdio` (Go binary via `go install`, needs `golang-go`), with Docker as an optional fallback — avoids requiring nested virtualization on locked-down/client machines.
- Hide framework wiring from a cloned repo via `.git/info/exclude` (local, untracked), not the tracked `.gitignore` — keeps the framework invisible to colleagues/clients.
- Keep `.bailiwick-outputs/` ignored in project git history.

## Multi-tool instruction layering
- All three tools discover instruction files by **filesystem, regardless of git tracking** — so a
  gitignored complement still loads. This is what lets framework guidance ride hidden alongside a
  team's tracked file.
- **Claude Code:** loads `CLAUDE.md` then `CLAUDE.local.md` (auto-discovered, gitignored, loads after
  and overrides); user-global `~/.claude/CLAUDE.md` applies to all repos; `@path` imports (≤4 hops).
- **Copilot (VS Code):** `.github/copilot-instructions.md` (single) + `.github/instructions/*.instructions.md`
  (multiple, `applyTo` glob — `applyTo:"**"` = always) + user-profile instructions (all repos).
  Precedence personal > repo > org; all matching files concatenate.
- **Codex:** loads the global `~/.codex/AGENTS.md` layer and the repo's `AGENTS.md`. Do not use a
  a repo-root instruction file for framework wiring: Codex treats it as higher priority than
  `AGENTS.md` in that directory, so it can shadow the team's actual instructions. The working pattern
  is a global `~/.codex/AGENTS.md` layer that conditionally tells Codex to read an untracked
  `.bailiwick.local.md` marker; the repo `AGENTS.md` remains authoritative.
- **Complement pattern:** keep the team's shared standard file untouched; put framework guidance in a
  hidden complement or global conditional layer the tool can reach — `CLAUDE.local.md` for Claude
  Code, `.github/instructions/bailiwick.instructions.md` (`applyTo:"**"`) for local Copilot, and
  global conditional layers (`~/.codex/AGENTS.md`, `~/.gemini/GEMINI.md`) that read
  `.bailiwick.local.md` for Codex/Gemini. Verify once locally (Copilot Chat → Diagnostics; Codex
  assembled context).

## GitHub MCP Authentication
- GitHub's official `github-mcp-server` (a local Go binary run over stdio, installed via
  `go install`) authenticates over the **HTTPS API**
  with a PAT/OAuth token (`GITHUB_PERSONAL_ACCESS_TOKEN`). This is unrelated to an SSH host
  alias (e.g. `github-personal` in `~/.ssh/config`), which only provides SSH **key** auth for
  git operations and yields no API token — two different credential types.
- Two token sources:
  - `${GITHUB_TOKEN}` env var — works everywhere (CI, token-only), but leaves a long-lived
    token in the exported environment.
  - **gh CLI keychain, resolved lazily at spawn** (preferred on workstations): wrap the server
    `"command": "sh", "args": ["-c", "GITHUB_PERSONAL_ACCESS_TOKEN=$(gh auth token --hostname <host> --user <you>) exec github-mcp-server stdio"]`.
    The token never lands in a dotfile or the environment — only in the server process.
- **Pin the account with `--user`** (gh ≥ 2.40). On a company-managed laptop gh's *active*
  account is usually the company identity (or a GHE host) that cannot see personal repos;
  pinning the account that owns the framework survives `gh auth switch` back to company.
- When `.bailiwick-sync.json` declares `github_account` (and optionally a host), prefer that account.
  Otherwise check `.bailiwick-sync.json.github_account_map[owner]`. If neither is set, fall back to the
  access probe below. If multiple gh accounts can read the repo, defaulting to the active account is
  ambiguous; warn and prefer an explicit `github_account`/`github_account_map` entry.
- **Resolve which account by access test, not name-match**: derive `OWNER/REPO` from the
  Bailiwick's own git remote (authoritative), then for each gh account run `gh api repos/OWNER/REPO`
  with its token and pick the first that succeeds. The owner may be an *org* whose login differs
  from the personal gh handle, so name-matching fails.
- `bootstrap.sh` / `bootstrap.ps1` do this automatically (derive owner → probe gh accounts →
  write the pinned wrapper; fall back to `${GITHUB_TOKEN}` when no account can reach the repo).
  `--no-gh-auth` / `-NoGhAuth` skips the probe (no network call) for offline / CI runs.

## Codex MCP and Skills
- `codex-cli 0.142.4` loads active MCP servers from user-scope `~/.codex/config.toml`. In current
  validation, repo-local `.codex/config.toml` was not loaded as active MCP config even after the
  project was trusted. Treat `.codex/config.toml` generated by `bootstrap.sh --with-agents` as a
  hidden draft/reference, not the working injection path.
- The working Codex MCP path is user-scope shadow wiring: `bootstrap.sh --shadow --with-agents`
  writes `bailiwick-*` MCP servers into `~/.codex/config.toml`.
- Codex skills are supported from `~/.codex/skills/`. The framework installs thin `$bailiwick-curate` and
  `$bailiwick-enrich` wrappers from `codex-skills/`; each wrapper reads the canonical Claude Code skill
  implementation under `skills/*/SKILL.md` before acting. This keeps Claude Code and
  Codex behavior aligned without copy-pasting prompts into each session.

## Token Security (threat model)
- You **cannot hash** an API token (one-way; the server needs it in plaintext) — a "hashed
  token file" really means encrypted-at-rest.
- Encryption-at-rest does **not** protect against an IT-admin / root adversary who owns the
  decryption-key path (keychain, `/proc/<pid>/environ`, process memory). On a machine you don't
  fully control, assume any local secret is readable.
- Real mitigation = **fine-grained, short-expiry PAT** with minimal scopes — bounds blast radius
  regardless of storage. Lazy keychain resolution additionally keeps the token out of
  dotfiles/history for the everyday (non-root) adversary.

## Known Pitfalls
- Assuming `.vscode/mcp.json` is sufficient for Claude Code causes partial wiring.
- Filesystem root typos in MCP config silently break framework reachability.
- Fixing MCP without installing hooks still leaves capture pipeline inactive.
- A hard terminal kill can't be caught by `SessionEnd`; rely on progressive capture during the session, not only at the end.
- Append-heavy shared JSON (`.telemetry.json`, `INDEX.md`) conflicts at the tail when two machines write; resolve with single-writer / central ownership, not parallel appends.
- Feeding the github MCP server gh's *active-account* token on a multi-account machine silently
  authenticates as the wrong identity → 404 on personal repos. Pin with `gh auth token --user`, and
  set `.bailiwick-sync.json.github_account` or `.bailiwick-sync.json.github_account_map[owner]` when more than
  one gh account can read the framework repo.
- gpg backup: **encrypt** uses the recipient public key (no passphrase), but **decrypt** needs the
  private key + passphrase — so never `--batch --no-tty` the decrypt/pull path or it fails silently
  on a passphrase-protected key (encrypt/push can stay `--batch`).
- gpg decrypt **"the key is present but it still fails"** — the key being on the machine is necessary
  but not sufficient; decrypt must **unlock** it via `gpg-agent` → **pinentry**, which needs somewhere
  to prompt. When `/curate` (or any hook/agent-run command) decrypts, it runs in a shell with **no
  TTY** and `GPG_TTY` unset, and the default **`pinentry-curses` is TTY-only** (it ignores `$DISPLAY`),
  so the prompt has nowhere to render → decrypt fails while `gpg --list-keys` still works (listing
  public keys never unlocks anything). Fixes, best→fallback:
  - **GUI pinentry** (`pinentry-gnome3`/gtk/qt) set in `~/.gnupg/gpg-agent.conf` — gpg-agent spawns it
    as its own window, so it can prompt even from a no-TTY agent shell that carries `$DISPLAY`
    (e.g. WSLg). Lets agent-run `/curate` decrypt directly. `gpgconf --kill gpg-agent` after editing.
  - **Run in a real terminal** with `export GPG_TTY=$(tty)` (curses pinentry then has a TTY).
  - **Prime the agent**: unlock once in a terminal; `gpg-agent` caches the key (shared per-user), so
    later no-TTY decrypts succeed within the cache TTL. Bump `default-cache-ttl`/`max-cache-ttl`.
  `capture_backup.sh pull` exports `GPG_TTY` itself and prints a clear preflight when no TTY/display/cache exists.
- **A newly-linked global skill doesn't appear in an already-open session.** Claude Code enumerates
  `~/.claude/skills/` at **SessionStart**. `bootstrap.sh --install-tools` symlinks each skill dir under
  `skills/` into `~/.claude/skills/`, but only when missing (`[ ! -e "$_link" ]`), so a
  brand-new skill (e.g. `enrich`) is linked on the next `--install-tools` run — then the open session
  still won't list it until **`/clear`** (which re-runs SessionStart and re-enumerates). A VS Code
  **window reload reattaches the same session and does NOT re-enumerate**. Skills are global, not
  per-project — there is no `.claude/skills/` in the target repo.
- **`.git/info/exclude` (and `.gitignore`) only affect *untracked* files** — neither can hide a file
  that is already tracked/committed. The framework's hidden-wiring trick works only because the
  complements (`CLAUDE.local.md`, `.bailiwick.local.md`, the Copilot instruction file) are
  untracked. A `bootstrap.sh --clobber` run that overwrites a **tracked** team baseline
  (`CLAUDE.md`/`AGENTS.md`/`.github/copilot-instructions.md`) therefore shows as a tracked
  modification in `git status` regardless of any exclude rule — recover the original via
  `git checkout -- <file>`.

## Open Questions / To Validate
- Whether standard project bootstrap should enforce `.mcp.json` by default in all templates.
- Whether user-scope MCP registration should be preferred over repo `.mcp.json` for teams.

## References
- `skills/curate/SKILL.md`
- `hooks/README.md`
- `README.md`

## Related
- [Agent CLI hook contracts](agent-cli-hook-contracts.md)
- [PowerShell UTF-8 BOM parsing](powershell-utf8-bom-parsing.md)
- [LLM context & token optimization](llm-context-token-optimization.md)
