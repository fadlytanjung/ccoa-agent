# ADR-002 — SQLite as the datastore

> **Status:** Accepted — **substantially amended by [ADR-005](ADR-005-runtime-and-persistence.md) §3 and [ADR-007](ADR-007-durable-sqlite-via-s3.md)**
> **Date:** 2026-08-21
> **Related:** [04 — Data model](../04-data-model.md), [15 — Datastore options](../15-datastore-options.md)

## Context

The requirements state that mock data is acceptable and the technology choice is ours.
The workload is **~2,000 rows, ~10 MB, one writer, read-mostly, relational, with a
nice-to-have vector search** ([15](../15-datastore-options.md) §3.1).

## Decision

**SQLite**, with `sqlite-vec` for vectors in the same file.

Nearly every managed database is built for a problem two or more orders of magnitude
larger. At this size a managed database adds a cluster, a subnet group, a credential to
rotate, a network hop, and a service that can be down — and buys nothing the workload
needs. Relational queries and vector search live in one file, so a semantic hit joins to
its interaction in a single query.

## Amendments

This ADR originally specified **SQLite on an EFS volume**. That was replaced in two steps:

| Change | By | Why |
|---|---|---|
| EFS → in-container | [ADR-005](ADR-005-runtime-and-persistence.md) §3 | The LangGraph checkpointer has a published SQLi→RCE chain; a shared network filesystem widened that surface for no benefit. Also made WAL usable |
| Ephemeral → durable | [ADR-007](ADR-007-durable-sqlite-via-s3.md) | In-container storage alone lost data on every restart. Litestream replicates to S3 and restores on boot |

The **SQLite decision itself survived both.** What changed was where the file lives and
how it is made durable.

## Consequences

**Good**
- Zero database infrastructure; ~$0.03/month total.
- Identical behaviour locally and in AWS, which makes tests meaningful.
- Vectors co-located, replicated for free.

**Bad**
- **One writer, ever.** `max_capacity = 1` is a correctness bound, and Litestream
  *corrupts* with more than one writer. This is the limit that would end the design if
  horizontal scaling were required.
- No point-in-time restore UI, no managed backups.
- Brute-force vector scan — fine to ~10⁵ vectors, wrong beyond.

**Alternatives** — DynamoDB, RDS, Aurora, Neon, Supabase — are costed in
[15](../15-datastore-options.md) and deliberately **not implemented**
([ADR-006](ADR-006-requirement-alignment-over-cost.md) §1a). Notably, DynamoDB was
declined on *shape*, not cost: the data model is join-heavy.
