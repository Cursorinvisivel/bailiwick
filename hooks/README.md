# Bailiwick hooks

Hard enforcement layer for the framework. Hooks are executed by the Claude Code
harness (not by the model), so they fire whether or not anyone remembers to
trigger them. They sit underneath the soft prompt-level design in
`../agents/memory.md`.

## What's here

| File | Hook event | Purpose |
|---|---|---|
| `guardrails.py` | Claude Code `PreToolUse` (`Bash`) · Codex CLI `PreToolUse` (arg `codex`) · Gemini CLI `BeforeTool` (arg `gemini`) | **Runtime guardrail — one engine, three adapters.** Identical tier evaluation; per-tool decision contracts: Claude/Gemini → forced confirmation (`ask`); Codex → **deny** with actionable reason (no ask exists) + `BAILIWICK_BREAK_GLASS=1` allow-once (logged). Three tiers, evaluated in order, each resolving to an in-the-moment gate — a forced confirmation under Claude/Gemini, a **deny** + break-glass under Codex (per the per-tool contracts above) — so nothing runs silently or on agent initiative: **EXEMPT** — dirty-zone capture plumbing (`capture_backup.sh`, the capture-mirror) always passes (data-loss prevention). **ASK-IMPACT** — real-world impact re-confirms *even when the user instructed it*: `terraform`/`terragrunt apply`+`destroy`; `kubectl apply/delete/patch/replace/scale/drain` + mutating rollouts; `helm install/upgrade/uninstall/rollback`; `gcloud`/`gsutil`/`az` `delete/destroy/update/patch/rm`; mutating `aws` verbs + `aws s3 rm/rb/mv`; recursive/forced `rm`; `git merge`; `gh repo delete`. **ASK-GO-AHEAD** — `git commit`/`push` and PR open/merge (`gh pr create\|merge\|close`) need a clear user go-ahead; a commit/PR message carrying an AI attribution signature (Co-Authored-By / "Generated with … Claude" / 🤖) gets its own confirmation. Validation-only commands (`terraform plan/validate/fmt`, `kubectl get`/`--dry-run`, read-only cloud CLI) pass untouched; line-continuations are folded before matching. **Tiered failure mode (ADR-005):** on an evaluation error it fails **closed** (deny) for commands tripping the destructive pre-filter, **open** otherwise; `BAILIWICK_BREAK_GLASS=1` downgrades that error-path deny to ask (logged). Every decision is appended to `~/.bailiwick/guardrail-audit.log`. **Direct-command patterns only — not a complete security boundary** (misses `make apply`, wrapper scripts, aliases, Terraform-MCP actions). |
| `session_start.sh` | `SessionStart` | Injects framework defaults (knowledge always on, orchestration proportional), injects the knowledge INDEX.md (the map, ~2k tokens — so relevance can be judged without a blind read), **fast-forwards the Bailiwick clone from `origin/main`** (inbound sync — throttled ~30 min, clean `main` only, non-fatal), nags when raw captures are pending curation, and nags when INDEX.md exceeds ~20 KB (shard a domain into `indexes/`). |
| `capture_session.py` | Claude Code `Stop`, `SessionEnd` · Codex CLI `Stop`, `SessionEnd` (>= 0.147) | Enforced raw capture: copies the transcript to `<project>/.bailiwick-outputs/raw/<session_id>.jsonl` when the session shows substantive work. No intelligence, no promotion. **One script, two transcript shapes:** both CLIs pass the same payload fields (`session_id`/`transcript_path`/`cwd`/`hook_event_name`), so only the transcript differs — Claude Code's `message.content[].tool_use` vs Codex's rollout `payload` records (`function_call`/`custom_tool_call`, plus `patch_apply_end` for a patch applied from inside a code-mode `exec`, which is otherwise invisible). Records are dispatched per line on that shape, so a resumed or mixed file cannot mislead it. Signals are read only from what the agent actually RAN — never from instruction text or command output. |
| `capture_backup.sh` | Claude Code + Codex `Stop`, `SessionEnd` (`push`); `/curate` (`pull`/`purge`) | **Optional** encrypted off-machine backup of the dirty zone. `push` gpg-encrypts new captures and pushes **ciphertext** to a per-machine branch of a dedicated private repo (throttled on `Stop`, forced on `SessionEnd`; **best-effort / fail-open** with local-mirror durability — see below; an unusable recipient key logs a health `error`, keeps the SOURCE capture untouched, and retries that file automatically once the key is fixed). `pull` decrypts blobs — every machine's `capture/*` branch, not just this one's — into `$BAILIWICK/.bailiwick-inbox/raw/` for `/curate`; `purge` drops a blob post-curation from whichever machine's branch holds it and **tombstones** it in that branch's root `.purged` manifest (hashed relpaths, no identifiers), so `push` never re-encrypts a purged blob while its source capture is still un-retired on some machine. No-op unless `capture_backup.enabled` (+ `confidentiality_ack`) in `.bailiwick-sync.json`. See *Encrypted dirty-zone backup* below. |
| `sync_knowledge.sh` | run by `/curate` (or manual) | **Outbound sync** of approved knowledge commits. Role-aware via `.bailiwick-sync.json`: `central` pushes `HEAD:main`; `satellite` parks commits on `sync/<machine>`, pushes `--force-with-lease`, and opens/refreshes a PR **as the account resolved by `gh_account.sh`, targeting the repo explicitly** (bare `gh` acts as the globally *active* account, which on a multi-account machine may not even see the repo — the push then succeeds while PR creation 404s and the knowledge strands). PR-creation failure is loud: health `error` + multi-line stderr with the exact manual command, **exit 2** (push-only, no `gh`, stays exit 0 — opening the PR manually is the documented flow there). Telemetry is central-owned and never synced from satellites. See docs/operations.md → Multi-machine sync. |
| `gh_account.sh` | sourced helper | **GitHub account resolution, shared** by `sync_knowledge.sh` (PR creation), `bootstrap.sh` (github MCP pinning), and `scripts/doctor.sh` (reachability check) — one implementation, so they can never disagree on the account. `bw_resolve_gh_account <root>` picks the account that can actually reach the clone's origin repo (priority: `github_account` override > `github_account_map[owner]` > access probe over every logged-in account; ambiguity warns and points at the map). `bw_gh <args…>` then runs `gh` as that account, re-reading the token from gh's keychain on every call — nothing lands in a dotfile, and the pin survives `gh auth switch` for daily work. `BW_NO_GH_AUTH=1` skips resolution. |
| `install_hooks.py` | helper (`bootstrap.sh --install-tools`) | Idempotent, non-destructive safe-merge of the `hooks` block into `~/.claude/settings.json` (dedups by command, preserves the `matcher`, preserves other keys, refuses on invalid JSON). **Adoption pass:** an existing install whose Bailiwick-owned hook commands run from ANOTHER root (old layout, a renamed/retired clone) is re-pointed at this clone (`MIGRATED: <old> -> <new>`) and deduped so hooks never fire twice — but a rewrite is committed ONLY when the result lands exactly on one of the template's own commands, so a user's hook that merely reuses an owned filename is never touched. |
| `install_global_layer.sh` + `codex-global-agents.tmpl.md` / `gemini-global.tmpl.md` | helper (`bootstrap.sh --install-tools`) | Installs/refreshes the **global Codex / Gemini operator layers** — a marker-delimited managed block in `~/.codex/AGENTS.md` and `~/.gemini/GEMINI.md` that conditionally reads a repo's untracked `.bailiwick.local.md`. Loaded BEFORE the repo's own `AGENTS.md`/`GEMINI.md` (team file keeps precedence); never shadows it. Safe-merge: replaces the managed block in place, leaves hand-written content untouched. One generic installer (`<bailiwick> <template> <dest>`) serves both. |
| `install_adapter_hooks.py` | helper (`bootstrap.sh --install-tools`) | Wires the guardrail into **Codex** (managed `# BEGIN/END bailiwick hooks` block in `~/.codex/config.toml`, `[[hooks.PreToolUse]]` matcher `^Bash$`) — plus, since codex-cli 0.147, the **capture pair** on `[[hooks.Stop]]` and `[[hooks.SessionEnd]]` (`capture_session.py` then `capture_backup.sh push`, the same order and scripts Claude Code runs). PreToolUse stays FIRST and byte-identical in the block because Codex keys hook trust by `<event>:<group>:<index>` — so the guardrail's existing trust entry keeps addressing the same hook (whether the stored `trusted_hash` also survives is unverified — worst case it re-prompts once). Each new hook definition is trusted **once** on its first fire, so a fresh install prompts per hook. Also wires **Gemini CLI** (named `bailiwick-guardrail` entry in `~/.gemini/settings.json` `hooks.BeforeTool`, matcher `run_shell_command`). Idempotent; preserves all other content; refuses malformed JSON. **Codex requires a one-time hook trust: it prompts the first time the hook fires in a trusted project (in the `codex` CLI — the VS Code extension does NOT surface it); trust persists as a `[hooks.state]` table in `~/.codex/config.toml`, which this installer preserves on reinstall.** Both hooks self-gate to wired/shadow repos. |
| `install_desktop_mcp.py` | helper (`bootstrap.sh --install-tools --with-desktop`, opt-in) | **Read-only knowledge reference, OUTSIDE the enforcement layer.** Claude Desktop and ChatGPT Desktop have no hook system at all, so none of the above (guardrail, capture, curation) can reach them. This merges a single `bailiwick-knowledge` MCP filesystem server — rooted at `knowledge/` only, never the rest of the framework — into each app's own `mcpServers` config (`claude_desktop_config.json` / `chatgpt_config.json`), auto-detected per OS by `bootstrap.sh` (macOS, native Windows, and WSL via `cmd.exe`+`wslpath` to the Windows-host path). Idempotent; preserves every other key and every other MCP server already configured; refuses malformed JSON. Pair with `knowledge/templates/desktop-reference-instructions.md` (paste into the app's Project/custom instructions) since retrieval discipline isn't auto-injected there. Removed by global `--uninstall` (`rm_desktop_mcp` in `bootstrap.sh`, path-scoped to just this one entry). |
| `public_origin.sh` | sourced helper + `check` entry point | **ADR-009 public-origin detection** (contribute-only instances): layer 1 = canonical-slug match (offline, always), layer 2 = live `gh api` visibility probe (catches public forks; fail-open without `gh`; timeout-bounded). `bw_public_origin_block` gates `sync_knowledge.sh` and bootstrap; `bash public_origin.sh check` (exit 3 = contribute-only) is the standalone entry `/curate` Step 0 runs. **Amendment 1 split:** the SessionStart *banner* may serve a cached negative verdict (≤24h, exact-URL-keyed, negative-only, 0600) via `BW_PO_CACHE=1`; every *enforcement* call stays live and uncached. |
| `config_common.sh` | sourced helper | **Shared config/identity primitives**: `bw_cfg_get`/`bw_cfg_bool` (the `.bailiwick-sync.json` scalar reads — one implementation instead of six), `bw_machine_token` (THE machine-token normalization; python mirrors it byte-identically, pinned by test), `bw_is_shadow_repo` (the allowlist gate, realpathing both sides). Batch heredoc parsers in `capture_backup.sh`/`doctor.sh` stay separate on purpose — one python spawn for nested config on hot paths. |
| `bw_common.py` | imported by the python hooks | **Shared python substrate** for `capture_session.py` + `guardrails.py`: `COMPLEMENT_FILES`, `bw_home`, `is_bailiwick_repo`, `is_shadow_repo`, `resolve_project_dir`, `machine_token`, `health` — one implementation of the self-gating/health layer both hooks previously carried verbatim (which is how two silent bash↔python drifts happened). Fail-safe: no public function ever raises. |
| `health_common.sh` | sourced helper | **Framework-health logging** (`bw_health <component> <event> <detail>`): best-effort JSONL append to the per-machine shard `~/.bailiwick/health/<machine>.jsonl`. Every component logs its failures there (guardrail engine errors, capture copy failures, ff-pull/sync/backup push failures, python3-missing). Each machine writes ONLY its own shard; `capture_backup.sh push` uploads it **encrypted** to the machine's dirty-repo branch (ADR-002: only ciphertext leaves the machine), `pull` refreshes the fleet's shards into `health/remote/`, and `/metrics` renders the per-source fleet view (last heartbeat, errors by component, backup push drift). SessionStart nags when errors were logged in the last ~24h. Local, never committed to the Bailiwick repo. |
| `settings.template.json` | — | The `hooks` block to install into `~/.claude/settings.json` (once, global). |

