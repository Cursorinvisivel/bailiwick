---
name: enrich
description: Scan a bootstrapped/existing repo and draft project-context-filled LLM instruction files for all four tools (Claude Code, Codex, Gemini, Copilot) — both the committed team baselines (framework-agnostic) and the hidden framework complements (framework-aware). Use after running bootstrap.sh on an existing project to enrich its instruction files. Scans the repo first, then asks only for gaps it couldn't infer. All output is drafts for review; never auto-commits.
---

# /enrich — project discovery → instruction files

Turn a freshly-bootstrapped repo into one with **rich, accurate LLM instructions** for every tool.
The skill scans the project, asks you only for what it couldn't infer, and drafts the filled-in
instruction files across **two layers** — keeping each on the right side of the framework's privacy
boundary. Everything is a **draft for your review**; nothing is written without approval and nothing
is ever committed by the skill.

Use the Docs agent (`$BAILIWICK/agents/docs.md`) as the writer, the domain agents
(`gcp.md` / `kubernetes.md` / `serverless.md` / `data.md` / `cicd.md`) as the "what to look for"
checklist, and `engineering-defaults.md` as the always-on baseline.

## The two layers (THE boundary rule — do not violate)
Each tool has a committed team file and a hidden framework complement; they carry **different content**:

| Layer | Files | Content rule |
|---|---|---|
| **Committed team baseline** (tracked, shared — **may be PUBLIC**) | `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.github/copilot-instructions.md` | **Framework-AGNOSTIC + public-safe.** Generic standards + only **non-identifying** context. No framework refs; no personal/company/client names; no concrete cloud identifiers (see Sanitization guard). Scaffold: `agnostic-standards-baseline.md`. |
| **Private complement** (hidden via `.git/info/exclude` — never pushed) | `CLAUDE.local.md`, `.bailiwick.local.md` (Codex+Gemini marker), `.github/instructions/bailiwick.instructions.md` | **Framework-AWARE.** The home for ALL concrete project specifics (IDs, buckets, env identifiers) **plus** the framework wiring. Scaffolds: `project-claude-md-template.md`, `project-agents-md-template.md`, `copilot-bailiwick-instructions-template.md`. |

> **Sanitization guard (mandatory) — committed files must be PUBLIC-SAFE.** A committed instruction
> file can end up in a public repo, so it must carry only generic standards + non-identifying context.
> Before presenting any *committed* file, scan the draft and **remove or generalize** every hit of:
> - **Framework:** `BAILIWICK|bailiwick|\.bailiwick-outputs|/curate|INDEX\.md`
> - **Personal:** the machine username / home path (`/home/<user>/…`, `/Users/<user>/…`), git
>   `user.name` / `user.email`, any individual's name.
> - **Company / client:** every shorthand AND full name registered in `context/org-shorthands.md`
>   (your own org, any employer, and every client engagement codename) and any other org name.
> - **Cloud identifiers:** concrete GCP **project IDs**, **state/backend bucket** names, org/folder/
>   billing IDs, internal IPs/hostnames, account emails, real per-environment identifiers.
>
> Any such concrete or sensitive detail belongs **only in the hidden complement** (which is never
> pushed) — move it there, or generalize it in the committed file (`[project-id per env]`,
> `[state bucket]`, `[dev/stg/prd]`). When in doubt, omit from the committed file. Mirrors Security
> Review's promotion-leakage check. (The static `agnostic-standards-baseline.md` is already clean;
> the risk is only what *you fill in* from the scan.)

## Hard rules
- **Drafts only.** Present every file as a proposed diff; write **only** on explicit approval.
- **Never `git commit`/`push`.** The team commits their own baseline files; the runtime guardrail will
  block it anyway. The hidden complements stay untracked.
