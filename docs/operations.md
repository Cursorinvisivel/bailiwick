# Day-2 Operations

Reference for keeping wired repos and machines healthy after the initial setup. If you are
onboarding a repo for the first time, start with [getting started](getting-started.md); for the
design rationale behind any of this see the [architecture spec](FRAMEWORK.md) and the
[threat model](threat-model.md).

Throughout, `$BAILIWICK` is your local clone of the framework and `/path/to/repo` is any repo
you have wired to it.

---

## 1. Updating a wired repo

After you pull a framework change into `$BAILIWICK`, refresh each wired repo so it picks up new
MCP servers, corrected paths, and reconciled exclude entries:

```bash
$BAILIWICK/scripts/bootstrap.sh --update /path/to/repo
```

The command is **idempotent** — safe to run repeatedly — and its behaviour depends on the repo's
mode:

- **Shadow mode** (the default; zero files in the repo) — refreshes the per-machine allowlist entry
  and the user-scope MCP / instruction wiring. Verify afterward: the repo path is present in
  `~/.bailiwick/allowlist`, and there are still zero framework files in the repo.
- **Seeded mode** (in-repo hidden wiring) — regenerates the **managed** configs to the current
  template: `.mcp.json`, `.vscode/mcp.json`, the Gemini MCP config, and the repo-local Codex MCP
  draft. It also reconciles `.git/info/exclude`. Verify afterward: `CLAUDE.local.md` and the MCP
  configs exist and are listed in `.git/info/exclude` (never the tracked `.gitignore`), and the
  team's own `CLAUDE.md` / `AGENTS.md` are untouched.

### Preserved vs regenerated

| Regenerated to template | Preserved (only path drift corrected) |
|---|---|
| `.mcp.json`, `.vscode/mcp.json`, Gemini + Codex MCP configs | `CLAUDE.local.md` and other hand-edited complements |
| `.git/info/exclude` framework block | The `.bailiwick.local.md` marker, Copilot instructions |

A plain re-run with **no flag** is also safe: it skips everything that already exists.

### `--force` / clobber semantics

Use `--force` only to deliberately overwrite **seeded** complement files back to the template —
this discards your hand edits to `CLAUDE.local.md` and friends. Without it, `--update` never
clobbers a file you have edited; it only corrects a stale Bailiwick path inside it.

Also confirm the machine-level hooks are installed in `~/.claude/settings.json`
(`bootstrap.sh --install-tools` does this once per machine; the installer substitutes the machine's
real Bailiwick path automatically, so satellites need no manual edit).

### Removing the framework (uninstall / un-seed)

`--uninstall` reverses what `bootstrap.sh` wired, at two scopes. It is the counterpart of install and,
like `/purge`, is **strictly bailiwick-scoped** — it only ever removes the framework's *own* entries
(a coexisting framework, your own config, and tracked team files are never touched). Preview any of it
with `--dry-run`.

- **Un-wire the whole machine** — `bootstrap.sh --uninstall` (no target). Removes Bailiwick's hook
  entries from `~/.claude/settings.json` (path-scoped to *this* clone), its Codex/Gemini guardrail +
  MCP blocks and operator layers (marker-delimited), the skill symlinks that resolve into this clone,
  the user-scope Claude MCP servers, and the shadow allowlist. Leaves the clone itself, your
  `~/.bailiwick/` data (captures, health, audit log), and the `go`-installed MCP binaries.
- **Clean one seeded repo** — `bootstrap.sh --uninstall <repo>`. For a repo wired **without** shadow
  mode, this removes the seeded complement/MCP files it wrote (`CLAUDE.local.md`, `.bailiwick.local.md`,
  `.mcp.json`, `.vscode/mcp.json`, `.codex/config.toml`, `.gemini/settings.json`, the Copilot
  instructions), strips **only the framework's own block** from `.git/info/exclude` (your own exclude
  rules are preserved), and drops the repo's line from the shadow allowlist. It removes a seeded file
  only when it is **untracked and carries this clone's path**, so a tracked team file — or an untracked
  file that isn't ours — is left alone. `--with-standards` baselines (tracked, shared) are never removed.
  - **Captures are preserved by default.** If `.bailiwick-outputs/` holds uncurated captures, they are
    left in place with a warning — run `/curate` first, or pass `--purge-captures` to delete
    `.bailiwick-outputs/` outright (irreversible).

Windows PowerShell has parity: `bootstrap.ps1 -Uninstall`, `bootstrap.ps1 -Uninstall <repo> [-PurgeCaptures] [-DryRun]`.

---

## 2. Multi-machine sync

