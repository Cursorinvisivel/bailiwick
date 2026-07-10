# Prompt: IAM Review

```
Perform an IAM review of the following Terraform code.

Check:
1. Primitive roles (owner, editor, viewer) on workload resources
2. Overly permissive bindings against the least privilege principle
3. Service accounts shared across multiple workloads
4. Key files referenced instead of Workload Identity
5. Bindings to individual users in production (should be groups)
6. Missing IAM conditions where they would be recommended

For each issue:
- Severity: critical / warning / info
- Location: file and line
- Problem description
- Fix suggestion with Terraform code

[PASTE CODE HERE]
```
