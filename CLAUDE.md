# CCOA — AI Contact Center Operations Assistant

An AI operations assistant that helps customer-service
agents look up customers, review past interactions, investigate cases, and create
tickets — through a conversational interface.

**Domain:** insurance customer service (the reference scenario is a *failed claim
submission*, so seed data and tools are modelled on claims).

## Working agreement

This repo is built **spec-driven**. Specs in `docs/` are the source of truth; code
implements them. Before writing code for a feature, read its spec. If the code needs
to diverge from the spec, **update the spec in the same change** — never let them drift.

Read `docs/00-constitution.md` first. It is short and binding.

Then read **`docs/20-implementation-status.md`** — it is the checkpoint for what is
actually built versus only specified. Every other document reads the same whether or not
code exists behind it; that one says which. **Any change that adds, removes, or completes
a component updates it in the same change** (`/checkpoint`, or
`python3 tools/check_implementation_status.py --update-counts`).

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | FastAPI + LangGraph orchestration service (Python 3.12) |
| `frontend/` | React 19 + Vite + TypeScript SPA, served by nginx |
| `terraform/` | AWS infrastructure (ap-southeast-1) |
| `docs/` | Specifications — numbered, read `docs/README.md` for the reading order |
| `backend/app/agents/skills/` | Agent behaviour — one directory per agent, `SKILL.md` + references + templates |
| `docs/adr/` | Architecture Decision Records |
| `backend/evals/` | Agent evaluations — DeepEval, real model, `dataset.yaml` (`docs/19`) |
| `tools/` | Repo-wide CI checks that are not tests |
| `.claude/commands/` | Spec-driven workflow commands (`/spec`, `/plan`, `/tasks`, `/verify`, `/checkpoint`) |
| `scripts/` | Runnable entry points — preflight, dev, verify, AWS bootstrap, Cognito |
| `.github/workflows/` | CI. **No `deploy.yml`** — there is nothing to deploy until `terraform/` exists |

## Stack (pinned — do not silently upgrade)

| Component | Choice | Version |
|---|---|---|
| Orchestration | LangGraph | `1.2.11` |
| Checkpointer | `langgraph-checkpoint-sqlite` | `3.1.1` (≥3.0.1 — CVE fix, see below) |
| LLM | Google Gemini API | `gemini-3.5-flash` (stable) |
| LLM binding | `langchain-google-genai` | `4.3.4` |
| Embeddings | Gemini | `gemini-embedding-001` |
| Backend | FastAPI | `0.141.1` |
| Vector store | `sqlite-vec` | `0.1.9` |
| Frontend | React + Vite + TypeScript | React 19 |
| IaC | Terraform | ≥1.11 (native S3 state locking; no DynamoDB) |
| Compute | ECS Fargate, ARM64, `min 0 / max 1` backend | — |
| Edge / TLS | CloudFront + VPC origin → **internal** ALB | default `*.cloudfront.net` cert |
| Persistence | SQLite in-container + **Litestream → S3** | — |
| Migrations | SQLAlchemy models + Alembic (plain SQL is an acceptable fallback) | — |
| Tracing | LangSmith (`LANGSMITH_TRACING`, opt-in) | — |
| Region | `ap-southeast-1` (Singapore) | — |
| Environments | `dev` (ephemeral), `prod` (scale-to-zero) | — |

**Not Bedrock.** The LLM is the Gemini Developer API over the public internet.
Bedrock is documented as an alternative in `docs/adr/ADR-001-llm-provider.md` only.

## Non-negotiable constraints

1. **Never commit secrets.** The Gemini API key lives in AWS Secrets Manager and, for
   local dev, in `backend/.env` (git-ignored). No key in Terraform state, image layers,
   task definitions, logs, or docs.
2. **`LANGGRAPH_STRICT_MSGPACK=true` must be set** wherever a checkpointer runs.
   CVE-2026-28277 (msgpack deserialization → RCE) and CVE-2025-67644 (SQLi in the
   SQLite checkpointer) make this and the version pins load-bearing, not cosmetic.
