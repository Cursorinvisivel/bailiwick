---
id:            adr-003-shadow-mode
type:          decision
status:        accepted
date:          2026-07-01
authors:       [Francisco Ferrinho]
tags:          [adr, shadow-mode, activation, capture, dirty-zone, multi-tool, privacy, governance]
supersedes:    []
superseded_by:
scope:         generic
---

# ADR-003 — Shadow mode: zero-footprint framework activation with central captures

## Context

Framework activation today is **anchored to an in-repo marker file**. The Claude Code hooks self-gate
on a file physically present in the target repo (`session_start.sh` → `is_bailiwick_repo`: a
`.bailiwick.local.md` / `CLAUDE.local.md` containing `BAILIWICK`); the other three
tools' global operator layers gate on the same marker. So the minimum footprint bootstrap writes is
`CLAUDE.local.md` + `.mcp.json` + `.bailiwick-outputs/`, hidden via `.git/info/exclude`. Hidden ≠ absent —
the files are invisible to colleagues but present on disk in the repo tree.

The goal of this ADR is a **true shadow mode**: bring the brain (knowledge + agents + MCP + the Claude
Code hooks) to a repo we want to leave **completely untouched** — the motivating case is a **client
clone** — writing **zero files** into it. Two facts make this feasible:

- **All four tools already run off a global operator layer** (`~/.claude/CLAUDE.md`,
  `~/.codex/AGENTS.md`, `~/.gemini/GEMINI.md`, VS Code user-scope instructions). The per-repo files
  today exist mostly to *gate* activation, not to deliver it — so activation can move fully global.
- **Memory is already central.** The KB lives in `$BAILIWICK`, read live over MCP; `/curate`
  writes promotions back into the framework, never the target repo. Shadow mode changes nothing here.

The only genuinely repo-local artifact was **outputs/captures** (`.bailiwick-outputs/`). The ADR-002
dirty-zone backup pipeline **already stores captures centrally, keyed by origin repo** (its
`capture/<machine>` branch records `capture: <origin>/<repo> <ts>`). That is exactly the "central,
per-repo-keyed captures" primitive shadow mode needs — it already exists as a proven pipeline
(`capture_backup.sh` → dirty repo → `/curate` pull/decrypt/promote/purge).

**Non-goals.** The GitHub-**hosted** Copilot cloud agent is explicitly **out of scope** — it runs in
GitHub's environment, cannot see `$BAILIWICK`, local MCP, or user settings, and could only be
reached by committing a shared instruction file. Shadow mode targets **local** tools only. This is no
regression: the current hidden-complement model can't reach the cloud agent either.

## Decision

Add an opt-in **shadow mode** that activates the framework from **global state** instead of an in-repo
marker, and routes captures to a **central plaintext staging dir keyed by origin repo** consumed by
the existing dirty-zone pipeline (**Option A**). Seeded mode remains the default; shadow is opt-in.

1. **Non-file activation gate.** Add a signal the gates honour in addition to the in-repo marker:
   `BAILIWICK_SHADOW=1` (shell/env) and/or a `~/.bailiwick/allowlist` of repo paths. When the
   current repo matches, `is_bailiwick_repo` passes with **nothing in the repo**. The same gate conditions
   the global instruction layers (so global activation is selective, not every-repo). For **Claude
   Code** the instruction delivery is the **SessionStart hook injection itself** (it already injects
   defaults + INDEX for gated repos) — no global `~/.claude/CLAUDE.md` is used, so activation stays
   selective per repo with no every-repo instruction bleed.
2. **Global MCP root.** A single user-scoped MCP filesystem root = `$BAILIWICK` (+ enabled
   federation sources) serves every repo. The working repo is reached **natively** by each agent, so
   the MCP root never needs the (dynamic) workspace path — one fixed global config suffices for all
   four tools.
3. **Central captures (Option A).** A shadow variant of `capture_session.py` writes plaintext to
   `~/.bailiwick/captures/<repo-key>/raw/` instead of `<repo>/.bailiwick-outputs/raw/`. `<repo-key>` =
   git remote URL, falling back to a repo-root path hash; the origin repo + scope are stamped in each
   capture's metadata so `/curate` can still route to the correct `client:<id>` / `generic` scope.
   The existing `capture_backup.sh` sources from this central dir (unchanged posture: gpg-encrypt →
   ciphertext → dirty repo). `/curate`'s gather step and the SessionStart pending-capture nag read
   the central dir (filtered by the current repo, or swept across all pending).

