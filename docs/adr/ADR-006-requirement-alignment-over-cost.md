# ADR-006 — Requirement alignment takes priority over cost

> **Status:** Accepted
> **Date:** 2026-08-21
> **Amends:** [ADR-004](ADR-004-ephemeral-infrastructure.md), [ADR-005](ADR-005-runtime-and-persistence.md)
> **Affects:** [04](../04-data-model.md), [08](../08-infrastructure.md), [09](../09-networking.md), [10](../10-security.md), [11](../11-cicd.md)

## Context

Several controls were omitted, and one was actively weakened, on cost grounds. That
priority is now reversed: **the budget is not the binding constraint — satisfying the
stated requirements is.** Where a standard-practice control was skipped to save money,
it is restored.

Three related instructions land at the same time:

1. Migrations use **Alembic**, even on SQLite.
2. **Only `dev` is ever deployed.** `prod` exists as configuration and as a pipeline
   target, and is never applied.
3. Cost optimisation is no longer a design driver.

## Decisions

### 1. Alembic, reversing the plain-SQL decision

[04](../04-data-model.md) §3.7 argued for forward-only `.sql` files on the grounds that
the schema is small and the database disposable. That reasoning is withdrawn.

| | Plain SQL *(was)* | Alembic *(now)* |
|---|---|---|
| Downgrade | Not possible | `downgrade()` per revision |
| Ordering | Lexical filename | Explicit revision graph, `down_revision` |
| Drift detection | None | `alembic check` against the ORM models in CI |
| Applied-state tracking | Hand-rolled table | `alembic_version` |
| Pairs with | Nothing | SQLAlchemy models — one definition of the schema |

> **Correction.** An earlier revision of this ADR called cross-backend portability
> "the decisive argument" — that the schema must run on both SQLite and Postgres.
> **That argument is now void:** Postgres is documented as an alternative and will not be
> implemented (§1a). Alembic is still the right choice, but on the remaining grounds
> above — chiefly that it pairs with SQLAlchemy ORM models so the schema has one
> definition rather than two that can drift.

**If Alembic proves awkward on SQLite, plain forward-only SQL is an acceptable
fallback.** The `CHECK`-constraint-heavy schema needs `op.batch_alter_table` for most
changes, and autogenerate does not reliably detect `CHECK` changes. If that friction
outweighs the benefit, hand-written `.sql` migrations with a `schema_migrations` table
are fine — the schema is small and the corpus regenerates in seconds. An ORM-backed
migration remains preferable; this is a fallback, not a coin-flip.

### 1a. `DATABASE_URL` is documented, not implemented

Scope correction to [ADR-005](ADR-005-runtime-and-persistence.md) §4. The data layer is
**~100 seeded records in an in-container SQLite file**, and stays that way.

| | Status |
|---|---|
| In-container SQLite | **Implemented** — the only datastore |
| Neon / Supabase via `DATABASE_URL` | **Documented alternative. Not implemented, not tested, no code path** |
| RDS, Aurora, DynamoDB, DocumentDB | **Documented with costs, never provisioned** |

The requirements say mock data is acceptable and the technology choice is ours. At ~100
customers a managed database would be cost and operational weight buying nothing —
[15](../15-datastore-options.md) prices the alternatives so the decision is visible, and
stops there.

The repository interface stays ([04](../04-data-model.md) §3.6) because it is good
structure and makes the alternative *credible* rather than hypothetical. But there is no
second implementation, and the docs must not imply one is a config flag away.

Consequences:

- `backend/alembic/versions/` replaces `backend/app/migrations/*.sql`.
- `alembic upgrade head` runs at container start, before the app serves traffic.
- **Autogenerate is a drafting aid, never trusted output.** SQLite's limited
  `ALTER TABLE` support means batch operations (`op.batch_alter_table`) are required for
  column changes; every generated revision is reviewed and edited by hand.
- CI asserts `upgrade head` then `downgrade base` then `upgrade head` succeeds on a
  scratch database, so a broken downgrade is caught at build time.
- Seeding stays separate from migration. Schema is Alembic's; data is `app.seed`'s.

### 2. `dev` is the only deployed environment

`prod` is defined in Terraform (`envs/prod.tfvars`), targeted by the pipeline, and
**never applied**. This is deliberate and is documented rather than hidden:

| | `dev` | `prod` |
|---|---|---|
| Applied | **Yes** | **No — configuration only** |
| Purpose | The running system | Demonstrates environment separation and the promotion path |
| Pipeline | Auto-deploy on merge to `main` | Job exists, gated on a protected GitHub Environment with required reviewers |

The `prod` job is real, not commented out. It is gated on a manual approval that is
never granted, which is the same mechanism a real promotion gate uses — so the pipeline
demonstrates a genuine promotion path (REQ-073) without provisioning a second stack.

