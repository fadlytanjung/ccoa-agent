# 06 — Backend API

> **Status:** Approved — 2026-08-22
> **Satisfies:** REQ-002, REQ-004, REQ-005, REQ-015
> **Depends on:** [03 — Architecture](03-architecture.md), [05 — LangGraph orchestration](05-langgraph-orchestration.md)

## 1. Purpose

The HTTP contract between the SPA and the orchestration service: routes, schemas,
streaming protocol, authentication, and error format.

## 2. Scope

**In scope:** REST + SSE contract, auth dependency, SSE event taxonomy, error format,
health probes, OpenAPI generation, configuration.

**Out of scope:** graph internals ([05](05-langgraph-orchestration.md)), SQL
([04](04-data-model.md)), UI ([07](07-frontend.md)), IAM and network policy
([09](09-networking.md), [10](10-security.md)).

---

## 3. Design

### 3.1 Conventions

- Base path `/api/v1`. Version in the path, because ALB path routing is already the
  dispatch mechanism.
- JSON in, JSON out; `application/json`, UTF-8. Streaming endpoints emit
  `text/event-stream`.
- Every request carries `Authorization: Bearer <Cognito access token>` except
  `/healthz` and `/readyz`.
- Every response carries `X-Trace-Id`, echoing an inbound `X-Request-Id` when present.
- Field names are `snake_case`, matching the domain models.

### 3.2 Routes

| Method | Path | Purpose | Auth |
|---|---|---|---|
| `GET` | `/healthz` | Liveness — process is up | none |
| `GET` | `/readyz` | Readiness — DB reachable, model bound, migrations applied | none |
| `POST` | `/api/v1/threads` | Create a conversation thread | agent |
| `GET` | `/api/v1/threads` | List the caller's threads — **paginated** ([§3.2a](#32a-listing-conversations)) | agent |
| `GET` | `/api/v1/threads/{thread_id}` | Thread metadata and message history | owner |
| `DELETE` | `/api/v1/threads/{thread_id}` | Delete a thread and its checkpoints | owner |
| `POST` | `/api/v1/threads/{thread_id}/messages` | **Send a message — SSE stream** | owner |
| `POST` | `/api/v1/threads/{thread_id}/resume` | Approve or reject a pending action | owner + group |
| `GET` | `/api/v1/threads/{thread_id}/state` | Current graph state, incl. pending interrupt | owner |
| `GET` | `/api/v1/customers/{customer_id}` | Customer detail for the context sidebar | agent |
| `GET` | `/api/v1/customers/{customer_id}/interactions` | Paged interaction list | agent |
| `GET` | `/api/v1/customers/{customer_id}/cases` | Case list | agent |
| `GET` | `/api/v1/tickets/{ticket_id}` | Ticket detail | agent |
| `GET` | `/api/v1/meta` | Feature flags, model ID, build SHA | agent |
| `GET` | `/api/v1/config` | Auth mode and Cognito pool, **before** sign-in | none |

The `/customers/*` routes exist so the sidebar can render context without going
through the graph. They are **read-only by construction** — there is no non-graph
write path in the API, which keeps "every mutation is approved and audited"
([00](00-constitution.md) §6) a structural property rather than a convention.

### 3.2a Listing conversations

`GET /api/v1/threads?limit=30&cursor=<opaque>` returns an envelope, not a bare array:

```json
{
  "items": [ { "thread_id": "th_…", "title": "…", "updated_at": "…", "…": "…" } ],
  "next_cursor": "MjAyNi0wOC0yMlQxMTozODoxNFp8dGhfM2E0…"
}
```

Follow `next_cursor` until it is `null`. **A short page is not the end** — under a keyset
scheme a full page can be the last one and a short page can have a successor, so the
cursor is the only termination signal.

**Keyset, not offset**, and the reason is specific to this list. It is ordered by
`updated_at`, and sending a message rewrites that column — so between two requests the
thread the agent is working in jumps to the front and pushes every later row down one.
With `OFFSET 30` that shift is invisible and lossy: page two starts counting from a
position that no longer means what it did, and whichever row slid across the boundary is
never returned to anyone. Anchoring to the last row the client actually received cannot
skip, because the anchor moves with the data.

The sort key is `(updated_at, thread_id)`. `updated_at` alone is not unique — seeded rows
share a timestamp to the microsecond — and a page boundary landing inside a group of equal
timestamps would drop the rest of that group.

