# ADR-004 — Ephemeral infrastructure

> **Status:** Accepted — **amended by [ADR-006](ADR-006-requirement-alignment-over-cost.md) §2**
> **Date:** 2026-08-21
> **Related:** [08 — Infrastructure](../08-infrastructure.md), [16 — Cost model](../16-cost-model.md)

## Context

The environment exists to run and demonstrate the system, not to serve continuous
production traffic. An always-on stack costs about **$190/month**
([16](../16-cost-model.md) §3.4), dominated by NAT gateways, VPC endpoints, and the ALB
— none of which can scale to zero.

## Decision

**Infrastructure is applied when needed and destroyed afterwards.**

```bash
terraform apply   -var-file=envs/dev.tfvars    # ~15-20 min
# ... use it ...
terraform destroy -var-file=envs/dev.tfvars    # ~15 min
```

This is not a cost optimisation in the ADR-006 sense — it does not weaken any control.
It simply declines to pay for an environment nobody is using. Every control is fully
present while the stack is up.

Three constraints follow, and each shapes the infrastructure spec:

| Constraint | Consequence |
|---|---|
| **`destroy` must complete cleanly** | ECR uses `force_delete`; the replica bucket uses `force_destroy`; log groups have finite retention |
| **`apply` must work on an empty account** | No console steps, no pre-existing resources except the state backend. REQ-093 is only proven if this holds |
| **No long-lived state outside ECR** | The corpus ships in the image; user writes replicate to S3 and are destroyed with the stack, by design |

## Amendment

[ADR-006](ADR-006-requirement-alignment-over-cost.md) §2 narrowed this: **only `dev` is
ever applied.** `prod` exists as `envs/prod.tfvars` and as a gated pipeline job that is
never approved. The honest limitation is that `prod` configuration has therefore **never
been executed** and is unproven.

## Consequences

**Good**
- $0 when not in use, against ~$190/month always-on.
- Every `apply` exercises the full provisioning path, so REQ-093 is continuously proven
  rather than assumed.
- No configuration drift — the environment is never long-lived enough to drift.
- The account returns to its surveyed green-field state ([02](../02-research.md) §1).

**Bad**
- **15–20 minutes of lead time** before the system is usable; CloudFront dominates.
- **User data is destroyed with the stack.** Litestream replicates to a bucket that is
  itself destroyed — durability spans restarts, not teardowns
  ([ADR-007](ADR-007-durable-sqlite-via-s3.md) §3).
- Cognito user pool is recreated, so demo users get new credentials each time.
- The CloudFront domain changes on every apply, so any bookmarked URL breaks.

**Mitigation not taken:** a scheduled nightly `destroy` would make the posture enforced
rather than remembered. Recorded as an open question in [16](../16-cost-model.md) §6.
