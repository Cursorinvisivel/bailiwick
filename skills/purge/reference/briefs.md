# /purge reference: review and Advisor briefs (Steps 3a, 3b, 5a)

Templates for `skills/purge/SKILL.md`. The gates (model, effort, mode, when a stage may be skipped)
live in SKILL.md. `$W` is `${BAILIWICK_HOME:-$HOME/.bailiwick}/purge-work`; spell it out in commands.

## Minimal-brief rules (all three)

A brief is itself an identifier-bearing surface: it lands in this session's host state and in the
subagent's transcript. So:

- The reviewer (`bailiwick-security-review-local`: Read, Grep, Glob only, no Bash, no web) cannot run
  commands. The main session runs the git and list commands and pastes their output: `git grep -l`,
  `git ls-files | grep -ciE -f "$W/tokens.ere"`, and the Step 2 count loops.
- Send the tokens (the reviewer must search for them), per-surface counts, file paths, the
  classification, and the execution order. For an ABSTRACT item send only the matching line plus one
  line of context, never the whole file.
- Never send capture bodies, audit-log lines, or transcript text.
- Tell the reviewer it may Grep, Glob, and Read within the Bailiwick clone and `$BAILIWICK_HOME`, but
  it may inspect captures, the audit log, health shards, the inbox, and `$W` **only** with Grep in
  `files_with_matches` or `count` mode, never by reading content, and it reports paths and counts.
- For a token of 4 characters or fewer, give the reviewer the boundary pattern
  `(^|[^A-Za-z0-9])<tok>([^A-Za-z0-9]|$)` (case-insensitive) rather than the bare token, so its
  counts follow the same rule as `scripts/purge_scrub.py`.
- Host state under `$CC` is outside its reach. Pass the Step 2 counts instead.
- Reviewer and Advisor output is advisory. The main session folds it into the plan; neither stage
  edits, deletes, or executes, and neither one's output is the approval.

## 3a. Plan review: `bailiwick-security-review-local`, opus, high

Input: the Step 2 scan (per-surface counts and paths), the Step 3 classification, and the draft plan
including its execution order. Ask:

1. **Missed identifiers:** spelling and case variants, abbreviations, `{org}` token forms,
   identifiers in file and directory names, frontmatter, telemetry keys, registry entries, link
   targets, and encoded or hashed forms (URL-encoded, base64, slug and underscore variants).
2. **Uncovered surfaces:** anything that holds the identifiers and is not in the Step 2 list.
3. **Over-deletion:** reusable knowledge classified DELETE that should be ABSTRACT or re-attributed
   (the default is ABSTRACT).
4. **Ordering risks:** a step that destroys something a later step still needs (Step 5's order).

Fold each finding into the draft plan as a change marked "added by review", or keep it visible as an
open finding. Append every new variant to `$W/tokens` (Write tool) and regenerate `$W/tokens.ere`.

## 3b. Advisor: `bailiwick-advisor`, fable, high (read-only, never executes)

The Advisor judges the plan's shape and completeness, so it does not need the identifiers. The brief
is **redacted**: replace the tokens with `<ID>`, `<ORG_TOKEN>`, and `<ORG_NAME>` everywhere, including
paths and the "before" side of diffs. It contains:

- the plan;
- the Step 2 scan summary as per-surface counts;
- the 3a findings and how each was folded in;
- the execution order;
- the erasure tier the run will claim.

**Mechanical redaction check, before dispatch.** Write the brief to `$W/advisor-brief.md` with the
Write tool, then run `grep -ciE -f "$W/tokens.ere" "$W/advisor-brief.md"` with `$W` spelled out. It
must print `0`. Otherwise fix the brief and re-check. Dispatch exactly that text.

Question: "Is this plan safe and complete to execute, and what would you change?"

## 5a. Post-execution review: `bailiwick-security-review-local`, opus, medium

The input is mechanical: the reviewer checks a finished change against lists. Pass:

- the `purge_verify.sh residual` output, verbatim;
- `git show --name-status <sha>` for the knowledge commit (no diffs pasted);
- the per-surface record from Step 5a.1 (`tool`, `manual`, or `not checked`, with counts);
- for each DELETEd content file (a `knowledge/` or `definitions/` text file, not a capture), its
  pre-deletion text, written with `git show <sha>^:<path> > "$W/deleted/<n>.md"` (a redirect, which
  is unguarded) so the reviewer can Read it. Name the copies by number, not by the original path.

Ask:

1. Does any token or variant remain on a Step 2 surface?
2. Was anything reusable lost, that is, a generic rule in a deleted file that should have been
   abstracted?
3. Are INDEX, `## Related`, `scope:`, and `confidence:` consistent after the change?
4. Does the claimed erasure tier match the residual and the per-surface record?
