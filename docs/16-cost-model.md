# 16 — Cost model

> **Status:** Approved — 2026-08-22
> **Satisfies:** REQ-045
> **Depends on:** [08 — Infrastructure](08-infrastructure.md), [ADR-006](adr/ADR-006-requirement-alignment-over-cost.md)

## 1. Purpose

What the environment actually costs to run. **Cost is reported here, not used as a
design driver** — [ADR-006](adr/ADR-006-requirement-alignment-over-cost.md) removed it
as a constraint, and several line items below are the direct, deliberate consequence.

## 2. Scope

**In scope:** verified rates, the idle and active hourly build-up, realistic session and
monthly figures, what drives the number, and the cost of the requirement-alignment
decisions.

**Out of scope:** which datastore and why ([15](15-datastore-options.md)), network design
([09](09-networking.md)).

---

## 3. Design

### 3.1 Verified rates — `ap-southeast-1`

Queried from the AWS Pricing API on 2026-08-21 ([02](02-research.md) §6). On-demand
list, USD, excluding tax.

| Resource | Rate | Source usage type |
|---|---|---|
| Fargate vCPU (ARM64) | **$0.04045** / vCPU-hour | `APS1-Fargate-ARM-vCPU-Hours` |
| Fargate memory (ARM64) | **$0.00442** / GB-hour | `APS1-Fargate-ARM-GB-Hours` |
| NAT Gateway | **$0.059** / hour | `APS1-NatGateway-Hours` |
| Application Load Balancer | **$0.0252** / hour | `LoadBalancing:Application` |
| ALB capacity units | $0.008 / LCU-hour | Negligible at this traffic |
| Interface VPC endpoint | **$0.013** / hour **per AZ** | `APS1-VpcEndpoint-Hours` |
| S3 Standard storage | **$0.025** / GB-month | First 50 TB |
| S3 PUT requests | **$0.000005** / request | $5 per million |
| AWS WAF Web ACL | **$5.00** / month | Per ACL |
| AWS WAF requests | **$0.0000006** / request | $0.60 per million |
| S3 gateway endpoint | **free** | — |
| CloudFront | **free tier** | 1 TB egress + 10 M requests/month, perpetual |
| Cognito | **free tier** | Well under 50 k MAU |

### 3.2 Idle — nothing running, stack applied

Tasks scale to zero ([ADR-007](adr/ADR-007-durable-sqlite-via-s3.md) §1), so idle cost
is the always-on network and edge layer:

| Component | Qty | Hourly |
|---|---|---|
| NAT Gateway | 2 (one per AZ) | $0.1180 |
| Interface VPC endpoints | 4 services × 2 AZ = 8 | $0.1040 |
| Application Load Balancer | 1 | $0.0252 |
| AWS WAF Web ACL | 1 ($5/mo ÷ 730) | $0.0068 |
| WAF managed rule groups | 2 (~$1/mo each) | $0.0027 |
| S3 (replica + state) | ~30 MB | ~$0.0000 |
| CloudFront, Cognito, ECR | — | free tier |
| **Idle total** | | **≈ $0.257 / hour** |

### 3.3 Active — both tasks running

| Component | Spec | Hourly |
|---|---|---|
| Idle baseline | above | $0.2570 |
| `backend` task | 0.5 vCPU / 1 GB, ARM64 | $0.0247 |
| `frontend` task | 0.25 vCPU / 0.5 GB, ARM64 | $0.0123 |
| **Active total** | | **≈ $0.294 / hour** |

Task compute is **4% of the bill**. Scale-to-zero saves about $0.037/hour — real, but
not the lever it looks like. The network layer is the cost.

### 3.4 Realistic figures

| Usage | Cost |
|---|---|
| One 8-hour working session | **≈ $2.35** |
| One 24-hour day, applied throughout | **≈ $6.60** |
| A working week (5 × 8 h, destroyed nightly) | **≈ $12** |
| Always-on for a month | **≈ $190** |