The cursor is **opaque** (base64 of the anchor pair). That is not a security measure; it
encodes only data the caller already has. It exists so clients do not parse it, because a
parsed cursor makes the sort key permanent. A cursor that cannot be decoded returns the
**first page** rather than a `400`: cursors travel in URLs, where they get truncated and
hand-edited, and the useful answer to an uninterpretable position is the beginning.

`limit` is bounded to `1..100` by the route and rejected with `422` outside it — unlike the
agent-facing tool limits, which are clamped rather than rejected ([04](04-data-model.md)
§3.6), because a human-facing API benefits from being told it asked for something silly.

### 3.3 Authentication dependency

```python
async def current_actor(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> Actor:
    claims = await verify_cognito_jwt(creds.credentials)   # RS256, JWKS cached 1h
    return Actor(
        sub=claims["sub"],
        email=claims.get("email", ""),
        groups=claims.get("cognito:groups", []),
    )
```

Verified on every request: signature against the cached JWKS, `iss` matches the user
pool, `token_use == "access"`, `client_id` matches, and `exp`/`nbf` are current. All
failures return `401` with no detail about which check failed.

Thread ownership is enforced separately: a thread records its creator's `sub`, and a
mismatch is `404`, not `403` — a wrong-owner `403` would confirm the thread exists.

### 3.4 Sending a message — SSE

```http
POST /api/v1/threads/th_01J.../messages
Authorization: Bearer <token>
Content-Type: application/json

{ "content": "Show me the details for customer John Tan." }
```

Response is `text/event-stream`. Event types:

| Event | When | Payload |
|---|---|---|
| `trace` | First, always | `{trace_id, thread_id}` |
| `step` | Node entered | `{node, label}` — drives the progress indicator |
| `tool` | Tool invoked and returned | `{name, args_summary, ok, ref}` |
| `token` | Model tokens for the final answer | `{text}` |
| `message` | Answer complete | `{message_id, content, citations[]}` |
| `approval_required` | `interrupt()` reached | `{action, summary, payload, evidence_refs[]}` |
| `error` | Terminal failure | `{code, message, trace_id, retryable}` |
| `done` | Always last | `{status: "complete"\|"interrupted"\|"error"}` |

```
event: step
data: {"node":"lookup","label":"Looking up customer"}

event: tool
data: {"name":"search_customer","args_summary":"John Tan","ok":true,"ref":"customer:CUST-004217"}

event: token
data: {"text":"John Tan holds two active policies"}

event: message
data: {"message_id":"msg_01J...","content":"...","citations":["customer:CUST-004217","policy:POL-00931744"]}

event: done
data: {"status":"complete"}
```

Transport details that matter in practice:

- **Heartbeat comment (`: ping`) every 15 s.** The ALB idle timeout is raised to 120 s
  ([08](08-infrastructure.md)), but a long investigation can still out-wait a default,
  and a silent stream looks like a hang to the user.
- **`X-Accel-Buffering: no`** and `Cache-Control: no-cache` so no intermediary buffers
  the stream.
- **Client disconnect cancels the run.** FastAPI's disconnect signal cancels the graph
  task; the checkpoint written so far survives, so a refresh resumes rather than
  restarts.
- **`approval_required` is followed by `done: interrupted`, and the stream closes.**
  The connection is not held open waiting for a human ([05](05-langgraph-orchestration.md) §3.7).

### 3.5 Resuming after approval

```http
POST /api/v1/threads/th_01J.../resume
{ "approved": true, "note": "confirmed with customer" }
```

Also SSE, with the same event taxonomy. Semantics:

| Condition | Response |
|---|---|
| No pending interrupt | `409` — `no_pending_approval` |
| Actor lacks the required group | `403` + audit row `outcome='denied'` |
| Already resumed | `409` — `already_resumed` (idempotent, not a double-write) |
| `approved: false` | `200`, graph acknowledges, audit row `outcome='denied'` |

### 3.6 Error format — RFC 9457

```json
{
  "type": "https://ccoa.internal/errors/customer-not-found",
  "title": "Customer not found",
  "status": 404,
  "detail": "No customer matches identifier CUST-999999.",
  "instance": "/api/v1/customers/CUST-999999",
  "trace_id": "01J8XQ2R7B4K..."
}
```

