"""Request dependencies — docs/06 §3.3.

Authentication is verified in the application rather than at the ALB. That keeps the
authorisation model testable without AWS and works cleanly for XHR and SSE, neither of
which handles a redirect-based OIDC flow well (docs/03 §4).
"""

from __future__ import annotations

import time
from typing import Annotated, Any

import httpx
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
from jose.exceptions import JWTError

from app.config import Settings, get_settings
from app.domain.actor import DEV_ACTOR, Actor
from app.domain.enums import Group
from app.domain.errors import Forbidden, Unauthorized
from app.telemetry import get_logger, set_actor_sub

log = get_logger(__name__)

#: ``auto_error=False`` so a missing header produces our RFC 9457 body rather than
#: FastAPI's default JSON shape.
bearer = HTTPBearer(auto_error=False)


class JwksCache:
    """Caches the pool's signing keys.

    Fails **closed**: once the cache expires and a refresh fails, requests are rejected
    rather than accepted unverified (docs/06 §5).
    """

    def __init__(self, url: str, ttl_seconds: int) -> None:
        self._url = url
        self._ttl = ttl_seconds
        self._keys: dict[str, Any] | None = None
        self._fetched_at = 0.0

    async def get(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._keys is not None and now - self._fetched_at < self._ttl:
            return self._keys

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(self._url)
            response.raise_for_status()
            self._keys = dict(response.json())
        self._fetched_at = now
        return self._keys


def _jwks(request: Request) -> JwksCache:
    cache = getattr(request.app.state, "jwks", None)
    if cache is None:
        raise Unauthorized("jwks_unavailable")
    return cache  # type: ignore[no-any-return]


async def verify_token(token: str, settings: Settings, jwks: JwksCache) -> dict[str, Any]:
    """Validate signature, issuer, audience, token use, and expiry.

    Every failure returns the same ``401`` with no detail about which check failed —
    telling an attacker whether the signature or the audience was wrong is free
    information (docs/06 §3.3).
    """
    try:
        keys = await jwks.get()
        claims: dict[str, Any] = jwt.decode(
            token,
            keys,
            algorithms=["RS256"],
            issuer=settings.cognito_issuer,
            options={"verify_aud": False},
        )
    except (JWTError, httpx.HTTPError, ValueError) as exc:
        log.info("token rejected", reason=exc.__class__.__name__)
        raise Unauthorized() from exc

    if claims.get("token_use") != "access":
        raise Unauthorized()
    if claims.get("client_id") != settings.cognito_client_id:
        raise Unauthorized()
    return claims


async def current_actor(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)] = None,
) -> Actor:
    settings = get_settings()

    if settings.auth_mode == "dev":
        # Guarded in Settings: this combination cannot exist outside local development,
        # because the process refuses to start (docs/14 §3.7).
        set_actor_sub(DEV_ACTOR.sub)
        return DEV_ACTOR

    if credentials is None or not credentials.credentials:
        raise Unauthorized()

    claims = await verify_token(credentials.credentials, settings, _jwks(request))
    actor = Actor(
        sub=str(claims["sub"]),
        email=str(claims.get("email", "")),
        groups=tuple(str(g) for g in claims.get("cognito:groups", [])),
    )
    set_actor_sub(actor.sub)
    return actor


CurrentActor = Annotated[Actor, Depends(current_actor)]


async def require_agent(actor: CurrentActor) -> Actor:
    """Every authenticated route needs at least the `agent` group."""
    if not actor.has_group(Group.AGENT):
        raise Forbidden("insufficient_group", "This action requires the 'agent' group.")
    return actor


AgentActor = Annotated[Actor, Depends(require_agent)]
