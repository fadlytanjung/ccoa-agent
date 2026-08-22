# CCOA backend

FastAPI + LangGraph orchestration service. Implements
[`docs/05`](../docs/05-langgraph-orchestration.md), [`docs/06`](../docs/06-backend-api.md),
and [`docs/17`](../docs/17-agent-skills.md).

```bash
uv sync
cp .env.example .env                    # then add GEMINI_API_KEY
uv run alembic upgrade head
uv run python -m app.seed --reset

uv run uvicorn app.main:app --reload    # API on :8000
uv run langgraph dev                    # Studio on :2024 — graph work only
uv run pytest
uv run ruff check . && uv run mypy app
```

`langgraph dev` and the API are **alternatives, not a stack** —
[`docs/14` §3.4](../docs/14-local-dev.md) explains why.

## Layout

| Path | Contents |
|---|---|
| `app/api/` | HTTP layer — routers, auth dependency, SSE framing, RFC 9457 errors |
| `app/graph/` | LangGraph state, nodes, tools, `build_graph()` |
| `app/agents/` | Skill registry + `skills/*/SKILL.md` — all prompt text lives here |
| `app/domain/` | Pure types and rules, no I/O |
| `app/repositories/` | SQLite access, one module per aggregate |
| `app/services/` | LLM binding, embeddings, retrieval, audit |
| `app/seed/` | Deterministic corpus generation |
| `alembic/` | Schema migrations |
| `tools/` | CI checks that are not tests |
