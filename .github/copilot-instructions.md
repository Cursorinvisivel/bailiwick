# Copilot Instructions — bailiwick

This repo is the central framework — it contains no production IaC.

## Base patterns
See: copilot-instructions/terraform-gcp.md

## Structure
- agents/ — agent role definitions (lead + 5 domain: gcp, kubernetes, serverless, data,
  cicd + 7 execution: implementer, quality, security-review, docs, memory, cloud-research, federation)
- knowledge/ — knowledge library (INDEX.md is the entry point)
- hooks/ — capture/guardrail/sync hooks (Claude Code only)
- skills/ — /curate, /enrich, /learn, /metrics (canonical); codex-skills/ — Codex wrappers
- scripts/ — bootstrap.sh / bootstrap.ps1 (repo onboarding)
- copilot-instructions/ — base instructions by repo type
- vscode/ — MCP config template and snippets
- prompts/ — reusable prompts

## Commit conventions for this repo
- Changes to knowledge/ use prefix `knowledge:`
- Knowledge commits are always separate from tooling commits
