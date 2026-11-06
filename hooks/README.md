# Bailiwick hooks

Hard enforcement layer for the framework. Hooks are executed by the Claude Code
harness (not by the model), so they fire whether or not anyone remembers to
trigger them. They sit underneath the soft prompt-level design in
`../agents/memory.md`.

## What's here

| File | Hook event | Purpose |
|---|---|---|
| `guardrails.py` | Claude Code `PreToolUse` (`Bash`) · Codex CLI `PreToolUse` (arg `codex`) · Gemini CLI `BeforeTool` (arg `gemini`) | **Runtime guardrail — one engine, three adapters.** Identical tier evaluation; per-tool decision contracts: Claude/Gemini → forced confirmation (`ask`); Codex → **deny** with actionable reason (no ask exists) + `BAILIWICK_BREAK_GLASS=1` allow-once (logged). Four tiers, evaluated in order, each resolving to an in-the-moment gate — a forced confirmation under Claude/Gemini, a **deny** + break-glass under Codex (per the per-tool contracts above) — so nothing runs silently or on agent initiative: **EXEMPT** — dirty-zone capture plumbing (`capture_backup.sh`, the capture-mirror) always passes (data-loss prevention). **ASK-IMPACT** — real-world impact re-confirms *even when the user instructed it*: `terraform`/`terragrunt apply`+`destroy`; `kubectl apply/delete/patch/replace/scale/drain` + mutating rollouts; `helm install/upgrade/uninstall/rollback`; `gcloud`/`gsutil`/`az` `delete/destroy/update/patch/rm`; mutating `aws` verbs + `aws s3 rm/rb/mv`; recursive/forced `rm`; `git merge`; `gh repo delete`. **ASK-GO-AHEAD** — `git commit`/`push` and PR open/merge (`gh pr create\|merge\|close`) need a clear user go-ahead; a commit/PR message carrying an AI attribution signature (Co-Authored-By / "Generated with … Claude" / 🤖) gets its own confirmation. **SIGNED-COMMIT SHAPE** — in a repo that signs (`commit.gpgsign=true` or `user.signingkey`), a commit must be `/sign`-shaped (`git commit -S -F .git/COMMIT_MSG_<slug>`) or it is **denied** on every adapter (break-glass downgrades the deny); the `-F` message file is scanned for attribution signatures, since the command text no longer carries the message. Validation-only commands (`terraform plan/validate/fmt`, `kubectl get`/`--dry-run`, read-only cloud CLI) pass untouched; line-continuations are folded before matching. **Tiered failure mode (ADR-005):** on an evaluation error it fails **closed** (deny) for commands tripping the destructive pre-filter, **open** otherwise; `BAILIWICK_BREAK_GLASS=1` downgrades that error-path deny to ask (logged). Every decision is appended to `~/.bailiwick/guardrail-audit.log`. **Direct-command patterns only — not a complete security boundary** (misses `make apply`, wrapper scripts, aliases, Terraform-MCP actions). |
| `session_start.sh` | `SessionStart` | Injects framework defaults (knowledge always on, orchestration proportional), injects the knowledge INDEX.md (the map, ~2k tokens — so relevance can be judged without a blind read), **fast-forwards the Bailiwick clone from `origin/main`** (inbound sync — throttled ~30 min, clean `main` only, non-fatal), nags when raw captures are pending curation, and nags when INDEX.md exceeds ~20 KB (shard a domain into `indexes/`). |
| `fetch_guard.py` | Claude Code `PreToolUse` (`WebFetch`) — two layers | **Fetch-time allowlist for the `/curate` freshness agent.** Checks the URL with `skills/curate/scripts/check_source.py` (same code as the orchestrator's post-hoc check) and **denies** anything outside the GCP source registry. **Agent-scoped layer:** the agent's own frontmatter hook (`agents/cloud-research-freshness.md`) runs `--scoped` through a fixed-path launcher that `install_hooks.py` writes at `$BAILIWICK_HOME/hooks/fetch_guard.py`; Claude Code runs it only while that agent is active, so it needs no `agent_type`, and a missing launcher (or a launcher whose clone is gone) **blocks every fetch of that agent**. **Global layer:** the `settings.json` hook acts only when the payload `agent_type` is `bailiwick-cloud-research-freshness`; every other caller passes untouched. Inside scope it fails **closed** on errors it can see (unreadable registry, unusable URL or payload, internal error) and **open** when it cannot run (no `python3` on PATH, crash or timeout) or, for the global layer, cannot identify the caller. `doctor.sh` runs both installed layers against a synthetic off-registry and registry URL; `scripts/smoke_fetch_guard.sh` runs one live session after a Claude Code upgrade and checks that **both** layers logged the refusal (`fetch-deny:scoped` / `fetch-deny:global` — the latter proves `agent_type` is still sent). The frontmatter command uses POSIX shell expansion; on Windows it is unverified. A **missing** script is the opposite trap: `python3` exits 2, which Claude Code treats as blocking, so a moved clone blocks every WebFetch until `--install-tools` is re-run (`doctor.sh` fails on hook paths that no longer exist). Sees the requested URL only, not same-host redirects the fetch tool follows. Every denial is appended to `~/.bailiwick/guardrail-audit.log` with the host and a hash of the URL, never the raw URL. The fallback `bailiwick-cloud-research` agent is not covered; neither are the generated Gemini/Codex/Copilot adapters. |
| `capture_session.py` | Claude Code `Stop`, `SessionEnd` · Codex CLI `Stop`, `SessionEnd` (>= 0.147) | Enforced raw capture: copies the transcript to `<project>/.bailiwick-outputs/raw/<session_id>.jsonl` when the session shows substantive work. No intelligence, no promotion. **One script, two transcript shapes:** both CLIs pass the same payload fields (`session_id`/`transcript_path`/`cwd`/`hook_event_name`), so only the transcript differs — Claude Code's `message.content[].tool_use` vs Codex's rollout `payload` records (`function_call`/`custom_tool_call`, plus `patch_apply_end` for a patch applied from inside a code-mode `exec`, which is otherwise invisible). Records are dispatched per line on that shape, so a resumed or mixed file cannot mislead it. Signals are read only from what the agent actually RAN — never from instruction text or command output. **Subagents (Claude Code only):** it also scans `<session_id>/subagents/agent-*.jsonl` beside the main transcript — reads credited as `loaded_via_subagents`, header `capture_schema: 2` — and appends those records to the same capture tagged `isSidechain`/`agentId` (`capture.include_subagents` in `.bailiwick-sync.json`, default on), keeping one `.jsonl` + `.md` per session. **Never captures a `/purge` session** (see *Design guarantees*): detected by skill name — `purge` always, plus any exact names in `capture.skip_skills` — or by the `mark_purge_session.sh` sentinel once it has run successfully. Only a user-typed name or the confirmed main-transcript sentinel skips and retracts; an agent `Skill` call, an injected skill body, or anything in a subagent only holds the capture local (`purge_detection: error`). Inert inside an applying drill sandbox (`BW_DRILL_SANDBOX` with its `.drill-sandbox` marker, project inside it) when this clone is not `$BW_DRILL_SANDBOX/framework`; a stale variable is ignored with a warn. |
| `mark_purge_session.sh` | run by `/purge` as its first action | **Positive sentinel** for a `/purge` session: `bash "$BAILIWICK/hooks/mark_purge_session.sh"`. Takes no argument (refuses any, exit 2), writes nothing, prints a fixed confirmation plus the one accepted invocation form (so the agent can self-check). The tool call that ran it is what `capture_session.py` matches; the script itself has no effect. Because that match disables capture and deletes the session's captures, `guardrails.py` **asks** before it runs (Codex: deny; `/purge` there relies on the typed `$bailiwick-purge`), and it counts only in the main transcript, never a subagent's, and only once it has run successfully (its paired result is not an error / exits 0 and carries the fixed success line; a declined ask leaves the session captured). |
| `capture_backup.sh` | Claude Code + Codex `Stop`, `SessionEnd` (`push`); `/curate` (`pull`/`purge`) | **Optional** encrypted off-machine backup of the dirty zone. `push` gpg-encrypts new captures and pushes **ciphertext** to a per-machine branch of a dedicated private repo (throttled on `Stop`, forced on `SessionEnd` — **detached**: the hook returns immediately and a background child does the push; **best-effort / fail-open** with local-mirror durability — see below; an unusable recipient key logs a health `error`, keeps the SOURCE capture untouched, and retries that file automatically once the key is fixed). `pull` decrypts blobs — every machine's `capture/*` branch, not just this one's — into `$BAILIWICK/.bailiwick-inbox/raw/` for `/curate`; `purge` drops a blob post-curation from whichever machine's branch holds it and **tombstones** it in that branch's root `.purged` manifest (hashed relpaths, no identifiers), so `push` never re-encrypts a purged blob while its source capture is still un-retired on some machine. `retract` drains the purge-session ledger (below). No-op unless `capture_backup.enabled` (+ `confidentiality_ack`) in `.bailiwick-sync.json`; inert under a foreign `BW_DRILL_SANDBOX`. See *Encrypted dirty-zone backup* below. |
| `sync_knowledge.sh` | run by `/curate` (or manual) | **Outbound sync** of approved knowledge commits. Role-aware via `.bailiwick-sync.json`: `central` pushes `HEAD:main`; `satellite` parks commits on `sync/<machine>`, pushes `--force-with-lease`, and opens/refreshes a PR **as the account resolved by `gh_account.sh`, targeting the repo explicitly** (bare `gh` acts as the globally *active* account, which on a multi-account machine may not even see the repo — the push then succeeds while PR creation 404s and the knowledge strands). PR-creation failure is loud: health `error` + multi-line stderr with the exact manual command, **exit 2** (push-only, no `gh`, stays exit 0 — opening the PR manually is the documented flow there). Telemetry is central-owned and never synced from satellites. See docs/operations.md → Multi-machine sync. |
| `gh_account.sh` | sourced helper | **GitHub account resolution, shared** by `sync_knowledge.sh` (PR creation), `bootstrap.sh` (github MCP pinning), and `scripts/doctor.sh` (reachability check) — one implementation, so they can never disagree on the account. `bw_resolve_gh_account <root>` picks the account that can actually reach the clone's origin repo (priority: `github_account` override > `github_account_map[owner]` > access probe over every logged-in account; ambiguity warns and points at the map). `bw_gh <args…>` then runs `gh` as that account, re-reading the token from gh's keychain on every call — nothing lands in a dotfile, and the pin survives `gh auth switch` for daily work. `BW_NO_GH_AUTH=1` skips resolution. |
| `install_hooks.py` | helper (`bootstrap.sh --install-tools`) | Idempotent, non-destructive safe-merge of the `hooks` block into `~/.claude/settings.json` (dedups by command, preserves the `matcher`, preserves other keys, refuses on invalid JSON). **Adoption pass:** an existing install whose Bailiwick-owned hook commands run from ANOTHER root (old layout, a renamed/retired clone) is re-pointed at this clone (`MIGRATED: <old> -> <new>`) and deduped so hooks never fire twice — but a rewrite is committed ONLY when the result lands exactly on one of the template's own commands, so a user's hook that merely reuses an owned filename is never touched. |
| `install_global_layer.sh` + `codex-global-agents.tmpl.md` / `antigravity-global.tmpl.md` | helper (`bootstrap.sh --install-tools`) | Installs/refreshes the **global Codex / Gemini operator layers** — a marker-delimited managed block in `~/.codex/AGENTS.md` and `~/.gemini/GEMINI.md` that conditionally reads a repo's untracked `.bailiwick.local.md`. Loaded BEFORE the repo's own `AGENTS.md`/`GEMINI.md` (team file keeps precedence); never shadows it. Safe-merge: replaces the managed block in place, leaves hand-written content untouched. One generic installer (`<bailiwick> <template> <dest>`) serves both. |
| `install_adapter_hooks.py` | helper (`bootstrap.sh --install-tools`) | Wires the guardrail into **Codex** (managed `# BEGIN/END bailiwick hooks` block in `~/.codex/config.toml`, `[[hooks.PreToolUse]]` matcher `^Bash$`) — plus, since codex-cli 0.147, the **capture pair** on `[[hooks.Stop]]` and `[[hooks.SessionEnd]]` (`capture_session.py` then `capture_backup.sh push`, the same order and scripts Claude Code runs). PreToolUse stays FIRST and byte-identical in the block because Codex keys hook trust by `<event>:<group>:<index>` — so the guardrail's existing trust entry keeps addressing the same hook (whether the stored `trusted_hash` also survives is unverified — worst case it re-prompts once). Each new hook definition is trusted **once** on its first fire, so a fresh install prompts per hook. Also wires **Gemini CLI** (named `bailiwick-guardrail` entry in `~/.gemini/settings.json` `hooks.BeforeTool`, matcher `run_shell_command`). Idempotent; preserves all other content; refuses malformed JSON. **Codex requires a one-time hook trust: it prompts the first time the hook fires in a trusted project (in the `codex` CLI — the VS Code extension does NOT surface it); trust persists as a `[hooks.state]` table in `~/.codex/config.toml`, which this installer preserves on reinstall.** Both hooks self-gate to wired/shadow repos. |
| `install_desktop_mcp.py` | helper (`bootstrap.sh --install-tools --with-desktop`, opt-in) | **Read-only knowledge reference, OUTSIDE the enforcement layer.** Claude Desktop and ChatGPT Desktop have no hook system at all, so none of the above (guardrail, capture, curation) can reach them. This merges a single `bailiwick-knowledge` MCP filesystem server — rooted at `knowledge/` only, never the rest of the framework — into each app's own `mcpServers` config (`claude_desktop_config.json` / `chatgpt_config.json`), auto-detected per OS by `bootstrap.sh` (macOS, native Windows, and WSL via `cmd.exe`+`wslpath` to the Windows-host path). Idempotent; preserves every other key and every other MCP server already configured; refuses malformed JSON. Pair with `knowledge/templates/desktop-reference-instructions.md` (paste into the app's Project/custom instructions) since retrieval discipline isn't auto-injected there. Removed by global `--uninstall` (`rm_desktop_mcp` in `bootstrap.sh`, path-scoped to just this one entry). |
| `public_origin.sh` | sourced helper + `check` entry point | **ADR-009 public-origin detection** (contribute-only instances): layer 1 = canonical-slug match (offline, always), layer 2 = live `gh api` visibility probe (catches public forks; fail-open without `gh`; timeout-bounded). `bw_public_origin_block` gates `sync_knowledge.sh` and bootstrap; `bash public_origin.sh check` (exit 3 = contribute-only) is the standalone entry `/curate` Step 0 runs. **Amendment 1 split:** the SessionStart *banner* may serve a cached negative verdict (≤24h, exact-URL-keyed, negative-only, 0600) via `BW_PO_CACHE=1`; every *enforcement* call stays live and uncached. |
| `config_common.sh` | sourced helper | **Shared config/identity primitives**: `bw_cfg_get`/`bw_cfg_bool` (the `.bailiwick-sync.json` scalar reads — one implementation instead of six), `bw_machine_token` (THE machine-token normalization; python mirrors it byte-identically, pinned by test), `bw_is_shadow_repo` (the allowlist gate, realpathing both sides). Batch heredoc parsers in `capture_backup.sh`/`doctor.sh` stay separate on purpose — one python spawn for nested config on hot paths. |
| `bw_common.py` | imported by the python hooks | **Shared python substrate** for `capture_session.py` + `guardrails.py`: `COMPLEMENT_FILES`, `bw_home`, `is_bailiwick_repo`, `is_shadow_repo`, `resolve_project_dir`, `machine_token`, `health`, `sync_config` — one implementation of the self-gating/health layer both hooks previously carried verbatim (which is how two silent bash↔python drifts happened). Fail-safe: no public function ever raises. |
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
- **`/purge` sessions are never backed up; a typed or sentinel-confirmed one is never captured.** An
  agent-invoked one without that confirmation is held local (captured, never pushed; see trust tiers
  below). A session that ran `/purge` holds the identifiers it
  removes, yet its capture would carry the origin of the repo it ran in, so `/purge`'s origin-based
  sweep would never find it. `capture_session.py` detects an **invocation**, never a mention (prose,
  a grep, a Read of the skill or the script, a longer command line):
  - **Skill name:** a Claude Code `Skill` tool call with `skill: "purge"`, a typed `/purge` command
    header, Codex `$bailiwick-purge` or its injected `<skill>` block. The names are `purge` (always)
    plus any listed in `capture.skip_skills` in `.bailiwick-sync.json`, matched exactly; the list adds
    names and never removes `purge`, and a malformed value falls back to the default with one health
    warning per run.
  - **Sentinel:** `/purge`'s first action is `bash "$BAILIWICK/hooks/mark_purge_session.sh"`. A Claude
    Code `Bash` tool call, or a Codex `exec`/`exec_command`/`shell`/`shell_command` call, whose
    **whole** command is that script (optionally behind `bash `/`sh `; via `$BAILIWICK`,
    `${BAILIWICK}`, or an absolute path) marks the session. This covers what name detection can only
    hold, such as a skill the model invoked on its own in Claude Code (an agent `Skill` call is
    unconfirmed until the sentinel it then runs is confirmed). On Codex the guardrail denies the
    sentinel, so it never runs successfully there; only a typed `$bailiwick-purge` is trusted. A
    Codex shell wrapper is unwrapped only from a bare `bash|sh|zsh` or `/bin/`/`/usr/bin/` one (an
    exec `shell` argument likewise), and duplicate argument keys void the call: a sentinel run
    through, say, Homebrew's bash is not credited, so the session is captured (fail-safe), and an
    agent-built fake shell cannot print the success line for it. An absolute path counts only when its `realpath` is
    this hook's own sibling `mark_purge_session.sh`; any other path ending in
    `/hooks/mark_purge_session.sh` (nonexistent, or another copy) is a mention, so naming a file cannot
    opt a session out of capture. The `$BAILIWICK`/`${BAILIWICK}` forms match as written: the
    transcript holds the command text, not the shell's expansion. The script prints the accepted form
    on every run so the agent can check the command it ran. The one accepted prefix is the exact
    assignment `BAILIWICK_BREAK_GLASS=1 `; any other prefix is a mention. The sentinel **counts only
    once it has run successfully**: the call is paired with its result (Claude Code: the `tool_result`
    with the same `tool_use_id`, not `is_error`; Codex: the `function_call_output` with the same
    `call_id`, exit code 0), and that result must carry the script's fixed success line
    `[bailiwick] purge session marked: …` (`MARK_OK_LINE`). A declined ask, a Codex deny, an error
    exit, or a call with no result yet leaves the session captured, so declining the ask stops the
    effect. A later `Stop` that sees the successful result retracts as usual.
  - **The sentinel is gated, and main-transcript only.** Running it deletes the session's captures and
    tombstones their backup blobs, so it must never be agent-silent: `guardrails.py` ASK_IMPACT asks
    the user to confirm any command-position invocation (on the quote-stripped command, plus a
    raw-command check for a quoted path holding a space); a Read/grep/cat of the script stays quiet.
    This ask, and the `purge_delete.sh`/`purge_scrub.py --apply` asks, run on every segment **before**
    the `capture_backup.sh` exemption, which itself requires the script name to end the path token (a
    path *through* it, `…/capture_backup.sh/../../hooks/mark_purge_session.sh`, is not exempt). A
    command that is exactly `bash|sh|zsh -c/-lc '<cmd>'` (how a Codex argv call can arrive) is also
    checked as the inner `<cmd>`.
    Codex has no ask, so there it is denied (break-glass only by relaunching Codex with
    `BAILIWICK_BREAK_GLASS=1`, which the guardrail reads from the hook's own environment, not from a
    command prefix). The sentinel is **ignored in subagent transcripts**: no `/purge` subagent runs it
    (`security-review-local` has no Bash), so a prompt-injected subagent cannot opt the session out.
  - **Trust tiers: only a user-originated trigger deletes anything.** *Trusted*: a typed `/purge`
    command header, a typed Codex `$bailiwick-purge`, and the sentinel confirmed by a successful
    result in the main transcript. These get the full skip below. *Unconfirmed*: an agent `Skill`
    tool call (`skill: "purge"` or a `capture.skip_skills` name), a Codex injected `<skill>` block on
    its own, a code-mode `exec` sentinel (the JS cell controls what its result says), and **any**
    detector in a subagent transcript. These only **hold** the capture local, through the same
    `purge_detection: error` header line as a detection fault: `capture_backup.sh push` never uploads
    it, and nothing is deleted or retracted. The health line names them with an ` (unconfirmed)`
    suffix (`purge detection unconfirmed (detected by: skill (unconfirmed)) …`). When both tiers occur
    in one session the trusted tier wins and the skip line lists the union. Residual: an
    agent-originated trigger can keep one session's capture off the backup. It is held local, never
    deleted, and visible in the health line, so it is detectable, not silent.

  On a trusted match the hook writes nothing and deletes any capture an earlier `Stop` of the same session
  staged (seeded and shadow locations). The fallback id `unknown-session` never retracts (it names no
  particular session), and an id that is not a safe file name is refused on both the write and the
  delete path. The health shard gets a content-free `capture skipped: purge session (detected by:
  <sources>; earlier capture files removed: N; backup retraction requested: yes|no; backup retractions
  pending: M)` line, but only when something was removed or at `SessionEnd`. `<sources>` names only
  the detector(s): `slash command` (typed `/purge` or `$bailiwick-purge`), `sentinel`, or `config` (a
  typed name added via `capture.skip_skills`, never printed), plus any unconfirmed ones seen in the
  same session (`skill (unconfirmed)` for a Skill tool call or Codex injected `<skill>` block,
  `sentinel (unconfirmed)`, `config (unconfirmed)`). Retraction is the common path, not an edge case:
  detection reads the transcript as it stands at each `Stop`, so a session's first substantive `Stop`
  usually captures it (and may back it up) before `/purge` runs, and a later `Stop` retracts it.
  Claude Code's own transcript
  (`~/.claude/projects/…`) is outside this hook: delete it yourself (`/purge` lists it).