### 4a The cheap `dev` profile

*(Added 2026-08-23.)* The figures above describe the **full-fidelity** configuration,
which is what `prod.tfvars` sets. `dev.tfvars` turns off the two largest line items:

| Setting | Saves | Given up |
|---|---:|---|
| `single_nat_gateway = true` | $0.0590 / hr | One AZ's egress now depends on the other AZ's NAT |
| `enable_interface_endpoints = false` | $0.1040 / hr | ECR, Secrets Manager, and Logs traffic goes out via NAT rather than staying in the VPC |

| | Full fidelity | `dev` default |
|---|---:|---:|
| Idle | ≈ $0.257 / hr | **≈ $0.094 / hr** |
| A month, always on | ≈ $190 | **≈ $69** |
| A working day | ≈ $2.06 | **≈ $0.75** |

Neither change removes a capability, and no requirement stops being met — both are
availability and network-path trades, argued in [09](09-networking.md) §6.3. The
remaining cost is dominated by the ALB and the single NAT, and neither can be removed
without changing the architecture: the ALB is what a CloudFront VPC origin requires, and
the NAT is how the backend reaches the Gemini API from a private subnet.

**The largest saving is still `terraform destroy`.** An environment that is not running
costs nothing, which is the entire point of ADR-004.
| **Destroyed between sessions** | **$0** |

The gap between $190 and $12 is the entire argument for the ephemeral posture
([ADR-004](adr/ADR-004-ephemeral-infrastructure.md)). Nothing in the design needs to be
cheaper; the stack needs to not be running.

### 3.5 What the requirement-alignment decisions cost

[ADR-006](adr/ADR-006-requirement-alignment-over-cost.md) restored controls that had been
omitted for cost. Being explicit about the bill they carry:

| Control | Hourly | Share of idle | Buys |
|---|---|---|---|
| Interface VPC endpoints (8) | $0.1040 | **40%** | Secrets Manager, ECR, and Logs traffic never leaves the VPC |
| Second NAT Gateway | $0.0590 | 23% | No single-AZ egress dependency |
| WAF | $0.0095 | 4% | Managed rules + rate limiting on the only public surface |
| VPC Flow Logs | ~$0.002 | <1% | Network forensics; REQ-052 demonstrable |
| **Total restored** | **≈ $0.175** | **68%** | |

**Two-thirds of the idle bill is controls that were previously skipped to save money.**
Before ADR-006 the idle floor was about $0.084/hour; it is now $0.257. That is the
honest price of the posture — worth stating plainly rather than burying, because it is a
deliberate choice and someone should be able to reverse it knowingly.

The interface endpoints are the single largest line item, **larger than the NAT they
supplement**. That reads as poor value on a spreadsheet and is defensible only on the
security argument: without them the Gemini and LangSmith API keys were fetched across
the public internet on every task start ([09](09-networking.md) §5.2).

### 3.6 Gemini and LangSmith

| Service | Basis | Estimate |
|---|---|---|
| Gemini `gemini-3.5-flash` | Per token | **`[UNVERIFIED]`** |
| Gemini `gemini-embedding-001` | Per token, build-time only | Negligible — ~650 documents once per image |
| LangSmith | Per trace, free tier | $0 at this volume |

The default model was moved from `gemini-3.6-flash` to `gemini-3.5-flash` on 2026-08-22
to reduce per-token cost ([02](02-research.md) §3.1). The saving is **not quantified
here**, because the rates it would be computed from are the same ones that could not be
confirmed. `gemini-3.5-flash-lite` is cheaper again and is one environment variable away.

Published per-token prices for the Gemini 3.x family varied across secondary sources and
were **not confirmable from Google's own pricing page** during the environment survey
([02](02-research.md) §3.1). Rather than assert a number, the backend **records token
usage per run** (`span.model_request_end` equivalents in the structured log, plus
LangSmith when enabled), so spend is measured rather than predicted.

