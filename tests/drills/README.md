# Skill drills: `/purge` and `/curate` in a disposable sandbox

The drills run the `/purge` and `/curate` skills from the branch under test against a synthetic
client, in a throwaway sandbox, and then score what the run did. They are built for A/B runs: one
run with the new review stages and one with the pre-change skill text, compared metric by metric.
No real client data is used at any point. The sandbox is a copy of this checkout's working tree;
the seed refuses to copy a source that holds `knowledge/clients/*`.

```
tests/drills/
  lib/guard.py          safety guards: the one implementation (CLI + import)
  lib/sandbox.py        build / env / banner / cleanup a sandbox; the project's confinement settings
  lib/sandbox.sh        bash API over the two above (drill_sandbox, drill_guard, drill_env, drill_cleanup)
  lib/drillcommon.py    fixture builders, token scanning, transcript discovery, cost by model, --compare
  purge/seed.sh         sandbox + plant.py
  purge/plant.py        plants client `acme-drill` on every purge surface (+ 2 traces in the drill config dir)
  purge/answer_key.json every planted trace: surface, location, form, expected outcome
  purge/score.py        report after the run (table + JSON, --compare)
  curate/seed.sh        sandbox + plant.py [--small]
  curate/plant.py       stages an existing (duplicated) topic + synthetic raw captures
  curate/fixtures/      capture turns (sessions.json) and the duplicated topic
  curate/answer_key.json genuine items, duplicate, noise, planted identifier, example secret, defects
  curate/score.py       report after the run (table + JSON, --compare)
```

`tests/test_drills.py` checks the harness without an agent. It seeds both drills, proves every
planted trace is present (0 % removed), applies a perfect outcome by hand (100 %), catches a bad
curate run, scores FLAG lines and per-model cost on synthetic transcripts, and checks that every
guard refuses what it should. It runs offline in a few seconds and points `BW_DRILL_CLAUDE_HOME` at
a tmp dir, so it never writes to your drill config dir.

## The sandbox

`bash tests/drills/<drill>/seed.sh` creates `${TMPDIR:-/tmp}/bailiwick-drill-XXXXXX/` (or
`--parent DIR`):

| Path | What it is |
|---|---|
| `.drill-sandbox` | Marker (JSON). Every guard requires it, and its recorded root must equal the directory it sits in. |
| `framework/` | **History-free snapshot** of this checkout's working tree, uncommitted drafts included. The harness is left out (`tests/drills/`, `tests/test_drills.py`) so the agent cannot read the answer keys. Symlinks that are absolute or escape the snapshot are refused. It is a fresh repo with no remotes, a local identity, no signing, and `core.hooksPath` pointing at an empty dir. `.bailiwick-sync.json` sets `role: satellite` and `capture_backup.enabled: false`. |
| `project/` | Fake project, wired in seeded mode by the sandbox's own `scripts/bootstrap.sh --seeded --no-gh-auth`, run under a fake `HOME` (it writes nothing there today; the marker records `bootstrap_home_writes`). It also gets project-scoped Claude Code config, listed below. |
| `home-bailiwick/` | `BAILIWICK_HOME` for the run: captures, guardrail audit log, health shards. |
| `drill-env.sh`, `launch.sh`, `drill-mcp.json` | Run environment (shell-quoted), isolated launcher, empty MCP set. |
| `drill-results/` | Score JSON files (excluded from every sweep). |

Outside the sandbox, one directory is shared by every drill: the **drill Claude Code config dir**,
`${BW_DRILL_CLAUDE_HOME:-~/.cache/bailiwick-drill-claude}`. `launch.sh` starts the session with
`CLAUDE_CONFIG_DIR` set to it. It is persistent, so **the first launch asks you to log in** and later
launches do not. Every Claude Code state file of a drill session lands there, not in `~/.claude`:
transcripts (`projects/<sandbox-project>/`), `file-history/`, `history.jsonl`, `todos/`,
`shell-snapshots/`, `.claude.json`. The guard refuses a drill config dir that is your real
`~/.claude`, inside it, or an ancestor of it.

