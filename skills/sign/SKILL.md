---
name: sign
description: Create a GPG-signed git commit end to end — scope the staged change, draft a Conventional Commits message, pre-flight it against the framework's AI-attribution guardrail, handle the pinentry unlock handshake, commit with -S, and verify the signature actually verifies. Use whenever the user asks for a signed commit, says "commit and sign it", or a repo requires signed commits. Works in any repo, not just Bailiwick-wired ones. Commits only — never pushes, never opens a PR.
---

# /sign — verified signed commit, no agent signature

A signed commit fails in two quiet ways: the signing key never engages (you get an ordinary
commit and nobody notices until a branch protection rule does), or **pinentry blocks on a TTY
the agent does not have** and the tool call hangs until timeout. This skill removes both, and
enforces the framework's attribution rule *before* the commit rather than at the guardrail.

**Never pushes.** Publishing is a separate, explicitly-authorised step.

## Step 0 — can this repo sign at all?

```bash
git config user.name && git config user.email
git config user.signingkey || echo "NO SIGNING KEY"
git config commit.gpgsign  || echo "(not auto — -S must be explicit)"
```

No `user.signingkey` → stop and ask which key to use. Do not guess, and do not fall back to an
unsigned commit: the user asked for a signature, and silently producing an unsigned commit is the
exact failure this skill exists to prevent.

## Step 1 — scope the change

```bash
git status --short && git diff --stat
```

Show what is staged vs unstaged and **confirm the intended scope before staging anything**. Stage
explicit paths — never `git add -A` unless the user asked for exactly that; it sweeps in stray
capture files, local configs, and editor droppings.

If on the default branch and the change is a fix or feature, offer a `fix/…` or `feat/…` branch
first. If the user prefers the default branch, that is their call — proceed.

## Step 2 — draft the message to a file

Write it to `.git/COMMIT_MSG_<slug>` (inside `.git/`, so it can never be committed or land in
`git status`), then commit with `-F`. This keeps multi-paragraph bodies intact, avoids shell
quoting damage, and lets the user edit before you commit.

Match the repo's existing convention — check `git log --oneline -15` first. Bailiwick uses
Conventional Commits (`fix(scope): …`). Explain **why**, not just what.

## Step 3 — pre-flight the attribution rule (before signing, not after)

```bash
python3 <skill-dir>/check_message.py .git/COMMIT_MSG_<slug>
```

Exit 0 clean · exit 1 signature found. The pattern is imported live from
`hooks/guardrails.py` (`SIGNATURE_RE`) — the same regex the PreToolUse guardrail enforces — so
the two can never drift.

**The rule:** no `Co-Authored-By: Claude`, no "Generated with … Claude", no 🤖 — in the commit
message or a PR body. A signature never lands by agent initiative. Keep one *only* when the user
explicitly asked for it; then expect the guardrail to confirm, which is correct behaviour.

Outside a Bailiwick clone the helper is unreachable — say so, and check by eye instead. The rule
does not depend on the tooling.

## Step 4 — the unlock handshake (the part that hangs)

A protected key makes `gpg` spawn pinentry, which **cannot render inside a tool call**: the call
blocks until it is killed. Always probe first, and never run `git commit -S` on a failed probe —
it hangs exactly the same way.

```bash
timeout 10 gpg --batch --no-tty --pinentry-mode error \
  --local-user "$(git config user.signingkey)" --sign -o /dev/null <<< probe
```

`--pinentry-mode error` is load-bearing: it makes gpg **fail instantly** instead of waiting on a
prompt. Measured on a locked key: without it, 12s hang and a timeout kill; with it, `rc=2` in 0s.
Unlocked: `rc=0` in under a second.

- **rc=0** → agent has the passphrase cached. Go to step 5.
- **non-zero** → ask the user to unlock it themselves, then wait for them:

  ```
  ! printf sigtest | gpg --local-user <KEY> --sign -o /dev/null && echo unlocked
  ```

  In Claude Code the `!` prefix runs it in the session shell. Any terminal on the machine works —
  `gpg-agent` is per-user, so the cache is shared. The passphrase is theirs; never ask them to
  type, paste, or echo it anywhere you can see, and never use `--passphrase` or
  `--pinentry-mode loopback` to work around this.

