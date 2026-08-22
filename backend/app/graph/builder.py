"""``build_graph`` — the only construction entry point (docs/00 §7, docs/14 §3.1).

Persistence and the model are **parameters**, not decisions made here. The same graph
runs under the LangGraph Agent Server (which supplies its own checkpointer), under
FastAPI (``AsyncSqliteSaver``), and under pytest (``MemorySaver`` plus a stubbed model).
A graph that hard-wired either would fight all three.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.deps import GraphDependencies
from app.graph.nodes.errors import build_error_handler
from app.graph.nodes.guard import guard, route_guard
from app.graph.nodes.human import build_commit, build_human
from app.graph.nodes.orchestrator import build_orchestrator, build_respond
from app.graph.nodes.specialists import build_specialists
from app.graph.state import AgentState

log = logging.getLogger(__name__)


def build_graph(
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    model: BaseChatModel | None = None,
    deps: GraphDependencies | None = None,
) -> CompiledStateGraph[AgentState, Any, Any, Any]:
    """Compile the orchestration graph.

    ``model`` overrides the factory wholesale, which is how the test suite stays offline
    and deterministic: a stub returning scripted tool calls satisfies every node.
    """
    resolved = deps or GraphDependencies.build()
    if model is not None:
        resolved = _with_fixed_model(resolved, model)

    specialists = build_specialists(resolved)

    builder: StateGraph[AgentState, Any, Any, Any] = StateGraph(AgentState)
    _register(builder, "guard", guard)
    _register(builder, "orchestrator", build_orchestrator(resolved))
    for name, node in specialists.items():
        _register(builder, name, node)
    _register(builder, "human", build_human(resolved))
    _register(builder, "commit", build_commit(resolved))
    _register(builder, "respond", build_respond(resolved))
    _register(builder, "error_handler", build_error_handler(resolved))

    builder.add_edge(START, "guard")
    builder.add_conditional_edges(
        "guard", route_guard, {"orchestrator": "orchestrator", "respond": "respond"}
    )
    # Every other hop is a `Command(goto=...)` returned by the node itself, which keeps
    # the routing decision next to the state that produced it rather than split across
    # a predicate function a reader has to go and find.
    builder.add_edge("respond", END)

    compiled = builder.compile(checkpointer=checkpointer) if checkpointer else builder.compile()
    log.info(
        "graph compiled checkpointer=%s skills=%s",
        type(checkpointer).__name__ if checkpointer else "none",
        ",".join(resolved.registry.names()),
    )
    return compiled


def _register(builder: StateGraph[AgentState, Any, Any, Any], name: str, node: Any) -> None:
    """Attach a node.

    ``node: Any`` is the one concession to LangGraph's typing. Its node protocols are
    parameterised on the state type in a position mypy resolves to ``Never`` for a
    ``TypedDict`` state, so a precisely-typed callable is reported as a mismatch at every
    ``add_node`` call. Confining the loosening to this helper keeps ``--strict``
    meaningful everywhere else instead of scattering suppressions through the builder.
    """
    builder.add_node(name, node)


def _with_fixed_model(deps: GraphDependencies, fixed: BaseChatModel) -> GraphDependencies:
    """Replace the model factory with one that always returns ``fixed``.

    Per-skill temperature and token limits are discarded on purpose: when a caller
    supplies a concrete model it has already decided how that model behaves, and
    silently rebuilding it from skill frontmatter would make a test's stub unusable.
    """
    from dataclasses import replace

    def factory(
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_output_tokens: int = 2048,
    ) -> BaseChatModel:
        del model, temperature, max_output_tokens
        return fixed

    return replace(deps, model_factory=factory)
