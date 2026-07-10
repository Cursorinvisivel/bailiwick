---
id: code-review-rubric
type: pattern
tags: [review, terraform, gcp, blast-radius, security]
confidence: high
last_validated: 2026-06-04
supersedes: []
scope: generic
---

# Pattern: Code Review Rubric — Terraform / GCP

## Priorities
Prioritise findings by:
1. Production risk
2. Blast radius
3. Security impact
4. State / replacement risk
5. Operational impact
6. Cost impact
7. Maintainability

## Review Checklist

### Terraform — correctness
- Are resource types, arguments, and references valid and consistent with the existing repository?
- Are module inputs/outputs coherent and backwards-compatible unless an interface change was explicitly intended?
- Are version constraints still explicit and appropriate?

### Reuse — did this duplicate an existing pattern?
- Does the change add a **new standalone resource** for a concern the repo already manages through a
  reusable construct — a `for_each`/`count`/`dynamic` block, a driving `map`/`list`/`locals`/`*.tfvars`
  collection, a factory module, or a root-module loop? If so, **flag it**: the entry usually belongs in
  that collection/module, not in a new block. Common offenders: a fresh `google_project_iam_member`
  beside an existing IAM bindings map; a new `google_sql_database_instance` beside an instances map.
- If a new resource genuinely is warranted, did the author state which existing pattern they checked
  and why it could not absorb the change?

### State and lifecycle risk
- Does this change risk replacing resources?
- Does it require moved blocks, imports, or state migration?
- Does it alter backend, provider aliasing, naming keys, `count`, or `for_each` identity?
- Does it introduce lifecycle behaviour prone to drift?

### Security
- Does it broaden IAM unnecessarily?
- Does it create public exposure or overly broad network rules?
- Does it expose secrets or encourage insecure secret handling?
- Does it weaken encryption, identity boundaries, or tenant separation?

### GCP-specific concerns
- Project / folder / organisation scope correctness
- Service account scope and impersonation implications
- Workload Identity / KSA↔GSA mapping correctness
- VPC, subnet, routing, NAT, DNS, PSC, LB, and firewall implications
- Cloud SQL private connectivity correctness
- Org policy and quota side effects

### Operations and observability
- Are logging, metrics, alerting, and diagnostics affected?
- Are rollback and failure modes clear?
- Does the change increase toil or hidden operational dependencies?

### Cost
- Does the change likely increase spend materially?
- If yes, is the increase justified and visible?

### Documentation
- Are README, examples, variables, outputs, and comments aligned with the current implementation?

## Output Format
Use this structure:
- Critical findings
- Medium-risk findings
- Low-risk findings
- Assumptions / unknowns
- Suggested fixes

## Related
- [GCP IAM conventions](gcp-iam-conventions.md)
- [Engineering defaults](../context/engineering-defaults.md)
