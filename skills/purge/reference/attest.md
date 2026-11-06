# /purge reference: the attestation (`--attest`, Step 7)

Detail for `skills/purge/SKILL.md` Step 7. It produces a record that a scrub happened *without
re-creating the identity you just removed*. It is an **engineering record of what was mechanically
done, not a legal or compliance assurance**, and it never asserts legal sufficiency. `$W` is
`${BAILIWICK_HOME:-$HOME/.bailiwick}/purge-work`; spell it out in commands.

## 1. Verification re-scan

`$W` was removed at Step 5.7. Recreate it exactly as Step 1.4 does (0700; `tokens` with every 3a
variant; `tokens.ere`). Every re-scan below is count-only and reads `$W/tokens.ere`, so no token is
on a command line.

Re-run the Step 2 scan across **every** surface (`scan.md`): the library, `INDEX`, `## Related`,
telemetry, local and central captures (origin and unstamped passes), **the guardrail audit log, the
health shards (local and `health/remote/`), `.bailiwick-inbox/`, the host agent state under `$CC`**,
and the encrypted backup (below).

**Backup: stream-decrypt, never `pull`.** `capture_backup.sh pull` decrypts the whole pool into
`.bailiwick-inbox/raw/` and re-materialises `health/remote/`, refilling surfaces Step 5.7 just
cleared. Instead, clone the backup repo into `$W` (0700), decrypt each blob to a pipe, count blobs
that match, and delete the clone in the same command. No plaintext touches the disk. Capture blobs
and health blobs are counted separately. This is the last re-scan, because it removes `$W`:

```bash
W="${BAILIWICK_HOME:-$HOME/.bailiwick}/purge-work"; if [ -z "${GPG_TTY:-}" ] && t=$(tty 2>/dev/null); then export GPG_TTY="$t"; fi; R=$(python3 -I -c 'import json,sys; print((json.load(open(sys.argv[1])).get("capture_backup") or {}).get("repo") or "")' "$BAILIWICK/.bailiwick-sync.json"); if [ ! -s "$W/tokens.ere" ]; then echo "no tokens.ere: not checked"; elif [ -z "$R" ]; then echo "backup disabled"; elif ! git clone -q --mirror "$R" "$W/backup"; then echo "clone-failed"; else for ref in $(git -C "$W/backup" for-each-ref --format='%(refname)' refs/heads); do git -C "$W/backup" ls-tree -r --name-only "$ref" | grep '\.gpg$' | while IFS= read -r rel; do echo blobs; if pt=$(git -C "$W/backup" show "$ref:$rel" | gpg --quiet --decrypt 2>/dev/null); then echo decrypted; printf '%s\n' "$pt" | grep -qiE -f "$W/tokens.ere"; g=$?; if [ "$g" -eq 0 ]; then case "$rel" in health/*) echo health;; *) echo capture;; esac; elif [ "$g" -ge 2 ]; then echo grep-error; fi; else echo decrypt-failed; fi; done; done | sort | uniq -c; fi; rm -r -- "$W"
```

Decryption must be able to unlock the private key: when `GPG_TTY` is unset and the shell has a
terminal, the command exports it (as `capture_backup.sh` does) so a terminal pinentry can prompt. It
exports nothing without a terminal: `tty` then fails and prints `not a tty`, which must never become
the value of `GPG_TTY`. The command never passes `--batch` or
`--no-tty` to the decrypt. The gpg exit status is taken **per blob** (the exit status of the
`pt=$(… | gpg --decrypt)` substitution is gpg's, the last command of that pipeline; this is
portable across bash and zsh, where `PIPESTATUS` is not), and the plaintext stays in memory, never on
disk.

It prints `<n> blobs`, `<n> decrypted`, and, when non-zero, `<n> capture`, `<n> health` and
`<n> decrypt-failed` and `<n> grep-error`. Read it strictly:

- `no tokens.ere: not checked`: `$W/tokens.ere` is missing or empty, so nothing could be matched.
  Record the backup surface as `not checked (no tokens.ere)`, never `0`; recreate `$W` and re-run.
