# History purge — the thorough procedure

`/purge` de-identifies **working trees**. Git history is a separate, deliberate operation — this
runbook is the "we actually need it gone" path the skill's `--history` flag points at. Everything
here is run **by the operator, by hand** (ADR-008: the skill outputs commands, never executes a
history rewrite), because every step below changes commit hashes or destroys keys, and both break
every clone in the fleet.

**Read this whole page before running anything.** The ordering is load-bearing.

---

## 0. Preflight — never destroy what hasn't been curated

History rewrite and key destruction are unrecoverable. Un-curated captures anywhere in the fleet
are knowledge that has not been distilled yet — destroy the history/keys first and it is gone.

```bash
bash scripts/purge_verify.sh preflight
```

This blocks (exit 1) while: this machine's inbox / shadow staging / allowlisted repos hold pending
captures, or **any `capture/*` branch of the backup repo still carries ciphertext blobs**. It also
lists every machine seen in the health shards — their *local-only* staging is invisible from here,
so before proceeding, each listed machine must confirm its own SessionStart nag / `doctor` is
clean. Freeze new work fleet-wide (no sessions in wired repos) until you finish.

Run everything on this page from a **plain shell whose history is not saved** (`bash --norc`, then
`unset HISTFILE`). The commands carry the tokens, and an agent session or a saved shell history
would record them again. `bash --norc` skips your profile, so set `BAILIWICK=<path to the clone>`.

Write the tokens **once**, to a private temp file that every command below reads. No token is
regex-escaped by hand. `scripts/purge_scrub.py` (the matcher `/purge` uses everywhere) derives the
grep patterns and the filter-repo expressions from it. A token of 4 characters or fewer matches
only on alphanumeric boundaries, so `adi` never rewrites "loading"; longer tokens match as
case-insensitive substrings:

```bash
T=$(mktemp) && chmod 600 "$T"
printf '%s\n' '<id>' '<org-token>' '<org name>' > "$T"     # plus every variant /purge Step 3a found
python3 -I "$BAILIWICK/scripts/purge_scrub.py" ere   --tokens "$T" --out "$T.ere"    # for grep -iE -f
python3 -I "$BAILIWICK/scripts/purge_scrub.py" exprs --tokens "$T" --out "$T.expr"   # for filter-repo
```

Remove all three (`rm -f -- "$T" "$T.ere" "$T.expr"`) once §4 verifies.

Then measure the starting state, so "after" means something:

```bash
bash scripts/purge_verify.sh residual --tokens-file "$T" \
  --backup-path <machine>/<repo-key>/        # repeat per matched subtree from /purge Step 2
```

## 1. Knowledge repo — choose ONE of two paths

Back up first, off-machine: `git clone --mirror . ../pre-purge-backup.git` (and delete that backup
when the procedure is verified — it is itself a copy of everything you are removing).

### Path A — surgical rewrite (keep history, remove the identifiers)

Use when the history is worth keeping and only the client must vanish. Run it in a **fresh
clone**: filter-repo refuses to run elsewhere, so don't reach for `--force` in your working clone.

It runs as **two passes, in this order, in the same fresh clone**:

```bash
# Pass 1: file contents, and commit and tag messages (one expressions file feeds both flags)
git filter-repo --replace-text "$T.expr" --replace-message "$T.expr"
# Pass 2: token-named paths
git filter-repo --path knowledge/clients/<id>/ --path definitions/clients/<id>/ \
  --path-glob '*<id>*' --path-glob '*<org-token>*' --invert-paths
```

Three surfaces, three mechanisms. None of them covers another's:

- **File contents** (pass 1): `--replace-text`. It rewrites blob contents only, **not** commit
  messages and **not** file names.
- **Commit and tag messages** (pass 1): `--replace-message`, fed the same expressions file. Use a
  real file: a `<(…)` process substitution can be read only once, so it cannot feed both flags.
- **File and directory names** (pass 2): path filtering. `--path-glob '*<tok>*' --invert-paths`
  drops every path containing a token. Globs are case-sensitive, so add one per case variant found
  by `/purge` Step 2. Use `--path-rename OLD:NEW` for a path whose history you keep. Preview first:
  `git log --all --name-only --format= | sort -u | grep -ciE -f "$T.ere"` (drop `-c` to see the
  paths). A glob is a plain substring, so a short token can match unrelated paths. Use
  `--path-rename` for those.

Branch and tag *names* carrying a token are renamed by hand. Every commit hash after the earliest
touched commit changes. Flag names follow the git-filter-repo manual. Verified 2026-11-03 (git 2.53)
as the two invocations above: pass 1 (`--replace-text` plus `--replace-message`) rewrites contents
and messages, then pass 2 (`--path …`/`--path-glob …` with `--invert-paths`) removes token-named
paths. It can run without installing: `uvx --from git-filter-repo git-filter-repo`. **Caveat:** it
aborts with `ValueError: dictionary update sequence element … has length 1` when any git config value
spans multiple lines (e.g. a shell-function alias in `~/.gitconfig`). Prefix each pass with
`GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1` (it needs no user config).

**Post-rewrite checks.** Each must print `0`:

```bash
git log --all --format=%B                          | grep -ciE -f "$T.ere"  # messages
git log --all --name-only --format=                | grep -ciE -f "$T.ere"  # paths
git for-each-ref --format='%(refname) %(contents)' | grep -ciE -f "$T.ere"  # ref names, tag messages
```

### Path B — orphan squash (remove ALL older commits)

Use when the whole history should go — simplest, strongest for the knowledge repo, and the right
default when the library's current state is all that matters (the working tree is already clean
after `/purge`, so squashing keeps exactly the clean state and drops every pre-purge revision):

```bash
git checkout --orphan fresh
git add -A
git commit -m "knowledge: library state after purge ($(date +%Y-%m-%d))"
git branch -M fresh main
git reflog expire --expire=now --all && git gc --prune=now --aggressive
```

One commit, no history, nothing to recover locally. Note what you lose: blame/provenance for every
topic, and telemetry's commit-dated context — the library files themselves are unaffected.

### Push and re-point the fleet (both paths)

```bash
git push --force origin main
```

Then, on **every satellite**: **re-clone — never pull.** A fetch/merge resurrects the old objects
into the new clone. The one-liner per machine:

```bash
mv bailiwick-private bailiwick-private.old && git clone <origin-url> bailiwick-private \
  && cp bailiwick-private.old/.bailiwick-sync.json bailiwick-private/ \
  && rm -rf bailiwick-private.old   # after doctor passes
```

Run `scripts/doctor.sh` in each new clone (hooks must point at it — re-run
`bootstrap.sh --install-tools` since the path likely changed under it). Delete any open
`sync/<machine>` branches/PRs first — they pin pre-rewrite objects and can no longer merge.

## 2. Backup repo (the ciphertext) — crypto-erasure is the RECOMMENDED path

`git filter-repo` on the holding repo (`--path <machine>/<repo-key>/ --invert-paths`, force-push,
every machine deletes its capture-mirror at `~/.cache/bailiwick/capture-mirror` so it re-clones)
works — but it can never chase copies you don't control. **Key destruction can.** Old ciphertext
anywhere — satellite mirrors, repo backups, forgotten clones — is unrecoverable once the private
key is gone:

1. Generate a new keypair on the curating machine; distribute the new PUBLIC key to every
   satellite (`gpg --import`), update `gpg_recipients` in every machine's `.bailiwick-sync.json`.
2. Re-encrypt the **retained** blobs (the ones you are keeping) to the new key:
   pull → decrypt → re-encrypt → replace on the branch. The preflight already proved everything
   pending was drained, so this set is small or empty.
3. Verify every retained blob decrypts with the NEW key alone.
4. **Destroy the old private key** — `gpg --delete-secret-keys <old-fpr>` on the curating machine,
   plus every backup of that key (paper, password manager, disk images). This is the erasure.
5. Rewrite the holding-repo history (step above) when the client's **repo key** is itself a token.
   Otherwise this step is optional hygiene. Key destruction erases contents only. Blob **paths**
   (`<machine>/<repo-key>/<file>.gpg`) and the backup repo's **commit messages**
   (hashed: `capture: <machine>/<repo12> <ts>`, `purge: <rel12> (curated)`, `purge: <h12> …
   (purge-session)`, written by `hooks/capture_backup.sh`) are plaintext. The paths name the repo;
   the messages no longer do. In that case run the same two passes as §1 on the backup repo:
   pass 1 `--replace-message "$T.expr"` (the blobs are ciphertext, so `--replace-text` has nothing
   to find), then pass 2 `--path <machine>/<repo-key>/ --invert-paths` per matched subtree. Then run
   the §1 post-rewrite checks against the backup repo.

## 3. Host-side residuals (GitHub)

A force-push does **not** erase the old objects from the host:

- Unreachable objects remain **fetchable by SHA** until server-side GC (timing not yours to
  control), and cached diff/commit views can persist.
- **`refs/pull/*` never move**: every merged/closed PR pins its pre-rewrite objects permanently.
  `scripts/purge_verify.sh residual` counts these for you.

For guaranteed removal, contact the host's support (GitHub: request a manual GC + cached-view
purge for the repository, referencing the rewritten refs). Until confirmed, the honest claim is
"removed from all refs we control", not "removed from the host".

## 4. Verify, then claim the tier

```bash
bash scripts/purge_verify.sh residual --tokens-file "$T" \
  --backup-path <machine>/<repo-key>/        # every token and variant in "$T"
```

The residual does not read commit messages, file names, or ref names. Run the §1 post-rewrite
checks on every rewritten repo as well. All-clean output from both is what lets `/purge --attest`
claim **Fully erased** (ADR-008 erasure tiers: derive the tier from *verifiable state*, never from
an operator assertion). Two further conditions hold the claim at **De-identified**: any `/purge`
Step 5b host-state item (session transcripts, `file-history/`, `history.jsonl` lines) still in
place, or any surface left `not checked`. Anything less stays **De-identified**. Delete the
pre-purge mirror backups from step 1 last — after verification, they are the only remaining copy —
and then the token files from §0.
