# /purge reference: the scan (Step 2) and what the residual measures (Step 5a.1)

Detail for `skills/purge/SKILL.md` Steps 2 and 5a.1. `$W` is
`${BAILIWICK_HOME:-$HOME/.bailiwick}/purge-work`; spell it out in commands. Every search here is
list-only or count-only, with the boundary-aware patterns: `grep -rlIiE -f "$W/tokens.ere" <dirs> |
wc -l`. Never print matched lines.

## Surfaces (report a count for each)

1. **`clients/<from>/`** subtree in `knowledge/`.
2. **`$BAILIWICK/definitions/clients/<from>/`**, the client's document build specs (ADR-011). It is
   outside `knowledge/` and may hold binaries (draw.io, fonts, logos): count files, do not grep them.
3. **Scoped files:** files carrying `scope: client:<from>` (or `external:<from>`).
4. **Telemetry:** `.telemetry.json` `distinct_projects_used[]` entries containing the id.
5. **Inline mentions** of any token across `knowledge/` (topics, patterns, context), `INDEX.md`, and
   `## Related` links.
6. **Captures, enumerated by origin stamp, not path.** A repo basename can be shared by two clients,
   so a path prefix over- or under-matches.
   - local `.bailiwick-outputs/`: `raw/`, the manual and `learn-*.md` captures at its top level, and
     the curate-retired `.curated/` and `raw/.curated/`;
   - central `$BAILIWICK_HOME/captures/*/` (the same four places under each `<repo-key>/`): match
     each capture `.md` header's `origin_remote`;
   - the encrypted backup branch **across every machine**: run
     `bash $BAILIWICK/hooks/capture_backup.sh pull`, then match each decrypted capture's
     `origin_remote`. Record the matched blob rel-paths (`<machine>/<repo-key>/<file>.gpg`) for
     Step 5.6. Blobs are per-machine, so a client used on several machines has blobs under several
     `<machine>/` subtrees. The pull decrypts the whole pool into `.bailiwick-inbox/raw/`, so this run
     adds the client's plaintext there too (removed in Step 5.6).
7. **Unstamped captures:** a second, content-based pass over the same capture sets (local raw,
   central, decrypted pool) for captures that origin matching misses: no `origin_remote` header, or
   client work done from a generic repo. Report how many files match by content but not by origin.
8. **The `org-shorthands.md` registry row.**
9. **Machine-local operational logs.** They are outside `knowledge/` and easy to miss, but both hold
   client identifiers in plaintext, and an attestation that omits them is false.
   - `$BAILIWICK_HOME/guardrail-audit.log` (default location): every ask/deny line carries the
     **absolute project path** and the first 500 chars of the raw command, so project names, bucket
     URIs, and hostnames appear verbatim. `fetch-deny*` lines from the freshness fetch guard carry the
     agent name and a URL host plus hash instead. This run adds lines of its own, which is why the
     scrub comes last (Step 5.7).
   - `$BAILIWICK_HOME/health/*.jsonl` **and** `health/remote/*`: health detail strings embed repo keys
     and push targets. `capture_backup.sh pull` re-materialises remote shards, so scrub the local
     shards *and* note that the encrypted `health/<machine>.jsonl.gpg` blobs on the backup branch
     carry the same identifiers until the branch history is rewritten (`--history`).
10. **`$BAILIWICK/.bailiwick-inbox/`:** decrypted plaintext captures from the cross-machine pool, left
    behind if a previous `/curate` did not clear them. Gitignored, but still on disk.
11. **A leftover `$BAILIWICK_HOME/purge-work/`** from an earlier, unfinished run (found at Step 1.4;
    file count only).
12. **Host agent state:** all of `$CC`, not only transcripts. Count it with `host-state.md` §2, and
    record this session's `<proj>` and `<sid>` with §3. The skill only reports this surface; the user
    deletes after the session ends (Step 5b). For client work done in Codex, Gemini, or Copilot, ask
    the user where those tools keep sessions (not verified here).
13. **(with `--history`)** commits whose message, diff, or file path contains a token, and branch or
    tag names that contain one.

## What `purge_verify.sh residual` measures (Step 5a.1)

It measures the case-insensitive text contents of **tracked** files, `git log -S` diffs on all refs
(`-G` with a boundary pattern for tokens of 4 characters or fewer), origin `refs/pull/*`, and backup
ciphertext by **path**. It does **not** read file or directory names, commit messages, branch or tag
names, binary files, or anything untracked or gitignored (local and central captures,
`.bailiwick-inbox/`, the audit log, health shards, host agent state), and it cannot see encoded
variants. Cover those with the list-only searches above and
`git ls-files | grep -ciE -f "$W/tokens.ere"`.

Record each surface as `tool` (the residual measures it), `manual` (name the list-only search that
ran), or `not checked`.
