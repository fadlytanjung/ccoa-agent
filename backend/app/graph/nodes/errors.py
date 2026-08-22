"""Error handling — docs/05 §3.11.

Errors are classified, and the class decides what happens: retry with a budget, or
surface honestly. **Degradation is preferred to failure** — but the user is always told
which they got, because a silently degraded answer is a correctness bug rather than a
resilience feature.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from app.domain.errors import RETRY_BUDGET, ErrorClass
from app.graph.deps import GraphDependencies
from app.graph.state import AgentState

log = logging.getLogger(__name__)


def should_retry(state: AgentState) -> bool:
    """True when the class is retryable *and* the failing node has budget left.

    Pure, so the retry policy is unit-testable without running a graph (docs/05 §3.12).
    """
    error = state.get("error")
    if not error:
        return False

    try:
        error_class = ErrorClass(str(error.get("error_class", "")))
    except ValueError:
        return False

    budget = RETRY_BUDGET.get(error_class)
    if budget is None:
        return False

    node = str(error.get("node") or "")
    return (state.get("attempts") or {}).get(node, 0) <= budget


def build_error_handler(
    deps: GraphDependencies,
) -> Callable[[AgentState, RunnableConfig], Command[Any]]:
    del deps

    def error_handler(state: AgentState, config: RunnableConfig) -> Command[Any]:
        del config
        error = state.get("error") or {}
        retrying = should_retry(state)
        log.info(
            "error class=%s code=%s node=%s retrying=%s",
            error.get("error_class"),
            error.get("code"),
            error.get("node"),
            retrying,
        )

        if retrying:
            # Clearing the error is what makes this a retry rather than an immediate
            # second trip through the handler. The attempt counter is *not* cleared —
            # that is the budget, and it has to survive the loop (docs/05 §3.2).
            return Command(goto="orchestrator", update={"error": None})

        return Command(goto="respond")

    return error_handler
