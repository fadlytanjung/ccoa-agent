"""Liveness, readiness, and build metadata — docs/06 §3.7.

`/healthz` and `/readyz` are deliberately different. A backend whose database failed its
integrity check, or whose migrations did not reach head, is *alive* but must stop
receiving traffic — conflating the two would leave the load balancer routing into a
broken task.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response

from app.api.deps import AgentActor
from app.config import get_settings

router = APIRouter(tags=["ops"])

#: The revision the code expects. Checked at startup against what is applied, so a task
#: running last release's migrations never serves traffic.
EXPECTED_HEAD = "0003_threads"


@router.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    """Liveness only: the process is up and answering."""
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
def readyz(request: Request, response: Response) -> dict[str, Any]:
    """Readiness: the database is intact, migrated, and the model handle exists."""
    state = request.app.state
    settings = get_settings()

    checks: dict[str, bool] = {}

    database = getattr(state, "database", None)
    checks["database"] = database is not None and database.quick_check()

    applied = database.schema_version() if database is not None else None
    checks["migrations"] = applied == EXPECTED_HEAD

    checks["skills"] = bool(getattr(state, "registry", None))
    checks["checkpointer"] = getattr(state, "checkpointer", None) is not None
    # Constructing the handle proves the key is present and the binding imports; it
    # does not call the API, because a readiness probe must not depend on a third party.
    checks["model"] = bool(settings.gemini_api_key.get_secret_value()) or (
        settings.environment == "local"
    )

    ready = all(checks.values())
    if not ready:
        response.status_code = 503

    return {
        "status": "ready" if ready else "not_ready",
        "checks": checks,
        "schema_version": applied,
    }


@router.get("/api/v1/config")
def config() -> dict[str, Any]:
    """Runtime configuration the SPA needs **before** it can authenticate.

    Unauthenticated on purpose, and the reason is a genuine ordering problem: the SPA
    cannot ask an authenticated endpoint which identity provider to authenticate
    against. docs/07 §3.9 says runtime config comes from `/meta`, which is true of the
    parts that are useful *after* login; the Cognito pool and client id are needed
    strictly before it.

    Nothing here is a secret. A user pool id and an app client id are public by
    construction — they appear in the sign-in URL of every OIDC client on earth — and
    `auth_mode` tells the SPA whether to run the redirect flow at all, which is what
    lets one image serve a local dev environment and a deployed one.
    """
    settings = get_settings()
    return {
        "auth_mode": settings.auth_mode,
        "environment": settings.environment,
        "cognito": {
            "user_pool_id": settings.cognito_user_pool_id,
            "client_id": settings.cognito_client_id,
            "region": settings.cognito_region,
            "domain": settings.cognito_domain or None,
        },
    }


@router.get("/api/v1/meta")
def meta(request: Request, actor: AgentActor) -> dict[str, Any]:
    """Feature flags, model id, and skill digests. Authenticated only.

    The model id is mildly informative to an attacker and materially useful for support
    and for reproducing a bad answer; docs/06 §6 settles that trade in favour of
    exposing it behind authentication.
    """
    del actor
    settings = get_settings()
    registry = getattr(request.app.state, "registry", None)
    return {
        "environment": settings.environment,
        "build_sha": settings.build_sha,
        "model": settings.gemini_model,
        "embedding_model": settings.gemini_embedding_model,
        "features": {
            "vector_search": bool(getattr(request.app.state, "vector_search", False)),
            "tracing": settings.langsmith_tracing,
        },
        "skills": registry.digests() if registry else {},
    }
