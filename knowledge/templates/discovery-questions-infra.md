# Discovery Questions — Infrastructure

> Use as a facilitation guide, not as a form. Adapt to the client's context.

---

## Organisational Context

- Who are the technical and business stakeholders with infrastructure decision-making authority?
- What is the current operating model — internal team, MSP, or hybrid?
- Are there relevant regulatory or compliance constraints (GDPR, sector-specific, geographic)?
- What is the current maturity level in DevOps and IaC practices?

## Current Environment

- Which cloud platforms are in use today, and what is the historical reason for each?
- Is there IaC in production? What is the actual adoption state?
- How is identity and access control currently managed?
- What is the network model: on-premises, cloud-only, or hybrid?
- Are there critical integrations with external or legacy systems?

## Pain and Motivation

- What is failing, too slow, or too expensive today?
- What triggered this project now — a specific event, strategic decision?
- What is the current estimated monthly cloud cost?
- Are there recurring incidents related to infrastructure?

## Conditions and Constraints

- Is there a Cloud Service Provider preference or restriction?
- What is the tolerance for downtime during a migration or transformation?
- Is there an internal team available to operate the new infrastructure?
- What is the available budget — order of magnitude is sufficient at this stage?
- Is there a business date or milestone constraining the timeline?
- Any data or workloads with special residency or security requirements?

## Success Criteria

- How do you define success for this project in 6 and 12 months?
- Who validates internally that it was successful?
- Is there a current metric (cost, availability, deploy time) that serves as a baseline?

## Specific Technical Questions (adapt)

### If GKE / Kubernetes
- What is the team's current Kubernetes experience?
- Is there multi-cluster management today?
- How are applications currently deployed?

### If migration
- Is there an inventory of what exists today?
- Are there applications that cannot have downtime during migration?
- Is there a defined rollback plan?

### If FinOps
- Is there cost allocation by team or project today?
- Who currently receives cost reports?
- Is there an approved budget per environment or component?
