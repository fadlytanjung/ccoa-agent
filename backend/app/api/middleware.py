"""Trace identifiers and access logging — docs/06 §3.9.

Order matters: the trace id is bound first so every subsequent layer, including the
exception handler, has one to report.
"""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.telemetry import get_logger, new_trace_id, set_actor_sub, set_trace_id

log = get_logger("app.access")

REQUEST_ID_HEADER = "X-Request-Id"
TRACE_ID_HEADER = "X-Trace-Id"

#: Paths that are not worth a log line each. Health probes fire every few seconds and
#: would otherwise be most of the log volume.
_QUIET_PATHS = frozenset({"/healthz", "/readyz"})


def _adopt(request: Request) -> str:
    """Adopt an inbound request id when it looks like one, else mint a fresh id.

    The value ends up in logs, so an unvalidated header is a log-injection vector; only
    a hex string of plausible length is accepted.
    """
    inbound = request.headers.get(REQUEST_ID_HEADER, "").strip()
    if 8 <= len(inbound) <= 64:
        try:
            uuid.UUID(hex=inbound.replace("-", ""))
        except ValueError:
            return new_trace_id()
        return inbound.replace("-", "")
    return new_trace_id()


class TraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        trace_id = _adopt(request)
        set_trace_id(trace_id)
        set_actor_sub("")

        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - started) * 1000)

        response.headers[TRACE_ID_HEADER] = trace_id

        if request.url.path not in _QUIET_PATHS:
            # Method, path, status, duration. Never the body, never the query values —
            # a customer search puts a name in the query string (docs/04 §3.8).
            log.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
            )
        return response
