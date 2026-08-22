"""The contract every tool returns — docs/05 §3.8."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.errors import ToolError


class ToolResult(BaseModel):
    """A tool's outcome. Never an exception.

    A raised exception would abort the run and discard evidence already gathered; a
    returned error is a value the graph can route on and the model can be told about.
    """

    model_config = ConfigDict(frozen=True)

    ok: bool
    data: dict[str, Any] | None = None
    error: ToolError | None = None
    #: Stable evidence identifiers for whatever this result contains, e.g.
    #: ``["customer:CUST-000042", "policy:POL-00000073"]``.
    refs: tuple[str, ...] = ()

    @classmethod
    def success(cls, data: dict[str, Any], refs: tuple[str, ...] = ()) -> ToolResult:
        return cls(ok=True, data=data, refs=refs)

    @classmethod
    def failure(cls, error: ToolError) -> ToolResult:
        return cls(ok=False, error=error)

    def as_payload(self) -> dict[str, Any]:
        """What the model is shown. Errors are surfaced, not hidden."""
        if self.ok:
            return {"ok": True, **(self.data or {})}
        assert self.error is not None
        return {
            "ok": False,
            "error": self.error.code,
            "message": self.error.message,
            "retryable": self.error.retryable,
        }


class ToolCallRecord(BaseModel):
    """One tool invocation, for the SSE `tool` event and the structured log.

    ``args_summary`` rather than ``args``: arguments can contain a customer's name, and
    PII is never logged (docs/04 §3.8).
    """

    model_config = ConfigDict(frozen=True)

    name: str
    args_summary: str
    ok: bool
    refs: tuple[str, ...] = ()
    duration_ms: int = Field(default=0, ge=0)