- `backup disabled`: record the backup surface as `not checked (backup disabled)`.
- `clone-failed`, **any** `decrypt-failed`, or `blobs` present with `decrypted` absent or lower than
  `blobs` (a locked key, no TTY, a wrong machine's key): record `not checked (decrypt failed on <n>
  blob(s))`, **never `0`**. A failed decrypt reads as "no match" to `grep`, so counting it as clean
  would turn a locked key into a false de-identification claim. Unlock the key (run `gpg --decrypt` on
  one blob in a terminal) and re-run from the `$W` recreation.
- **Any** `grep-error` (`grep` exit 2 or higher: an unreadable `tokens.ere`, a bad pattern): record
  `not checked (grep error on <n> blob(s))`, never `0`. `grep -q` exits 1 for "no match" and 2 or
  higher for an error, and only the 1 means clean.
- Only `decrypted` equal to `blobs` with no `capture`, `health` or `grep-error` line is a `0` for the
  backup.
  No `blobs` line at all (an empty backup) is also `0`.

A `health` hit is another machine's shard that still carries identifiers. Per the rule below it is a
non-zero surface. This command's only guarded part is the token-free `rm -r`, so no re-scrub is
needed afterwards.

Record each surface as `tool`, `manual`, or `not checked` (Step 5a.1), with its residual count. A
surface left `not checked` is named as such in the attestation, never reported as a clean scan, and
blocks deriving the tier. A credible attestation shows **0 residual hits** for every token. If any
surface is non-zero, **STOP and report; do not attest.**

**What this session cannot verify.** The purge session's own host state (Step 5b) cannot be clean
while the session is live, and the 5b user block and any Step 6 commands run only after it ends. So
the in-session attestation never asks for, or records, a confirmation that they ran. It lists them
as **"pending user action (printed below)"**:

- `projects/<proj>/<sid>.jsonl` and the `projects/<proj>/<sid>/` directory;
- `file-history/<sid>/`, which holds the pre-edit copies of the ABSTRACT rewrites;
- the matching `history.jsonl` lines;
- the listed `paste-cache/`, `plans/`, `todos/`, `shell-snapshots/`, `session-env/`, and `debug/`
  entries;
- with `--history`, the Step 6 rewrite and crypto-erasure commands.

The session's capture and backup blob must still verify as removed (`host-state.md` §4).

## 2. Derive the tier from verified state, never assert it

In the purge session the tier is **`de-identified`**: host state and any history rewrite are still
pending. `fully erased` can only be derived in a later session (§5), once the backup-history rewrite
has run on all remotes and/or the gpg key is destroyed (SKILL.md Step 6 tiers), and the re-scan,
host state included, reads 0. Check what you can, and default to the conservative tier.

## 3. (A) Client-facing attestation: a draft, never sent

A Markdown **draft** from `knowledge/templates/purge-attestation-template.md`:

- the client (named: it is for them), the request reference and date, the operator;
- per-surface scope and counts;
- the abstract-vs-delete method and what generic know-how was retained, **stated as fact, flagged for
  the client's legal review, never asserted as lawful**;
- the honest caveats: the derived tier, ciphertext in history unless erased, the scope boundary (this
  fleet only), the items pending user action, and **not legal advice**;
- the verification re-scan result.

Treat it like a capture: **hand it over, do not retain it**. It re-identifies the client.

## 4. (B) Internal audit stub: retained, non-reversible

A record that *a* purge ran, without being a client dossier: a **salted hash** of the client token
(store the salt separately from the stub), the timestamp, the knowledge-cleanup commit SHA,
per-surface counts, the derived tier, and the method version. **No client name, no removed
content.** Write it to `$BAILIWICK_HOME/purge-audit/`, **outside** the telemetry-tracked library,
never in the shared brain. Compute the hash from `$W/tokens` with a command that prints only the
hash.

Output-only, like `--history`: draft (A) for human review and signature, and write (B). The skill
never sends anything.

## 5. Upgrading the tier later: a fresh `/purge --attest` session

After the user has run the 5b user block (and, for `fully erased`, the Step 6 rewrite and/or key
destruction), a tier upgrade is a **new** session, started from the clone with
`BAILIWICK_SHADOW=1 claude`, that runs **only** Step 1.1 (the sentinel, first), 1.2, and Step 7.

- The user writes `$W/tokens` **from a plain shell** before the session starts (create `$W` with
  `umask 077`). The session generates `tokens.ere` but never reads or prints the tokens, so its own
  transcript holds no identifier.
- In that session the user confirms which of the pending items they ran. The confirmation is
  recorded, but it does not replace the scan: the `$CC` re-scan (this live session included) and
  every other surface must read 0, along with `residual` and the `docs/history-purge.md` post-rewrite
  checks for `fully erased`.
- Draft (A) with a `<CLIENT>` placeholder that the user fills in outside the session. Update (B) with
  the new tier.
- Then print this session's own `host-state.md` §5 block as well, as hygiene.