- **Purge-session backup retraction is ledgered, hash-only.** With backup enabled **and**
  `confidentiality_ack` true, the hook appends sha256 of both blob relpaths
  (`<machine>/<repo-key>/<session>.{jsonl,md}.gpg`) to `$BAILIWICK_HOME/backup-retract.pending`
  (mode 0600, hashes only, never synced) and runs `capture_backup.sh retract` detached, with no
  argument. The ledger is only written under its `.lock`; when that stays busy, the hashes go to a
  spool file `backup-retract.pending.spool-<time_ns>-<pid>-<n>` (same rules, renamed into place
  whole) instead of an unlocked append that a concurrent rewrite could lose. Ledger plus spools is
  the pending set, and the next locked writer folds the spools in. `retract` finds the blobs by
  hashing its own mirror tree, tombstones the hashes in `.purged`, commits `purge: <hash12>… (purge-session)`, pushes, and removes an entry only once origin
  holds its tombstone (health `purge ok (<hash12>)`). Anything left (mirror busy, offline, rejected) is
  retried first by every later `push`. No plaintext relpath is stored, because the tombstone is the
  hash itself. *Accepted residual:* anything that can write `$BAILIWICK_HOME` (an agent included) can
  list a hash there, and the guardrail-exempt `push` then retracts that blob with no sentinel ask.
  The impact is limited to the backup: the blob leaves this machine's branch tip (its ciphertext stays
  in git history) and is tombstoned, so that capture is never backed up again. The local source
  capture is untouched, but it loses off-machine durability and cross-machine `pull`.
