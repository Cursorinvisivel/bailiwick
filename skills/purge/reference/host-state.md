# /purge reference: host agent state and the user-run block

Mechanics for `skills/purge/SKILL.md` Step 2 (host-state surface) and Step 5b. The gates live in
SKILL.md; this file holds the commands. `$CC` is `${CLAUDE_CONFIG_DIR:-$HOME/.claude}`, `$W` is
`${BAILIWICK_HOME:-$HOME/.bailiwick}/purge-work`. Spell both out in every command, because shell
state does not persist between tool calls. `$W/tokens.ere` is the boundary-aware pattern file from
Step 1.4: a token of 4 characters or fewer matches on alphanumeric boundaries only.

## 1. What Claude Code keeps under `$CC` (verbatim)

- `projects/<proj>/<sid>.jsonl` is the transcript. The `projects/<proj>/<sid>/` directory holds
  `subagents/agent-*.jsonl`, `.meta.json`, and `tool-results/`.
- `file-history/<sid>/` holds pre-edit copies of every file the session edited. Once Step 5.1 runs,
  that includes the "before" side of every ABSTRACT rewrite.
- `history.jsonl` holds every prompt typed, in all projects, one JSON line each.
- `paste-cache/`, `plans/`, `todos/`, `shell-snapshots/`, `session-env/`, `debug/`.

Earlier client work lives here. So does this purge session, including each reviewer and Advisor
dispatch. The hook cannot reach any of it, and the skill never deletes it (hard rule). For client
work done in Codex, Gemini, or Copilot, ask the user where those tools keep sessions; their stores
are not verified here.

## 2. Inventory: count only, per top-level entry (Step 2)

`projects/` subdirectory names are the mangled working directory, so they embed repo names. Never
print them from inside the session. This loop prints only top-level entry names and counts:

```bash
CC="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"; E="${BAILIWICK_HOME:-$HOME/.bailiwick}/purge-work/tokens.ere"
for d in "$CC"/*; do
  c=$(grep -rlIiE -f "$E" -- "$d" 2>/dev/null | wc -l)
  n=$(find "$d" 2>/dev/null | sed 's|.*/||' | grep -ciE -f "$E")
  printf '%s\tfiles=%s\tnames=%s\n' "${d##*/}" "$c" "$n"
done; grep -ciE -f "$E" "$CC/history.jsonl"   # lines, not files
```

## 3. This session's `<proj>` and `<sid>`

Claude Code names `projects/<proj>/` after the session's working directory. It replaces every
non-alphanumeric character with `-` (`/home/u/bailiwick` becomes `-home-u-bailiwick`). Started from
the Bailiwick clone (SKILL.md, "Run location"), `<proj>` carries no client name. The id is the
newest `.jsonl` there:

```bash
P="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects/$(pwd | sed 's/[^A-Za-z0-9]/-/g')"; ls -t "$P"/*.jsonl | head -1
```

Use `pwd -P` if the directory is missing. This naming is observed behaviour, not a framework
contract: the hooks receive `transcript_path` rather than deriving it (`hooks/capture_session.py`).
Another session in the same directory may be newer, so confirm the file is this session's:
`grep -c mark_purge_session.sh <file>` must print 1 or more. Record `<proj>` and `<sid>` for
Step 5b.

For the backup blob paths in §5, `<machine>` and `<repo-key>` come from the hooks' own code:

```bash
python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import capture_session as c, bw_common as b; print(b.machine_token(str(b.sync_config().get("machine") or "unknown")), c.repo_key(sys.argv[2]))' "$BAILIWICK/hooks" "$PWD"
```

## 4. In-session hook verification (Step 5b, count-only)

Once the Step 1.1 sentinel has run, `hooks/capture_session.py` writes nothing for this session. On
each Stop it deletes any earlier raw capture of the session (seeded and shadow dirs). With
`capture_backup` enabled it also queues a retraction of the session's blobs. Verify it; do not
assume it:

1. `grep -c 'capture skipped: purge session'` over `$BAILIWICK_HOME/health/*.jsonl`. The line is
   written only when something was removed, or at SessionEnd. So 0 mid-session is fine when (3) is
   clean. It reads `capture skipped: purge session (earlier capture files removed: N; backup
   retraction requested: yes|no; backup retractions pending: M)`.