The framework is cloned on every machine you work from. Each clone curates **locally** — raw captures
never leave the machine. What flows between machines is only the **curated, human-approved knowledge
commits**.

### Roles — `.bailiwick-sync.json`

Copy `.bailiwick-sync.example.json` → `.bailiwick-sync.json` (gitignored) on each machine and set its role:

```json
{ "role": "satellite", "machine": "laptop-01" }
```

- **central** — your primary machine. Owns `.telemetry.json`; an approved `/curate` pushes commits
  straight to `origin/main`.
- **satellite** — every other machine (the default when the file is absent). Skips the telemetry
  step entirely; `/curate` parks its commits on `sync/<machine>` and opens a PR to `main`.

### Inbound — automatic

The SessionStart hook fast-forwards the Bailiwick clone from `origin/main` (throttled ~30 min, only
on a clean `main`, non-fatal when offline). On a `sync/<machine>` branch it prints a
"N commits behind" note instead of auto-merging.

### Outbound — after an approved `/curate`

`/curate` runs `hooks/sync_knowledge.sh` (you can also run it directly):

- **central** → `git push origin HEAD:main`.
- **satellite** → moves the new commits onto `sync/<machine>`, pushes `--force-with-lease`, and
  opens/refreshes a PR to `main`; local `main` stays a clean mirror of `origin/main`. You merge the
  PR on the central side, and central seeds telemetry rows for the new files on its next `/curate`
  reconcile.

### Why branch + PR (not direct push)

Several machines pushing to `main` collide on append-heavy files (`.telemetry.json`, `INDEX.md`).
Per-machine branches plus one central merge keep a single integration authority and one place to
resolve conflicts; central-owned telemetry removes its conflict class entirely.

### Prerequisites

- Each satellite needs SSH push access to the Bailiwick repo, and `gh` authenticated for PR creation
  (without `gh` the branch still pushes — open the PR manually).
- Confirm that pushing client-*derived* (sanitised) knowledge to the shared repo is acceptable for
  the engagement before enabling a client machine.

---

## 3. Encrypted dirty-zone backup (optional)

**Why.** The dirty zone (`.bailiwick-outputs/`) is local and gitignored, so **un-curated** captures are
lost if a disk fails before you run `/curate`. This feature keeps a durable, off-machine copy
without exposing raw transcripts.

**How.** The Stop/SessionEnd hooks `gpg`-encrypt new captures and push **ciphertext only** to a
per-machine branch of a **dedicated private repo**. The gpg **private key never leaves the machine**
that runs `/curate`, which decrypts blobs into `.bailiwick-inbox/raw/`, promotes the relevant bits to the
clean zone, and purges the blob. Because the remote only ever holds ciphertext, the post-curate
purge is hygiene — not a history rewrite you have to trust.

Delivery is **best-effort / fail-open** with local-first durability: the raw transcript is always on
local disk, ciphertext is committed to a local mirror before the network push, and an unpushed
commit rides along on the next successful push — a failed push lags only the *remote* copy, it never
loses the capture. `/metrics` surfaces per-machine push drift (including unpushed-commit count) and
SessionStart nags on recent errors.

Enable it in `.bailiwick-sync.json`:

```json
"capture_backup": {
  "enabled": true,
  "confidentiality_ack": true,
  "repo": "git@github.com:you/bailiwick-holding.git",
  "gpg_recipients": ["<fingerprint>"],
  "branch": "capture/<machine>",
  "throttle_minutes": 5
}
```

- **`confidentiality_ack` gate** — the backup refuses to run unless this is `true`. Setting it
  asserts that your engagement terms permit backing up data that may include client material.
- **Dedicated PRIVATE repo** — not the framework repo, not a client repo. The per-machine branch
  (`capture/<machine>`) means machines never conflict.
- **Key distribution** — every backup machine imports the recipient *public* key (to encrypt); the
  *private* key lives only on the curating machine (to decrypt).

> **Key-recovery warning.** The captures are recoverable **only** with the gpg private key. Keep an
> offline copy of that key. Lose it and the encrypted backups are permanently unreadable — there is
> no recovery path.

Rationale, delivery semantics, and the confidentiality assumptions are covered in the
[threat model](threat-model.md); operational detail lives in
`$BAILIWICK/hooks/README.md → Encrypted dirty-zone backup`.

---

## 4. Federated memory (optional)

The framework can **consult** read-only external knowledge — a company or central KB, another
team's library — during a task, and **ingest** chosen items into your own library under the
`/curate` gate. It only ever pulls inward: external sources are never written to, and your KB never
flows outward.

### Register a source — `.bailiwick-sources.json`

Copy `.bailiwick-sources.example.json` → `.bailiwick-sources.json` (gitignored, per machine) and enable a
source:

