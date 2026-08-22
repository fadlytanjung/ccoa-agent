"""Error taxonomy shared by tools, the graph, and the HTTP layer — docs/05 §3.11.

The class of an error decides what happens to it: whether it is retried, how often,
whether it degrades, and what the user is told. Tools return these; they never raise
into the graph, because a raised exception would abort the run and discard evidence
already gathered (docs/03 §3.6).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, Field


class ErrorClass(StrEnum):
    TRANSIENT = "transient"
    RATE_LIMITED = "rate_limited"
    NOT_FOUND = "not_found"
    INVALID_INPUT = "invalid_input"
    FORBIDDEN = "forbidden"
    BUDGET_EXCEEDED = "budget_exceeded"
    INTERNAL = "internal"


#: Retry budget per node, by error class. Anything absent is not retried.
RETRY_BUDGET: Final[dict[ErrorClass, int]] = {
    ErrorClass.TRANSIENT: 2,
    ErrorClass.RATE_LIMITED: 1,
}

#: HTTP status for each class, used by the RFC 9457 mapper (docs/06 §3.6).
HTTP_STATUS: Final[dict[ErrorClass, int]] = {
    ErrorClass.TRANSIENT: 503,
    ErrorClass.RATE_LIMITED: 429,
    ErrorClass.NOT_FOUND: 404,
    ErrorClass.INVALID_INPUT: 422,
    ErrorClass.FORBIDDEN: 403,
    ErrorClass.BUDGET_EXCEEDED: 200,
    ErrorClass.INTERNAL: 500,
}


class ToolError(BaseModel):
    """A failure a tool returns rather than raises."""

    model_config = {"frozen": True}

    error_class: ErrorClass
    code: str
    message: str
    node: str | None = None
    retry_after_seconds: float | None = None
    detail: dict[str, str] = Field(default_factory=dict)

    @property
    def retryable(self) -> bool:
        return self.error_class in RETRY_BUDGET

    @property
    def http_status(self) -> int:
        return HTTP_STATUS[self.error_class]


class AppError(Exception):
    """Raised inside the HTTP layer only. The graph never sees these."""

    def __init__(
        self,
        error_class: ErrorClass,
        code: str,
        message: str,
        *,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.code = code
        self.message = message
        self.status = status if status is not None else HTTP_STATUS[error_class]


class NotFound(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(ErrorClass.NOT_FOUND, code, message)


class Forbidden(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(ErrorClass.FORBIDDEN, code, message)


class Conflict(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(ErrorClass.INTERNAL, code, message, status=409)


class Unauthorized(AppError):
    """Deliberately carries no detail about which check failed — docs/06 §3.3."""

    def __init__(self, code: str = "unauthorized") -> None:
        super().__init__(ErrorClass.FORBIDDEN, code, "Authentication required.", status=401)


def not_found(entity: str, identifier: str) -> ToolError:
    return ToolError(
        error_class=ErrorClass.NOT_FOUND,
        code=f"{entity}_not_found",
        message=f"No {entity} matches identifier {identifier}.",
        detail={"identifier": identifier},
    )


def invalid_input(message: str, **detail: str) -> ToolError:
    return ToolError(
        error_class=ErrorClass.INVALID_INPUT,
        code="invalid_input",
        message=message,
        detail=detail,
    )


def forbidden(action: str, required_group: str) -> ToolError:
    return ToolError(
        error_class=ErrorClass.FORBIDDEN,
        code="forbidden",
        message=f"Action {action!r} requires membership of the {required_group!r} group.",
        detail={"action": action, "required_group": required_group},
    )


def internal(message: str, *, node: str | None = None) -> ToolError:
    return ToolError(
        error_class=ErrorClass.INTERNAL,
        code="internal_error",
        message=message,
        node=node,
    )
