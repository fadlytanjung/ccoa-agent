# 14 — Local development

> **Status:** Approved — 2026-08-22
> **Satisfies:** REQ-092, REQ-016 (debuggability), REQ-071
> **Depends on:** [05 — LangGraph orchestration](05-langgraph-orchestration.md), [17 — Agent skills](17-agent-skills.md)

## 1. Purpose

Running and debugging the system on a laptop: the pluggable-checkpointer mechanism that
lets one graph run under three different runtimes, LangGraph Studio, and the
prompt-iteration loop.

## 2. Scope

**In scope:** prerequisites, first-run setup, the three runtimes, `langgraph dev` and
Studio, checkpointer injection, skill hot reload, debugging, tracing, common failures.

**Out of scope:** graph design ([05](05-langgraph-orchestration.md)), deployment
([08](08-infrastructure.md)), CI ([11](11-cicd.md)).

---

## 3. Design

### 3.1 The central mechanism — one graph, three runtimes

The same graph runs under LangGraph Studio, FastAPI, and pytest. **It must not know
which.** This is the origin of the rule in [00](00-constitution.md) §7 and it is
load-bearing for REQ-092.

LangChain's documentation is explicit about why:

> "When using the Agent Server, you do not need to implement or configure checkpointers
> or stores manually. The server handles persistence infrastructure behind the scenes."

So a graph that hard-wires `AsyncSqliteSaver` would fight the Agent Server under
`langgraph dev`. The single construction entry point takes persistence as a parameter:

```python
def build_graph(
    checkpointer: BaseCheckpointSaver | None = None,
    model: BaseChatModel | None = None,
) -> CompiledStateGraph:
    g = StateGraph(AgentState)
    ...
    return g.compile(checkpointer=checkpointer) if checkpointer else g.compile()
```

| Runtime | Checkpointer | Model | Supplied by |
|---|---|---|---|
| **LangGraph Studio** (`langgraph dev`) | **None** — the server injects its own | Real Gemini | `langgraph.json` |
| **FastAPI** (local or ECS) | `AsyncSqliteSaver` | Real Gemini | `app.main` lifespan |
| **pytest** | `MemorySaver` | **Stub** returning scripted tool calls | Test fixture |

The `model` parameter exists for the same reason: unit tests must not touch the network
([11](11-cicd.md) §3.4), so the model is injected exactly as persistence is.

### 3.2 Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.12 | Matches the container |
| `uv` | ≥0.8 | Dependency management |
| Node | ≥22 | Frontend |
| Docker | ≥27 | Only for full-stack runs |
| Terraform | ≥1.11 | Only for deploying — native S3 state locking |

A **Gemini API key** is required to run the agent. Everything else — tests, linting,
type checking — runs without one.

### 3.3 First run

```bash
cd backend
uv sync
cp .env.example .env          # then add GEMINI_API_KEY
uv run alembic upgrade head   # create schema
uv run python -m app.seed --reset

cd ../frontend
npm ci
```

`.env` is git-ignored ([10](10-security.md) §4). `.env.example` documents every variable
with a safe placeholder and is committed.

```bash
# .env.example — every variable the backend reads
ENVIRONMENT=local
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-3.5-flash       # gemini-3.5-flash-lite is cheaper, docs/02 §3.1
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
DB_PATH=./data/app.db
CHECKPOINT_DB_PATH=./data/checkpoints.db
LANGGRAPH_STRICT_MSGPACK=true       # CVE-2026-28277 — required, not optional
ENABLE_VECTOR_SEARCH=false
LANGSMITH_TRACING=false             # true also requires LANGSMITH_API_KEY
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=ccoa-local
COGNITO_USER_POOL_ID=local-dev
COGNITO_CLIENT_ID=local-dev
AUTH_MODE=dev                       # bypasses JWT — see §3.7
```

Two of these are validated as a *pair*, not individually: `LANGSMITH_TRACING=true` with
an empty `LANGSMITH_API_KEY` fails at boot rather than starting up and tracing nothing,
because an operator who believes they have observability and does not is worse off than
one who knows tracing is off.

### 3.4 The three ways to run

