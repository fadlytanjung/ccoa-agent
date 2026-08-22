# 01 — Requirements traceability

> **Status:** Approved
> **Source:** Product requirements — AI Contact Center Operations Assistant

Every requirement in the requirements is assigned a stable `REQ-*` ID here, exactly once.
Specifications reference these IDs; nothing else defines them. The right-hand columns
say where each requirement is designed and how it will be shown to be satisfied.

Requirements marked **Derived** are not literal text from the requirements but are necessary
consequences of it — they are flagged so the distinction stays visible.

---

## A. Application

| ID | Requirement | Spec | Verified by |
|---|---|---|---|
| REQ-001 | A web-based interface allowing support agents to interact with the assistant | [07](07-frontend.md) | Manual demo; Vitest component tests |
| REQ-002 | A backend responsible for LangGraph orchestration | [05](05-langgraph-orchestration.md), [06](06-backend-api.md) | Graph unit tests |
| REQ-003 | Backend executes business workflows | [05](05-langgraph-orchestration.md) | Per-intent integration tests |
| REQ-004 | Backend performs data access | [04](04-data-model.md), [06](06-backend-api.md) | Repository tests against seeded DB |
| REQ-005 | Backend handles integrations | [06](06-backend-api.md) §Tool surface | Gemini binding test (opt-in) |
| REQ-006 | **Both services must be deployed independently** | [08](08-infrastructure.md) | Two ECS services, two task definitions, two ECR repos, two pipeline jobs |

## B. LangGraph orchestration

| ID | Requirement | Spec | Verified by |
|---|---|---|---|
| REQ-010 | LangGraph is the **primary** orchestration engine | [05](05-langgraph-orchestration.md) | No business branching outside the graph |
| REQ-011 | Handle multiple user intents and route workflows appropriately | [05](05-langgraph-orchestration.md) §Router | Intent-classification test matrix |
| REQ-012 | Demonstrate **state management** | [05](05-langgraph-orchestration.md) §State | Typed `AgentState`; reducer tests |
| REQ-013 | Demonstrate **conditional routing** | [05](05-langgraph-orchestration.md) §Routing | Edge-selection tests per intent |
| REQ-014 | Demonstrate **multi-step workflows** | [05](05-langgraph-orchestration.md) §Case investigation | Trace assertion over ≥3 sequential tool calls |
| REQ-015 | Demonstrate **human-in-the-loop interactions** | [05](05-langgraph-orchestration.md) §HITL | `interrupt()` → resume test, incl. rejection path |
| REQ-016 | Demonstrate **error handling** | [05](05-langgraph-orchestration.md) §Failure modes | Fault-injection tests (timeout, 429, not-found, invalid tool args) |
| REQ-017 | Demonstrate **workflow orchestration** | [05](05-langgraph-orchestration.md) | End-to-end scenario tests |

## C. Supported scenarios

These are the reference example prompts. Seed data is built so each works **verbatim**.

| ID | Scenario | Prompt from the requirements | Spec |
|---|---|---|---|
| REQ-020 | Customer lookup | *"Show me the details for customer John Tan."* | [05](05-langgraph-orchestration.md) |
| REQ-021 | Conversation review | *"Summarize previous interactions for customer John Tan."* | [05](05-langgraph-orchestration.md) |
| REQ-022 | Case investigation | *"Customer reports a failed claim submission. Help me investigate the issue."* | [05](05-langgraph-orchestration.md) |
| REQ-023 | Ticket creation | *"Create a support ticket for this issue."* | [05](05-langgraph-orchestration.md) |

## D. Data layer

| ID | Requirement | Spec | Verified by |
|---|---|---|---|
| REQ-030 | Demonstrate **customer records** | [04](04-data-model.md), [12](12-seed-data.md) | Seed produces ≥100 customers |
| REQ-031 | Demonstrate **previous interactions** | [04](04-data-model.md), [12](12-seed-data.md) | Seed produces multi-channel interaction history |
| REQ-032 | Demonstrate **tickets** | [04](04-data-model.md), [12](12-seed-data.md) | Seed + live creation through the graph |
| REQ-033 | Demonstrate **case information** | [04](04-data-model.md), [12](12-seed-data.md) | Seed produces cases linked to claims |
| REQ-034 | Mock data is acceptable; technology choice is ours | [15](15-datastore-options.md) | ADR-002 with costed alternatives |

## E. Infrastructure

| ID | Requirement | Spec | Verified by |
|---|---|---|---|
| REQ-040 | Application **must be deployed on AWS** | [08](08-infrastructure.md) | Live demo in `ap-southeast-1` |
| REQ-041 | Infrastructure **must be provisioned using Terraform** | [08](08-infrastructure.md) | `terraform apply` from a clean account; no console steps |
| REQ-042 | Must use **Docker** | [08](08-infrastructure.md) | Two Dockerfiles; images in ECR |
| REQ-043 | Must use **ECS** | [08](08-infrastructure.md) | Two ECS Fargate services |
| REQ-044 | Must use **CI/CD** | [11](11-cicd.md) | GitHub Actions run history |
| REQ-045 | Service selection is part of the exercise | [08](08-infrastructure.md), [16](16-cost-model.md) | Each service choice justified with its cost |

## F. Networking — documentation is the deliverable

The requirements ask that these be **explained**, not merely built.