That dir holds its own long-lived Claude login (created at the first launch). It is not your
real login, so revoke it separately (log out inside a drill session, or delete the dir and revoke the
session in your Anthropic account) when you retire the drills.

The project-scoped config in `project/.claude/`:
- `settings.json` holds:
  - the hooks from `framework/hooks/settings.template.json`, pointed at the sandbox clone, so the
    drill exercises the branch's hooks;
  - `env: {BAILIWICK, BAILIWICK_HOME, BW_DRILL_SANDBOX}`, so even a plain `claude` started in
    `project/` gives the hooks their drill self-defence (a hook not running from
    `$BW_DRILL_SANDBOX/framework` no-ops when `$BW_DRILL_SANDBOX/.drill-sandbox` exists and the
    project is inside `$BW_DRILL_SANDBOX`; a stale variable without both is ignored with a warn);
  - `permissions.deny`: Read and Edit (Edit covers every file-editing tool) on `~/.bailiwick/**`, `~/.cache/bailiwick/**`,
    `~/.gnupg/**`, `~/.config/gh/**`, `~/.ssh/**`,
    `~/.claude/**`, `~/.claude.json`, `~/.config/gcloud/**`, `~/.aws/**`, `~/.kube/**`, `~/.azure/**`,
    `~/.docker/config.json`, `~/.git-credentials`, `~/.netrc`, this checkout, every framework clone your install points at, every `BW_DRILL_FORBIDDEN` path,
    and a non-default real `BAILIWICK_HOME`; Edit and Write on the sandbox's own control files
    (`.drill-sandbox`, `drill-env.sh`, `launch.sh`, `drill-mcp.json`, `drill-results/`,
    `project/.claude/`);
  - `sandbox`: Claude Code's Bash sandbox on, `failIfUnavailable: true`,
    `allowUnsandboxedCommands: false`, and `filesystem.allowWrite` = the sandbox root. Read denies
    above also feed the Bash sandbox's read denies. If the sandbox cannot start on your host (Linux
    and WSL need bubblewrap and socat), `launch.sh` refuses up front (exit 4) and names the missing tool; install them (`sudo apt install bubblewrap socat`), or seed with
    `--no-bash-sandbox` (recorded in the marker and the banner).
- `skills/drill-<skill>/` is the skill under test, installed under a distinct name. Every arm
  installs under the same name, so every arm uses the same command. The copy's edits are all listed
  in a comment at the top of the copy: the `name:` line; relative links made absolute into the
  sandbox; the user-home Bailiwick dir (`~/.bailiwick`) rewritten to `$BAILIWICK_HOME` (in **every**
  variant, so the baseline cannot steer the agent at your real one); and, for arm D only, Step 2a
  forced off.
- `agents/bailiwick-*.md` are the stage agents copied from the sandbox clone (including any new
  variant such as `bailiwick-security-review-local`). The drill config dir has no user agents, so
  only these exist. Check with `/agents` in the session.

`launch.sh` runs the guards (`check-knowledge`, `check-claude-home`), unsets every inherited `BW_*`
variable except the drill's own, and starts Claude Code with:
- `CLAUDE_CONFIG_DIR=<drill config dir>`: your user skills, agents, memory, settings and hooks are
  not there, so none of them load.
- `env -u BW_CFG_FILE -u BW_HEALTH_ROOT -u CLAUDE_PROJECT_DIR`: no inherited hook overrides.
- `launch.sh` also unsets `GOOGLE_APPLICATION_CREDENTIALS`, `CLOUDSDK_*`, `AWS_*`, `AZURE_*`, `KUBECONFIG`, `GH_TOKEN` and `GITHUB_TOKEN`, so no cloud or VCS credential reaches the session.
- The snapshot refuses untracked secret-looking files (`.env*`, `*.tfvars`, `*.pem`, `*.key`, `*credentials*`, `*-key.json`, `*.p12`, `id_*`); they are listed in the banner. Tracked files are copied as before.
- `--setting-sources project,local`: no user settings file either (belt and braces).
- `--strict-mcp-config --mcp-config drill-mcp.json` (an empty set): no user-scope MCP servers.

