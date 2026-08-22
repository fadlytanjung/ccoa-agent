"""Structured logging and the trace identifier — docs/03 §3.6.

One identifier links an HTTP request, its graph run, its tool calls, and its audit
rows. It is minted at the edge (or adopted from ``X-Request-Id``), held in a
``contextvar`` so every log line picks it up without being passed one, and attached to
the LangGraph config so nodes carry it too.

**Never logged:** message content, customer PII, or the API key. What is logged is the
shape of what happened — node names, tool names, decisions, durations, outcomes.
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog

_trace_id: ContextVar[str] = ContextVar("trace_id", default="")
_actor_sub: ContextVar[str] = ContextVar("actor_sub", default="")


def new_trace_id() -> str:
    return uuid.uuid4().hex


def set_trace_id(value: str) -> None:
    _trace_id.set(value)


def get_trace_id() -> str:
    return _trace_id.get()


def set_actor_sub(value: str) -> None:
    _actor_sub.set(value)


def _inject_context(
    _logger: Any, _method: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    if trace_id := _trace_id.get():
        event.setdefault("trace_id", trace_id)
    if actor := _actor_sub.get():
        event.setdefault("actor_sub", actor)
    return event


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Configure structlog and route stdlib logging through it.

    JSON to stdout in every deployed environment, because CloudWatch Logs Insights can
    query fields but cannot parse prose. Console rendering locally, because a developer
    reading a terminal cannot.
    """
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        _inject_context,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(processor=renderer, foreign_pre_chain=shared)
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # These are informative at DEBUG and pure noise at INFO on every model call.
    for noisy in ("httpx", "httpcore", "google_genai.models", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
