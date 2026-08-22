# Documentation index

Specifications for the CCOA assistant. These are the source of truth — code implements
them, and any divergence is resolved by updating the spec in the same change.

## Reading order

Read top to bottom on first pass. Later documents assume the earlier ones. Numbers are
stable identifiers, not positions — the table below is the reading order.

| # | Document | What it settles | Status |
|---|---|---|---|
| — | [**20 — Implementation status**](20-implementation-status.md) | **What is actually built versus only specified. Read this first.** | Living |
| — | [22 — Getting started](22-getting-started.md) | Clone → run → sign in → deploy, in order | Living |
| — | [00 — Engineering constitution](00-constitution.md) | Binding principles for every other document | Approved |
| — | [01 — Requirements traceability](01-requirements-traceability.md) | Brief → `REQ-*` IDs → which spec satisfies each | Approved |
| — | [02 — Research](02-research.md) | Verified facts about the environment, region, versions, and prices | Approved |
| **Design** | | | |
| 03 | [Architecture](03-architecture.md) | Services, boundaries, request lifecycle | Approved |
| 04 | [Data model](04-data-model.md) | Entities, SQLite schema, indexes, Alembic migrations | Approved |
| 05 | [LangGraph orchestration](05-langgraph-orchestration.md) | Orchestrator + specialists, state, routing, human-in-the-loop, error handling | Approved |
| 17 | [Agent skills and prompt assets](17-agent-skills.md) | Where behaviour lives: skill files, progressive disclosure, templates, no hardcoded prompts | Approved |
| **Services** | | | |
| 06 | [Backend API](06-backend-api.md) | HTTP contract, SSE streaming, tool surface | Approved |
| 07 | [Frontend](07-frontend.md) | React + Vite SPA, screens, state, auth flow | Approved |
| **Platform** | | | |
| 08 | [Infrastructure](08-infrastructure.md) | AWS resources, Terraform layout, deploy/teardown | Approved |
| 09 | [Networking](09-networking.md) | Topology, traffic flow, ingress/egress, boundaries | Approved |
| 10 | [Security](10-security.md) | AuthN/Z, secrets, service-to-service, auditability | Approved |
| 11 | [CI/CD](11-cicd.md) | Validate → test → build → deploy pipeline | Approved |
| **Data & operations** | | | |
| 12 | [Seed data](12-seed-data.md) | Deterministic generation of 100+ records | Approved |
| 13 | [Vector search](13-vector-search.md) | Semantic retrieval (nice-to-have) | Approved |
| 14 | [Local development](14-local-dev.md) | `langgraph dev`, pluggable checkpointer, debugging | Approved |
| 15 | [Datastore options](15-datastore-options.md) | SQLite vs DynamoDB vs Aurora, costed | Approved |
| 16 | [Cost model](16-cost-model.md) | What a demo actually costs, and at rest | Approved |
| 18 | [AWS access and manual steps](18-aws-access-and-manual-steps.md) | Who touches AWS and as whom; what needs a human, and how | Approved |
| 19 | [Agent evaluation](19-agent-evaluation.md) | Measuring agent quality repeatably — DeepEval, four layers | Approved |
| 21 | [Design system](21-design-system.md) | Tokens, components, composition, motion — what the interface looks like and why | Approved |
| — | [Operations log](ops-log.md) | Every manual AWS action, and its route back to IaC | Living |

**All specifications were approved on 2026-08-22.** Implementation may proceed; from
this point a change to behaviour and a change to the spec that describes it are the same
change ([00 — Constitution](00-constitution.md) §1).

## Decision records

Architectural decisions that are expensive to reverse get an ADR.

| ADR | Decision |
|---|---|
| [ADR-001](adr/ADR-001-llm-provider.md) | Gemini Developer API over Amazon Bedrock |
| [ADR-002](adr/ADR-002-datastore.md) | SQLite as the datastore — superseded by ADR-005/006 |
| [ADR-003](adr/ADR-003-frontend-runtime.md) | React + Vite on ECS rather than S3 + CloudFront |
| [ADR-004](adr/ADR-004-ephemeral-infrastructure.md) | Ephemeral infrastructure rather than always-on |
| [ADR-005](adr/ADR-005-runtime-and-persistence.md) | **CloudFront + private ALB, in-container SQLite, scale-to-zero, LangSmith** |
| [ADR-006](adr/ADR-006-requirement-alignment-over-cost.md) | **Requirement alignment over cost — Alembic, dev-only deploy, restored controls** |
| [ADR-007](adr/ADR-007-durable-sqlite-via-s3.md) | **Warm tasks (`min 1`) and durable SQLite via Litestream → S3** |
| [ADR-008](adr/ADR-008-provisioned-identity.md) | **Provisioned identity in Cognito — no self-registration, no application-managed passwords** |

