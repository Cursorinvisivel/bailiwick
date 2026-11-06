# /purge reference: target lists, the delete step, the log scrub (Steps 4, 5.2, 5.6, 5.7)

Commands for `skills/purge/SKILL.md`. The gates live there. Shell state does not persist between
tool calls, so every command spells out its paths. None of them names a target or a token on its
command line: guarded commands are logged verbatim, before expansion, to the audit log.

## Target lists (Step 4)

With the Write tool, write **absolute, physical** paths (`pwd -P`; a path through a symlink is
refused), one per line:

- `$W/targets`: the Step 5.2 deletions (`knowledge/clients/<from>/`, `definitions/clients/<from>/`,
  and surfaced files the user chose to delete);
- `$W/targets-captures`: the Step 5.6 capture files (local and central raw captures, the manual and
  `learn-*.md` captures, their curate-retired `.curated/` copies, and the client's
  `.bailiwick-inbox/raw/` files, matched by origin, plus the unstamped ones the user chose to delete).

Show both in the plan as count and **approval hash** (unguarded). The approval hash binds the list
**and** `$W/from`: it is the sha256 of the two lines `<sha256(list)>` and `<sha256(from)>`, and
`--print-sha` prints it (no `sha256sum`/`shasum` difference to handle):

```bash
W="${BAILIWICK_HOME:-$HOME/.bailiwick}/purge-work"; for f in targets targets-captures; do wc -l < "$W/$f"; bash "$BAILIWICK/scripts/purge_delete.sh" --list "$W/$f" --from-file "$W/from" --print-sha; done
```

Then show the **dry run** of each list (the default mode, unguarded; substitute the hash just
printed):

```bash
W="${BAILIWICK_HOME:-$HOME/.bailiwick}/purge-work"; bash "$BAILIWICK/scripts/purge_delete.sh" --list "$W/targets" --from-file "$W/from" --sha <sha256>
```

It prints `line N: would delete (<kind>)` or `line N: skip (<reason>)`, never a path. A `skip` in the
dry run is resolved in the plan (fix the line, or drop it) before approval. Approval covers exactly
these counts and hashes.

## The delete step (Steps 5.2 and 5.6)

`scripts/purge_delete.sh` with `--apply`, the **approved** sha256 on the command line, and the list
`targets` (5.2) or `targets-captures` (5.6):

```bash
W="${BAILIWICK_HOME:-$HOME/.bailiwick}/purge-work"; bash "$BAILIWICK/scripts/purge_delete.sh" --list "$W/targets" --from-file "$W/from" --sha <approved-sha256> --apply
```

The script first copies the list and `$W/from` into a private temp dir and works only on that copy.
It re-hashes the copy and, **on a mismatch with the approved sha256, deletes nothing and exits 1**:
the list or `$W/from` changed after approval; STOP. It reads `<from>` from `$W/from`, so neither the
targets nor the token appear on the command line, and it prints line numbers only (the output of
`git rm`/`rm` is discarded, because it would name the path). Before
classifying a line it refuses: empty or relative lines; `..`, `.`, or empty (`//`) path components;
glob characters (`*`, `?`, `[`); symlinks, including a symlinked directory given with a trailing
slash; and a path whose parent directory is reached through a symlink. Every git call uses
`--literal-pathspecs`, so no line is ever read as a pathspec glob. The allowed roots:

- `knowledge/clients/<from>/` and `definitions/clients/<from>/`, tracked or not (`git rm -r`, then
  `rm -r` for untracked leftovers);
- a single **tracked** `knowledge/**/*.md` file outside `knowledge/clients/` whose frontmatter has
  `scope: client:<from>` (a surfaced file the user chose to delete; `git rm`, recoverable from git).
  Another client's `clients/<other>/` and any other `definitions/` path are always refused;
