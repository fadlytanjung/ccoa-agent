# ADR-005 — Runtime, persistence, and TLS

> **Status:** Accepted
> **Date:** 2026-08-21
> **Supersedes in part:** [03](../03-architecture.md), [04](../04-data-model.md), [08](../08-infrastructure.md), [09](../09-networking.md), [10](../10-security.md)
> **Related:** [ADR-004](ADR-004-ephemeral-infrastructure.md)

## Context

The original design used an internet-facing ALB, ECS tasks in private subnets behind a
NAT gateway, and SQLite on a shared EFS volume. Four problems surfaced:

1. **No TLS.** Without an owned domain there is no ACM certificate for the ALB, so the
   ALB would serve HTTP and Bearer tokens would cross the internet in the clear. This
   was flagged as blocking.
2. **EFS as an attack surface.** The LangGraph checkpointer has a published SQLi → RCE
   chain ([02](../02-research.md) §4.2). Putting the checkpoint database on a *shared
   network filesystem* widens that surface for no benefit at this scale.
3. **No idle scaling.** ALB, NAT, and a pinned `desired_count = 1` meant a constant
   ~$0.12/hour whether or not anyone was using the system.
4. **Environment naming.** `demo` is not a real environment name.

## Decisions

### 1. Environments are `dev` and `prod`

`demo` is removed. Two environments, differing only in tfvars:

| | `dev` | `prod` |
|---|---|---|
| Lifecycle | Ephemeral — `apply` to work, `destroy` after | Long-lived |
| Idle cost | **$0** (destroyed) | ~$61/month floor (ALB + NAT) |
| ECS min capacity | 0 | 0 |
| NAT | `t4g.nano` instance | NAT gateway |
| Log retention | 1 day | 7 days |

### 2. CloudFront with a VPC origin to a **private** ALB

```
Browser ──HTTPS (free *.cloudfront.net cert)──► CloudFront
                                                    │  VPC origin, HTTP
                                                    │  (AWS network, never the public internet)
                                                    ▼
                                            internal ALB (private subnets)
                                                    ▼
                                              ECS services
```

- Viewer TLS uses CloudFront's **default certificate** — HTTPS with no domain to buy,
  which was the whole blocker.
- The ALB is `internal`. It has no public IP and is reachable **only** through the
  CloudFront distribution.
- CloudFront→origin is HTTP, but over a VPC origin — AWS's own path to a private ALB,
  not the public internet. HTTPS on that hop would require a CA-signed certificate on
  the ALB, which requires a domain; the private path is the better trade.

**Rejected:** internet-facing ALB restricted to the CloudFront prefix list plus a
shared secret header. It works, but the CloudFront→ALB hop is plaintext across the
public internet.

### 3. SQLite **inside the container**, EFS removed

The database ships in the image, seeded deterministically at build time
([12](../12-seed-data.md)). No EFS filesystem, no access point, no mount targets, no
NFS.

| Consequence | Detail |
|---|---|
| Attack surface | The checkpoint database is process-local. No shared filesystem to compromise |
| Cold start | No mount to wait on — the database is already there |
| WAL | **Now usable.** `journal_mode = WAL` works on a local filesystem, unlike NFS |
| Cost | $0 |
| **Writes do not survive a task stop** | With scale-to-zero this is not hypothetical — a ticket created before an idle scale-in is gone afterwards |

That last row is the real cost of this decision, and it is accepted deliberately: the
data is synthetic, the seed is deterministic, and every restart yields an identical,
known-good corpus. What is lost is a ticket created during a session, and the audit row
that recorded it.

### 4. `DATABASE_URL` escape hatch for persistence

> ⚠ **Scoped down by [ADR-006](ADR-006-requirement-alignment-over-cost.md) §1a:**
> documented as an alternative only. **Not implemented.** In-container SQLite is the
> only datastore.

Repositories are already an interface ([04](../04-data-model.md) §3.6). A second
implementation is selected by configuration:

| `DATABASE_URL` | Business data | Checkpointer |
|---|---|---|
| unset *(default)* | SQLite in-container | `AsyncSqliteSaver` |
| `postgresql://…` | Postgres | `AsyncPostgresSaver` |

Pointing `DATABASE_URL` at Neon or Supabase gives durable writes with no redesign —
both scale to zero, which preserves the idle-cost posture. It is not the default
because it adds an external dependency, a second credential, and a network hop on the
read path.

> If this is enabled, the connection string is a **secret** and belongs in Secrets
> Manager on the same terms as the API keys. Serverless Postgres also has its own cold
> start, which stacks with the ECS one.

### 5. Scale to zero, cold start accepted

ECS Application Auto Scaling with `min_capacity = 0`. The service scales in after a
sustained idle period and scales out on the first request.

- **First request after idle waits ~35–60 s** for task placement, image pull, and
  application boot. CloudFront holds the connection; the SPA shows a warming state.
- Idle cost is then the ALB (~$0.0252/hr) plus NAT (~$0.059/hr); CloudFront sits
  comfortably inside the perpetual free tier at this volume.
