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

Re-probe after they confirm. The cache expires (commonly 10 min idle), so probe again if time has
passed between the unlock and the commit.

## Step 5 — commit

```bash
git commit -S -F .git/COMMIT_MSG_<slug>
```

The framework guardrail confirms every `git commit`. **That prompt is expected, not a failure** —
it is the "clear user go-ahead" rule doing its job. Do not treat it as an error or retry around it.

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