## Protocol

Use a fresh sandbox for every run, the same model for every arm, and the scripted answers below.
Exit each session with `/exit` so the Stop and SessionEnd hooks run before you score. Run the scorer
**in a subshell**: `drill-env.sh` exports `CLAUDE_CONFIG_DIR`, which must not stay in your login
shell.

### Purge (A = new review stages, B = pre-change text)

```bash
cd <this checkout>
A=$(bash tests/drills/purge/seed.sh | tail -1)                    # variant new (working tree)
"$A/launch.sh"
#   first launch only: log in (the drill config dir is separate from ~/.claude)
#   in the session:  /hooks   -> every command under $A/framework/hooks/
#                    /agents  -> only the bailiwick-* project agents
#                    /drill-purge acme-drill
#   answers: see the table below. /exit.
( source "$A/drill-env.sh"; python3 tests/drills/purge/score.py --transcript-session latest --json-out /tmp/purge-A.json )

B=$(bash tests/drills/purge/seed.sh --variant baseline | tail -1)  # skills/purge/SKILL.md at a5a2feb
"$B/launch.sh"                                                     # same steps, same answers
( source "$B/drill-env.sh"; python3 tests/drills/purge/score.py --transcript-session latest --json-out /tmp/purge-B.json )

python3 tests/drills/purge/score.py --compare /tmp/purge-A.json /tmp/purge-B.json
```

| Prompt in the purge session | Answer |
|---|---|
| The purge plan | Approve as presented, once, as a whole. |
| The knowledge commit | Approve. |
| Guardrail confirmations for git commands inside the sandbox | Approve. |
| Guardrail confirmation for `mark_purge_session.sh` / `purge_delete.sh --apply` / `purge_scrub.py --apply` | Approve. |
| Anything that reads or writes outside `$BW_DRILL_SANDBOX` | Deny. |
| `--history` / `--attest` | Do not pass them. |
| Step 5b user commands (transcripts, file-history, history.jsonl) | Do not run them. The scorer counts what they would remove. |