## Install (once, globally)

Merge the `hooks` block from `settings.template.json` into `~/.claude/settings.json`
(keep any existing keys). The hooks then fire in every project but **self-gate**: the
scripts no-op unless the repo is Bailiwick-wired — i.e. a framework complement
(`.bailiwick.local.md` / `CLAUDE.local.md` / `.github/instructions/bailiwick.instructions.md`)
references `$BAILIWICK`. The team's own shared files are never relied on for this. Scripts are referenced by absolute path, so
nothing is copied anywhere and there is **no per-repo hook setup**.

In each wired repo the capture staging (`.bailiwick-outputs/`) is hidden via the repo's
**`.git/info/exclude`** — never the tracked `.gitignore`, whose entries alone would expose the
framework's existence to anyone who clones. `bootstrap.sh` writes the exclude entries automatically;
in shadow mode (FRAMEWORK.md §7.1) captures stage centrally and the repo needs no entry at all.

## Design guarantees

- **Capture is enforced, promotion is gated.** Hooks only stage raw transcripts.
  Distillation into `$BAILIWICK/knowledge/` happens exclusively via
  `/curate` with explicit human approval — the non-negotiable rule is preserved.
- **Nothing leaks.** `.bailiwick-outputs/raw/` is excluded from git (via `.git/info/exclude`); unsanitised transcripts
  (which may contain client IAM / project IDs) are never committed. `/curate`
  abstracts to generic before promoting.
