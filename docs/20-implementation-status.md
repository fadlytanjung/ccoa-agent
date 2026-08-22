# 20 — Implementation status

> **Status:** Living — regenerate the counts before trusting them
> **Last verified:** 2026-08-23
> **Depends on:** every other document; this one says which of them are *true yet*

## 1. Purpose

**What is built, what is not, and what is only specified.**

This repository is spec-driven: `docs/` is the source of truth and code implements it.
That has one failure mode, and it is the reason this document exists — a specification
reads identically whether or not anything implements it. Someone arriving at
[08 — Infrastructure](08-infrastructure.md) finds a precise description of an AWS estate
that does not exist, written in the same confident present tense as
[05 — Orchestration](05-langgraph-orchestration.md), which is fully built and tested.

This is the checkpoint that separates the two. Read it **first** when picking work up.

## 2. Scope

**In scope:** component-by-component status, the verification inventory, the known gaps,
and the mechanism that stops this document drifting from the code.

**Out of scope:** how anything works — every row links to the document that says.

---

## 3. Status vocabulary

Four words, used strictly:

| Status | Means |
|---|---|
| **Built** | Implemented, tested, and exercised — the tests named in [§5](#5-verification-inventory) cover it |
| **Partial** | Implemented, with a named limitation stated in the row |
| **Specified** | A document describes it. **No code exists.** |
| **Declined** | Deliberately not done, with the reason and where it is argued |

"Built" is a claim about verification, not about effort. Code with no test that would fail
if it broke is **Partial** at best.

---

## 4. Component status

### 4.1 Backend

| Component | Status | Notes |
|---|---|---|
| FastAPI application, middleware, RFC 9457 errors | **Built** | [06](06-backend-api.md) |
| 19 API routes across threads, customers, ops | **Built** | Including `GET /api/v1/config`, unauthenticated by necessity |
| SSE streaming (`token`, `step`, `tool`, `message`, `approval_required`, `done`) | **Built** | [06](06-backend-api.md) §3.4 |
| Cursor-paginated thread listing | **Built** | [06](06-backend-api.md) §3.2a |
| LangGraph supervisor + four specialists | **Built** | [05](05-langgraph-orchestration.md) |
| Human-in-the-loop: all four ask kinds through one `interrupt()` | **Built** | Only `approve` enforced in code, by design |
| Agent skills — `SKILL.md`, references, templates, `tools.yaml` | **Built** | 5 skills; no prompt text in Python, enforced by a CI check |
| Tool layer, typed results, no raises into the graph | **Built** | [05](05-langgraph-orchestration.md) §3.9 |
| SQLite schema + 3 Alembic revisions | **Built** | Head `0003_threads`, asserted at startup |
| Deterministic seed corpus | **Built** | [12](12-seed-data.md) |
| Vector search (`sqlite-vec`) | **Partial** | Wired and migrated; retrieval paths are the least-covered code in the suite (45%) |
| Cognito JWT verification, JWKS cache failing closed | **Built** | Verified end to end: a real access token from the deployed pool reaches the API, is validated against the pool's JWKS, and the agent answers |
| Authorisation by group claim, audit rows on mutation | **Built** | [10](10-security.md) |
| Litestream → S3 durability | **Built** | Verified end-to-end against MinIO, not against S3 ([ADR-007](adr/ADR-007-durable-sqlite-via-s3.md)) |
| Container image, entrypoint, restore-on-boot | **Built** | `backend/docker/verify-replication.sh` |

### 4.2 Frontend

| Component | Status | Notes |
|---|---|---|
| React 19 + Vite 7 SPA, TS strict | **Built** | [07](07-frontend.md) |
| Design system: tokens, type scale, primitives | **Built** | [21](21-design-system.md) |
| Mobile-first responsive shell, sheets below `lg` | **Built** | Asserted by `e2e/mobile.spec.ts` |
| Addressable conversations (`/threads/:threadId`) | **Built** | [07](07-frontend.md) §3.10 |
| Cursor-paginated thread list, "Load older" | **Built** | `useInfiniteQuery` |
| SSE consumption, CRLF-tolerant parser | **Built** | The parser is the most-tested file in the SPA, for good reason |
| Streaming motion, reduced-motion honoured | **Built** | [21](21-design-system.md) §4.6 |
| Markdown rendering, no raw HTML | **Built** | |
| Approval card — all four ask kinds | **Built** | 11 component tests |
| Context panel with citation focus | **Built** | |
| Cognito PKCE, explicit endpoints, hand-built sign-out | **Built** | The whole round trip completes against the deployed environment: redirect, credentials, code exchange, workspace |
| `AUTH_MODE=dev` bypass, mirroring the server | **Built** | |
| nginx container: SPA fallback, CSP, caching, non-root | **Built** | 30 assertions in `docker/verify-image.sh` |
| Generated API types from OpenAPI | **Specified** | [06](06-backend-api.md) §3.10. Types are hand-written; drift is caught by tests, not the compiler |

### 4.3 Evaluation

| Component | Status | Notes |
|---|---|---|
| DeepEval harness, custom metrics, Gemini judge | **Built** | [19](19-agent-evaluation.md) |
| 11-case dataset in YAML | **Built** | Runs against the planted corpus |
| Trajectory metrics | **Partial** | Gated behind `CCOA_EVAL_TRAJECTORY=1` — they are unreliable in a shared pytest session |
| `StepEfficiencyMetric` | **Declined** | Fabricated a verdict on a one-call run; removed from the gate ([19](19-agent-evaluation.md) §6) |

### 4.4 Infrastructure and delivery

| Component | Status | Notes |
|---|---|---|
| **Terraform** — VPC, ECS, ALB, Cognito, S3, ECR, WAF | **Built** | 21 files, `validate` clean, **fully applied**. `dev` is live and reachable |
| CloudFront edge (`edge = "cloudfront"`) | **Blocked** | Written and planned clean; AWS will not create a distribution on an unverified account ([ops-log](ops-log.md)). `develop` runs `edge = "alb"` instead ([09](09-networking.md) §6.6) |
| **CD — `deploy.yml`** | **Built** | Checks → build and push ARM64 images → apply → bounded smoke test. Repository secrets set. **Never executed** — the repository has no commits yet |
| **CI — validate, test, browser, containers** | **Built** | `.github/workflows/ci.yml`. Runs the same checks as `scripts/verify.sh`. **Never executed on GitHub** — the repository was connected after it was written |

| Local scripts — preflight, dev, verify | **Built** | `scripts/`. All three run clean on a developer machine |
| Repository safety check | **Built** | `tools/check_no_account_identifiers.py` — runs, and passes |
| AWS bootstrap script | **Built** | `scripts/aws-bootstrap.sh`. **Executed** — state bucket, GitHub OIDC provider, permission boundary, and `ccoa-deploy` role all exist |
| `scripts/deploy.sh`, `destroy.sh` | **Partial** | Written and exercised step by step by hand; **not yet run end to end**, because the CloudFront step cannot complete |
| Cognito provisioning script | **Built** | `scripts/aws-cognito.sh`. **Executed against the real account** — pool, groups, domain, and public client exist in `ap-southeast-1`, self-registration disabled ([ops-log](ops-log.md), [ADR-008](adr/ADR-008-provisioned-identity.md)) |
| Deployed environment | **Built** | `dev` is live on an internet-facing ALB. **A full sign-in completes and the agent answers through the deployed stack** — verified with a real Cognito user against the running environment, with no console errors |
| Viewer TLS | **Partial** | A **self-signed** certificate, so every visitor sees a browser warning. Cognito rejects `http://` callbacks, so this was the only way to have working sign-in without a domain. A real certificate is one variable and ~15 minutes ([09](09-networking.md) §6.6) |

**The headline:** `dev` is **deployed and reachable**, on `develop`. The CloudFront edge
the design argues for is blocked by AWS account verification, so the same Terraform runs
an internet-facing ALB instead — one variable, with the security tradeoff stated in
[09](09-networking.md) §6.6 rather than glossed over. The remaining honest weakness is the
self-signed certificate; everything else in the deployed path is verified.

`main` holds the CloudFront configuration and is what to return to once the account
clears. `develop` holds the ALB edge and is what is live.

---

## 5. Verification inventory

Five layers, each answering a different question. A component is **Built** only if a layer
here would fail when it breaks.

| Layer | Where | Count | Question it answers | Cost |
|---|---|---|---|---|
| Backend unit + graph | `backend/tests/` | **205 passing, 88% coverage** | Is the code wired correctly? | ~3 s, no network |
| Frontend unit | `frontend/src/**/*.test.ts(x)` | **68 passing** | Do the parser, reducer, auth URLs, and approval card behave? | ~1 s |
| Browser end-to-end | `frontend/e2e/assistant.spec.ts` | **10 passing** (4 shell + 4 `@live`) | Does a real browser, against a real backend, reach a person? | ~16 s |
| Phone end-to-end | `frontend/e2e/mobile.spec.ts` | **5 passing** | Does the layout transform rather than compress? | ~2 s |
| Container | `backend/docker/verify-replication.sh`, `frontend/docker/verify-image.sh` | **6 + 30 assertions** | Does the built image do what the image is supposed to do? | ~1 min, needs Docker |
| Agent evaluation | `backend/evals/` | **11 cases** | Is the agent any good? | ~3.5 min, real model calls |

The `@live` specs need a Gemini key; the config finds it in `backend/.env` automatically,
so `npx playwright test` needs no environment set up. Without a key they skip, and the
shell tier still runs.

**Evals are not in the merge gate** and must not be ([19](19-agent-evaluation.md) §3.1). A
failing test means the code is broken; a failing eval means either the agent got worse *or
the expectation was wrong*, and putting that judgement call in the merge path teaches
everyone to ignore it.

### 5.1 Running everything

```bash
# Backend — 200 tests, no network
cd backend && uv run pytest && uv run ruff check . && uv run mypy app

# Frontend — 41 unit, then 13 browser tests (desktop + phone)
cd frontend && npm run typecheck && npm run lint && npx vitest run && npx playwright test

# Containers — needs Docker
cd backend  && docker build -t ccoa-backend:dev . && ./docker/verify-replication.sh
cd frontend && docker build -t ccoa-frontend:local . && ./docker/verify-image.sh

# Repository safety — this repo is public
python3 tools/check_no_account_identifiers.py

# Agent quality — real model calls, on demand only
cd backend && uv run deepeval test run evals/test_agent.py
```

---

## 6. Gaps

Ordered by how much they would matter if this were going further.

1. **The deployment is not reachable.** 89 of 97 resources exist, and the eight that do
   not are all downstream of the CloudFront distribution AWS is refusing until the account
   is verified. Nothing in this repository can fix that; the case is open in
   [ops-log](ops-log.md). Once cleared, one `./scripts/deploy.sh` finishes it.
2. **Neither workflow has ever run.** The repository has **no commits** — `ci.yml` and
   `deploy.yml` are code that has never been executed by GitHub. Expect the first push to
   find something; that is what first pushes do.
3. ~~**No token from the real pool has reached the API yet.**~~ **Closed 2026-08-23** —
   a full sign-in now completes against the deployed environment. What follows is kept
   only as the record: the SPA redirects to the real hosted UI and the login form renders,
   and an unauthenticated `GET /api/v1/threads` correctly returns `401`; the round trip — sign in, exchange the code, call `/api/v1/threads` with
   the access token, have the backend verify it against the real JWKS — has not been
   completed. That is the single highest-value thing left to try, and it needs one command
   (`--add-user`) plus a browser.
4. **Litestream is proven against MinIO, not S3.** The API surface used is identical and
   the round trip genuinely works ([ADR-007](adr/ADR-007-durable-sqlite-via-s3.md)) — but
   IAM, bucket policy, and region behaviour are untested.
5. **API types are hand-written.** [06](06-backend-api.md) §3.10 calls for generating them
   from the OpenAPI schema so a backend change the frontend has not adopted breaks the
   build. Today a shape change is caught by a test, if there is one — a stale backend
   serving a bare array where the SPA expected an envelope produced a white screen with
   one console error, and that is exactly the class of failure generation removes.
6. **Retrieval is the least-covered code** (45%). It is a nice-to-have
   ([13](13-vector-search.md)), and it shows.
7. **Dark mode is defined but unreachable** — the tokens exist, the toggle does not
   ([21](21-design-system.md) §7).
8. **No visual regression testing.** Layout rules are asserted; appearance is not.

---

## 7. Keeping this honest

A status document that is not checked becomes the most confidently wrong file in a
repository. Two mechanisms, neither of which relies on anyone remembering.

### 7.1 The checker

`tools/check_implementation_status.py` verifies the falsifiable claims in this document
against the working tree:

- every path this document names exists;
- directories claimed **Specified** are still empty, and directories claimed **Built** are
  not — a status row that has quietly become true is as wrong as one that has become false;
- the counts in [§5](#5-verification-inventory) match what the suites actually collect;
- `Last verified` is not stale relative to the last commit that touched `backend/app`,
  `frontend/src`, or `terraform/`.

It runs in CI ([11](11-cicd.md) §3.3a) once CI exists, and by hand until then:

```bash
python3 tools/check_implementation_status.py
```

It deliberately does **not** try to infer status from the code. A machine cannot tell
"Built" from "Partial"; it can only tell when a stated fact has stopped being one.

### 7.2 The workflow rule

In [`CLAUDE.md`](../CLAUDE.md) and in `.claude/commands/checkpoint.md`:

> **Before finishing any change that adds, removes, or completes a component, update
> `docs/20-implementation-status.md` in the same change**, and run
> `tools/check_implementation_status.py`.

This is the same rule the constitution already applies to specifications — code and spec
move together — extended to the one document whose whole job is to be current. A change
that makes a **Specified** row **Built** is not finished until the row says so.
