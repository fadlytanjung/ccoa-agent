# 08 — Infrastructure

> **Status:** Approved — 2026-08-22
> **Satisfies:** REQ-006, REQ-040–045, REQ-093
> **Depends on:** [03 — Architecture](03-architecture.md), [ADR-005](adr/ADR-005-runtime-and-persistence.md), [ADR-006](adr/ADR-006-requirement-alignment-over-cost.md)

## 1. Purpose

The AWS resources, the Terraform that provisions them, and the procedure for standing
the environment up and tearing it down. Network design is in [09](09-networking.md);
this document covers everything else and the module layout.

## 2. Scope

**In scope:** resource inventory, Terraform structure, state backend, ECS/ECR/CloudFront
configuration, Cognito, Secrets Manager, autoscaling, deployment and teardown.

**Out of scope:** VPC and security-group design ([09](09-networking.md)), IAM policy
rationale ([10](10-security.md)), pipeline mechanics ([11](11-cicd.md)), costs
([16](16-cost-model.md)).

---

## 3. Design

### 3.1 Guiding constraints

**Only `dev` is ever applied.** `prod` exists as `envs/prod.tfvars` and as a gated
pipeline job, and is never provisioned
([ADR-006](adr/ADR-006-requirement-alignment-over-cost.md) §2). `dev` is therefore the
environment the requirements are evaluated against — it is a full-fidelity environment,
not a stripped-down tier.

**Ephemeral.** `dev` is applied to work and destroyed afterwards. Consequences that
shape every choice below:

- **`terraform destroy` must complete cleanly.** No resource may require manual emptying
  first. ECR repositories set `force_delete = true`; log groups have finite retention;
  the CloudFront distribution is disabled before deletion by the provider.
- **`terraform apply` must work on an empty account.** No console clicks, no
  pre-existing resources except the state backend (§3.4). REQ-093 is only proven if
  this holds.
- **Data is disposable.** The database ships in the image; nothing needs backing up.
- **Cost is reported, not optimised.** ADR-006 removed cost as a design driver.

### 3.2 Resource inventory

| Resource | Configuration | Why |
|---|---|---|
| VPC `10.0.0.0/16` | 2 AZs, 2 public + 2 private subnets | [09](09-networking.md) §1 |
| Internet Gateway | 1 | NAT egress |
| **NAT Gateway** | 1 per AZ in `prod`; **1 total in `dev`** (`var.single_nat_gateway`) | Availability against 23% of the idle bill — [09](09-networking.md) §6.3 |
| **CloudFront distribution** | HTTPS, **default certificate**, VPC origin — `var.edge = "cloudfront"` | Viewer TLS with no domain to buy. Substitutable for an internet-facing ALB where CloudFront is unavailable ([09](09-networking.md) §6.6) |
| **AWS WAF** | Managed rule sets + rate limiting. `CLOUDFRONT` scope, or `REGIONAL` attached to the ALB — same rules either way | Whatever the internet-facing surface is |
| **Application Load Balancer** | `internal` under `edge = "cloudfront"`; **internet-facing** under `edge = "alb"`, 2 AZs | Under CloudFront it has no public IP at all. As the edge it is the only ingress, and the security group becomes the boundary ([09](09-networking.md) §6.6) |
| ALB target groups | 2 — `frontend:8080`, `backend:8000` | Independent health and deployment |
| **Interface VPC endpoints** | ECR API, ECR DKR, Secrets Manager, CloudWatch Logs — **`prod` only** (`var.enable_interface_endpoints`) | AWS-service traffic never leaves the VPC. 40% of the idle bill, so `dev` routes it via NAT instead ([16](16-cost-model.md) §4a) |
| **S3 gateway endpoint** | Free | ECR layer pulls stay off the internet |
| ECS cluster | Fargate, **Container Insights on** | Operational visibility |
| ECS service `frontend` | ARM64, 0.25 vCPU / 0.5 GB, **min 0 / max 2** | Stateless; scales to zero |
| ECS service `backend` | ARM64, 0.5 vCPU / 1 GB, **min 0 / max 1** | `max 1` is a correctness bound — §3.6 |
| ECR repositories | 2, enhanced scanning, `force_delete` | One per service |
| Cognito User Pool | Hosted UI, PKCE app client, 2 groups, **advanced security on** | Identity ([10](10-security.md) §2) |
| Secrets Manager | **2 secrets** — Gemini API key, LangSmith API key | Injected at task start |
| **S3 bucket** | Versioned, SSE-S3, public access blocked, `force_destroy` | Litestream replication target — [ADR-007](adr/ADR-007-durable-sqlite-via-s3.md) |
| CloudWatch log groups | 3 — two services + **VPC Flow Logs**, 7-day retention | Bounded cost, clean destroy |
| IAM roles | 4 — 2 execution, 2 task | Least privilege ([10](10-security.md) §3) |