- **No spam.** Capture only writes when a session mutated files or made >= 3 tool
  calls; pure conversation produces no capture and no nag.
- **Self-gating.** Installed once globally, the scripts stay inert in any repo that is
  not Bailiwick-wired — so unrelated projects see no banner and no capture.

## Encrypted dirty-zone backup (optional)

The dirty zone (`.bailiwick-outputs/`) is local + gitignored, so un-curated captures are lost if the disk
dies before `/curate`. `capture_backup.sh` adds a durable, **encrypted** off-machine copy. Opt in via
`.bailiwick-sync.json`:

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

- **Only ciphertext leaves the machine.** Captures are `gpg --encrypt`ed to `gpg_recipients` (public
  key fingerprints) before push; the **private key never leaves** the machine that runs `/curate`.
- **Dedicated PRIVATE repo** — not the framework repo, not a client repo. Per-machine branch
  (`capture/<machine>`), so machines never conflict.
- **`confidentiality_ack` gate** — backup refuses to run unless this is `true`. Setting it asserts
  your engagement terms permit backing up data that may include client material.
- **Distribute keys:** every backup machine needs the recipient *public* key imported (to encrypt);
  the *private* key lives only on the curating machine (to decrypt).
- **Erasure is a non-issue:** because the remote only ever holds ciphertext, post-curate `purge` is
  hygiene, not a security-critical history rewrite (which hosted git can't guarantee anyway).
- **Purged stays purged.** `purge` removes the blob *and* appends a tombstone to the branch-root
  `.purged` manifest — sha256 of the blob relpath, never the path itself, so the manifest carries no
  client identifier and `purge_verify.sh residual --backup-path` prefix checks stay clean. `push`
  skips tombstoned relpaths, so a source capture left un-retired on any machine cannot resurrect a
  purged blob. A purge may target another machine's blob: it routes to that machine's `capture/*`
  branch via a throwaway detached worktree.
- **Best-effort delivery, local-first durability.** The push is **fail-open** — any encrypt / commit /
  push error `exit 0`s, so a backup never wedges a session. Ciphertext is committed to a **local
  mirror** (`~/.cache/bailiwick/capture-mirror`) *before* the network push; an unpushed commit is
  retained (the mirror is **never reset to origin**) and rides along on the next successful push. The
  raw transcript is also written to local disk first (by `capture_session.py`), so a failed backup
  never loses the capture — only its **off-machine copy** lags. Cadence: throttled on `Stop`
  (`throttle_minutes`), forced on `SessionEnd` — but `SessionEnd` firing is itself best-effort (an
  abrupt crash / force-quit may skip it; the throttled `Stop` pushes and the local transcript cover
  that gap). Hooks run under Claude Code's default 600 s command timeout, so a normal push has ample
  headroom.
- **Detectability caveat (silent remote drift).** The push tracks whether a capture was **encrypted**
  (a per-file `.gpg.sha256` sidecar), not whether it was **pushed**. So an encrypted-but-unpushed blob
  won't retry on its own — it drains only when a *later* capture triggers a new push (which sends the
  whole unpushed local history). If a repo goes idle right after a failed push, its remote copy can lag
  silently while the local mirror stays complete. Surfacing push success (last-success + unpushed-commit
  count) is surfaced by `/metrics` and the SessionStart health nag.

`/curate` restores off-machine captures with `capture_backup.sh pull` (decrypts to `.bailiwick-inbox/raw/`,
gitignored) and drops promoted blobs with `capture_backup.sh purge <relpath>`. **`/curate` is
runnable from any wired repo** — it reaches the dirty pool (via the `pull`) and the knowledge library
by absolute path, so the active repo only contributes its own local `.bailiwick-outputs/`; the cross-repo
encrypted pool is identical wherever you invoke it (on a machine that holds the gpg private key).

## Requirements

- `python3` and `bash` on PATH (used by the hook commands).
- `gpg` on PATH only if `capture_backup` is enabled (encrypt on every machine; decrypt — with the private key — on the curating machine).
- `git` on PATH for inbound/outbound sync; `gh` (authenticated) on satellites for PR
  creation. Sync degrades gracefully — missing `git`/`gh` or being offline is non-fatal.
- `$BAILIWICK` paths in the `settings.template.json` commands are absolute; update them
  if the framework moves. The scripts themselves locate the framework by their own path, so they
  are portable across machines (central and satellites at different absolute paths).
