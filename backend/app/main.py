"""FastAPI application factory and lifespan — docs/03 §3.3, docs/06.

The lifespan is where this process makes the two decisions the graph refuses to make
for itself: which checkpointer to use (``AsyncSqliteSaver``, on its own database) and
which model factory. Under ``langgraph dev`` the Agent Server makes them differently,
and under pytest the fixtures do — the graph is identical in all three (docs/14 §3.1).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.api import errors
from app.api.deps import JwksCache
from app.api.middleware import TraceMiddleware
from app.api.v1 import api_router
from app.api.v1.health import router as ops_router
from app.config import Settings, apply_langsmith_env, get_settings
from app.graph.builder import build_graph
from app.graph.deps import GraphDependencies
from app.telemetry import configure_logging, get_logger

log = get_logger(__name__)

TITLE = "CCOA — Contact Center Operations Assistant"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.environment != "local")
    apply_langsmith_env(settings)

    log.info(
        "starting",
        environment=settings.environment,
        model=settings.gemini_model,
        auth_mode=settings.auth_mode,
        vector_search=settings.enable_vector_search,
    )

    deps = GraphDependencies.build(settings)

    async with AsyncExitStack() as stack:
        checkpointer = await stack.enter_async_context(
            AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_db_path))
        )
        await checkpointer.setup()

        app.state.settings = settings
        app.state.database = deps.database
        app.state.repos = deps.repos
        app.state.registry = deps.registry
        app.state.checkpointer = checkpointer
        app.state.vector_search = deps.toolbox.ctx.retrieval.method == "semantic"
        app.state.jwks = JwksCache(settings.jwks_url, settings.jwks_cache_seconds)
        app.state.graph = build_graph(checkpointer=checkpointer, deps=deps)

        log.info(
            "ready",
            schema_version=deps.database.schema_version(),
            skills=list(deps.registry.digests()),
            retrieval=deps.toolbox.ctx.retrieval.method,
        )
        try:
            yield
        finally:
            deps.database.dispose()
            log.info("stopped")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=TITLE,
        version="0.1.0",
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs" if settings.environment != "prod" else None,
        redoc_url=None,
    )

    app.add_middleware(TraceMiddleware)
    if settings.cors_origins:
        # Local development only. In AWS the SPA is same-origin behind the ALB, so an
        # empty list is the correct production value (docs/06 §3.9).
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
            expose_headers=["X-Trace-Id"],
        )

    errors.install(app)
    app.include_router(ops_router)
    app.include_router(api_router)
    return app


app = create_app()
