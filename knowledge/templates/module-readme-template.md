# [module-name]

> Brief description — what this module creates and what it is for.

## Usage

```hcl
module "[name]" {
  source = "git::https://github.com/your-org/[repo]//modules/[name]?ref=vX.Y.Z"

  project_id  = var.project_id
  environment = var.environment
}
```

## Inputs

| Name | Type | Default | Required | Description |
|---|---|---|---|---|
| `project_id` | `string` | — | Yes | GCP Project ID |
| `environment` | `string` | — | Yes | dev / stg / prd / shr |
| `[input]` | `[type]` | `[default]` | Yes/No | [description] |

## Outputs

| Name | Type | Description |
|---|---|---|
| `[output]` | `string` | [description] |

## Resources Created

- `google_[resource_type].[name]` — description

## Prerequisites

- GCP APIs enabled: `[api1]`, `[api2]`
- Required permissions: `[role]`

## Examples

### Minimal example
```hcl
module "[name]" {
  source      = "..."
  project_id  = "my-project"
  environment = "dev"
}
```

### Complete example
```hcl
module "[name]" {
  source      = "..."
  project_id  = "my-project"
  environment = "prd"
}
```

## Notes
- ...