2. With backup enabled, the pending-retraction ledger `$BAILIWICK_HOME/backup-retract.pending` and
   any spool file next to it (`backup-retract.pending.spool-*`, written when the ledger lock was
   busy) are absent or empty: `find "${BAILIWICK_HOME:-$HOME/.bailiwick}/" -maxdepth 1 -type f -name
   'backup-retract.pending*' -exec cat {} + 2>/dev/null | wc -l` prints `0` (the trailing `/`
   follows a symlinked home; `-type f` skips the `.lock` directory; no glob, so zsh prints no
   "no matches found"). Each completed retraction logs a `purge ok (<hash12>)` health line. A remaining line in the ledger or a spool
   means a retraction has not completed (for example, the mirror was busy or the push failed).
3. No `<sid>.jsonl` or `<sid>.md` remains in `<repo>/.bailiwick-outputs/raw/` or
   `$BAILIWICK_HOME/captures/<repo-key>/raw/` (`ls`).

A failure in any of these is reported, and the §5 block covers it. If detection missed the session,
a deletion made mid-session is undone by the next Stop. That is why the remedies are user-run after
the session ends.

## 5. The user-run block (Step 5b), printed every run

Print this block **every run**, whatever §4 showed. Its backup commands are idempotent and are
no-ops when backup is disabled. Substitute the tokens, `<proj>`, `<sid>`, `<machine>`, `<repo-key>`,
and the clone path. The user runs it **after ending this session and every other Claude Code
session** (each one appends to `history.jsonl`), from a plain shell whose history is not saved.
Verifying from inside an agent session records the identifiers again.

```bash
bash --norc          # then, inside it:
unset HISTFILE
BAILIWICK='<clone path>'; CC="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"; H="${BAILIWICK_HOME:-$HOME/.bailiwick}"
T=$(mktemp) && chmod 600 "$T" && printf '%s\n' '<id>' '<org-token>' '<org name>' > "$T"   # + 3a variants
python3 -I "$BAILIWICK/scripts/purge_scrub.py" ere --tokens "$T" --out "$T.ere"

# 1. Backup: drain the retraction ledger, then purge this session's blobs (both idempotent).
bash "$BAILIWICK/hooks/capture_backup.sh" retract
bash "$BAILIWICK/hooks/capture_backup.sh" purge '<machine>/<repo-key>/<sid>.jsonl.gpg'
bash "$BAILIWICK/hooks/capture_backup.sh" purge '<machine>/<repo-key>/<sid>.md.gpg'

# 2. List what still holds a token (host state, then the capture dirs as a check).
grep -rlIiE -f "$T.ere" -- "$CC"; find "$CC" | grep -iE -f "$T.ere"
grep -rlIiE -f "$T.ere" -- "$BAILIWICK/.bailiwick-outputs/raw" "$H"/captures/*/raw "$BAILIWICK/.bailiwick-inbox" 2>/dev/null

# 3. Delete this session's state. Add `rm -- <path>` lines for the matches step 2 listed in
#    paste-cache/, plans/, todos/, shell-snapshots/, and debug/, and for any leftover <sid>.jsonl or
#    <sid>.md in the raw dirs. Deleting earlier client-work state is your choice.
rm -r -- "$CC/projects/<proj>/<sid>.jsonl" "$CC/projects/<proj>/<sid>" "$CC/file-history/<sid>" "$CC/session-env/<sid>"

# 4. Redact history.jsonl in place: dry run, then apply. Lines are kept; matches become [redacted].
#    Non-ASCII tokens are also matched in their \uXXXX-escaped JSON form. The script accepts only
#    ${CLAUDE_CONFIG_DIR:-~/.claude}/history.jsonl (the $CC above), never a symlink, and refuses a
#    token under 3 characters unless --allow-short is added.
python3 -I "$BAILIWICK/scripts/purge_scrub.py" history --tokens "$T" "$CC/history.jsonl"
python3 -I "$BAILIWICK/scripts/purge_scrub.py" history --tokens "$T" --apply "$CC/history.jsonl"

# 5. Re-run step 2. It must list nothing, or only earlier work you chose to keep. Then:
rm -f -- "$T" "$T.ere"
```

Re-check §4 (2) and (3) after step 1. `capture.include_subagents: false` has no bearing on host
state; treat it as optional. Report host state as **pending user action**, never as clean.