3. **The graph must not hard-wire a checkpointer.** `build_graph(checkpointer=None)`
   is the only construction entry point — the LangGraph Agent Server supplies its own
   persistence, FastAPI supplies `AsyncSqliteSaver`, tests supply `MemorySaver`.
   See `docs/14-local-dev.md`.
4. **The database lives inside the container.** SQLite is baked into the image and
   seeded at build time — **no EFS, no shared filesystem**. `journal_mode = WAL` is
   used (valid on a local filesystem). Writes do **not** survive a task stop, and with
   `journal_mode = WAL`. Durability comes from **Litestream replicating both databases
   to S3**, restored on boot — so data survives deploys and crashes. The corpus is ~100
   seeded records. **Neon/Supabase/RDS are documented alternatives only — do not
   implement a second datastore.** `max_capacity = 1` is load-bearing: Litestream
   corrupts with >1 writer. `stopTimeout = 60` is too — it is what lets Litestream
   finish its final sync on scale-in. See `docs/adr/ADR-007-durable-sqlite-via-s3.md`.
5. **Environments are `dev` and `prod`.** Never `demo`, never `staging`. **Only `dev`
   is ever applied** — `prod` is configuration plus a gated pipeline job that is never
   approved. `dev` is ephemeral: `terraform destroy` when idle.
6. **HTTPS only, via CloudFront.** Viewers reach a `*.cloudfront.net` URL using
   CloudFront's default certificate. The ALB is `internal` and reachable only as a
   CloudFront VPC origin. There is no custom domain and no ACM certificate.
7. **LangSmith tracing is opt-in per environment.** `LANGSMITH_TRACING` defaults to
   `false`; when enabled it sends prompts, tool results, and graph state to a
   third-party service. Acceptable only because all data is synthetic.
8. **Every mutating tool is authorized and audited.** Ticket creation and case
   escalation check Cognito group claims and write an audit row. See `docs/10-security.md`.
9. **No prompt text in Python.** System prompts, routing policy, tool guidance, and
   output formats live in `backend/app/agents/skills/*/SKILL.md` (YAML frontmatter +
   Markdown body) with Jinja2 templates for structured output. A CI check fails the
   build on string literals over 200 characters under `app/graph/` and `app/agents/`.
   See `docs/17-agent-skills.md`.
10. **Human-in-the-loop is conversational, not a single gate.** Four ask kinds —
   `clarify`, `confirm`, `approve`, `steer` — share one `interrupt()` node. Only
   `approve` is enforced in code; the rest are declared per skill so the interaction
   stays natural. Resume payloads are free-form, never a bare boolean.
   See `docs/05-langgraph-orchestration.md` §3.7.
11. **This repository is public — nothing identifies the AWS account.** No account
   numbers, resource ids (`vpc-`, `subnet-`, …), access keys, console sign-in URLs,
   personal names, or local paths. Use `<AWS_ACCOUNT_ID>`, `<ORG>/<REPO>`,
   `vpc-EXAMPLE`. Enforced by `tools/check_no_account_identifiers.py`, not by
   discipline. See `docs/18-aws-access-and-manual-steps.md` §6.
12. **Never use the account owner (root) for work.** Root is for five listed tasks only;
   everything else uses `ccoa-deploy` (GitHub OIDC, no keys) or `ccoa-operator`
   (human, read-mostly). Manual AWS actions are recorded in `docs/ops-log.md`.
   See `docs/18-aws-access-and-manual-steps.md`.

## Commands

Prefer the scripts — they are what CI runs, and they check their own prerequisites:

```bash
./scripts/preflight.sh            # is this machine ready? (--deploy for AWS tools too)
./scripts/dev.sh                  # run everything locally (--cognito, --reset)
./scripts/verify.sh               # every check CI runs (--fast, --containers)
./scripts/aws-cognito.sh          # create the user pool, write backend/.env (docs/18 §7)
./scripts/aws-bootstrap.sh --repo <ORG>/<REPO>   # state bucket, OIDC, deploy role (docs/18 §4)
```

The underlying commands, when a script is too blunt an instrument:

```bash
# Backend
cd backend && uv sync                       # install
uv run uvicorn app.main:app --reload        # serve API on :8000
uv run langgraph dev                        # LangGraph Studio on :2024 (in-memory)
uv run pytest                               # tests — stubbed model, offline, ~4 s
uv run ruff check . && uv run mypy app      # lint + types
uv run python -m app.seed --reset           # regenerate seed data
uv run python tools/check_no_inline_prompts.py

# Agent evaluations — real model, opt-in (docs/19). Runs on the shipped model. The
# trajectory layer must run in its own session or it breaks the others.
uv sync --group evals
uv run pytest evals -m "eval and not judged"   # deterministic, no judge calls
uv run pytest evals                            # 29 checks — rubric, multi-turn, safety, end-to-end
CCOA_EVAL_TRAJECTORY=1 uv run deepeval test run evals/test_trajectory.py   # 3 checks

# Container
docker build -t ccoa-backend:dev .
./docker/verify-replication.sh              # ADR-007 round trip against MinIO

# Frontend
cd frontend && npm ci
npm run dev                                 # Vite dev server on :5173
npm run build && npm run typecheck && npm run lint

# Infra
cd terraform && terraform fmt -recursive && terraform validate
terraform plan -var-file=envs/dev.tfvars

# Repo-wide — this repository is public (docs/18 §6)
python3 tools/check_no_account_identifiers.py
```

## Conventions

- **Python:** `ruff` + `mypy --strict` on `app/`. Pydantic v2 models for all API and
  tool boundaries. No bare `except`. Tools return typed results, never raise into the graph.
- **TypeScript:** strict mode. No `any`. API types generated from the OpenAPI schema.
- **Terraform:** one file per concern (`network.tf`, `ecs.tf`, …), all values via
  variables, no hardcoded ARNs or account IDs. Remote state in S3 with native
  locking (`use_lockfile`) — **no DynamoDB anywhere in this project** (`docs/08` §3.4).
- **Commits:** conventional commits (`feat:`, `fix:`, `docs:`, `infra:`).
- **Tests:** graph behaviour is tested with `MemorySaver` and a stubbed LLM — no
  network in unit tests. Integration tests hit a live Gemini key and are opt-in.

## Current state

**Specs approved 2026-08-22. Backend implemented; frontend and Terraform not started.**

| Deliverable | State |
|---|---|
| `docs/` | All 20 specs + 7 ADRs **Approved**. Code and spec change together — see the working agreement above |
| `backend/` | **Complete and verified.** 195 tests, 88% coverage, `ruff` and `mypy --strict` clean, `alembic check` clean, no inline prompts |
| Container | **Built and verified.** Image runs, `/readyz` all-green, non-root. Litestream write → replicate → destroy → restore round trip passes against MinIO (`backend/docker/verify-replication.sh`) |
| End-to-end | **Wired and verified through HTTP.** Four reference prompts, one thread, two checkpoints, a ticket written and read back — stubbed in `tests/api/test_end_to_end.py` (in the gate), live in `evals/test_end_to_end.py` |
| Evals | **11 cases, 32 checks** across five layers — deterministic, rubric, multi-turn/safety, end-to-end, trajectory (`docs/19`). **All passing** against the shipped `gemini-3.5-flash` |
| `frontend/` | Not started — [07](docs/07-frontend.md) |
| `terraform/` | Not started — [08](docs/08-infrastructure.md). Terraform is still not installed on the deploy host |

Backend verification gate, all of which must pass:

```bash
cd backend
uv run ruff check . && uv run mypy app
uv run pytest
uv run python tools/check_no_inline_prompts.py
DATABASE_URL="sqlite+pysqlite:///$(pwd)/data/app.db" uv run alembic check
```

Also run before trusting a deploy:

```bash
python3 tools/check_no_account_identifiers.py   # repo root — this repository is public
cd backend && docker build -t ccoa-backend:dev . && ./docker/verify-replication.sh
```

**Not yet verified:** nothing has been applied to AWS. Terraform is not installed on
this host, and no account has been bootstrapped — `docs/18` §4 is the runbook for that
and has not been executed.