- **A detection error keeps the capture local.** If detection fails on a record, the session is
  still captured (a wrong skip loses data), but its header gets `- purge_detection: error`, written
  before the transcript copy. Both that early header and the final one are written to `<id>.md.tmp`
  and renamed over `<id>.md` (`os.replace`, same directory), so a parallel `push` reading the header
  sees the whole old file or the whole new one, never a truncated one. `capture_backup.sh push` never backs up a capture whose header has that
  line (health `warn`) until a human reviews it and deletes the line.
- **Drill self-defence.** A drill project sets `BW_DRILL_SANDBOX` in its `.claude/settings.json`
  `env`, which Claude Code passes to hook processes (verified on 2.1.317). The variable applies only
  when `$BW_DRILL_SANDBOX/.drill-sandbox` exists **and** the project (`capture_session.py`: the
  payload's project dir; `capture_backup.sh`: `CLAUDE_PROJECT_DIR`, else the detached child's
  `BW_HOOK_CWD`, else the cwd) resolves inside the sandbox. Otherwise it is ignored with a
  content-free health `warn`, and capture and backup run normally: a stale or leaked export must never
  turn capture into a silent no-op. When it applies and the running clone is **not**
  `$BW_DRILL_SANDBOX/framework` (realpath), `capture_session.py` and `capture_backup.sh push` exit 0
  with a health `info` line, and `pull`/`purge`/`retract` print the skip to stderr and exit 3, so a
  manual run never looks successful. The real clone's global hooks therefore never capture, push,
  pull, or purge inside a drill. `capture_session.py` evaluates the variable only **after** the
  wiring gate, so a set `BW_DRILL_SANDBOX` writes no health line from sessions in unwired repos.
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
- **Commit messages and health lines carry no identifier.** Repo keys open with the repo's (often
  client-named) basename and relpaths add the session id. The backup repo's commit messages are
  plaintext that crypto-erasure cannot reach, and the health shard is aggregated fleet-wide. So every
  message uses `sha256(<name>)[:12]` instead: `capture: <machine>/<repo-hash12> <ts>`,
  `purge: <relpath-hash12> (curated)`, `purge: <hash12>… (purge-session)`, `push ok (<repo-hash12> ->
  <branch>)`, `encrypt FAILED for <file-hash12>`. Terminal echoes keep the readable name.
  **Residual:** blob **paths** keep the `<machine>/<repo-key>/<session>` layout (changing it would orphan
  every existing blob), so the tree and history of the backup repo still name repo keys. Commits made
  before this change also keep their old plaintext messages. Removing either needs the history
  rewrite in `docs/history-purge.md`.