Given `gemini-3.5-flash` is a mid-tier model and a conversation turn is a few thousand
tokens, LLM spend is expected to be **well below the infrastructure cost** at demo
volumes — but that is a reasoned expectation, not a verified figure, and it is labelled
as such.

### 3.7 Cost controls in place

| Control | Effect |
|---|---|
| **`terraform destroy` between sessions** | The only control that matters — $190/month → $0 |
| Scale to zero | ~$0.037/hour while idle |
| ARM64 Fargate | ~20% off compute vs x86 |
| S3 gateway endpoint | ECR layer pulls avoid NAT data charges |
| 7-day log retention | Bounded CloudWatch growth |
| `default_tags` on every resource | Cost attribution by `Project` / `Environment` |
| Container Insights on | Adds cost; accepted for visibility (ADR-006) |

**No budget alarm is configured.** At $0.26/hour a runaway costs about $6/day, which is
visible long before it matters — and an alarm on an environment meant to be destroyed
would mostly generate noise. Worth revisiting if the stack is ever left up.

### 3.8 If cost mattered again

Recorded so the tradeoff is reversible knowingly rather than by accident:

| Change | Saves | Costs you |
|---|---|---|
| Drop interface endpoints | $0.104/hr (40%) | Secrets/ECR/Logs traverse the internet |
| Single NAT Gateway | $0.059/hr (23%) | Single-AZ egress dependency |
| NAT instance (`t4g.nano`, $0.0053/hr) | $0.054/hr | A host to patch, single point of failure |
| Drop WAF | $0.0095/hr | No rate limiting or managed rules |
| **All of the above** | **$0.227/hr → $0.030/hr idle** | The posture ADR-006 exists to establish |

Even fully stripped, the ALB alone keeps idle above zero. **`terraform destroy` remains
the only route to $0.**

---

## 4. Decisions and tradeoffs

| Decision | Alternative | Rationale |
|---|---|---|
| Report cost, do not optimise it | Cost-driven design | [ADR-006](adr/ADR-006-requirement-alignment-over-cost.md) — requirement alignment is the binding constraint |
| Ephemeral `dev` | Always-on | $190/month → $0. The only control that materially matters |
| Scale to zero | Warm tasks | Safe once replication exists; saves $0.037/hr and adds a 45–75 s cold start |
| ARM64 | x86_64 | ~20% cheaper, verified, no dependency lacks an arm64 wheel |
| Measure LLM spend | Estimate it | Published rates were not confirmable; a measured number beats an invented one |
| No budget alarm | Alarm at a threshold | An environment meant to be destroyed would generate noise, not signal |

## 5. Failure modes

| Failure | Detection | Behaviour |
|---|---|---|
| Stack left applied over a weekend | Cost Explorer | ~$18. Annoying, not alarming |
| `destroy` fails partway | Terraform error | NAT and ALB are the expensive survivors — check those first |
| Runaway LLM spend | Token usage in logs / LangSmith | Bounded by graph iteration limits ([05](05-langgraph-orchestration.md) §3.5) |
| NAT data-processing spike | Cost Explorer by usage type | S3 gateway endpoint already removes the largest source (image layers) |
| Endpoints provisioned in more AZs | Plan diff | Per-AZ pricing means AZ count multiplies this line item directly |

## 6. Open questions

1. **Confirm Gemini per-token pricing** from Google's official pricing page and replace
   the `[UNVERIFIED]` marker in §3.6.
2. **Are eight endpoint-AZ pairs necessary?** Single-AZ endpoints would halve the largest
   line item at the cost of an AZ dependency for AWS-service calls — the same tradeoff
   §6.3 of [09](09-networking.md) makes for NAT, and it was answered differently there.
   Worth reconciling.
3. **Should `destroy` be automated** on a schedule, so a forgotten stack cannot accrue
   cost? A nightly teardown would make the ephemeral posture enforced rather than
   remembered.
