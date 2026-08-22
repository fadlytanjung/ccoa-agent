# 00 — Engineering constitution

> **Status:** Approved
> **Applies to:** every specification, every commit, every Terraform module in this repo.

This document is deliberately short. It exists so that later disagreements are settled
by a principle rather than by argument. Where another document contradicts this one,
this one wins — or this one gets amended, explicitly.

---

## 1. The specification is the source of truth

Code implements specs. When code and spec disagree, that is a **defect**, regardless
of whether the code works.

- Before implementing, read the spec.
- If implementation reveals the spec is wrong, **stop and fix the spec first**, then
  resume. Do not write code that silently contradicts an approved document.
- Every spec declares which `REQ-*` it satisfies. Work that satisfies no requirement
  is out of scope until a requirement is added for it.

## 2. Verified facts only

A plausible-sounding wrong number is worse than no number.

- Model IDs, package versions, AWS prices, quotas, and API signatures are **verified
  against the live account or the vendor's own documentation** before being written down.
- Anything not verified is marked `[UNVERIFIED]` inline. That marker is a to-do, not
  a disclaimer to hide behind.
- [02 — Research](02-research.md) records what was checked, how, and when.

## 3. State the tradeoff

Every meaningful choice closes a door. The spec names the door.

- In-container SQLite means each task owns its own database, so the service is capped
  at one task. That is written down in the spec, in the ADR, and in the README — not
  discovered later by someone else.
- A documented weakness is engineering judgement. An undocumented one is an oversight.
- Where a decision is expensive to reverse, it gets an ADR in `docs/adr/`.

## 4. Right-size the infrastructure

The requirements ask for a production-shaped design, not a production-scale bill.

- Build the **minimum footprint that genuinely satisfies the requirements** — Terraform,
  Docker, ECS, CI/CD, a defensible network, real auth.
- Infrastructure is **ephemeral**: `apply` before a demo, `destroy` after. Nothing may
  depend on long-lived state outside ECR.
- Where the cheap choice differs from the production choice, implement the cheap one
  and document the production one with its cost. Do not pay for realism nobody will see.

## 5. Security is a design input, not a review step

- **No secret is ever committed.** Not in Terraform state, image layers, task
  definitions, logs, test fixtures, or documentation. The Gemini API key lives in AWS
  Secrets Manager, and in a git-ignored `.env` locally.
- **No static AWS credentials.** CI authenticates through GitHub OIDC role assumption.
- **Default deny.** Security groups reference other security groups, not CIDR blocks.
  IAM policies name resources, not `"Resource": "*"`.
- **Every mutating action is authorised and audited.** Creating a ticket or escalating
  a case checks the caller's Cognito group claims and writes an audit record carrying
  the actor, the action, the target, and the trace ID.
- **Dependencies with known CVEs are pinned above the fix**, and the mitigating
  configuration is treated as load-bearing — see the LangGraph checkpointer pins in
  [02 — Research](02-research.md).

## 6. The agent is accountable for what it says

An assistant that fabricates a customer's claim history is worse than no assistant.

- Tools return **typed, validated results**. A tool never raises into the graph; it
  returns a typed error the graph can route on.
- Answers that assert facts about a customer, interaction, case, or ticket must be
  **grounded in a tool result recorded in state**, and the response cites which one.
- If the data is not there, the assistant says so. "Not found" is a correct answer.
- **Mutations require a human.** Ticket creation and escalation pause the graph for
  explicit approval; the model never commits a write on its own authority.

## 7. Portability across environments

The same graph runs in three places — LangGraph Studio, FastAPI on ECS, and the test
suite. It must not know which.

- `build_graph(checkpointer=None)` is the **only** construction entry point.
  Persistence is injected, never hard-wired.
- Configuration comes from the environment, validated once at startup by a typed
  settings model. A missing required variable fails fast and loudly at boot, not
  lazily on the first request.
- No code path branches on "am I running in AWS".

## 8. Observability is part of done

- Structured JSON logs, one `trace_id` propagated from the HTTP edge through every
  graph node and tool call.
- **Never log** message content, customer PII, or the API key. Log identifiers,
  decisions, durations, and outcomes.
- Health (`/healthz`) and readiness (`/readyz`) are distinct: readiness checks the
  database and the LLM binding; health does not.

## 9. Quality gate

A change is not done until this passes:

```bash
cd backend  && uv run ruff check . && uv run mypy app && uv run pytest
cd frontend && npm run lint && npm run typecheck && npm run build
cd terraform && terraform fmt -check -recursive && terraform validate
```

- **Never weaken a test to make it pass.**
- Unit tests do not touch the network. Graph behaviour is tested with `MemorySaver`
  and a stubbed model.
- Tests that need a live Gemini key or real AWS credentials are marked and opt-in.

## 10. Scope discipline

Deliver what the requirements asks, at the scope it asks.

- Build what is specified. Do not add abstractions, configuration surfaces, or
  "future-proofing" for requirements nobody stated.
- The nice-to-have (vector search) may not compromise the must-haves. If it slips,
  it ships disabled behind a flag, and that is fine.
- Finish the whole task, and report plainly what is incomplete and why.
