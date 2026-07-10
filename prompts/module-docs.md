# Prompt: Module Documentation

```
Generate complete documentation for this Terraform module.

Use the template at $BAILIWICK/knowledge/templates/module-readme-template.md.

The README.md must include:
1. Clear description of what the module creates and what it is for
2. Usage block with a minimal working example
3. Inputs table (name, type, default, required, description)
4. Outputs table (name, type, description)
5. List of GCP resources created
6. Prerequisites (GCP APIs, minimum permissions)
7. Two examples: minimal and complete

Tone: technical, direct, no decorative text.
Audience: engineers using the module without prior knowledge of the implementation.

[PASTE MODULE CODE HERE]
```
