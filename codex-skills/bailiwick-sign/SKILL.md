---
name: bailiwick-sign
description: Create a GPG-signed git commit end to end — scope the change, draft a Conventional Commits message, pre-flight it against Bailiwick's AI-attribution guardrail, handle the pinentry unlock handshake without hanging, commit with -S, and verify the signature actually verifies. Use when the user asks Codex for a signed commit, says "commit and sign it", or a repo requires signed commits. Commits only — never pushes, never opens a PR.
---

# Bailiwick Sign

## Overview

Run the Bailiwick signed-commit (`/sign`) workflow from Codex. This is a thin Codex wrapper; the
canonical procedure and guardrails live in Bailiwick's `skills/sign/SKILL.md`.

Two silent failures this exists to remove: a `-S` that never engages (you get an ordinary commit,
and nobody notices until a branch-protection rule does), and **pinentry blocking on a TTY the agent
does not have** — the command hangs until it is killed.

## Workflow

1. Resolve the Bailiwick root:
   - Prefer `$BAILIWICK`.
   - If unset and this skill is symlinked from the framework, infer the repo root two directories above this skill.
   - Fallback to `/path/to/bailiwick` if it exists.
2. Read the canonical instructions completely:
   - `$BAILIWICK/skills/sign/SKILL.md`
3. Follow the canonical `/sign` procedure exactly — steps 0–6: confirm the repo can sign, scope the
   change, draft the message to `.git/COMMIT_MSG_<slug>`, pre-flight it, unlock, commit with `-S`,
   and verify.

## The unlock handshake in Codex

The canonical skill shows Claude Code's `!` prefix for the unlock. **Codex has no equivalent, and
does not need one.** `gpg-agent` is per-user and its passphrase cache is shared across every process
of that user, so the unlock does not have to happen in the agent's shell — it only has to happen
*before* the agent signs.

Always probe first, and never run `git commit -S` on a failed probe — it hangs the same way:

```bash
timeout 10 gpg --batch --no-tty --pinentry-mode error \
  --local-user "$(git config user.signingkey)" --sign -o /dev/null <<< probe
```

`--pinentry-mode error` is load-bearing: it makes gpg fail instantly instead of waiting on a prompt
that can never be answered.

- **rc=0** → the agent can sign now. Proceed to the commit.
- **non-zero** → stop and ask the user to run this **in their own terminal** (any terminal on the
  machine — a second tab, a plain shell, their editor's terminal):

  ```
  printf sigtest | gpg --local-user <KEY> --sign -o /dev/null && echo unlocked
  ```

  Wait for them to confirm, then **re-probe**. The cache expires (commonly 10 min idle), so probe
  again if time passed between the unlock and the commit.

**If the re-probe still fails, do not loop.** On some machines the unlock leaves no usable cache for
the agent's process — `gpg-connect-agent 'keyinfo <KEYGRIP>' /bye` reads `-` in the cached column
immediately after a successful unlock — so re-probing fails forever while the user's own terminal
signs fine. Asking for a third and fourth unlock burns their time and teaches them the skill is
broken. After **one** failed re-probe, confirm the cache is genuinely absent, then hand the final
step over; the message file is already written and pre-flighted, so nothing is lost:

```
git commit -S -F .git/COMMIT_MSG_<slug>
```

Then verify it yourself exactly as if you had run it — verification is the part that must not be
skipped, and it needs no key. This is a supported path, not a failure: the contract is a *verified*
signed commit, not who typed the command. Get the keygrip with
`gpg --with-keygrip --list-secret-keys <KEY>`; the agent caches by keygrip, not fingerprint.

Never use `--passphrase` or `--pinentry-mode loopback` to sidestep the prompt, and never ask the
user to type, paste, or echo their passphrase anywhere the agent can see it.

## Guardrails

- **Never pushes.** Publishing is a separate, explicitly-authorised step. No push, merge, or PR as
  a follow-on.
- **No AI attribution signature** — no `Co-Authored-By: Claude`, no "Generated with … Claude", no
  🤖 — in the commit message or a PR body. Pre-flight it *before* signing:

  ```bash
  python3 "$BAILIWICK/skills/sign/check_message.py" .git/COMMIT_MSG_<slug>
  ```

  Exit `0` clean · `1` signature found · `2` the guardrail pattern could not be reached (a broken
  install — never treat this as a dirty message). The pattern is imported live from
  `hooks/guardrails.py`, the same regex the Codex PreToolUse adapter enforces, so the pre-flight and
  the runtime block cannot drift.
- The Codex guardrail adapter confirms every `git commit`. **That prompt is expected, not a
  failure** — it is the "clear user go-ahead" rule doing its job. Do not retry around it.
- **Verify, never assume.** `-S` can be accepted while verification still fails. Require
  `git log -1 --format='%G?'` to be `G`. Anything else — `U` untrusted, `B` bad, `E` unverifiable,
  `N` none — is a failed signing: report the letter and what it means rather than papering over it.
- No `user.signingkey` configured → stop and ask which key to use. Never guess, and never fall back
  to an unsigned commit: silently producing one is the exact failure this skill exists to prevent.
