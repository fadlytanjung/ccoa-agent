# ADR-007 — Durable SQLite via S3, with scale-to-zero retained

> **Status:** Accepted
> **Date:** 2026-08-21
> **Amends:** [ADR-005](ADR-005-runtime-and-persistence.md) §3, §5
> **Affects:** [03](../03-architecture.md), [04](../04-data-model.md), [08](../08-infrastructure.md), [10](../10-security.md)

## Context

[ADR-005](ADR-005-runtime-and-persistence.md) put SQLite inside the container and set
`min_capacity = 0`. Together those produced a defect that was accepted at the time and
should not have been: **a ticket created before an idle scale-in was gone afterwards,
along with any pending approval.** For a system whose headline feature is a
human-in-the-loop approval that survives a restart (REQ-091), that is close to
self-defeating.

Two questions were raised: should tasks stay warm, and can the data be made durable
without a managed database? The answer to the second makes the first unnecessary.

## Decisions

### 1. ~~`min_capacity = 1` for both services~~ — **REVISED to `min_capacity = 0`**

> **Revised 2026-08-21, same day.** The original decision set `min 1` on both services
> for two reasons: removing the cold start, and removing idle scale-in as a data-loss
> path. **§2 solves the second reason independently**, so it cannot also be used to
> justify warm tasks. Only the latency argument survives, and that is a weaker claim
> than the one made.

**Scale-in is graceful, which is the fact that decides this.** ECS sends `SIGTERM` and
waits `stopTimeout` before `SIGKILL`. Litestream runs as PID 1 under `-exec`, forwards
the signal to the app, waits for it to exit, and **performs a final sync before exiting
itself**. A planned scale-in therefore loses *nothing* — the ~1 s window in §3 applies
only to abrupt kills (crash, `SIGKILL`, host failure), which scale-to-zero does not
cause.

**Corrected decision:**

| Service | min | max | Cold start |
|---|---|---|---|
| `frontend` | **0** | 2 | ~30–45 s |
| `backend` | **0** | 1 (correctness bound) | ~45–75 s |

Two settings make this safe, and both are load-bearing rather than tuning:

| Setting | Value | Why |
|---|---|---|
| `stopTimeout` | **60 s** (not the 30 s default) | Litestream's final sync must complete before `SIGKILL`. Too short and planned scale-in *does* start losing writes |
| Entrypoint | `litestream replicate -exec …` | Litestream must be PID 1 to receive `SIGTERM` and own the shutdown ordering |

**Cold start is ~45–75 s** for the backend: task placement, image pull, Litestream
restore, `alembic upgrade head`, app boot. Accepted — scale-to-zero was explicitly
requested and cold start explicitly accepted.

### 1a. Restore-versus-seed precedence

Scale-to-zero makes boot-time restore routine rather than exceptional, which surfaces a
conflict the warm-task design never had to resolve: **the image ships a seeded database,
and S3 may hold a replicated generation.** Which wins?

```
if S3 generation exists for this seed version:   restore from S3   (has user writes)
else:                                            use the image's seeded database
                                                 and begin replicating
```

**The S3 prefix is namespaced by seed version**, e.g. `s3://…/litestream/v3/app.db`.
Without that, deploying a new image with a regenerated corpus would restore the *old*
generation over the new seed on first boot — the new data silently discarded. The seed
version is derived from the seed generator's inputs ([12](../12-seed-data.md)) and
bumping it starts a clean generation.

This is a genuine footgun that only appears under scale-to-zero, and it is the reason
§1a exists at all.

### 2. Durability via Litestream to S3

A container-local database is destroyed by every deploy, crash, task replacement, and
idle scale-in. Continuous replication closes all four gaps, which is what makes
`min_capacity = 0` safe rather than merely cheap (§1).

