# Prompt: PR Review — Terraform

```
Perform a technical review of this Terraform PR.

Security:
- IAM: least privilege, no primitive roles, no hardcoded keys
- Network exposure: public IPs, firewall rules, public buckets
- Secrets: no credentials in code

Operations:
- Resources causing replacement (immutable fields changed)
- Blast radius: other resources affected by changes
- Required labels present on new resources
- Deviations from knowledge library patterns

Code quality:
- for_each instead of count for critical resources
- Variables with description and validation where applicable
- Relevant outputs defined
- Naming conventions respected

Output: issue list with severity (critical/warning/info), location (file:line), concrete suggestion.

[PASTE PR DIFF HERE]
```