**`dev` is therefore the environment the requirements are evaluated against.** Every
control below applies to `dev` — it is no longer a stripped-down tier.

### 3. Controls restored

Each of these was previously omitted or weakened for cost. Verified rates in
[02](../02-research.md) §6; the column is retained for transparency, not as a
justification to skip anything.

| Control | Was | Now | Cost | Requirement served |
|---|---|---|---|---|
| NAT | 1 gateway (`prod`) / `t4g.nano` instance (`dev`) | **NAT gateway per AZ** | $0.059/hr each | REQ-053 — no single-AZ egress dependency, no host to patch |
| Interface VPC endpoints | Omitted — "NAT is needed anyway" | **Deployed**: ECR API, ECR DKR, Secrets Manager, CloudWatch Logs | $0.013/hr each per AZ | REQ-054, REQ-062 — **Secrets Manager traffic never touches the internet** |
| S3 gateway endpoint | Deployed | Unchanged | free | ECR layer pulls stay off the internet |
| AWS WAF on CloudFront | Omitted | **Deployed** — managed rule sets + rate limiting | ~$0.0075/hr + $0.60/M req | REQ-054, REQ-056 — the only internet-facing surface is now defended |
| VPC Flow Logs | Omitted | **Deployed** → CloudWatch, 7-day retention | ingest + storage | REQ-052, REQ-065 — the network design becomes demonstrable, not merely described |
| Container Insights | Off | **On** | per-metric | Operational visibility |
| ECR image scanning | Scan-on-push | Unchanged + **enhanced scanning** | per-image | REQ-094 |
| Cognito advanced security | Off | **On** (audit mode) | per-MAU | REQ-060 — compromised-credential detection |

**The single most valuable restoration is the Secrets Manager interface endpoint.**
Previously the Gemini and LangSmith API keys were fetched over NAT, across the public
internet, on every task start. That is now an entirely in-VPC call. It was the weakest
point in the secrets story ([10](../10-security.md) §4) and it was weak purely to save
$0.013/hour.

### 4. What is *not* restored

Honesty about the remaining gaps matters more than a complete-looking table.

| Still absent | Why |
|---|---|
| **Network Firewall** (FQDN egress allowlist) | ~$0.395/hr. Would genuinely restrict egress to named hosts. Omitted because all data is synthetic; this is the one control a real deployment would still need. Reconsider if `DATABASE_URL` ever points at real data |
| **GuardDuty** | Needs weeks to baseline; an environment applied and destroyed per session never provides that. Cost is not the reason |
| **Multi-region / DR** | Not a requirement; the environment is ephemeral by design |
| **End-to-end TLS to the task** | Needs per-task certificates and a rotation story for a hop that never leaves a private subnet. [09](../09-networking.md) §4.3 |
| **Custom domain + ACM** | Explicitly out of scope; CloudFront's default certificate covers viewer TLS |

### 5. Scale-to-zero is retained, but is now a preference, not a cost control

`min_capacity = 0` stays because it was explicitly requested and cold start is
acceptable. It is no longer justified by cost. **This should be revisited** — with the
budget constraint gone, `min_capacity = 1` removes the 35–60 s first-request delay and
makes the system materially better to demonstrate. Flagged as an open question rather
than reversed unilaterally.

## Consequences

**Good**

- The network and security posture is now standard practice rather than a
  cost-constrained subset. Nothing material is omitted to save money.
- Secrets, logs, and image pulls never traverse the internet.
- Per-AZ NAT removes the single-AZ egress dependency and the NAT host.
- WAF and Flow Logs make REQ-054 and REQ-052 demonstrable rather than asserted.
- One migration set runs on both SQLite and Postgres.
- The pipeline demonstrates a real promotion gate without a second live stack.

**Bad**

- `dev` running cost rises from ~$0.084/hr to roughly **$0.25/hr** (per-AZ NAT and eight
  endpoint-AZ pairs dominate). Still trivial against `terraform destroy` between
  sessions, and no longer the deciding factor.
- More resources to provision; `apply` and `destroy` both take longer.
- Alembic adds a dependency and a review burden on autogenerated revisions.
- `prod` is unproven — configuration that has never been applied is configuration that
  might not work. This is stated plainly rather than implied to be production-ready.

**Follow-up**

- [04](../04-data-model.md) §3.7 — rewrite for Alembic, including the SQLite
  `batch_alter_table` constraint.
- [08](../08-infrastructure.md) — add endpoints, WAF, Flow Logs, per-AZ NAT; state that
  only `dev` is applied.
- [09](../09-networking.md) — §5.2 and §6.5 change materially; endpoints and WAF move
  from "deliberately absent" to deployed.
- [10](../10-security.md) §4 — the Secrets Manager path is now in-VPC.
- [11](../11-cicd.md) — branch-to-environment mapping and the gated `prod` job.
- [16](../16-cost-model.md) — rebuild; cost is now reporting, not a design driver.