- **Tombstones merge as a union.** When a push rebase conflicts on `.purged` (both sides appended),
  the resolution keeps every line from both sides. Picking one side would drop the other's tombstones
  and let a later push resurrect purged ciphertext.
- **Best-effort delivery, local-first durability.** The push is **fail-open** — any encrypt / commit /
  push error `exit 0`s, so a backup never wedges a session. Ciphertext is committed to a **local
  mirror** (`~/.cache/bailiwick/capture-mirror`) *before* the network push; an unpushed commit is
  retained (the mirror is **never reset to origin**) and rides along on the next successful push. The
  raw transcript is also written to local disk first (by `capture_session.py`), so a failed backup
  never loses the capture — only its **off-machine copy** lags. Cadence: throttled on `Stop`
  (`throttle_minutes`), forced on `SessionEnd` — but `SessionEnd` firing is itself best-effort (an
  abrupt crash / force-quit may skip it; the throttled `Stop` pushes and the local transcript cover
  that gap). `Stop` hooks run under the 600 s per-hook default, but Claude Code gives **all
  `SessionEnd` hooks ~1.5 s in total** (`CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS`) and cancels them
  past it (`Hook cancelled`). A network push can't fit, so on `SessionEnd` the script detaches a
  background child (`setsid nohup`, output to `/dev/null`) and exits at once; the child waits
  `BW_BACKUP_SETTLE_S` (default 3 s) for the parallel `capture_session.py` write, then pushes, and
  its outcome lands in the health log, not the terminal. A mirror lock
  (`~/.cache/bailiwick/capture-mirror.lock`, taken over when stale after 10 min) serialises it with
  the next `Stop` push (which skips rather than waits) and with `/curate` `pull`/`purge`.
  `BW_BACKUP_SYNC=1` forces the foreground path (tests, manual runs).
- **Detectability caveat (silent remote drift).** The push tracks whether a capture was **encrypted**
  (a per-file `.gpg.sha256` sidecar), not whether it was **pushed**, so an encrypted-but-unpushed blob
  is never re-encrypted. It is still retried: any later `push` past the throttle drains a mirror that
  is **ahead** of origin (sending the whole unpushed local history) even when nothing new was
  encrypted. The lag therefore only persists when **no further hook push runs at all** after a failed
  one — the remote copy then lags silently while the local mirror stays complete. Push success
  (last-success + unpushed-commit count) is surfaced by `/metrics` and the SessionStart health nag.

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