| ID | Requirement | Spec |
|---|---|---|
| REQ-050 | Explain **network topology** | [09](09-networking.md) §1 |
| REQ-051 | Explain **service communication paths** | [09](09-networking.md) §2 |
| REQ-052 | Explain **security boundaries** | [09](09-networking.md) §3 |
| REQ-053 | Explain **traffic flow** | [09](09-networking.md) §4 |
| REQ-054 | Explain **ingress and egress controls** | [09](09-networking.md) §5 |
| REQ-055 | Explain **design tradeoffs** | [09](09-networking.md) §6 |
| REQ-056 | Design is appropriate for **sensitive customer information, internal use** | [09](09-networking.md), [10](10-security.md) |

## G. Security — documented and justified

| ID | Requirement | Spec |
|---|---|---|
| REQ-060 | **Authentication** | [10](10-security.md) §2 |
| REQ-061 | **Authorization** | [10](10-security.md) §3 |
| REQ-062 | **Secrets management** | [10](10-security.md) §4 |
| REQ-063 | **Service-to-service communication** | [10](10-security.md) §5 |
| REQ-064 | **Access controls** | [10](10-security.md) §6 |
| REQ-065 | **Auditability** | [10](10-security.md) §7 |

## H. CI/CD

| ID | Requirement | Spec | Verified by |
|---|---|---|---|
| REQ-070 | Pipeline demonstrates **validation** | [11](11-cicd.md) | `ruff`, `mypy`, `tsc`, `eslint`, `terraform validate`, `tflint` |
| REQ-071 | Pipeline demonstrates **testing** | [11](11-cicd.md) | `pytest` + `vitest`, coverage gate |
| REQ-072 | Pipeline demonstrates **build** | [11](11-cicd.md) | Docker buildx → ECR, SHA-tagged, scanned |
| REQ-073 | Pipeline demonstrates **deployment** | [11](11-cicd.md) | ECS deploy, wait-for-stable, smoke test, rollback |

## I. Deliverables

| ID | Requirement | Status |
|---|---|---|
| REQ-080 | `frontend/` | Created |
| REQ-081 | `backend/` | Created |
| REQ-082 | `terraform/` | Created |
| REQ-083 | `docs/` | Created |
| REQ-084 | `README.md` | Created |

## J. Derived requirements

Not stated in the requirements, but required for the stated requirements to hold.

| ID | Requirement | Why it is necessary | Spec |
|---|---|---|---|
| REQ-090 | The agent's factual claims are grounded in tool results and cited | REQ-020–023 are worthless if the assistant fabricates claim history | [00](00-constitution.md) §6, [05](05-langgraph-orchestration.md) |
| REQ-091 | Conversation state survives task restart | REQ-015 human-in-the-loop is meaningless if a pending approval is lost on redeploy | [05](05-langgraph-orchestration.md), [15](15-datastore-options.md) |
| REQ-092 | The same graph runs under Studio, FastAPI, and tests without modification | Required to satisfy REQ-016 and REQ-071 without a parallel test-only graph | [14](14-local-dev.md) |
| REQ-093 | Infrastructure can be destroyed and recreated from scratch | REQ-041 is only proven if `apply` works on an empty account | [08](08-infrastructure.md) |
| REQ-094 | Known CVEs in pinned dependencies are mitigated | Sensitive customer data (REQ-056) plus a checkpointer with a published RCE chain | [02](02-research.md), [10](10-security.md) |
| REQ-095 | Orchestration uses an orchestrator delegating to specialist agents | REQ-014 and REQ-017 are better served by context-isolated specialists than by one flat graph; also scopes tool capability per agent | [05](05-langgraph-orchestration.md), [17](17-agent-skills.md) |
| REQ-096 | No prompt, routing policy, or output format is hardcoded in application code | Behaviour must be reviewable, independently versioned, and changeable without a code edit | [17](17-agent-skills.md) |
| REQ-097 | Human involvement is conversational, not a single approval gate | REQ-015 is satisfied trivially by one modal, but that makes the interface a form with a chat skin | [05](05-langgraph-orchestration.md) §3.7 |

## K. Explicitly out of scope

Recorded so that absence reads as a decision rather than an omission.

| Item | Rationale |
|---|---|
| Multi-tenancy | Not required; single contact-centre tenant assumed |
| Real telephony / CTI integration | "You may use mock data" (p.3) |
| Horizontal scaling of the backend | Precluded by the single-writer SQLite choice; the migration path is costed in [15](15-datastore-options.md) |
| Production DR, backup, multi-region | Infrastructure is ephemeral by design — [ADR-004](adr/ADR-004-ephemeral-infrastructure.md) |
| Fine-tuning or model training | Not in the requirements |
| WAF, Shield Advanced, GuardDuty | Costed and recommended in [09](09-networking.md) §6 but not deployed in the demo footprint |

---

## Coverage summary

| Group | Count | Covered by a spec |
|---|---|---|
| A. Application | 6 | 6 |
| B. LangGraph | 8 | 8 |
| C. Scenarios | 4 | 4 |
| D. Data layer | 5 | 5 |
| E. Infrastructure | 6 | 6 |
| F. Networking | 7 | 7 |
| G. Security | 6 | 6 |
| H. CI/CD | 4 | 4 |
| I. Deliverables | 5 | 5 |
| J. Derived | 8 | 8 |
| **Total** | **59** | **59** |

Coverage here means *a specification exists that addresses the requirement*. It does
not yet mean *implemented* — implementation status is tracked per spec and verified
with `/verify`.