```bash
# 1. LangGraph Studio — graph development and debugging
uv run langgraph dev                  # → http://127.0.0.1:2024

# 2. FastAPI — the real API surface
uv run uvicorn app.main:app --reload  # → http://localhost:8000

# 3. Frontend
cd frontend && npm run dev            # → http://localhost:5173  (proxies /api → :8000)
```

Studio and FastAPI are **alternatives, not a stack** — both build the same graph, with
different persistence. Run Studio to work on the graph; run FastAPI to work on the API
or the UI.

**They are deliberately not runnable together, and this is settled.** `langgraph dev`
exists to measure the *quality of the graph* — routing, delegation, evidence
accumulation, interrupt behaviour — not to serve the product. Everything the API adds
around the graph (JWT verification, SSE framing, thread ownership, RFC 9457 mapping) is
noise when the question is "did the orchestrator delegate correctly?", and each of those
layers is tested on its own terms in `tests/api/`. Running both would also mean two
processes holding two different checkpointers over the same thread IDs, which is a
correctness problem, not just a port conflict.

The practical rule: **graph behaviour is a Studio question, product behaviour is a
FastAPI question.** If a bug is reproducible in Studio it belongs to the graph; if it
only appears through the API it belongs to the transport.

### 3.5 LangGraph Studio

`langgraph dev` (from `langgraph-cli[inmem]` `0.4.31`) starts an in-memory Agent Server
on `127.0.0.1:2024` and opens Studio at
`https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`.

```json
// backend/langgraph.json
{
  "dependencies": ["."],
  "graphs": { "ccoa": "./app/graph/studio.py:graph" },
  "env": ".env"
}
```

```python
# app/graph/studio.py — module-level export for the Agent Server
graph = build_graph()          # no checkpointer: the server supplies one
```

That one line is the whole integration. Because `build_graph` defaults to no
checkpointer, the export is naturally correct.

**The export lives in `studio.py`, not in `builder.py`.** *(Amended 2026-08-22.)*
Constructing the graph opens a database, loads the skill registry, and validates the
tool surface — the right thing to do at import time for `langgraph dev`, and the wrong
thing for `import app.graph.builder` in a unit test. Isolating the side effect keeps
`builder` importable without any I/O, which is what lets the graph tests construct their
own dependencies.

What Studio gives that a terminal cannot:

| Capability | Why it matters here |
|---|---|
| Visual graph with live node highlighting | The orchestrator/specialist topology is hard to follow in logs |
| **State inspection at every step** | See `evidence` accumulate and `intent` get set |
| **Time travel** — fork from any checkpoint | Re-run a delegation decision without replaying the conversation |
| **Interrupt inspection and resume** | Approve/reject a HITL gate by hand, with the exact payload visible |
| Per-node latency and token counts | Find which specialist is expensive |
| Edit state and continue | Force a routing branch that is hard to trigger by prompting |

Time travel is the one that changes how the graph gets built: reproducing a
mis-classification normally means re-typing the conversation, and forking a checkpoint
removes that loop entirely.

**Studio persistence is in-memory** — threads vanish when the server stops. That is
correct for development and is precisely why the graph must not assume a durable
checkpointer.

### 3.6 Skill hot reload

Agent behaviour lives in `SKILL.md` files ([17](17-agent-skills.md)). Locally the
registry watches them:

```
edit app/agents/skills/investigator/SKILL.md
  → registry re-parses and re-validates
  → next run in Studio uses the new prompt
  → no restart
```

This is the main practical payoff of externalising prompts. In the deployed image skills
are frozen and digest-logged; hot reload is local-only ([17](17-agent-skills.md) §3.8).

Validation runs on every reload, so a malformed frontmatter or an unknown tool name
surfaces as an error in the terminal rather than as strange model behaviour.

### 3.7 Auth in local development

`AUTH_MODE=dev` replaces the Cognito JWT dependency with a fixed actor:

```python
Actor(sub="local-dev-user", email="dev@localhost", groups=["agent", "supervisor"])
```

Standing a Cognito pool up to click through a login on every reload would make the loop
unusable. Two guards keep this from becoming a vulnerability:

- **`AUTH_MODE` may only be `dev` when `ENVIRONMENT == "local"`.** Any other combination
  raises at startup, so a deployed task with `AUTH_MODE=dev` fails to boot rather than
  serving unauthenticated.
- **A test asserts the guard**, so removing it fails the build.