**No EFS, no RDS, no DynamoDB, no Aurora.** The datastore is a SQLite file inside the
backend image ([ADR-005](adr/ADR-005-runtime-and-persistence.md) §3). Managed database
alternatives are costed in [15](15-datastore-options.md) and deliberately not
provisioned ([ADR-006](adr/ADR-006-requirement-alignment-over-cost.md) §1a).

Still absent, with reasons that are **not** cost: Network Firewall (synthetic data only)
and GuardDuty (needs weeks to baseline) — [09](09-networking.md) §6.5.

### 3.3 Terraform layout

```
terraform/
├── main.tf              providers, locals, default_tags
├── versions.tf          terraform >= 1.11, aws ~> 5.70
├── variables.tf
├── outputs.tf           cloudfront_domain_name, cognito ids, ecr urls
├── backend.tf           S3 state, native locking — no DynamoDB
├── network.tf           VPC, subnets, IGW, NAT per AZ, routes    ─► docs/09
├── endpoints.tf         interface endpoints + S3 gateway         ─► docs/09
├── security_groups.tf   CloudFront-origin, ALB, services, endpoints
├── alb.tf               internal LB, listener, target groups, rules
├── cloudfront.tf        distribution, VPC origin, cache behaviours, WAF association
├── waf.tf               managed rule groups + rate limit
├── ecr.tf               two repositories + lifecycle policies
├── ecs_cluster.tf       cluster + Container Insights
├── ecs_frontend.tf      task definition, service, autoscaling
├── ecs_backend.tf       task definition, service, autoscaling
├── cognito.tf           pool, client, domain, groups, seed users
├── secrets.tf           two secret containers (values set out-of-band)
├── iam.tf               execution + task roles                   ─► docs/10
├── logs.tf              log groups + VPC Flow Logs
├── bootstrap/           one-time state backend (separate root)
└── envs/
    ├── dev.tfvars       the only environment ever applied
    └── prod.tfvars      configuration only — never applied
```

Flat, one file per concern. Two environments differing only in tfvars do not justify a
module hierarchy; if a third appears, the flat root becomes a module unchanged.

**Conventions:** no hardcoded account IDs or ARNs — everything is a variable, data
source, or resource reference. Common tags (`Project`, `Environment`, `ManagedBy`)
applied via `default_tags` so cost attribution is automatic and destroy scope is
verifiable.

### 3.4 State backend

Remote state in S3, **locked by S3 itself**, created once by `terraform/bootstrap/`:

| Resource | Configuration |
|---|---|
| S3 bucket | Versioning on, SSE-S3, public access blocked, `prevent_destroy` |

```hcl
backend "s3" {
  bucket       = var.state_bucket
  key          = "dev/terraform.tfstate"
  region       = "ap-southeast-1"
  use_lockfile = true    # a .tflock object, written conditionally
  encrypt      = true
}
```

**No DynamoDB lock table.** *(Amended 2026-08-22 — an earlier draft specified one.)*
Terraform 1.10 added native S3 locking via a conditional write and 1.11 deprecated
`dynamodb_table`, so the table is now a second service, a second IAM permission, and a
second thing to destroy, in exchange for nothing. Removing it also removes the only
place DynamoDB appeared in this project — which matters beyond tidiness, because a lock
table sitting in the architecture invites the reasonable question of why the
application does not just use DynamoDB too ([15](15-datastore-options.md) §3.4,
[18](18-aws-access-and-manual-steps.md) §3.4).

This is why [02](02-research.md) §1.1 requires Terraform **≥1.11**.

The bootstrap root is the **only** thing that survives `terraform destroy` of the main
stack, and costs effectively nothing at rest. It is what makes repeated destroy/apply
cycles safe. Both environments use the same bucket with distinct state keys.

### 3.5 CloudFront