Re-probe after they confirm — but note that the probe only describes the moment it ran.
`default-cache-ttl` is an **idle** timer (600s by default; `max-cache-ttl` 7200s is the absolute
ceiling), and *your own approval prompts consume it*: the delay between issuing a call and the user
approving it counts against the cache exactly like any other idle time. This is the reason a probe
fails seconds after a successful unlock — not a broken agent. Step 5 closes the gap by chaining the
probe to the commit.

**Verify this yourself in ten minutes** rather than taking it on faith — the claim is the whole
justification for step 5's chaining, and it is cheap to reproduce:

```bash
printf sigtest | gpg --local-user <KEY> --sign -o /dev/null   # unlock; keyinfo now reads 1
sleep 600                                                      # idle, touching nothing else
timeout 10 gpg --batch --no-tty --pinentry-mode error \
  --local-user <KEY> --sign -o /dev/null; echo "rc=$?"         # rc=2, keyinfo now reads -
```

Observed exactly so: `1` → `-` across a clean 600s idle window, with the probe failing `No pinentry`
— the same symptom as a key that was never unlocked. That indistinguishability is the trap: an
expired cache and an absent one look identical, which is why the fix is to leave no gap rather than
to interpret the error.

### When the re-probe still fails — hand the commit over

**Do not loop.** On some machines the unlock does *not* leave a usable cache for the agent's
process: `gpg-connect-agent 'keyinfo <KEYGRIP>' /bye` reads `-` in the cached column immediately
after a successful unlock, so re-probing will fail forever while the user's own terminal signs
fine. Asking for a third and fourth unlock burns their time and teaches them the skill is broken.

After **one** failed re-probe, confirm the cache is genuinely absent, then hand the commit over —
the message file is already written and pre-flighted, so nothing is lost by letting the user run
the final step:

```bash
gpg-connect-agent 'keyinfo <KEYGRIP>' /bye     # 4th field: 1 = cached, - = not
```

```
! git commit -S -F .git/COMMIT_MSG_<slug>
```

Then verify it yourself (step 6) exactly as if you had run it — the verification is the part that
must not be skipped, and it does not need the key. This is a supported path, not a failure: the
skill's contract is a *verified* signed commit, not who typed the command.

Get the keygrip with `gpg --with-keygrip --list-secret-keys <KEY>` — the agent caches by keygrip,
not by fingerprint, so the fingerprint will not match anything in `keyinfo` output.

## Step 5 — commit, in the same call as a fresh probe

**Chain the probe and the commit.** `default-cache-ttl` (600s) is an *idle* timer, and the clock
keeps running while a tool-approval prompt sits unanswered — so a probe that passed in an earlier
call proves nothing about now. `git commit -S` re-signs at execution time; if the cache expired in
between, gpg needs pinentry mid-commit, which is the hang this skill exists to prevent.

```bash
timeout 10 gpg --batch --no-tty --pinentry-mode error \
  --local-user "$(git config user.signingkey)" --sign -o /dev/null <<< probe \
  && git commit -S -F .git/COMMIT_MSG_<slug>
```

Approval happens *before* the call runs, so the probe is fresh at execution and the commit follows
microseconds later — no window for expiry. A failed probe short-circuits the `&&`, so the commit is
never attempted on a cold key.

The framework guardrail confirms every `git commit`. **That prompt is expected, not a failure** —
it is the "clear user go-ahead" rule doing its job. Do not treat it as an error or retry around it.
Its latency is exactly the gap this chaining closes: the user thinking for eleven minutes at that
prompt is enough to expire a cache that was warm when you probed separately.

## Step 6 — verify it actually signed

Never report success from the commit's exit code alone — `-S` can be accepted while verification
still fails.

```bash
git log -1 --format='%h %G? %GS' && git log --show-signature -1 | head -3
```

Require **`%G?` == `G`** (good signature). Anything else — `U` untrusted, `B` bad, `E`
unverifiable, `N` none — is a failed signing: report it plainly with the letter and what it means,
do not paper over it. Then confirm the author is who they expect and the file list matches step 1.

Finally, remove the message file: `rm -f .git/COMMIT_MSG_<slug>`.

## Report

State the short SHA, the `%G?` letter, the signer identity, the file count, and that no
attribution signature is present. Then stop — note what remains unpushed and let the user decide
whether to publish. Never push, merge, or open a PR as a follow-on.