## Status meanings

| Status | Meaning |
|---|---|
| **Draft** | Being written or revised. Do not implement against it. |
| **Under review** | Complete and awaiting sign-off. Comment, do not implement. |
| **Approved** | Settled. Implementation may begin; changes require a spec update. |
| **Re-baseline** ⚠ | Superseded in part by a later ADR. The ADR is authoritative where they disagree; the spec is being rewritten against it. *(No document currently carries this status.)* |

## What the code changed about the specs

Implementing the backend, containerising it, and building the eval suite surfaced ten
places where a spec was wrong, unreachable, or missing. Each was corrected in the same change as the code, per the working agreement —
they are listed here because "the spec was updated" is easy to claim and hard to audit.

| Spec | Change | Why |
|---|---|---|
| [02](02-research.md) §3.1 | Default model → `gemini-3.5-flash` | Cost. Also recorded that no stable `gemini-3-flash` exists — it is preview-only |
| [02](02-research.md) §4.2, §5.1 | Marked the EFS reasoning as superseded | Stale relative to ADR-005; the findings still explain *why* EFS was rejected |
| [04](04-data-model.md) §3.4 | Indexes are ascending, not `DESC` | SQLite scans either direction at the same cost, and an expression index makes `alembic check` report a phantom diff forever |
| [04](04-data-model.md) §3.4a | **Added the `thread` table** | Ownership checks and thread listing cannot be answered from the checkpointer's database |
| [12](12-seed-data.md) §3.1 | Exact counts replace estimates | The generator is deterministic, so approximations were needlessly vague |
| [12](12-seed-data.md) §3.2 | **Dropped `Faker`** | Deterministic only for a pinned version; a dependency bump would silently change the corpus |
| [12](12-seed-data.md) §3.7 | Migrate *then* seed | The original ordering inserted rows into tables that did not exist yet |
| [14](14-local-dev.md) §3.5 | Studio export moved to `app/graph/studio.py` | Constructing the graph opens a database — wrong at import time for a unit test |
| [17](17-agent-skills.md) §3.9a | **Added `tools.yaml`** | Tool descriptions are prompt text and were the one category still living in Python |
| [08](08-infrastructure.md) §3.6a, [ADR-007](adr/ADR-007-durable-sqlite-via-s3.md) | **Added a durability round-trip test** | The restore silently never ran; the guarantee had no observable symptom when it failed |
| [11](11-cicd.md) §3.3a, §3.4a | Repository checks, and where evals sit | The public-repo rule needed enforcing, and evals needed a home that is not the merge gate |
| [06](06-backend-api.md) §3.2a | **Thread listing is cursor-paginated** | The sort key is `updated_at` and sending a message rewrites it, so an `OFFSET` page silently drops whatever row slid across the boundary |
| [07](07-frontend.md) §3.10 | **A conversation is a route**, `/threads/:threadId` | Addressable, and it deletes a class of race rather than patching an instance of it |
| [07](07-frontend.md) §3.6a | Free text answers a checkpoint **in the composer** | The card's own input duplicated it — and the composer was posting to a suspended graph |
| [07](07-frontend.md) §3.9 | **Security headers moved into a per-location include** | `add_header` inside a `location` discards every inherited one, so the CSP reached no response at all |
| [18](18-aws-access-and-manual-steps.md) §7 | **Added the Cognito runbook**, CLI and console | Sign-in was the one flow with no path from nothing to working |
| [08](08-infrastructure.md) §3.4, [18](18-aws-access-and-manual-steps.md) §4 | **Removed the DynamoDB lock table** | Terraform ≥1.11 locks state in S3 natively. It was the only DynamoDB in the project, and its presence invited the reasonable question of why the app did not use it too |
| [19](19-agent-evaluation.md) §3.11, §3.12 | Multi-turn, safety, and trajectory eval layers | Three defects the other layers could not see — including `read_reference` failing on every call |
| [19](19-agent-evaluation.md) §3.13 | End-to-end layer, through the HTTP API | The seam between a working graph and a working transport was untested by either side |

One behavioural bug the specs did not predict is worth naming: the `confirm` checkpoint
was declared to fire above 20 interactions, but the corpus's long tail peaks at 12 — so
a documented behaviour could never occur. The threshold is now 10, and a test exercises
it.

## Conventions used throughout

- Requirements are referenced as `REQ-NNN` and defined once, in
  [01 — Requirements traceability](01-requirements-traceability.md).
- Anything not independently verified is marked `[UNVERIFIED]` inline. Prices, model
  IDs, package versions, and AWS API behaviour in these documents were checked against
  the live account or the vendor's own documentation — see
  [02 — Research](02-research.md) for the evidence and the date it was gathered.
- Diagrams are mermaid so they render in GitHub and stay diffable.