| Status | Used for |
|---|---|
| `400` | Malformed JSON |
| `401` | Missing, expired, or invalid token |
| `403` | Authenticated but lacking the required group |
| `404` | Resource absent, or present but not owned by the caller |
| `409` | State conflict — no pending approval, already resumed |
| `422` | Schema or pattern validation failure |
| `429` | Upstream model rate limit, with `Retry-After` |
| `503` | Model or database unavailable |

`detail` never contains PII, a stack trace, or an internal path. The `trace_id` is the
handle for correlating with logs.

### 3.7 Health and readiness

| Probe | Checks | Used by |
|---|---|---|
| `/healthz` | Process responds | ECS container health check |
| `/readyz` | `PRAGMA quick_check` on `app.db`; checkpointer table present; `alembic_version` at head; LLM handle constructed | ALB target group |

They are deliberately different. A backend whose database failed its integrity check,
or whose migrations did not reach head, is *alive* but must stop receiving traffic —
conflating the two would leave the ALB routing into a broken task.

### 3.8 Configuration

```python
class Settings(BaseSettings):
    environment: Literal["local", "dev", "prod"] = "local"
    log_level: str = "INFO"

    gemini_api_key: SecretStr                     # Secrets Manager → env at task start
    gemini_model: str = "gemini-3.5-flash"
    gemini_embedding_model: str = "gemini-embedding-001"

    db_path: Path = Path("/data/app.db")
    checkpoint_db_path: Path = Path("/data/checkpoints.db")

    cognito_user_pool_id: str
    cognito_client_id: str
    cognito_region: str = "ap-southeast-1"

    enable_vector_search: bool = False             # docs/13
    cors_origins: list[str] = []
```

Validated at import. A missing required value fails the container at boot — visible in
the ECS deployment as a failing task, rather than as a `500` on the first real request.
`gemini_api_key` is `SecretStr`, so it cannot be accidentally logged or serialised.

### 3.9 Middleware order

1. Trace ID — mint or adopt, bind to `contextvar`
2. Structured access log — method, path, status, duration, actor `sub`, `trace_id`
3. CORS — only for local development; in AWS the SPA is same-origin behind the ALB
4. Exception handler — map to RFC 9457
5. Auth dependency — per-route

### 3.10 OpenAPI

FastAPI generates the schema at `/api/v1/openapi.json`. The frontend generates its
TypeScript types from it in CI, so a backend contract change that the frontend has not
adopted breaks the build rather than production.

---

## 4. Decisions and tradeoffs

| Decision | Alternative | Rationale |
|---|---|---|
| SSE | WebSocket | One-directional streaming; no upgrade handshake through the ALB; native reconnect |
| Resume is a separate request | Hold the stream open for approval | An approval can take minutes. Holding a connection wastes a worker and dies with the task |
| Read-only non-graph routes | Full CRUD REST API | Keeps every mutation inside the approved-and-audited path |
| RFC 9457 | Ad-hoc `{error: "..."}` | Standard, machine-readable, and carries `trace_id` naturally |
| `404` for wrong-owner threads | `403` | `403` confirms existence |
| App-level JWT validation | ALB `authenticate-cognito` | Testable without AWS; works cleanly for XHR and SSE |
| Types generated from OpenAPI | Hand-written client types | Contract drift becomes a build failure |

## 5. Failure modes

| Failure | Detection | Behaviour |
|---|---|---|
| Token expired mid-stream | Validated at request start only | Stream completes; the next request `401`s and the SPA refreshes silently |
| Client disconnects mid-run | FastAPI disconnect signal | Graph task cancelled; checkpoint retained |
| Graph raises unexpectedly | Exception in the stream generator | `error` event, then `done: error`. Stream always terminates cleanly |
| JWKS fetch fails | Exception on cache miss | Cached keys serve until TTL; then `401` (fail closed) |
| Concurrent messages on one thread | Checkpointer write conflict | Second request `409` — `thread_busy` |
| `/readyz` fails | Probe | Target drained; ECS replaces the task |
| Oversized request body | `Content-Length` check | `413` before parsing |

## 6. Open questions

1. **Token refresh during a long stream.** A 45-second investigation cannot fail
   because a token expired at second 30 — validation is at request start only, which is
   correct but should be stated in the SPA's refresh logic too.
2. **Pagination style.** Cursor vs offset for interaction lists. Offset is simpler and
   the datasets are small; cursor is the right answer if the datastore migrates.
3. **Should `/api/v1/meta` expose the model ID?** Useful for the demo and for support,
   mildly informative to an attacker. Leaning: expose it, authenticated only.