- capture `.jsonl` and `.md` files, regular files only, **directly** inside one of the `/curate`
  gather or retire directories (a deeper subdirectory is refused; the list decides which origin):
  local `<repo>/.bailiwick-outputs/` (seeded manual and `learn-*.md` captures), `.bailiwick-outputs/raw/`,
  `.bailiwick-outputs/.curated/`, `.bailiwick-outputs/raw/.curated/`; central
  `$BAILIWICK_HOME/captures/<repo-key>/` (shadow manual and `learn-*.md` captures), `<repo-key>/raw/`,
  `<repo-key>/.curated/`, `<repo-key>/raw/.curated/` (`<repo-key>` is one path component);
- regular files under `.bailiwick-inbox/`.

**Exit codes:** `0` done (dry run, or every line deleted or skipped); `1` the whole list refused
(hash mismatch, bad `<from>`, unreadable list), nothing deleted; `2` usage; `3` one or more lines
printed `line N: FAILED (<kind>: <reason>)` under `--apply` (for example `git rm` refusing a tracked
file with local changes). The summary reads `N deleted, M failed, K skipped`. **On exit 3, STOP:**
do not commit (5.5), delete captures, or purge backup blobs (5.6); report the FAILED line numbers and
reasons, resolve each with the user (a new plan line, a new approval hash), and re-run. Report every
`skip` line in the run card. Never retry a skipped or failed path by naming it on a command line.
Its tests are `tests/shell/test_purge_delete.sh`.

**Guardrail note.** The `rm` calls run inside the script, so the generic `rm -r` pattern does not
see them; `hooks/guardrails.py` has its own ask-impact pattern for `purge_delete.sh … --apply`, so
the user re-confirms at run time (the prompt shows the bound hash). The plan approval still comes
first: never run `--apply` before it.

## Backup blobs (Step 5.6)

Per matched rel-path from Step 2, sweeping every `<machine>/` subtree:
`bash $BAILIWICK/hooks/capture_backup.sh purge <machine>/<repo-key>/<file>.gpg`. Purge by the
matched rel-paths, never by a guessed path. `capture_backup.sh` is exempt from the guardrails, so
these lines are neither confirmed nor audited. Each purge removes the blob from the current backup
tree, **not** from the backup repo's git history (ciphertext stays there until that history is
rewritten or the gpg key is destroyed). It also adds a plaintext backup-repo commit message,
`purge: <rel12> (curated)`, which names the blob by hash; the blob path itself still names the repo.

## The log scrub (Step 5.7)

1. Redact in place. Lines are kept and matches become `[redacted]`. Counts are printed per token
   index, never the tokens or the lines. `scrub` is a **dry run by default**: run it first to show
   the counts, then the same command with `--apply` for the atomic rewrite (the `--apply` run
   re-confirms through the guardrail):

   ```bash
   H="${BAILIWICK_HOME:-$HOME/.bailiwick}"; python3 -I "$BAILIWICK/scripts/purge_scrub.py" scrub --tokens "$H/purge-work/tokens" "$H/guardrail-audit.log" "$H"/health/*.jsonl "$H"/health/remote/*
   H="${BAILIWICK_HOME:-$HOME/.bailiwick}"; python3 -I "$BAILIWICK/scripts/purge_scrub.py" scrub --apply --tokens "$H/purge-work/tokens" "$H/guardrail-audit.log" "$H"/health/*.jsonl "$H"/health/remote/*
   ```

   A `NOT rewritten` line means the file changed during the scrub (another session ran): re-run.
   The encrypted `health/<machine>.jsonl.gpg` blobs keep the identifiers until the backup history is
   rewritten (Step 6), and the next `pull` re-materialises them into `health/remote/`.

2. Re-scan, count-only. Each command must print `0`:

   ```bash
   H="${BAILIWICK_HOME:-$HOME/.bailiwick}"; E="$H/purge-work/tokens.ere"
   grep -ciE -f "$E" "$H/guardrail-audit.log"
   grep -rlIiE -f "$E" -- "$H/health" | wc -l
   grep -rlIiE -f "$E" -- "$BAILIWICK/.bailiwick-inbox" 2>/dev/null | wc -l
   ```

3. Remove `$W`: `rm -r -- "${BAILIWICK_HOME:-$HOME/.bailiwick}/purge-work"`. It is guarded and carries
   no token, so its audit line is harmless.