The dev actor holds **both** groups, so both authorisation paths are reachable. To
exercise a denial, drop `supervisor` and attempt an escalation.

### 3.8 Debugging

| Symptom | Approach |
|---|---|
| Wrong intent chosen | Studio → `classify` node → inspect `Classification.rationale` and confidence |
| Investigation loops | Studio → watch `attempts`; check the distinct-tool counter ([05](05-langgraph-orchestration.md) §3.5) |
| Answer cites a nonexistent record | Compare the answer's refs against `state.evidence` — the grounding test does this automatically |
| Interrupt never fires | Confirm `pending_ask` is set; confirm a checkpointer exists (interrupts need one) |
| Tool never called | Check the skill's `tools:` list — the tool may not be bound to that agent |
| Prompt change has no effect | Check the registry reloaded; check you edited the skill the *active agent* uses |
| Slow response | LangSmith trace, or Studio per-node latency |

Set `LANGSMITH_TRACING=true` locally for full run replay. It sends prompts and state to
LangSmith — fine for synthetic data, and the same caveat as production
([ADR-005](adr/ADR-005-runtime-and-persistence.md) §7).

### 3.9 Testing locally

```bash
uv run pytest                          # everything except live-LLM
uv run pytest -m live                  # requires a real key
uv run pytest --cov=app --cov-report=term-missing
uv run pytest tests/graph -k hitl -x   # one area, stop on first failure
```

Unit and graph tests need **no key and no network** — the model is stubbed and the
checkpointer is `MemorySaver`. This is the practical benefit of §3.1: the same graph
under test needs no special construction.

### 3.10 Full-stack locally

```bash
docker compose up --build
```

Compose runs the backend and an nginx-served frontend build, approximating the deployed
topology. It does **not** include CloudFront, the ALB, Cognito, or Litestream — those are
tested by deploying. Compose exists for verifying the container builds and the nginx
config, not as a production simulator.

---

## 4. Decisions and tradeoffs

| Decision | Alternative | Rationale |
|---|---|---|
| `build_graph(checkpointer=None, model=None)` | Construct persistence inside the graph | The Agent Server supplies its own; tests need `MemorySaver`. Injection is the only thing that satisfies all three |
| Module-level `graph = build_graph()` for Studio | A factory in `langgraph.json` | Simplest correct export; the no-checkpointer default makes it right by construction |
| `AUTH_MODE=dev` | Local Cognito, or mocked JWTs | A login on every reload destroys the loop. Guarded so it cannot ship |
| Studio *or* FastAPI, not both | Run Studio behind the API | They are different runtimes of one graph; conflating them hides the injection point |
| Skill hot reload local-only | Hot reload everywhere | Fast iteration locally; immutable, digest-logged behaviour when deployed |
| Compose for container checks only | Full local AWS emulation | LocalStack for CloudFront + VPC origins is more fiction than fidelity |
| Live tests opt-in | Run everything always | Deterministic, offline, no credentials in CI |

## 5. Failure modes

| Failure | Detection | Behaviour |
|---|---|---|
| `langgraph dev` cannot import the graph | Startup traceback | Check `graphs` path in `langgraph.json` |
| Studio shows no threads after restart | — | Expected: in-memory persistence |
| `interrupt()` raises "no checkpointer" | Runtime error | FastAPI path constructed without a saver — the injection was skipped |
| Skill edit ignored | No reload log line | Watcher not running, or a different skill is active |
| `AUTH_MODE=dev` with `ENVIRONMENT != local` | Startup validation | **Fails to boot** — deliberate |
| Missing `GEMINI_API_KEY` | Settings validation | Fails at import with the variable named |
| `LANGGRAPH_STRICT_MSGPACK` unset | Startup check | Warns loudly; CVE mitigation is not optional ([02](02-research.md) §4.2) |
| Vector search on without an index | `vec_meta` check | Flag forced off; keyword search ([13](13-vector-search.md) §3.6) |

## 6. Open questions

1. **A `make demo` target** that seeds, starts both services, and prints the reference
   prompts would shorten the first-run path considerably.
2. **Studio against deployed state.** Studio can attach to a remote Agent Server, but the
   deployed backend is FastAPI, not an Agent Server — so production threads are not
   inspectable in Studio. LangSmith covers this; worth stating so nobody expects otherwise.
