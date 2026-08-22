# 15 — Datastore options

> **Status:** Approved — 2026-08-22
> **Satisfies:** REQ-034, REQ-045, REQ-091
> **Depends on:** [04 — Data model](04-data-model.md), [ADR-007](adr/ADR-007-durable-sqlite-via-s3.md)

## 1. Purpose

The requirements leave the data-layer technology to our discretion. This document
records what was chosen, what was considered, and what each alternative costs — so the
decision is visible rather than assumed.

**None of the alternatives are implemented.** They are priced and compared, and the
build stops there ([ADR-006](adr/ADR-006-requirement-alignment-over-cost.md) §1a).

## 2. Scope

**In scope:** the chosen datastore, evaluated alternatives with verified costs, the
migration path if requirements changed, and honest limits.

**Out of scope:** schema ([04](04-data-model.md)), corpus ([12](12-seed-data.md)),
vector storage ([13](13-vector-search.md)).

---

## 3. Design

### 3.1 What is actually needed

Sizing the problem first, because most of the alternatives below are answers to a much
larger question:

| Requirement | Value |
|---|---|
| Rows | **~2,000** across all tables ([12](12-seed-data.md) §3.1) |
| Size | **~10 MB** including vectors |
| Concurrent writers | **1** — the ECS service is capped at one task |
| Concurrent readers | 1–5 (a handful of agents) |
| Write rate | A few per session — ticket creation, escalation, audit |
| Read rate | Tens per conversation turn |
| Durability | Must survive deploys, crashes, and scale-in (REQ-091) |
| Relational queries | Yes — joins across customer, claim, case, interaction |
| Vector search | Yes, nice-to-have ([13](13-vector-search.md)) |

**This is a small, relational, single-writer, read-mostly workload.** Nearly every
managed database is built for a problem two or more orders of magnitude larger.

### 3.2 Chosen — SQLite in-container, replicated to S3

| Aspect | Value |
|---|---|
| Engine | SQLite, `journal_mode = WAL` |
| Location | Inside the container image, seeded at build |
| Durability | Litestream → S3, restored on boot ([ADR-007](adr/ADR-007-durable-sqlite-via-s3.md)) |
| Migrations | Alembic ([04](04-data-model.md) §3.7) |
| Vectors | `sqlite-vec` in the same file |
| **Cost** | **~$0.03/month** (S3 storage + requests) |

Why it fits:

- **Zero infrastructure.** No cluster, no subnet group, no parameter group, no
  credential to rotate, no service that can be down independently.
- **Relational and vector in one file**, so a semantic hit joins to its interaction in a
  single query.
- **Identical locally and in AWS**, which makes [14](14-local-dev.md) simple and makes
  tests meaningful.
- **Replicated for free** — Litestream already covers whatever the file contains.
- **Sub-millisecond reads** on a 10 MB working set that stays in page cache.

Why it is defensible rather than merely cheap: at 2,000 rows a managed database adds
operational weight, a network hop, and a failure mode, and buys nothing the workload
needs.

### 3.3 Limits — stated plainly

| Limit | Consequence |
|---|---|
| **One writer, ever** | `max_capacity = 1` is a correctness bound. Litestream **corrupts** with more than one writer |
| No horizontal scaling | More traffic means a bigger task, not more tasks |
| ~1 s write window on abrupt kill | Graceful scale-in and deploys lose nothing; a crash can lose the last second |
| `terraform destroy` destroys the data | The bucket goes with the stack, by design |
| Brute-force vector scan | Fine to ~10⁵ vectors, wrong beyond |
| No point-in-time restore UI | Litestream supports it; there is no console for it |

**The single-writer bound is the one that would end this design** if the requirements
changed. Everything else is a matter of degree.

### 3.4 Alternatives, costed

Rates verified from the AWS Pricing API for `ap-southeast-1` ([02](02-research.md) §6).

| Option | Monthly (idle) | Fits? | Assessment |
|---|---|---|---|
| **SQLite + Litestream** *(chosen)* | **~$0.03** | ✓ | Zero infrastructure; single-writer |
| **DynamoDB on-demand** | **~$0** (25 GB free tier) | ✗ relational | Genuinely near-free and scales horizontally — but no joins, no SQL, no `sqlite-vec`. The data model is join-heavy ([04](04-data-model.md) §3.1); modelling it in single-table DynamoDB would be significant work for a 2,000-row corpus. **The strongest alternative if horizontal scaling were required** |
| **RDS PostgreSQL `db.t4g.micro`** | ~$13 + storage | ✓ | Real relational database, `pgvector` available, multi-writer. Adds a subnet group, a parameter group, a credential to rotate, and a service that can be down. ~400× the cost for a workload that fits in RAM |
| **Aurora Serverless v2** | ~$43 (0.5 ACU minimum) | ✓ | Scales to 0.5 ACU, not to zero. Excellent at scale; disproportionate here |
| **Neon (serverless Postgres)** | $0 free tier | ✓ | Genuinely scales to zero, generous free tier, `pgvector`. **Outside AWS** — a third-party dependency, a credential, and customer data leaving the account boundary |
| **Supabase** | $0 free tier | ✓ | As Neon, plus auth and storage we do not need. Free tier **pauses after inactivity**, which stacks badly with ECS cold start |
| **DocumentDB** | ~$200+ | ✗ | Wrong shape and wrong price |
| **EFS + SQLite** | ~$0.36 | ✗ | Rejected: shared-filesystem attack surface, and WAL is unusable over NFS ([ADR-005](adr/ADR-005-runtime-and-persistence.md)) |