The net effect: a shadow-activated repo has **zero framework files** in its tree, yet gets full
knowledge + agents + MCP + (for Claude Code) capture and guardrails.

## Options Considered

### Option A — Env/allowlist gate + global layers + central captures via dirty-zone (CHOSEN)
**Pros:** Truly zero-footprint in the target repo. Reuses the proven dirty-zone pipeline for
per-repo-keyed captures — no parallel store invented. Single global curation queue across all repos.
**Cons:** The activation signal moves from a per-repo file to global shell/config state ("which repos
the framework attaches to" is now global, not self-evident in the repo). Central staging
**concentrates** dirty data (see Consequences). Requires stamping origin/scope that the in-repo
location gave for free.

### Option B — Keep today's hidden in-repo artifacts, only lift instruction/MCP files global
**Pros:** Smallest change; captures stay self-identifying in-repo; no central-aggregation risk.
**Cons:** **Not** zero-footprint — `.bailiwick-outputs/` (and any seeded complement) still sits in the repo
tree, merely `.git/info/exclude`'d. Fails the motivating "touch nothing" requirement for client clones.

### Option C — Always-on global `~/.claude/CLAUDE.md` activation, no gate
**Pros:** Simplest possible activation.
**Cons:** Activates the framework in **every** repo indiscriminately — loses selectivity and the
privacy property (no way to keep the brain out of a repo). Rejected.

## Rationale

The framework's four tools are already global-layer-based, so global activation is the natural model
and the per-repo marker is mostly a gate — Option A replaces that gate with an explicit, selective
global signal rather than an implicit in-repo file. Option A was chosen over B because only A meets
the stated requirement (leave a client clone **completely** untouched); B's excluded-but-present files
still fail "touch nothing." Central captures reuse the existing dirty-zone pipeline, which **already**
keys captures by origin repo — so the incremental work is a staging-path redirect plus an
origin/scope stamp, not a new subsystem. The accepted trade is that the activation signal becomes
global state (env var / allowlist) instead of a per-repo file — acceptable and arguably clearer for
the "bring the brain, write nothing" use case.

## Consequences

### Positive
- **Zero framework footprint** in the target repo — the client-clone requirement is met.
- **One central curation queue** across all repos (rather than per-repo `.bailiwick-outputs/`); `/curate`
  can sweep everything pending in a single pass.
- Cleaner multi-tool story: Codex/Gemini drop their per-repo MCP configs + markers in favour of the
  global `~/.codex/config.toml` / `~/.gemini/settings.json` layers.

### Negative / Accepted trade-offs
- **Activation is now global state.** "Which repos the framework attaches to" lives in an env var /
  allowlist, not a visible per-repo file — an accepted discoverability/hygiene shift.
- **Central aggregation concentrates dirty data.** One staging dir pools **every** client's raw
  transcripts. This raises — not lowers — the importance of ADR-002's controls (encrypt-before-push,
  private key never leaves the curating machine, offline key-recovery copy). The plaintext staging
  dir itself is a new concentrated exposure until encrypted/curated.
- Scope routing now depends on the **stamped** origin/scope rather than the implicit in-repo location;
  a wrong/missing stamp mis-routes a capture's scope.

### Risks and mitigation
| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Central staging dir (`~/.bailiwick/captures/`) read by another local process / leaked | Medium | High | Restrict dir perms (0700); keep it out of any synced/cloud folder; encrypt-at-rest posture per ADR-002; purge on curation |
| Shadow left globally on for a repo that must stay brain-free (e.g. a shared/recording session) | Medium | Medium | Allowlist is explicit opt-in per repo path; `BAILIWICK_SHADOW` is per-shell (not persistent); document a `status`/`off` check |
| Origin/scope mis-stamp → client capture routed as `generic` | Medium | High | Derive `<repo-key>` from git remote deterministically; `/curate` shows origin + proposed scope for confirmation before promotion (leakage check already gates cross-client) |
| Global-scope tool behaviour assumed but wrong (see Open items) | Medium | Medium | Verify each tool's user-scope mechanism against current official docs **before** implementing (per standing note) |

## Verified against official docs (2026-07-01)

