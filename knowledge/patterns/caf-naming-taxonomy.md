---
id: caf-naming-taxonomy
type: pattern
tags: [naming, conventions, caf, azure-caf, taxonomy, gcp, finops]
confidence: high
last_validated: 2026-06-24
supersedes: [gcp-naming-conventions]
scope: generic
---

# Pattern: Resource Naming Taxonomy (Azure CAF-based)

Adopted from the Azure Cloud Adoption Framework — *Define your naming convention* —
and applied **framework-wide** (including GCP). This supersedes the former
`{env}-{region}-{service}-{purpose}` GCP pattern.

## Format
`{org}-{type}-{workload}-{env}-{region}-{instance}`

## Tokens
| Token | Meaning | Rules | Example |
|---|---|---|---|
| `org` | Short code of the **owning** org/client | From the registry — `context/org-shorthands.md`. 2–4 chars, lowercase. Default `acme` | `acme` |
| `type` | Resource-type abbreviation | From the controlled table below — never invent | `gke` |
| `workload` | Application / service / workload | Lowercase, concise, no inner hyphen where possible | `webapp` |
| `env` | Environment | From the env table | `prd` |
| `region` | Deployment region | From the region table | `euw1` |
| `instance` | Instance ordinal | Zero-padded 2–3 digits | `01` |

> `org` represents the **resource owner**, not whoever builds it — this is what gives
> globally-unique resources their uniqueness across clients. Defaults to `acme`
> (Acme Corp) for own resources; a client's own short code when client-owned.

## Client-specific overrides
A client may carry its own naming rules. Per-client knowledge lives under `clients/<id>/`
with `scope: client:<id>` — the **same `<id>`** as the org-shorthand registry and the `scope`
field (one identifier, never two schemes; see `agents/memory.md`). When working in a client
context, that client's `clients/<id>/` override wins; otherwise this generic taxonomy applies
with `org = acme` (your own org shorthand) by default.

## Environments
| Abbr | Environment |
|---|---|
| dev | Development |
| stg | Staging |
| prd | Production |
| shr | Shared / common |

## Regions
| Abbr | Region |
|---|---|
| euw1 | europe-west1 |
| euw4 | europe-west4 |
| use1 | us-east1 |
| usw1 | us-west1 |

## Type abbreviations (`{type}`)
| Domain | Abbr → Resource |
|---|---|
| Org hierarchy | `fldr` folder · `prj` project · `sa` service account |
| Network | `vpc` VPC · `snet` subnet · `addr` static address · `nat` Cloud NAT · `fw` firewall rule |
| Compute / runtime | `gke` GKE cluster · `run` Cloud Run · `gcf` Cloud Function · `vm` Compute instance |
| Data | `sql` Cloud SQL · `bq` BigQuery dataset · `gcs` GCS bucket · `ps` Pub/Sub topic |
| Security | `kms` KMS key · `sec` Secret Manager secret |

> This is the controlled table. **Never invent abbreviations** — extend it via `/curate`
> (human-gated). For Azure resources, use Microsoft's official CAF abbreviation recommendations.

## Examples
| Resource | Name |
|---|---|
| Project | `acme-prj-webapp-prd-euw1-01` |
| Folder | `acme-fldr-platform-shr` *(env/region/instance optional for hierarchy)* |
| GKE cluster | `acme-gke-platform-prd-euw1-01` |
| Service account | `acme-sa-webapp-prd-euw1-01` |
| VPC network | `acme-vpc-main-prd-euw1-01` |
| Subnet | `acme-snet-gke-prd-euw1-01` |
| Cloud SQL | `acme-sql-postgres-prd-euw1-01` |
| GCS bucket | `acmeprjwebappprdeuw101` *(globally unique — see constraints)* |

## Constraints & flex
CAF principle: **bend the rule when a resource's own limits require it.**
- Lowercase always; hyphen `-` as separator; never underscores.
- Length-limited / globally-unique resources reduce or drop tokens:
  - **GCP project ID**: 6–30 chars → keep `org-type-workload-env`, drop `region`/`instance` if over.
  - **GCS bucket**: 3–63 chars, globally unique, no uppercase → **drop hyphens**, keep order.
  - **Service account id**: 6–30 chars.
- **Optional tokens**: for org-hierarchy (folders, parent projects), `env`/`region`/`instance` may be omitted when they don't apply.
- `instance`: omit only when a single instance is guaranteed; otherwise always pad.

## Related
- [GCP naming conventions (superseded)](gcp-naming-conventions.md)
- [Required GCP labels](gcp-labels-required.md)
- [GCP IAM conventions](gcp-iam-conventions.md)
- [Org shorthands](../context/org-shorthands.md)
- [Environments](../context/environments.md)