- **True $0 idle requires `terraform destroy`** — neither an ALB nor a NAT can scale to
  zero. That is what `dev` is for.

### 6. ~~No NAT — tasks in public subnets with public IPs~~ — **REVERSED**

> **Superseded 2026-08-21, before implementation.** The original decision put ECS tasks
> in public subnets with `assign_public_ip = true` to avoid the $0.059/hour NAT gateway.
> It was wrong and is reversed here.

The argument for it was that the public IP is not an exposure, because the task
security group only admits the ALB's security group. That is true *while the security
group is correct*. It is a single-control design: one over-permissive SG rule and the
backend is directly addressable from the internet, with no second layer to stop it.
Private subnets make that failure unreachable by routing, independently of any SG.

It also contradicted this design's own stated posture — [09](../09-networking.md) §3
defines the network boundary as "tasks in private subnets, no public IPs" — and
REQ-056 asks for an architecture *appropriate for sensitive customer information*.
Trading defence-in-depth for $39/month is the wrong trade in a system whose security
argument is the deliverable.

**Corrected decision: all compute stays in private subnets with no public IPs.**
Egress is via NAT. The cost is reconciled by choosing the NAT implementation per
environment rather than by moving the workload:

| | `dev` | `prod` |
|---|---|---|
| NAT | **NAT instance**, `t4g.nano` — **$0.0053/hr** | **NAT gateway** — **$0.059/hr** |
| Rationale | Ephemeral and low-traffic; a managed host is acceptable for hours | Managed, no host to patch, no single instance to lose |
| Idle floor | $0 — the stack is destroyed | ~$0.084/hr (ALB + NAT) ≈ $61/month |

Nothing in the VPC carries a public IP except the NAT itself. Verified rates in
[02](../02-research.md) §6.

**Interface VPC endpoints are documented but not deployed.** At **$0.013/hr per
endpoint per AZ**, the four needed (ECR API, ECR DKR, Secrets Manager, CloudWatch Logs)
cost $0.052/hr single-AZ — comparable to the NAT they would supplement, and NAT is
required regardless for Gemini and LangSmith. Only the **S3 gateway endpoint** is
deployed, because it is free and carries ECR layer pulls. Full analysis:
[09](../09-networking.md) §5.2.

| | Before ADR-005 | After correction |
|---|---|---|
| EFS | $0.36/GB-month | removed |
| ALB | internet-facing | **internal**, CloudFront VPC origin only |
| Compute | private subnets | private subnets *(unchanged)* |
| NAT | gateway, both envs | gateway in `prod`, `t4g.nano` instance in `dev` |
| Idle floor | ~$0.084/hr | ~$0.084/hr `prod`, **$0** `dev` |

### 7. LangSmith tracing enabled

LangGraph emits traces to LangSmith, configured by environment variable:

```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<secret>
LANGSMITH_PROJECT=ccoa-<environment>
```

This gives per-node timing, token accounting, and full run replay — the debugging
surface that makes a multi-agent graph tractable. It is a genuine strength for an
orchestration-heavy system.

**It also sends prompts, tool results, and graph state to a third-party service.**
Acceptable here only because all data is synthetic ([12](../12-seed-data.md)), on the
same reasoning that permits the Gemini call. It is a second egress destination and a
second secret. `LANGSMITH_TRACING` defaults to `false` and is enabled explicitly per
environment, so tracing is never on by accident.

### 8. MFA is available, not mandated

Cognito MFA is a configuration flag and is documented as such. The earlier
recommendation to enforce it is withdrawn — enabling it is a one-line change the
operator can make, not something this design should insist on.

## Consequences

**Good**

- HTTPS end-to-end from the browser, with no domain purchase.
- The origin is unreachable except through CloudFront.
- The EFS attack surface is gone; WAL becomes available.
- Idle cost in `dev` drops to $0 (destroyed); `prod` holds at ~$0.084/hr.
- Fewer moving parts: no EFS, no access point, no mount targets.
- All compute stays in private subnets with no public IPs — the network boundary is
  intact and independent of security-group correctness.
- LangSmith makes the multi-agent graph debuggable.

**Bad**

- **Writes are lost on task stop**, and scale-to-zero makes that routine rather than rare.
- First request after idle takes ~35–60 s.
- NAT remains an unavoidable cost floor in `prod` (~$0.059/hr), because Gemini and
  LangSmith are public endpoints.
- CloudFront→ALB is HTTP, albeit never over the public internet.
- Two third-party egress destinations now carry conversation data.
- CloudFront adds a distribution to provision; changes take minutes to propagate.

**Follow-up**

- [04](../04-data-model.md): drop the EFS/NFS constraints, switch to WAL, document the
  `DATABASE_URL` implementation.
- [08](../08-infrastructure.md), [09](../09-networking.md): rewritten against this ADR.
- [10](../10-security.md): remove the EFS section, add LangSmith egress, soften MFA.
- [15](../15-datastore-options.md): lead with in-container SQLite; cost Neon and Supabase
  alongside DynamoDB and Aurora.
- [16](../16-cost-model.md): rebuild on the new floor.
