---
id: llm-context-token-optimization
type: topic
tags: [llm, context, tokens, optimization, agents, claude-code, tooling, reference]
confidence: low
last_validated: 2026-07-05
supersedes: []
scope: generic
---

# Topic: LLM Context & Token Optimization Patterns (agent frameworks)

> Discovery investigation (2026-07-05): patterns to reduce token spend and extend workable
> session length for knowledge-heavy agent setups (frameworks like Bailiwick and client
> agent deployments). Sources are primary (Anthropic docs/engineering); see Provenance.

## The pattern landscape

**1. Prompt caching (align content to the cache, don't fight it)**
- Anthropic: 5-min ephemeral TTL (1h at 2× write cost); cache WRITES cost 1.25× base input,
  cache READS 0.1× — a ~90% discount on repeated prefix content within the TTL.
- Invalidation is hierarchical (`tools` → `system` → `messages`): changing any tool definition
  invalidates everything downstream; put breakpoints on the LAST STABLE block, never on
  changing content. Minimum cacheable size is model-dependent (512–4096 tokens).
- Implication: a per-session injected block (like an index) is cheap *within* a session —
  it is message content, cached after the first turn — but everything upstream of it
  (system prompt, tool definitions) must stay byte-stable to keep hits.

**2. Progressive disclosure / index-as-map (the highest-leverage pattern)**
- Anthropic's context-engineering guidance (2025-09): agents should hold "lightweight
  identifiers" and load data just-in-time via tools, assembling understanding "layer by
  layer", rather than pre-loading corpora. Hybrid (small always-on map + on-demand depth)
  is explicitly endorsed.
- Agent Skills implement this as 3 tiers: only `name` + `description` of every skill in the
  system prompt; full SKILL.md on invocation; bundled files only as needed. Guidance: split
  SKILL.md when it grows; keep always-loaded surfaces minimal.
- Claude Code guidance: keep the always-loaded memory file (CLAUDE.md) **under ~200 lines**;
  move workflow-specific instructions into skills so they cost zero until invoked.

**3. Context rot & session hygiene**
- Documented degradation: recall accuracy drops as context grows (attention is n²; long
  sequences are undertrained) — long sessions get *worse*, not just costlier.
- Tactics (Claude Code docs): `/clear` between unrelated tasks (stale context taxes every
  subsequent message); custom compaction instructions (`/compact <focus>` or a
  "# Compact instructions" section in the memory file); plan mode before complex work to
  avoid expensive wrong-direction tokens; specific prompts over vague ones (vague requests
  trigger broad scanning); tune thinking effort/budget for simple tasks.
- Compaction = summarize + reinitiate window, preserving decisions/open issues, discarding
  redundant tool output.

**4. Subagent / context isolation for verbose work**
- Delegate high-volume operations (test runs, doc fetching, log processing, research) to
  subagents: the verbose material stays in the subagent's window; only a condensed summary
  (typically 1,000–2,000 tokens) returns. Multi-instance "agent teams" cost ~7× a standard
  session — isolation is for verbosity, not parallel escalation.

**5. Tool/MCP schema overhead**
- Quantified (Anthropic tool-search docs): a typical 5-server MCP setup consumes ~55k tokens
  in definitions before any work; deferred loading (tool search) cuts this >85%, and tool
  *selection accuracy* degrades beyond ~30–50 in-context tools. Threshold guidance: defer
  when >10 tools or >10k tokens of definitions.
- Claude Code now defers MCP tool schemas by default; plain CLIs (`gh`, `gcloud`, `aws`,
  `terraform`) remain cheaper than MCP servers (no per-tool listing at all) — prefer them
  where capability is equivalent, and disable unused MCP servers per repo.
- Hooks can pre-filter verbose command output before it enters context (e.g. grep a 10k-line
  log to the error lines) — tens of thousands of tokens down to hundreds.

**6. Output-token minimization (minimal-codegen rulesets)**
- Ponytail (github.com/DietrichGebert/ponytail, MIT, v4.8.4 2026-06, ~74.6k stars): a
  laziness-prior ruleset/plugin (YAGNI → reuse → stdlib → native → existing dep → one line →
  minimum). Claims ~54% less code / ~20% cheaper / ~27% faster — mean of 12 feature tasks,
  Haiku 4.5, n=4 (thin evidence, app-code tasks).
- **Evaluated 2026-07-05, NOT adopted for Bailiwick**: overlaps the framework's own
  reuse-first defaults (engineering-defaults §0) which are IaC-specific and stronger; its
  per-repo file drops break shadow-mode zero-footprint; adds Node hook dependency; savings
  target codegen-heavy app work, not knowledge/IaC sessions. Its ladder *formulation* was
  grafted into engineering-defaults instead.
- **Consider for**: app-code-heavy client projects where agents visibly over-build and the
  team accepts a visible plugin.

## Verdict & applicability (what to actually do)
- For an index-driven framework: the architecture (lean injected map + on-demand loading +
  budgets) IS the vendor-endorsed pattern — keep the map lean and byte-stable; resist
  restating content in always-on surfaces.
- Biggest per-session levers, in order: session hygiene (/clear between tasks, plan mode,
  specific prompts) → subagent isolation for verbose research/logs → MCP diet (CLI-first,
  disable unused servers) → thinking-effort tuning → output-minimalism priors (already
  covered by reuse-first defaults).
- For client deployments: check the ~55k-token MCP trap first — it is the most common
  silent cost in multi-server setups; defer or prune.

## Provenance
- Investigation date: 2026-07-05 (sources fetched same day).
- Anthropic prompt caching docs (platform.claude.com/docs/en/build-with-claude/prompt-caching).
- "Effective context engineering for AI agents" — Anthropic engineering, 2025-09-29.
- "Equipping agents for the real world with Agent Skills" — Anthropic engineering, 2025-10-16.
- Claude Code cost-management docs (code.claude.com/docs/en/costs).
- Anthropic tool-search-tool docs (platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool).
- Ponytail repo (github.com/DietrichGebert/ponytail), MIT, examined at v4.8.4 (2026-06).
- Codex/Gemini equivalents not examined in depth this pass — UNVERIFIED beyond Claude surfaces.

## Related
- [Claude MCP wiring](claude-mcp-wiring.md)
- [Engineering defaults](../context/engineering-defaults.md)
