# CCOA — AI Contact Center Operations Assistant

An AI-powered operations assistant that helps customer-service agents investigate
issues, retrieve customer information, review previous interactions, determine
appropriate actions, escalate complex cases, and create service tickets — through a
conversational interface.

Built with **LangGraph** for orchestration and deployed on **AWS** with **Terraform**,
**Docker**, **ECS Fargate**, and a **GitHub Actions** CI/CD pipeline.

> **Status.** The application is **built and tested** — backend, frontend, agent
> evaluations, and both container images. **Nothing is deployed:** `terraform/` is empty
> and no AWS API call in this repository has ever been made.
>
> [`docs/20-implementation-status.md`](docs/20-implementation-status.md) is the authority
> on what is real, component by component, and a CI check keeps it honest. Every other
> document reads the same whether or not code exists behind it — so start there.

---

## Quick start

```bash
cp backend/.env.example backend/.env    # add a Gemini API key
./scripts/preflight.sh                  # check your tooling
./scripts/dev.sh                        # API on :8000, app on :5173
```

Open <http://localhost:5173> and ask:

> *Why did John Tan's claim submission fail? Check his policies and open cases.*

Two customers share that name in the seeded corpus, deliberately — so the agent stops and
asks which one, then investigates and answers with citations you can click.

| | |
|---|---|
| Full guide, clone → deployment | [`docs/22-getting-started.md`](docs/22-getting-started.md) |
| Run every check CI runs | `./scripts/verify.sh` |
| Real Cognito sign-in, from localhost | `./scripts/aws-cognito.sh`, then `./scripts/dev.sh --cognito` |
| What is built vs. specified | [`docs/20-implementation-status.md`](docs/20-implementation-status.md) |

---

## The scenario

The assistant is modelled on an **insurance** contact centre, because the reference scenario is a *failed claim submission*. Seed data, tools, and workflows are
built around claims, policies, tickets, and cases.

Supported requests include:

| Request | Workflow |
|---|---|
| *"Show me the details for customer John Tan."* | Customer lookup |
| *"Summarize previous interactions for customer John Tan."* | Interaction review + summarisation |
| *"Customer reports a failed claim submission. Help me investigate."* | Multi-step case investigation |
| *"Create a support ticket for this issue."* | Ticket creation — gated on human approval |
| *"This needs a supervisor."* | Escalation — gated on supervisor authorisation |

---

## Architecture at a glance

```
                         Browser
                            │  HTTPS  (free *.cloudfront.net certificate)
                    ┌───────▼────────┐
                    │   CloudFront   │   no custom domain required
                    └───────┬────────┘
                            │  VPC origin — AWS network, never the public internet
                    ┌───────▼────────┐
                    │  internal ALB  │   no public IP; reachable only via CloudFront
                    └───┬────────┬───┘   Cognito JWT required on every /api/*
             /  (SPA)   │        │  /api/*
        ┌───────────────▼─┐  ┌───▼───────────────┐
        │    frontend     │  │      backend      │  two independent ECS Fargate
        │  nginx + Vite   │  │ FastAPI+LangGraph │  services, ARM64, scale 0↔1
        └─────────────────┘  └───┬───────────┬───┘
                                 │           │  egress via NAT (private subnets)
                    ┌────────────▼──┐   ┌────▼──────────────────┐
                    │ SQLite in the │   │ Gemini API            │
                    │  container    │   │ LangSmith (opt-in)    │
                    │ + vectors     │   │ Secrets Manager       │
                    │ + checkpoints │   └───────────────────────┘
                    └───────────────┘
```

Idle floor is the ALB plus NAT (~$0.084/hour in `prod`); tasks scale to zero and the first request
after idle takes ~35–60 s. In `dev` the whole stack is destroyed when not in use.

Full detail: [`docs/03-architecture.md`](docs/03-architecture.md) and
[`docs/09-networking.md`](docs/09-networking.md).

---

## Repository layout

```
frontend/    React 19 + Vite + TypeScript SPA (nginx container)
backend/     FastAPI + LangGraph orchestration service (Python 3.12)
terraform/   AWS infrastructure — ap-southeast-1, envs/dev.tfvars + envs/prod.tfvars
docs/        Specifications (start at docs/README.md)
```

---

## Key engineering decisions