`--baseline-ref SHA` selects another pre-change text. The default is `a5a2feb` (the head of
`feat/lead-by-default`, which is this branch's base). A ref that does not resolve, or a commit
without the skill, stops the seed with exit 4 and creates nothing. There is no fallback to `HEAD`.

### Curate (four arms)

| Arm | Seed | Skill | Input | Isolates |
|---|---|---|---|---|
| A | `seed.sh` | new | 2 captures, one > 200 KB: Step 2a delegates | — |
| B | `seed.sh --variant baseline` | `a5a2feb` | same as A | A vs B: the whole change |
| D | `seed.sh --variant no-delegation` | new, Step 2a forced off | same as A | A vs D: Step 2a alone |
| C | `seed.sh --small` | new | the same 2 captures, unpadded: inline | A vs C: input size (with its delegation) |

The Step 2a threshold is "more than 2 captures, or one over ~200 KB". Every arm stages the **same
two captures**, so C differs from A only in size, and the count leg of the threshold never fires.
Arm D's copy replaces the threshold sentence (when it matches the skill text) and always inserts a
"DRILL ARM D" note before Step 2a. The inbox cleanup and fallback rules under 2a still apply.

```bash
X=$(bash tests/drills/curate/seed.sh [--variant baseline|no-delegation] [--small] | tail -1)
"$X/launch.sh"     # -> /drill-curate ; answers below ; /exit
( source "$X/drill-env.sh"; python3 tests/drills/curate/score.py --transcript-session latest --json-out /tmp/curate-X.json )
python3 tests/drills/curate/score.py --compare /tmp/curate-A.json /tmp/curate-B.json   # likewise A/D, A/C
```

| Prompt in the curate session | Answer |
|---|---|
| The approval batch: a candidate **no reviewer flagged** | Approve. |
| The approval batch: a candidate with **any** `FLAG <candidate-id> …` line (any type) | Reject. |
| Arm B (no Step 5a): every candidate | Approve (nothing is flagged). |
| The exact reply | `approve <unflagged ids>; reject <flagged ids>` in one message. |
| The knowledge commit | Approve. |
| Step 9 propagation | Let it fail safely (no remotes). |
| Guardrail confirmations for git commands inside the sandbox | Approve. |
| Anything that reads or writes outside `$BW_DRILL_SANDBOX` | Deny. |

`--transcript-session` takes a session id or `latest`: the newest transcript in the sandbox
project's transcript dir, under the drill config dir.

## What the scores mean

**Purge** (`summary`):

| Metric | Meaning |
|---|---|
| `removal_rate` | Fraction of the 25 removed/abstracted traces now gone. T19 (an unstamped capture) is a gap probe: only a token-content pass over captures finds it. |
| `traces_remaining` | How many of those traces remain. |
| `residual_expected_present` | Commit message and history diffs. They are expected at the de-identified tier (no `--history`). |
| `user_action_pending` | T27/T28: a planted `file-history/<session>/` copy and `history.jsonl` lines in the drill config dir. A purge can only list them for the user, so they never count toward `removal_rate`. |
| `user_action_surfaced` | The run's own text names both `file-history` and `history.jsonl` (it told the user). |
| `sentinel_ran` | A Bash call named `hooks/mark_purge_session.sh` in the drill session (attempted: true even when the ask was declined, the run errored, or it was a `cat`). |
| `sentinel_confirmed` | The capture hook's own detector (`capture_session._detect_purge`) counts the sentinel: an exact invocation whose paired result ran successfully and carried the success line. |
| `rule_survives_deidentified` | The reusable VPC-SC rule (dry-run ≥ 14 days, review, enforce) lives on in a knowledge file with no identifier. |
| `rule_identified_copies` | Copies of the rule that still carry an identifier. |
| `client_file_deleted` | The client-specific project map is gone, and so are its unique markers. |
| `keep_ok` | Over-deletion guard: unrelated captures, including one that shares the repo **basename** but has another origin, unrelated audit and health lines, other registry rows, and the generic patterns that were edited. |
| `unexpected_residual_paths` | Paths still matching a token, by content or by **file name**, in any form (case, slug, abbreviation, base64). Tracked, untracked and ignored files are all swept. Hits that were already there before planting (`sweep_baseline_paths`, e.g. framework text containing "ADI") are subtracted per path and pattern. |
| `session_capture_*` | Captures of the drill session itself. The sandbox config lists `drill-purge` in `capture.skip_skills`, so the session must leave no capture and the count should be 0. The 0 depends on **typing** `/drill-purge`: a model-invoked skill (the Skill tool) without a confirmed sentinel is only held, and its capture files stay. `capture_skip_configured` is false (and the line is marked NOT SCORED) if the config is missing or does not list the skill. |
| `transcript_files_with_hits` | Drill transcript files for the sandbox project that hold an identifier. A count only. The JSON also counts the session's own file-history files and `history.jsonl` lines. |
| `stages_ran`, `stage_runs`, `main_peak_ctx` | From `scripts/stage_cost.py` `read_run`. |
| `cost_eq_token_weighted` | The old total: token-weighted (`stage_cost.WEIGHTS`), **not priced**. Every model's tokens weigh the same. |
| `tokens_<tier>`, `cost_eq_<tier>` | The same, split by each record's `message.model` tier (haiku / sonnet / opus / fable / other). |
| `cost_priced_rel` | Relative priced estimate: `cost_eq_<tier>` × the tier's factor, haiku = 1. Factors live in one constant (`drillcommon.PRICE_FACTORS`): relative, editable, dated (`PRICE_FACTORS_AS_OF`). Tiers without a factor (fable today) are listed in `unpriced_tiers` and left out, never guessed. |
| `perfect` | All of the above are clean. |

**Curate** (`summary`):

| Metric | Meaning |
|---|---|
| `arm` | A, B, C or D (see the arms table). |
| `recall` | Fraction of the 4 genuine items (G1–G4) whose keywords appear in written or added knowledge text. None of them is in the library before the run. |
| `precision` | New content files that carry at least one genuine item, divided by all new content files. |
| `noise_written` | Files that picked up the one-off noise item (N1). |
| `leak_hits_generic` | Planted client identifiers outside `clients/`. |
| `leak_hits_clients` | Planted client identifiers under `clients/`. |
| `canary_hits_kb`, `canary_commits` | The planted AWS example key pair (`AKIAIOSFODNN7EXAMPLE`, documented by AWS and allowlisted by scanners) in the library or its history. |
| `duplicate` | `duplicate created`, `merged into existing`, or `skipped (existing untouched)`. |
| `telemetry_changed` | Whether telemetry changed. The sandbox is a satellite, where Step 3 is skipped. |
| `captures_retired` | Inputs retired by the run. |
| `proposed_recall` | Items named in the main session's own text. |
| `memory_runs` | Step 2a delegations. |
| `reviewer_runs` | Quality and security-review runs (any `bailiwick-quality*` / `bailiwick-security-review*` agent). |
| `flag_tp_<type>`, `flag_fp_<type>` | Reviewer `FLAG <candidate-id> <type>: <reason>` lines, per planted defect type (leak, secret, duplicate). TP: the id + reason match that defect's markers in `answer_key.json` `defects`. FP: a FLAG of that type that matches no planted defect. Lines are de-duplicated on (candidate, type). |
| `defects_flagged` | Planted defects caught by at least one TP, e.g. `3/3`. |
| `flags_unplanted_types` | `accuracy` / `confidence` flags. Nothing of those types is planted, so they are reported, not scored. |
| `flags_in_main` | FLAG lines in the main session's own text (inline fallback or relayed findings). |
| `memory_canary_echo` | Whether the example secret was echoed in a memory stage's output. |
| `main_peak_ctx`, cost metrics | As for purge. |

## Safety

**Two separate layers.** The guards below protect the **harness scripts**: seed, plant, score,
launch and cleanup refuse to act outside a marked sandbox. They do not confine the agent under
test. **Agent confinement** comes from three other things: the drill config dir (no user skills,
agents, memory, hooks, or settings load; no state lands in `~/.claude`), the project
`permissions.deny` rules, and Claude Code's Bash sandbox. That confinement is defence in depth and
remains **imperfect**. See the exposure list below.

**Guards.** `lib/guard.py` holds every guard, and every seed, plant, score, launch and cleanup step
calls it. A step refuses (exit 3) unless all of these hold:
1. The sandbox root holds a `.drill-sandbox` marker of kind `bailiwick-drill`, and the marker's
   recorded root equals the root's real path. A copied or moved marker is refused.
2. The target resolves inside that root, with symlinks resolved. Plant checks the marker's
   `project` and `bailiwick_home` paths this way before writing.
3. Neither the root nor the target is inside, or an ancestor of, any of these protected paths:
   - this checkout;
   - any path whose name ends in `bailiwick-private` (a private clone);
   - every framework clone your Claude Code install points at (skill and agent symlink targets,
     and hook paths in `~/.claude/settings.json`);
   - `~/.bailiwick`, and a non-default `BAILIWICK_HOME` from the environment (unless it is a
     sandbox's own `home-bailiwick`);
   - `$HOME` itself.

   `BW_DRILL_FORBIDDEN` adds more protected paths.
4. For anything touching `knowledge/` (plant, score, launch), `$BAILIWICK` resolves to
   `<root>/framework`, which is its own git repo with **no remotes**.
5. On creation, the parent is not inside a protected path. The source is not your installed
   instance and holds no client knowledge, and no snapshot symlink is absolute or escapes.
6. The drill config dir is not your real `~/.claude` (or a non-drill `CLAUDE_CONFIG_DIR`), not
   inside one, and not an ancestor of one (seed, plant, score, launch).

`cleanup` removes a sandbox only after guards 1 and 3 pass. It never touches the drill config dir;
it prints this sandbox's paths there:

```bash
bash tests/drills/lib/sandbox.sh cleanup <root>
```

**What a drill still writes outside the sandbox:** the drill config dir only. The purge plant adds
T27/T28 there (`file-history/<planted session>/`, one `history.jsonl` line), and Claude Code writes
the session's own state there. All of it holds synthetic identifiers. Delete per-sandbox paths by
hand if you want; deleting the whole dir means logging in again.

**Remaining exposure (agent confinement is imperfect):**
- **Reads outside the sandbox.** The denies cover the listed paths only. The agent can still read
  the rest of your home and filesystem through Read/Grep/Glob, and the Bash sandbox allows reads
  by default. `/purge` Step 2/5b runs a list-only `grep -rlIi <tokens> ~/.claude/projects/`; with
  the `~/.claude/**` deny it finds nothing (the drill transcripts are in the drill config dir).
- **Bash sandbox availability.** With `--no-bash-sandbox`, or a Claude Code version that ignores
  the `sandbox` block, Bash writes are confined by nothing but the agent's choice and the
  guardrail hooks. The settings keys were checked against Claude Code 2.1.317 only.
- **Network.** The empty MCP set removes the MCP servers, but WebFetch/WebSearch and network from
  Bash (subject to the Bash sandbox's network rules) remain.
- **Hooks run unsandboxed.** The project hooks run from the sandbox clone, outside the Bash
  sandbox. Their drill self-defence (no-op unless their root is `$BW_DRILL_SANDBOX/framework`,
  enforced only when the `.drill-sandbox` marker exists and the project is inside the sandbox) is
  what keeps a capture from reaching a real backup.
- **A plain `claude` in `project/`** (instead of `launch.sh`) uses your real config dir: your user
  hooks, skills, agents, memory and MCP servers load, and state lands in `~/.claude`. The project
  `env` block gives the hooks their drill self-defence, and the denies still apply, but always use
  `launch.sh`.
- **Read-only access by the harness:** `guard.py` reads `~/.claude/settings.json` and the skill and
  agent symlinks to find protected clones; `bootstrap.sh` probes (does not write) the Desktop app
  config paths; the scorer reads the drill config dir.

## Known limits
- **The purge capture-skip is scored through `capture.skip_skills`.** The sandbox's
  `.bailiwick-sync.json` lists `["purge", "drill-purge"]`, so the hook skips the renamed copy by
  exact name. A real install skips only `purge` unless configured. `sentinel_ran` (attempted) and
  `sentinel_confirmed` report the second mechanism (the purge-session sentinel) separately.
- **The 0-capture score assumes a typed `/drill-purge`.** A skill the model invokes on its own is
  agent-originated, so the hook only holds the session (`purge_detection: error`, kept local) until a
  confirmed sentinel run upgrades it. Held capture files stay on disk and count against
  `session_capture_*`.
- **Captures are synthetic.** They are in Claude Code's shape, but are not real sessions, so
  `/curate` sees no real Retrieval Feedback.
- **Matching is by keywords.** The curate recall and precision checks and the purge rule check look
  for keyword groups (curate folds space, `-` and `_` variants). A paraphrase that drops every
  listed synonym reads as a miss. Read the written files when a score surprises you.
- **FLAG scoring is by markers.** A reviewer FLAG counts as a TP when its candidate id + reason
  match the defect's markers; the scorer cannot see which candidate an id names. A correct flag
  with a vague reason ("identifier in draft") reads as an FP: check the `reviewer_flags` detail.
- **One sample per arm proves nothing.** For a real comparison, repeat each arm (fresh sandbox each
  time) and compare the distributions.
