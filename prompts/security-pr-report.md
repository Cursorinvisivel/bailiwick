# Prompt: Security PR Report — Terraform / GCP

Invoke the Security Review agent with this prompt to produce a PR-ready security report.

---

```
Produce a pull-request-ready security review for the Terraform and Google Cloud changes in scope.

Workflow:
1. Review changed Terraform files and adjacent context (variables, locals, outputs, providers, versions).
2. Apply repository guidance first, then supplier and industry best practices.
3. Map findings to CIS Google Cloud Foundations controls where possible.
4. Flag all relevant potential issues by default.
5. For each finding, include a clear accepted-risk justification path.
6. If web access is available, refresh uncertain guidance using current official sources and cite them.

Return output in this exact structure:

## Security Findings
List findings ordered by severity (Critical, High, Medium, Low).
For each finding include:
- Severity
- Title
- Evidence (file/resource/setting)
- CIS mapping
- Why it matters
- Recommended fix
- Confidence (confirmed or inferred)
- Accepted-risk justification path

## Accepted Risks
List only findings explicitly accepted by the user.
For each accepted risk include:
- Finding title
- Justification
- Decision owner (if available)
- Review date

If none, write: None recorded.

## Unaddressed Risks
List findings not remediated and not accepted.
For each unaddressed risk include:
- Finding title
- Current exposure summary
- Suggested next action

If none, write: None currently open.

## Open Questions and Assumptions
List unknowns that can change risk assessment.

## Residual Risk Summary
Summarize remaining risk after proposed/implemented mitigations.

## Validation Suggestions
Suggest safe validation commands appropriate for this repository.
Example: terraform validate, terraform plan, tflint, tfsec, checkov

## Sources
List source links used to refresh guidance when web access is available.
If no web lookup was needed, state that repository and supplier guidance were sufficient.

[PASTE DIFF OR FILE LIST IN SCOPE HERE]
```