The global-scope mechanisms this design rests on were confirmed against each tool's official docs
before committing (per the standing note to verify tool-discovery/MCP behaviour before changing
wiring). Findings:

- **Claude Code:** ✅ user-scoped MCP via `claude mcp add --scope user` (stored in `~/.claude.json`;
  project `.mcp.json` wins on conflict), **or** `permissions.additionalDirectories` in
  `~/.claude/settings.json` (user scope) for read access to `$BAILIWICK`. Hooks inherit the
  environment and receive `cwd`/`CLAUDE_PROJECT_DIR`, so the gate can be **path-based against the
  allowlist** (env var optional). Instruction delivery is the existing SessionStart hook injection —
  no global `CLAUDE.md` needed.
  (docs: code.claude.com/docs — mcp, settings, memory, hooks.)
- **Codex CLI:** ✅ global `[mcp_servers.*]` in `~/.codex/config.toml` and `~/.codex/AGENTS.md`
  **load regardless of project trust** — trust gates only the project `.codex/` layer, not the user
  layer. Zero repo files needed. (docs: developers.openai.com/codex — config-reference, mcp, agents-md.)
- **Gemini CLI / Code Assist:** ✅ global `mcpServers` in `~/.gemini/settings.json` and
  `~/.gemini/GEMINI.md` load every session; a repo file supplements (does not shadow). Code Assist's
  VS Code agent runs the bundled CLI and reads the same `~/.gemini/` config. (docs: gemini-cli
  configuration; Google Code Assist agentic-chat.)
- **Copilot (local VS Code):** ⚠️ **partial.** User-scope MCP is solid ("MCP: Open User
  Configuration" → user `mcp.json`, "available across all your workspaces"). User-scope *instructions*
  (New Instructions (User) `*.instructions.md`) are officially supported and highest-priority, **but**
  open VS Code bug **microsoft/vscode#304101** reports `applyTo:"**"` user instruction files are
  discovered yet not reliably auto-injected. Treat as "supported, empirically verify on the target
  build"; the deprecated `github.copilot.chat.codeGeneration.instructions` settings array is not a
  substitute for general agent codegen. (docs: code.visualstudio.com custom-instructions, mcp-servers.)

**Net:** zero-repo-file activation is fully achievable today for Claude Code, Codex, and Gemini. For
Copilot, user MCP is solid but user-scope instruction auto-injection must be verified empirically on
the running VS Code build (fallback if it fails: accept that local Copilot needs the one per-repo
`.github/instructions/…` file, i.e. Copilot is the single tool that may not reach *full* shadow).

## Affected components (implementation sketch)

- `hooks/session_start.sh` — `is_bailiwick_repo` also honours `BAILIWICK_SHADOW` /
  `~/.bailiwick/allowlist`; INDEX injection + nags unchanged.
- `hooks/capture_session.py` — shadow branch: write to
  `~/.bailiwick/captures/<repo-key>/raw/`, stamp origin repo + scope.
- `hooks/guardrails.py` — same gate extension (enforcement must apply in shadow repos too).
- `hooks/capture_backup.sh` — source captures from the central dir when in shadow mode.
- `skills/curate/SKILL.md` — gather from central dir; surface origin/scope per capture;
  nag/count from central.
- `scripts/bootstrap.sh` — `--shadow` sets up the global MCP root + allowlist entry (and global tool
  layers) **instead of** seeding repo files; `status` reports shadow state.
- Global layers: `~/.codex/AGENTS.md`, `~/.gemini/GEMINI.md`, VS Code user instructions — gate on the
  same allowlist/env signal.
- `docs/FRAMEWORK.md` — new subsection under §5/§7/§10 describing shadow mode; §6 capture lifecycle
  updated for central staging.

## References
- `adr-002-dirty-zone-backup-confidentiality.md` (dirty-zone controls this ADR leans on)
- `adr-001-kb-tooling-and-team-brain.md`
- `hooks/session_start.sh` (`is_bailiwick_repo` gate), `capture_session.py`,
  `capture_backup.sh`, `guardrails.py`
- `bailiwick-holding` — `capture/<machine>` branch (existing per-repo-keyed central captures)
- `docs/FRAMEWORK.md` §5 (hooks), §6 (capture lifecycle), §7 (bootstrap), §10 (four adapters)