| Decision | Choice | Rationale |
|---|---|---|
| LLM | Gemini `gemini-3.5-flash` via Developer API | Strong tool-calling at low cost; no Bedrock model-access dependency. [ADR-001](docs/adr/ADR-001-llm-provider.md) |
| Orchestration | LangGraph `1.2.11`, self-hosted | Required orchestration engine; self-hosted on ECS per the infrastructure requirements. [docs/05](docs/05-langgraph-orchestration.md) |
| Datastore | SQLite **inside the container**, no EFS | Removes a shared-filesystem attack surface and all storage cost. Writes do not survive a task stop; `DATABASE_URL` switches to Neon/Supabase Postgres for durability. [ADR-005](docs/adr/ADR-005-runtime-and-persistence.md) |
| Vector search | `sqlite-vec` in the same database file | Zero additional infrastructure, identical locally and in AWS. [docs/13](docs/13-vector-search.md) |
| Agent topology | Orchestrator delegating to four specialist agents | Context isolation and per-agent capability scoping. [docs/05](docs/05-langgraph-orchestration.md) |
| Agent behaviour | Versioned skill files (`SKILL.md` + YAML frontmatter + templates) | No prompt text in code — reviewable, hot-reloadable, independently versioned. [docs/17](docs/17-agent-skills.md) |
| Human-in-the-loop | Four ask kinds on a durable `interrupt()` | Clarify, confirm, approve, and steer — conversational rather than a single approval modal. [docs/05](docs/05-langgraph-orchestration.md) |
| Auth | Cognito User Pool, OIDC + PKCE, group-based RBAC | Managed identity; group claims drive tool authorisation. [docs/10](docs/10-security.md) |
| TLS | CloudFront default certificate + VPC origin to a private ALB | HTTPS with no domain to buy; the origin is unreachable except through CloudFront. [ADR-005](docs/adr/ADR-005-runtime-and-persistence.md) |
| Observability | LangSmith tracing, opt-in per environment | Per-node timing, token accounting, full run replay for a multi-agent graph. [ADR-005](docs/adr/ADR-005-runtime-and-persistence.md) |
| Cost posture | `dev` ephemeral ($0 idle); `prod` ~$61/mo floor | ALB and NAT cannot scale to zero — that floor is why `dev` is destroyed. [docs/16](docs/16-cost-model.md) |

---

## Quickstart

Prerequisites, local development, seeding, and deployment are documented in
[`docs/14-local-dev.md`](docs/14-local-dev.md) and
[`docs/08-infrastructure.md`](docs/08-infrastructure.md).

```bash
# Local
cd backend  && uv sync && uv run python -m app.seed --reset
uv run uvicorn app.main:app --reload      # API      → http://localhost:8000
uv run langgraph dev                      # Studio   → http://localhost:2024
cd frontend && npm ci && npm run dev      # SPA      → http://localhost:5173

# AWS — dev is ephemeral: apply to work, destroy when done
cd terraform && terraform apply -var-file=envs/dev.tfvars
# ... use it ...
terraform destroy -var-file=envs/dev.tfvars
```

You will need a **Gemini API key** (`backend/.env` locally, AWS Secrets Manager in
the cloud). Nothing else requires manual credential handling.

---

## Documentation

| | Document |
|---|---|
| **Start here** | [Reading order and status](docs/README.md) |
| Principles | [Engineering constitution](docs/00-constitution.md) |
| Traceability | [Requirements → specs](docs/01-requirements-traceability.md) |
| Research | [Verified environment survey](docs/02-research.md) |
| Design | [Architecture](docs/03-architecture.md) · [Data model](docs/04-data-model.md) · [LangGraph orchestration](docs/05-langgraph-orchestration.md) |
| Services | [Backend API](docs/06-backend-api.md) · [Frontend](docs/07-frontend.md) |
| Platform | [Infrastructure](docs/08-infrastructure.md) · [Networking](docs/09-networking.md) · [Security](docs/10-security.md) · [CI/CD](docs/11-cicd.md) |
| Data | [Seed data](docs/12-seed-data.md) · [Vector search](docs/13-vector-search.md) · [Datastore options](docs/15-datastore-options.md) |
| Operations | [Local development](docs/14-local-dev.md) · [Cost model](docs/16-cost-model.md) |