| Setting | Value |
|---|---|
| Viewer certificate | **CloudFront default** (`*.cloudfront.net`) — no ACM, no domain |
| Viewer protocol | `redirect-to-https`, TLS 1.2 minimum |
| Origin | **VPC origin** → internal ALB, HTTP |
| WAF | Associated; managed common rule set + rate limiting |

**Cache behaviours are the highest-risk configuration in this design.** Getting them
wrong could serve one agent's response to another:

| Path pattern | Caching | Forwarded |
|---|---|---|
| `/api/*` | **Disabled** (`CachingDisabled` managed policy) | `Authorization`, all query strings, all cookies |
| `/assets/*` | Aggressive — content-hashed filenames | none |
| `/*` (default) | `index.html` — no-store | none |

The `/api/*` behaviour must be asserted in a test, not merely configured
([09](09-networking.md) §8).

### 3.6 ECS task definitions and autoscaling

**Backend:**

```hcl
family                   = "ccoa-backend"
requires_compatibilities = ["FARGATE"]
cpu                      = 512      # 0.5 vCPU
memory                   = 1024     # 1 GB
runtime_platform {
  cpu_architecture        = "ARM64"     # ~20% cheaper — docs/02 §6
  operating_system_family = "LINUX"
}

container_definitions = [{
  name         = "backend"
  image        = "${ecr_url}:${image_tag}"      # immutable SHA tag, never :latest
  portMappings = [{ containerPort = 8000 }]

  environment = [
    { name = "ENVIRONMENT",              value = var.environment },
    { name = "GEMINI_MODEL",             value = "gemini-3.5-flash" },
    { name = "COGNITO_USER_POOL_ID",     value = aws_cognito_user_pool.main.id },
    { name = "COGNITO_CLIENT_ID",        value = aws_cognito_user_pool_client.spa.id },
    { name = "LANGGRAPH_STRICT_MSGPACK", value = "true" },   # CVE-2026-28277 — docs/02 §4.2
    { name = "LANGSMITH_TRACING",        value = tostring(var.enable_langsmith) },
    { name = "LANGSMITH_PROJECT",        value = "ccoa-${var.environment}" },
  ]

  secrets = [
    { name = "GEMINI_API_KEY",    valueFrom = aws_secretsmanager_secret.gemini.arn },
    { name = "LANGSMITH_API_KEY", valueFrom = aws_secretsmanager_secret.langsmith.arn },
  ]

  healthCheck = {
    command  = ["CMD-SHELL", "curl -fsS http://localhost:8000/healthz || exit 1"]
    interval = 30, timeout = 5, retries = 3, startPeriod = 90
  }
}]
```

Load-bearing details, not boilerplate:

- **`LANGGRAPH_STRICT_MSGPACK=true`** is a CVE mitigation ([02](02-research.md) §4.2),
  not a tuning flag. Removing it reintroduces a deserialisation RCE path.
- **`secrets`, not `environment`, for both API keys.** Values never appear in the task
  definition, in `terraform show`, or in the ECS console.
- **Immutable SHA image tags.** `:latest` makes rollback ambiguous and redeploy
  non-reproducible.
- **`startPeriod = 90`** accommodates `alembic upgrade head` running before the app
  serves traffic ([04](04-data-model.md) §3.7).

**Autoscaling:**

| Service | min | max | Policy |
|---|---|---|---|
| `frontend` | **0** | 2 | Target tracking on ALB request count |
| `backend` | **0** | **1** | Scale 0↔1 on ALB request count |

`backend` max is **1 as a correctness constraint**, not as tuning. Each task carries its
own database copy, so two tasks would be two divergent datasets — a ticket created on
one invisible to the other ([04](04-data-model.md) §3.5). Raising it requires changing
the datastore, not the variable.

`min = 0` — compute costs nothing while idle. Scale-to-zero is safe **because**
replication is in place, not despite it: ECS scale-in is graceful (`SIGTERM`, then
`stopTimeout`), and Litestream as PID 1 performs a final sync before exiting, so a
planned scale-in loses nothing ([ADR-007](adr/ADR-007-durable-sqlite-via-s3.md) §1).

Two settings are correctness-critical, not tuning:

| Setting | Value | Why |
|---|---|---|
| `stopTimeout` | **60 s** | Litestream's final sync must finish before `SIGKILL`. Shorter and planned scale-in starts losing writes |
| Entrypoint | `litestream replicate -exec …` | Litestream must be PID 1 to own shutdown ordering |

**Cold start is ~45–75 s** on the backend: placement, image pull, Litestream restore,
`alembic upgrade head`, boot. Explicitly accepted.

**Durability.** The container entrypoint wraps the app in Litestream, which restores
both databases from S3 on boot and replicates the WAL continuously:

```dockerfile
ENTRYPOINT ["litestream", "replicate", "-exec", "uvicorn app.main:app --host 0.0.0.0 --port 8000"]
```

This makes tickets, approvals, and audit rows survive deploys, crashes, and task
replacement — up to ~1 s of writes may be lost on an abrupt kill. **Litestream would
silently corrupt data with more than one writer**, so `max_capacity = 1` is now
load-bearing twice over and carries a comment saying so.

The entrypoint restores into a temporary file and swaps it in, rather than using
Litestream's `-if-db-not-exists`. That flag is the obvious choice and is wrong here:
`/data/app.db` is *always* present because the build bakes the corpus in, so it skips
the restore on every boot. See §3.6a for why that matters more than it sounds.

### 3.6a Verifying durability

*(Added 2026-08-22.)* Everything above is a claim about a failure path nobody exercises
in normal use, and its failure mode is **silent**: a container that never restores still
boots, still passes both health checks, and still answers correctly. It just serves the
corpus baked in at build time, with none of the user's writes. Nothing in the logs says
so.

That is not hypothetical — it was the behaviour of the first working image here. The
entrypoint used `-if-db-not-exists`, restore never ran, and it took destroying a
container and looking for the data to notice.

So durability has a test:

```bash
cd backend
docker build -t ccoa-backend:dev .
./docker/verify-replication.sh
```

It runs against **MinIO** rather than S3 — same API surface for what Litestream uses,
and a check that needs a bucket, a role, and a region is a check nobody runs. Six
assertions, in the order the real lifecycle happens:

| Assertion | Guards |
|---|---|
| First boot falls through to the image's corpus | A first deploy must not fail for want of a replica |
| `app.db` is replicating | The business data reaches the bucket |
| `checkpoints.db` is replicating | A pending approval survives a task replacement (REQ-091) |
| `SIGTERM` produces a clean Litestream shutdown | `stopTimeout` and PID 1 are doing their job |
| Second boot restores from the replica | The failure described above |
| A write made before the kill is still there | The whole of [ADR-007](adr/ADR-007-durable-sqlite-via-s3.md), end to end |

Run it after any change to the Dockerfile, the entrypoint, or `litestream.yml`.

### 3.7 Cognito

| Resource | Configuration |
|---|---|
| User pool | Email sign-in, MFA optional, password ≥12 chars with complexity, **advanced security in audit mode** |
| App client | Public SPA client, **no secret**, Authorization Code + PKCE, callback to the CloudFront domain |
| Hosted UI domain | `ccoa-${environment}-<suffix>.auth.ap-southeast-1.amazoncognito.com` |
| Groups | `agent` (create tickets), `supervisor` (escalate) — [10](10-security.md) §3 |
| Seed users | Two demo users created by Terraform, temporary passwords surfaced as outputs |

The callback URL depends on the CloudFront domain, which Terraform knows only after the
distribution is created — so `cognito.tf` references
`aws_cloudfront_distribution.main.domain_name` directly rather than a variable.

### 3.8 Deployment procedure

```bash
# One-time, per account
cd terraform/bootstrap && terraform init && terraform apply

# Supply both secret values once (never in Terraform, never in git)
aws secretsmanager put-secret-value --secret-id ccoa/dev/gemini-api-key \
  --secret-string "$GEMINI_API_KEY" --region ap-southeast-1
aws secretsmanager put-secret-value --secret-id ccoa/dev/langsmith-api-key \
  --secret-string "$LANGSMITH_API_KEY" --region ap-southeast-1

# Per session
cd terraform && terraform init
terraform apply -var-file=envs/dev.tfvars     # ~15-20 min; CloudFront dominates
terraform output cloudfront_domain_name

# Teardown
terraform destroy -var-file=envs/dev.tfvars   # ~15 min; CloudFront disable is slow
```