[Litestream](https://litestream.io) streams SQLite's WAL to object storage and restores
on boot. It replaces no application code — the container entrypoint wraps the app:

```dockerfile
ENTRYPOINT ["litestream", "replicate", "-exec", "uvicorn app.main:app --host 0.0.0.0 --port 8000"]
```

> **Verified 2026-08-22, after it did not work.** The first implementation passed
> `-if-db-not-exists` to `litestream restore`. Because the image always ships with
> `/data/app.db` baked in, that flag skipped the restore on **every** boot: the task
> booted, both health checks passed, and it served build-time data with none of the
> user's writes — silently. The entrypoint now restores into a temporary file and swaps
> it in, and `backend/docker/verify-replication.sh` exercises the whole cycle against
> MinIO so the regression cannot return unnoticed ([08](../08-infrastructure.md) §3.6a).
>
> The lesson worth keeping: this ADR's guarantee has no observable symptom when it
> fails. It needed a test, not a review.

On start it restores each database from S3 if a newer generation exists, then execs the
app and replicates continuously.

| Aspect | Value |
|---|---|
| Databases replicated | `app.db` **and** `checkpoints.db` — pending approvals are graph state |
| Requires WAL | Yes — available since the database became container-local ([ADR-005](ADR-005-runtime-and-persistence.md) §3) |
| Writer model | **Single writer only** — guaranteed by `max_capacity = 1` |
| Replication lag | ~1 s |
| Restore cost | A few seconds on cold start |
| S3 storage | **$0.025/GB-month** — a ~10 MB corpus is under a cent |
| S3 requests | **$5 per million PUTs**; idle periods write nothing. Realistically cents per month |

**Total durability cost is well under $1/month**, against roughly $13/month for the
smallest RDS instance plus storage — and RDS would also reintroduce a managed database,
a subnet group, and a credential to rotate, for ~100 records.

### 3. What this does and does not guarantee

Stated precisely, because "durable" is easy to overclaim:

| Scenario | Before | After |
|---|---|---|
| Idle scale-in | Data lost | **Nothing lost** — graceful `SIGTERM`, Litestream final sync (§1) |
| Deploy / task replacement | Data lost | **Restored from S3**, up to ~1 s of writes lost |
| Task crash | Data lost | **Restored from S3**, up to ~1 s of writes lost |
| `terraform destroy` | Data lost | Data lost — the bucket is destroyed with the stack, by design |
| Two concurrent writers | Corruption | Prevented by `max_capacity = 1`; **Litestream would corrupt if that bound were raised** |

The ~1 second window is real. A ticket approved and written at the instant the task is
killed can be lost. For synthetic data in an internal tool that is acceptable; it is
recorded rather than glossed.

### 4. Rejected alternatives

| Option | Why not |
|---|---|
| **Snapshot the whole file on each write** | Simpler, no extra binary — but racy, and loses everything since the last snapshot. Litestream is barely more work and much better. Kept as the fallback if Litestream proves troublesome |
| **RDS / Aurora Serverless** | ~$13+/month, a managed database, a subnet group, a credential to rotate — for ~100 records. Explicitly out of scope ([ADR-006](ADR-006-requirement-alignment-over-cost.md) §1a) |
| **DynamoDB** | Near-free at this scale, but a full datastore rewrite and it abandons SQL and `sqlite-vec` |
| **Neon / Supabase** | Documented alternatives only, never implemented ([ADR-006](ADR-006-requirement-alignment-over-cost.md) §1a) |
| **EFS** | Reintroduces the shared-filesystem surface ADR-005 removed |
| **SQLite VFS over S3** | Fragile; not a supported production pattern |

## Consequences

**Good**

- Approvals, tickets, and audit rows survive deploys, crashes, task replacement, **and
  idle scale-in**.
- Compute costs nothing while idle — scale-to-zero is restored, now safely.
- Under $1/month, versus a managed database.
- No application code changes — replication is an entrypoint concern.
- REQ-091 becomes true across restarts rather than only within one task's lifetime.

**Bad**

- Litestream is a third-party binary in the image: **pin the version and verify its
  checksum in the Dockerfile**, and record it as supply-chain surface
  ([10](../10-security.md) §6.1).
- ~1 s of writes can be lost on an **abrupt** kill (crash, host failure). Planned
  scale-in and deploys lose nothing.
- **Cold start is ~45–75 s** on the backend, and now happens after every idle period.
- `stopTimeout = 60` and the Litestream-as-PID-1 entrypoint are correctness settings; a
  future change to either silently reintroduces write loss on scale-in.
- The S3 prefix must be namespaced by seed version, or a reseed is discarded on boot
  (§1a).
- **Litestream would silently corrupt data if `max_capacity` were ever raised above 1.**
  This makes that bound doubly load-bearing and it must carry a comment saying so.
- One more IAM policy (S3 read/write, scoped to the bucket prefix) and one more bucket
  in the destroy path.

**Follow-up**

- [08](../08-infrastructure.md) — S3 bucket, task-role policy, `min_capacity = 1`,
  entrypoint change, `startPeriod` for restore.
- [04](../04-data-model.md) §3.5 — replication and the strengthened single-writer bound.
- [10](../10-security.md) — bucket encryption and public-access block; Litestream in the
  dependency-control table.
- [16](../16-cost-model.md) — one warm task pair plus S3.
