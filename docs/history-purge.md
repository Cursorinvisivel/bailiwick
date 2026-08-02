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

Then measure the starting state, so "after" means something:

```bash
bash scripts/purge_verify.sh residual <id> "<org token>" "<org name>" \
  --backup-path <machine>/<repo-key>/        # repeat per matched subtree from /purge Step 2
```

## 1. Knowledge repo — choose ONE of two paths

Back up first, off-machine: `git clone --mirror . ../pre-purge-backup.git` (and delete that backup
when the procedure is verified — it is itself a copy of everything you are removing).

### Path A — surgical rewrite (keep history, remove the identifiers)

Use when the history is worth keeping and only the client must vanish:

```bash
git filter-repo --replace-text <(printf '%s==>[redacted]\n' '<id>' '<org-token>' '<org name>') \
                --path clients/<id>/ --invert-paths
```

Every commit hash after the earliest touched commit changes. Commit *messages* containing the
tokens are also rewritten by `--replace-text` (message and diff both).

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
5. Optionally still rewrite the holding-repo history (step above) for hygiene — after key
   destruction it removes only undecryptable bytes.

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
bash scripts/purge_verify.sh residual <id> "<org token>" "<org name>" \
  --backup-path <machine>/<repo-key>/
```

All-clean output is what lets `/purge --attest` claim **Fully erased** (ADR-008 erasure tiers:
derive the tier from *verifiable state*, never from an operator assertion). Anything less stays
**De-identified**. Delete the pre-purge mirror backups from step 1 last — after verification,
they are the only remaining copy.
