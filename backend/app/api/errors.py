"""RFC 9457 problem details — docs/06 §3.6.

`detail` never contains PII, a stack trace, or an internal path. The `trace_id` is the
handle for correlating with logs, and it is the only thing a caller needs to quote when
reporting a problem.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain.errors import AppError
from app.telemetry import get_trace_id

log = logging.getLogger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"
ERROR_BASE = "https://ccoa.internal/errors"

_TITLES = {
    400: "Malformed request",
    401: "Authentication required",
    403: "Forbidden",
    404: "Not found",
    409: "Conflict",
    413: "Request too large",
    422: "Validation failed",
    429: "Rate limited",
    500: "Internal error",
    503: "Service unavailable",
}


def problem(
    request: Request,
    *,
    status: int,
    code: str,
    detail: str,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"{ERROR_BASE}/{code.replace('_', '-')}",
        "title": _TITLES.get(status, "Error"),
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        "trace_id": get_trace_id(),
    }
    if extra:
        body.update(extra)
    headers = {"X-Trace-Id": get_trace_id()}
    return JSONResponse(
        status_code=status, content=body, media_type=PROBLEM_CONTENT_TYPE, headers=headers
    )


def install(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return problem(request, status=exc.status, code=exc.code, detail=exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # The field paths are safe to return; the submitted *values* are not, so only
        # the location and the message are echoed back.
        errors = [
            {"loc": ".".join(str(p) for p in err.get("loc", [])), "msg": err.get("msg", "")}
            for err in jsonable_encoder(exc.errors())
        ]
        return problem(
            request,
            status=422,
            code="validation_failed",
            detail="The request did not match the expected schema.",
            extra={"errors": errors},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return problem(
            request,
            status=exc.status_code,
            code=_TITLES.get(exc.status_code, "error").lower().replace(" ", "_"),
            detail=str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Logged with the exception, returned without it. The caller gets a trace id.
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        del exc
        return problem(
            request,
            status=500,
            code="internal_error",
            detail="The request could not be completed. Quote the trace id when reporting this.",
        )