- **Enrich, do not clobber.** If a file already has content (the team's own, or a prior run), MERGE a
  project-context section / fill placeholders — never overwrite wholesale. Show the diff.
- **Respect the tracked-file guard.** A committed file the repo already tracks is the team's — enrich
  it in place (never hide it). A complement stays hidden.
- **No secrets.** Never copy literal secrets, tokens, or full client-identifying detail into any file;
  reference Secret Manager / ESO, and keep client specifics generic (route real detail to `clients/<id>/` via `/curate`, not here).

## Procedure

1. **Preflight.**
   - Confirm the repo is bootstrapped: at least one complement (`.bailiwick.local.md` /
     `CLAUDE.local.md` / the Copilot instructions) exists and references `$BAILIWICK`.
     If not, tell the user to run `bootstrap.sh <repo>` first and stop.
   - Inventory which files exist now: committed (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`,
     `.github/copilot-instructions.md`) vs complements. Note which are git-tracked. This decides
     enrich-in-place vs create-draft for each.
   - **Assess exposure.** Check `git remote get-url origin` — a public GitHub/GitLab URL (or any repo
     you intend to publish/share, e.g. open-source Terraform modules) ⇒ treat the committed files as
     **public**. If you can't tell, **ASK the user** "is this repo public/shared?". In public/shared
     mode, hold the committed files to the **Sanitization guard** strictly: generic standards only,
     every concrete project specific routed to the hidden complement. (Read `context/org-shorthands.md`
     now to load the exact company/client names to keep out of committed files.)

2. **Scan the repo (autonomous).** Delegate a broad read (Explore agent) and extract a structured
   **project profile**. Look for, at minimum:
   - **Stack & IaC:** Terraform version + providers (`required_providers`), backend config (bucket +
     prefix), root modules, internal/published modules used (source + ref), tfvars per environment.
   - **GCP footprint:** project IDs per environment, regions, key services (GKE, Cloud Run, Cloud SQL,
     BigQuery, Pub/Sub…), shared-VPC / networking hints.
   - **Environments:** env names + their GCP projects (dev/stg/prd…) and any naming/labelling patterns
     (cross-check `caf-naming-taxonomy.md` + `gcp-labels-required.md`).
   - **CI/CD:** every pipeline file (GitHub Actions, Atlantis, Cloud Build…) and whether each is
     authoritative for the Terraform lifecycle (this populates the complement's CI/CD Footprint table).
   - **Repo structure:** the directory layout worth telling an agent about; existing READMEs/docs.
   - **Conventions in evidence:** naming, module structure, commit style.
   - **Extension points (the reuse map):** for each common change type (IAM grant, database, bucket,
     service account, firewall, and any domain prominent in this repo), find the **data-driven construct
     used to add one** — a `for_each`/`count`/`dynamic` block, the driving `map`/`list`/`locals`/`*.tfvars`,
     a factory module, or a root-module loop — and record its **file path** and how to add an entry
     (e.g. "IAM → add a key to `local.iam_bindings` in `iam.tf`, keyed `role||member`"). This populates
     the complement's **Practical Change Guide** so agents extend the right construct each task instead
     of re-scanning the repo (or worse, creating a new standalone resource).
   Present the profile as a compact summary so the user can sanity-check what was inferred.

3. **Ask only for the gaps.** Diff the profile against the template placeholders and the relevant
   prompts in `discovery-questions-infra.md`. Ask the user a **single batched set** of targeted
   questions for what the scan could not determine — typically: environment *purposes*/intent, team
   conventions not visible in code, blast-radius notes, which pipelines must never be auto-run,
   project ownership. Do not re-ask anything the scan already answered.

4. **Draft both layers.** Fill the scaffolds with the profile + answers:
   - **Committed baselines** from `agnostic-standards-baseline.md` — generic standards + only
     **non-identifying** context (apply the Sanitization guard; in public/shared mode, omit concrete
     specifics entirely and keep them in the complement). Only for the tools the user wants committed;
     enrich an existing team file in place.
   - **Private complements** from the `project-*-template.md` scaffolds — same project context **plus**
     the framework wiring (Bailiwick path, proportional orchestration, engineering-defaults pointer,
     capture note appropriate to each tool: hooks for Claude; manual `.bailiwick-outputs/` for Codex/Gemini/Copilot).
     Fill the **Practical Change Guide** from the extension-points scan (real files/constructs, not
     placeholders), and **stamp the snapshot** (`git rev-parse --short HEAD` + date) in its header so its
     verify-not-gospel framing is honest. The reuse map carries file paths/module names → it lives in the
     **complement only**, never the public-safe committed baseline.
   - Run the **leakage guard** over every committed-file draft before showing it.

5. **Human gate.** Present all drafts as diffs, grouped by layer, with the **sanitization-guard result**
   for the committed files (explicitly: "scanned for framework / personal / company-client / cloud
   identifiers — N found, redacted/moved to complement"). Write **only** the files the user approves.
   Remind the user: the **committed** files are theirs to `git add`/commit (public-safe); the
   **complements** stay hidden (already in `.git/info/exclude`).
   Suggest re-running `/enrich` later when the project's stack, CI/CD, or **module / reuse layout
   (the Practical Change Guide)** changes materially — a stale reuse map misleads agents.

## Notes
- This is a **Claude Code** skill (like `/curate`), but its output serves all four tools.
- It writes **instruction files**, not the knowledge library — so it is not gated by `/curate`. Genuinely
  reusable patterns discovered here should still be promoted to the library via `/curate`, separately.