**Ordering constraint:** ECS services reference images that must already exist in ECR.
The pipeline builds and pushes before applying ([11](11-cicd.md)); for a first manual
apply, target the ECR repositories, push images, then apply fully. Documented rather
than automated because it happens once per account.

**Secret values are set outside Terraform deliberately.** Passing one as a variable
writes it to state in plaintext, where it stays in every historical version.

---

## 4. Decisions and tradeoffs

| Decision | Alternative | Rationale |
|---|---|---|
| `dev` only; `prod` config never applied | Provision both | Demonstrates environment separation and a real promotion gate without a second stack. Honest limitation: `prod` is unproven — [ADR-006](adr/ADR-006-requirement-alignment-over-cost.md) §2 |
| CloudFront + internal ALB | Internet-facing ALB | HTTPS with no domain; the origin is unreachable from the internet. [ADR-005](adr/ADR-005-runtime-and-persistence.md) §2 |
| SQLite in the image | EFS, RDS, DynamoDB | Removes a shared-filesystem attack surface; right-sized for ~100 records. Alternatives costed in [15](15-datastore-options.md), not provisioned |
| ARM64 Fargate | x86_64 | ~20% cheaper, verified; no dependency lacks an arm64 wheel |
| Fargate | EC2-backed ECS, App Runner, Lambda | No hosts to patch. App Runner does not satisfy "ECS". Lambda fits neither a long SSE stream nor a container-local writer |
| `min_capacity = 0` + Litestream to S3 | Warm tasks; RDS; DynamoDB | Replication removes the data-loss path independently, so warm tasks would buy only latency. Under $1/month against ~$13/month for the smallest RDS. [ADR-007](adr/ADR-007-durable-sqlite-via-s3.md) |
| Interface endpoints deployed | Route AWS traffic via NAT | Secrets Manager traffic never leaves the VPC. [ADR-006](adr/ADR-006-requirement-alignment-over-cost.md) §3 |
| Flat Terraform root | Module hierarchy | Two environments differing only in tfvars |
| Secret values set out-of-band | Terraform variable | A variable lands in state in plaintext |
| SHA image tags | `:latest` | Reproducible deploys, unambiguous rollback |

## 5. Failure modes

| Failure | Detection | Behaviour |
|---|---|---|
| Task cannot pull the image | ECS event, task stops | Deployment stalls; previous task keeps serving. Check execution-role policy and the ECR endpoint |
| Secret missing or empty | Container exits at boot | Config validation names the missing variable in the log |
| `alembic upgrade head` fails | Container exits before serving | Task never becomes healthy; migration error is the first log line |
| CloudFront cannot reach the VPC origin | 502 at the edge | Fails closed — no public path exists to fall back to |
| AZ loss | One NAT and one subnet lost | Second AZ carries traffic; per-AZ NAT means egress survives |
| ALB health checks fail | Targets drain | `/readyz` output identifies whether database or model binding is at fault |
| Task replaced during an active approval | Task stops | Databases restored from S3 on the new task; approval survives. Up to ~1 s of writes may be lost — [ADR-007](adr/ADR-007-durable-sqlite-via-s3.md) §3 |
| `destroy` blocked by a non-empty ECR | Terraform error | Prevented by `force_delete = true` |
| State lock stuck | Apply hangs | `terraform force-unlock <id>` after confirming no run is active |
| Backend scaled above 1 | — | Prevented: `max_capacity = 1` with an explanatory comment |

## 6. Open questions

1. **CloudFront cache behaviour for `/api/*`** must be asserted by a test, not just
   configured. This is the highest-risk item in the stack — see §3.5.
2. **Litestream version pinning**, by version *and* SHA-256 in the Dockerfile — it is
   third-party supply-chain surface in the image.
3. **`stopTimeout = 60` must be asserted by a test**, not merely configured. Shortening
   it silently reintroduces write loss on every scale-in.
4. **S3 prefix must be namespaced by seed version** or a reseed is discarded on boot
   ([ADR-007](adr/ADR-007-durable-sqlite-via-s3.md) §1a).
3. **Deployment gap.** With `max_capacity = 1` and `minimumHealthyPercent = 0`, a
   backend deploy causes ~30–60 s of downtime. Unavoidable while the datastore is
   container-local.
4. **Should `prod` be applied once and destroyed**, to prove the configuration works?
   It would remove the "unproven configuration" caveat at the cost of one apply cycle.