Two honest observations:

- **DynamoDB is not expensive** — the "no high-cost AWS database" concern does not apply
  to it. The reason to decline it is *shape*, not cost: this data is relational, and
  flattening it into single-table design to avoid a $0 bill on a 10 MB dataset is effort
  spent in the wrong place.
- **And it would take the checkpointer with it.** *(Added 2026-08-22.)* Human-in-the-loop
  durability rests on `langgraph-checkpoint-sqlite` **3.1.1**, pinned to a version
  carrying two CVE fixes ([02](02-research.md) §4.2). The DynamoDB equivalent on PyPI is
  a third-party package at **0.1.0**. Moving the datastore means either replacing a
  pinned, patched checkpointer with a pre-1.0 one in the component that guarantees an
  approval survives a task replacement, or running SQLite for checkpoints and DynamoDB
  for business data — two datastores, which is worse than either.
- **Nothing else in this design pulls DynamoDB in.** The Terraform state lock used to,
  and no longer does: native S3 locking (`use_lockfile`, Terraform ≥1.11) removed the
  last reason this project would create a table at all
  ([18](18-aws-access-and-manual-steps.md) §4).
- **Neon and Supabase are technically strong** and would fix the single-writer limit for
  free. They are declined because they move customer data outside the AWS account
  boundary for a system whose requirements emphasise sensitive information and internal
  use ([09](09-networking.md) §5.3) — and because `DATABASE_URL` is documented, not
  implemented ([ADR-006](adr/ADR-006-requirement-alignment-over-cost.md) §1a).

### 3.5 What would change the decision

The chosen datastore is right for the stated requirements. It stops being right if any
of these become true:

| Trigger | Move to | Why |
|---|---|---|
| More than one backend task required | **DynamoDB** or RDS/Aurora | Single-writer is a hard bound, not a tuning limit |
| Real customer data | **RDS/Aurora in-VPC** | Third-party and outside-account options become unacceptable |
| Corpus beyond ~10⁵ vectors | Aurora + `pgvector`, or S3 Vectors | Brute-force scan stops being viable |
| Zero-tolerance for the ~1 s window | Any synchronous-commit database | Replication is asynchronous by nature |
| Cross-region availability | Aurora Global, or DynamoDB global tables | Out of scope today |

### 3.6 Migration path

The repository interface ([04](04-data-model.md) §3.6) exists to make this credible
rather than hypothetical — but it is a **design affordance, not a shipped capability**:

```
repositories/  ← Protocol per aggregate, returning Pydantic models
   sqlite/     ← the only implementation
   postgres/   ← does not exist
```

Moving to Postgres would mean: a second repository implementation, Alembic already
targets both dialects, `AsyncPostgresSaver` in place of `AsyncSqliteSaver`
([05](05-langgraph-orchestration.md)), `pgvector` in place of `sqlite-vec`, and removing
the `max_capacity = 1` bound plus Litestream.

That is a real project, not a config flag, and the docs should not pretend otherwise.

---

## 4. Decisions and tradeoffs

| Decision | Alternative | Rationale |
|---|---|---|
| SQLite in-container | Any managed database | 2,000 rows, one writer, read-mostly. Managed databases solve a problem this workload does not have |
| Litestream → S3 for durability | Accept data loss; use RDS | Satisfies REQ-091 for ~$0.03/month against ~$13/month |
| Not DynamoDB | DynamoDB on-demand | Cost is not the objection — the data model is join-heavy and `sqlite-vec` co-location is valuable |
| Not Neon/Supabase | Either free tier | Moves customer data outside the AWS account boundary |
| Repository interface with one implementation | Concrete SQLite calls throughout | Keeps the migration path real and the code testable, without pretending a second backend exists |
| Vectors in the same file | Separate vector store | One query, one file, replicated free ([13](13-vector-search.md)) |

## 5. Failure modes

| Failure | Detection | Behaviour |
|---|---|---|
| Corrupt database | `PRAGMA quick_check` at boot | `/readyz` fails; ECS replaces the task; Litestream restores |
| Litestream restore fails | Startup error | Task fails to become healthy — fails closed rather than serving an empty corpus |
| S3 unreachable at boot | Restore timeout | Falls back to the image's seeded database; replication resumes when S3 returns |
| `max_capacity` raised above 1 | — | **Silent corruption.** The only defence is the bound and its comment (§3.3) |
| Disk pressure in the task | Task-level metrics | 10 MB against a Fargate task's ephemeral storage is not a realistic risk |
| Write during scale-in | Graceful `SIGTERM` + final sync | Nothing lost ([ADR-007](adr/ADR-007-durable-sqlite-via-s3.md) §1) |

## 6. Open questions

1. **Should Litestream snapshot retention be bounded?** It defaults to keeping
   generations indefinitely; on an ephemeral bucket that never matters, but a lifecycle
   rule would make it explicit.
2. **Is `PRAGMA quick_check` enough at boot, or should it be `integrity_check`?**
   `quick_check` is much faster and cold start is already 45–75 s; `integrity_check` is
   thorough but slow on every boot.
3. **Should the audit log be exported to S3 with Object Lock**, independently of
   Litestream? It is the one table where tamper-evidence has real value
   ([10](10-security.md) §8, limitation 9).
