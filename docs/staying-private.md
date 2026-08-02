# Staying private — and contributing upstream

Bailiwick is built so **your knowledge and your work never have to touch the public repository.** The
library you grow is yours; the framework only needs to be *cloned*, not published to. This page covers
how to keep it that way — whether you never contribute, or you want to send generic improvements back
upstream while keeping a private superset.

> **Internalize this first:** your **`knowledge/` library is tracked in git** — that's how it syncs
> across your machines. So privacy is **not** a `.gitignore` question; it's about **which remote you
> push to.** Push your instance to a remote *you* control, never to the public one.

This is the repository-level privacy layer. Bailiwick gives you two others:

- **Shadow mode** keeps the framework invisible in the repos you *work on* (client/colleague repos) —
  zero files written. See [FRAMEWORK.md §7.1](FRAMEWORK.md).
- **Scopes & de-identification** keep client specifics out of shared knowledge (`client:<id>`,
  de-identified `/curate`, `/purge`). See [FRAMEWORK.md §4](FRAMEWORK.md).
- **Repository topology** (this page) keeps your *whole instance* — private knowledge, roles, config —
  separate from the public OSS you cloned.

## Tier 1 — just clone and use (nothing leaves your machine)

Clone it, wire your repos, grow your library. As long as you never push your clone to a public remote,
everything stays local. This is enough for a solo user on one machine.

```bash
git clone git@github.com:<owner>/bailiwick.git ~/bailiwick
export BAILIWICK="$HOME/bailiwick"
$BAILIWICK/scripts/bootstrap.sh --install-tools
```

## Tier 2 — a private instance (backup, multiple machines, or a private superset)

To back up your instance, sync it across machines, or extend it with private content, push it to a
**private remote you own** and pull public updates down from the OSS. The safest shape is **two local
clones**, each with a single-purpose remote:

| Clone | `origin` | Role |
|---|---|---|
| `~/bailiwick` | the **public** OSS | Contribute-only. Not installed. Where generic work is born. |
| `~/bailiwick-private` | your **private** repo | Your daily driver. Installed. Holds your private content. |

> A GitHub **fork of a public repo is itself public** — you can't make it private. For a private
> downstream, create a **new private repo** and track the OSS as an extra remote (below).

Set up the private clone to pull public updates but never push to them:

```bash
git clone git@github.com:<you>/bailiwick-private.git ~/bailiwick-private
cd ~/bailiwick-private
git remote add upstream git@github.com:<owner>/bailiwick.git
git remote set-url --push upstream DISABLED       # pull-down works; push-up is blocked
export BAILIWICK="$HOME/bailiwick-private"
$BAILIWICK/scripts/bootstrap.sh --install-tools    # install from the PRIVATE clone — your daily driver
```

**Install from the private clone only.** Global hooks are one-per-machine, so a single installed
instance avoids capture/guardrail collisions. Keep the public clone contribute-only (never run
`--install-tools` from it).

Bringing an *existing* private framework into the private clone? Don't `git merge` two divergent
histories — that would drag old, unrelated history back in. Bailiwick already **is** the clean,
generic core, so add only your private delta (private knowledge, `clients/<id>/`, private config, any
private machinery) as fresh commits on top.

## The flows

- **Public → private (routine, always safe):** `git pull upstream main` in the private clone absorbs
  upstream improvements. Public content is already clean, so this never leaks anything.
- **Private → public (deliberate, gated):** there is **no direct path**, by design. Re-create the
  generic change in the *public* clone and push from there. That extra step is the checkpoint — it
  forces a conscious "is this actually generic, and free of private detail?" every time.

```
                 git pull upstream  (safe, routine)
  public OSS  ───────────────────────────────────▶  bailiwick-private   (installed, private)
      ▲                                                      │
      └──────  clean, generic, sanitized PRs  ───────────────┘
             (re-created in the public clone — never a raw push from private)
```

## What must never cross upstream

When you do port something up, sanitize it — hold it to the same no-private-data rule the public repo
lives by. Never send to the public repo:

- Private/curated **knowledge** tied to a client or employer, `clients/<id>/` content, or real project
  IDs / org names (use placeholders `acme` / `globex` / `example.com`).
- **Captures** — `.bailiwick-outputs/` and the central
  `~/.bailiwick/captures/` pool. Raw session data, never committed anywhere.
- Machine/registry config: `.bailiwick-sync.json`, `.bailiwick-sources.json` (your federation sources).

Bailiwick's own tools exist for exactly this boundary: the **Security-Review leakage check** at
promotion, **de-identified `/curate`** (stores no identifiers), and **`/purge`** (retroactively strip a
client/project while keeping the reusable "how"). See [FRAMEWORK.md §4](FRAMEWORK.md) and
[ADR-008](decisions/adr-008-purge-and-deidentification.md).

## What protects you — and what doesn't

- **Directory separation makes *accidental* leaks near-impossible:** the public clone contains no
  private files, and the private clone can't push upstream.
- **It can't stop a *deliberate* act.** Copying a private file into the public clone and pushing it is
  a conscious choice — and a public push is a publish: it may be cached or indexed even if you revert
  it. Treat every push to the public remote as permanent.
- For a mechanical backstop, add a pre-push hook or a secret scanner (e.g. `gitleaks`) to the public
  clone.

See also: [operations.md](operations.md) (multi-machine sync, backup, federation) and
[CONTRIBUTING.md](../CONTRIBUTING.md).