```json
{ "sources": [
  { "id": "company-kb", "enabled": true, "kind": "filesystem",
    "location": "/abs/path/to/company/knowledge-root", "index": "INDEX.md",
    "scope": "external:globex", "trust": "reference", "mode": "consult+ingest" }
] }
```

Only `kind: filesystem` (a local read-only path or mounted clone) is implemented today; `git`,
`mcp`, and `http` are reserved. An empty or all-disabled list means federation is inactive.

### How it works

- **Access** — `bootstrap.sh --update /path/to/repo` adds each enabled source's `location` as an
  extra MCP filesystem root, so the agent can read it.
- **Read-only is policy, not transport.** The MCP filesystem server is read-write on **every** root.
  Read-only access to a federated source is enforced by the Federation Agent's rules
  (`agents/federation.md`), **not** by the server — so never point a source at a
  location you cannot afford to have written.
- **Consult** — after the local Memory query, the Federation Agent reads each source's index, loads
  a small number of external content files, and tags every external fact `[external:<id>]`. Conflicts
  resolve by the source-authority precedence (FRAMEWORK.md §11) — external/local reference never
  overrides project decisions or authoritative docs.
- **Ingest** — `/curate` can pull a chosen external item into your library, abstracted, with a
  `source:` line, a `## Provenance` block, and `scope: external:<id>`. Human-gated; never automatic.

---

## 5. Manual wiring (reference — what bootstrap does by hand)

You never need this if you use `bootstrap.sh`, but it documents exactly what seeded mode writes, for
anyone who wants to understand or customise the wiring. Two rules apply to everything below:

- **Never put framework entries in a tracked `.gitignore`.** Use the repo's untracked
  `.git/info/exclude`. A `.gitignore` entry is shared with everyone who clones — listing the wiring
  there already exposes the framework's existence.
- **The GitHub token is resolved lazily.** On a workstation with `gh`, the `github` MCP server
  resolves the token at spawn time from gh's keychain — it never lands in a dotfile or the
  environment.

### `.mcp.json` (Claude Code) and `.vscode/mcp.json` (VS Code)

Both serve two filesystem roots — the repo (`$PWD`) and `$BAILIWICK` — plus fetch, github, and
terraform servers:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "$PWD", "$BAILIWICK"]
    },
    "fetch":  { "command": "uvx", "args": ["mcp-server-fetch"] },
    "github": {
      "command": "sh",
      "args": ["-c", "GITHUB_PERSONAL_ACCESS_TOKEN=$(gh auth token --hostname github.com --user <you>) exec github-mcp-server stdio"]
    },
    "terraform": { "command": "terraform-mcp-server", "args": ["stdio"] }
  }
}
```

The `--user <you>` pin matters on a company-managed laptop: gh's *active* account is often a
company identity that cannot see your personal repos, so pin the account that owns the framework.
`bootstrap.sh` derives this automatically and falls back to a `${GITHUB_TOKEN}` env-var form when no
logged-in gh account can reach the repo.

### Hidden complements (one per tool)

Each tool auto-loads its complement **alongside** — never replacing — the team's standard file, and
loads it even when gitignored (all four discover instruction files by filesystem):

| Tool | Complement (hidden) | Template |
|---|---|---|
| Claude Code | `CLAUDE.local.md` (merges after `CLAUDE.md`) | `project-claude-md-template.md` |
| Codex / Gemini | `.bailiwick.local.md` marker (read via global `~/.codex/AGENTS.md` / `~/.gemini/GEMINI.md` layer) | `project-agents-md-template.md` |
| Copilot (local VS Code) | `.github/instructions/bailiwick.instructions.md` (`applyTo:"**"`) | `copilot-bailiwick-instructions-template.md` |

Templates live under `$BAILIWICK/knowledge/templates/`. Codex and Gemini never use a
same-directory override (which would shadow the team's `AGENTS.md` / `GEMINI.md`); their guidance
lives in the global layer that conditionally reads the untracked marker.

### `.git/info/exclude` entries

Add the wiring and the capture staging to the repo's untracked exclude file — exactly as
`bootstrap.sh` does:

```
# bailiwick framework wiring (local only)
.vscode/mcp.json
.mcp.json
.codex/config.toml
.gemini/settings.json
CLAUDE.local.md
.bailiwick.local.md
.github/instructions/bailiwick.instructions.md
.bailiwick-outputs/
```

Never list the team's own `CLAUDE.md` / `AGENTS.md` / `copilot-instructions.md` here — the framework
does not touch them. For a shared-team setup that *wants* the framework tracked, bootstrap with
`--visible` instead.
