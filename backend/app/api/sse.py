"""Server-sent events for a graph turn — docs/06 §3.4.

The stream is one-directional, so SSE rather than a WebSocket: no upgrade handshake to
get through the ALB, and native reconnect in the browser.

The important property is that **the stream always terminates cleanly**. Whatever
happens inside the graph — an interrupt, an exception, a cancelled client — the
generator emits a terminal `done` event, because a client waiting on a stream that
simply stops has no way to tell a hang from a completion.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import AIMessageChunk
from langgraph.graph.state import CompiledStateGraph

from app.graph.evidence import summarise_args
from app.graph.messages import content_text
from app.telemetry import get_logger, get_trace_id

log = get_logger(__name__)

#: What each node is doing, in words a support agent would use. Deliberately not the
#: node names: "investigator" is our vocabulary, not theirs.
NODE_LABELS: dict[str, str] = {
    "guard": "Checking the request",
    "orchestrator": "Working out what you need",
    "profile": "Looking up the customer",
    "history": "Reading past contacts",
    "investigator": "Investigating",
    "resolution": "Drafting",
    "human": "Waiting for you",
    "commit": "Saving",
    "respond": "Writing the answer",
    "error_handler": "Recovering",
}

#: Nodes whose model output is streamed to the user. Everything else runs silently —
#: an agent does not want the investigator's internal reasoning arriving token by token.
STREAMING_NODES = frozenset({"respond"})

#: `updates` drives progress and tool events; `messages` streams the final answer's
#: tokens. Deliberately not `values`, which would resend the whole state on every step.
#: A **list**, not a tuple: LangGraph decides whether to emit `(mode, chunk)` pairs by
#: checking for a list, and a tuple silently gets treated as a single mode.
STREAM_MODES: list[Literal["updates", "messages"]] = ["updates", "messages"]


@dataclass(frozen=True, slots=True)
class SseEvent:
    event: str
    data: dict[str, Any]

    def render(self) -> dict[str, str]:
        return {"event": self.event, "data": json.dumps(self.data, default=str)}


def _tool_events(update: dict[str, Any]) -> list[SseEvent]:
    events: list[SseEvent] = []
    for item in update.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        events.append(
            SseEvent(
                "tool",
                {
                    "name": item.get("source"),
                    "args_summary": summarise_args(item.get("args") or {}),
                    "ok": True,
                    "ref": item.get("ref"),
                },
            )
        )
    return events


def _interrupt_event(payload: Any) -> SseEvent:
    value = getattr(payload, "value", payload)
    if not isinstance(value, dict):
        value = {"question": str(value)}
    return SseEvent(
        "approval_required",
        {
            "kind": value.get("kind", "clarify"),
            "question": value.get("question", ""),
            "options": value.get("options"),
            "payload": value.get("payload"),
            "evidence_refs": value.get("evidence_refs", []),
            "skippable": bool(value.get("skippable")),
        },
    )


async def stream_turn(
    graph: CompiledStateGraph[Any, Any, Any, Any],
    graph_input: Any,
    config: Any,
    *,
    thread_id: str,
) -> AsyncIterator[dict[str, str]]:
    """Run one turn and translate LangGraph's stream into the API's event taxonomy."""
    trace_id = get_trace_id()
    yield SseEvent("trace", {"trace_id": trace_id, "thread_id": thread_id}).render()

    status = "complete"
    seen_nodes: set[str] = set()

    try:
        stream: AsyncIterator[Any] = graph.astream(graph_input, config, stream_mode=STREAM_MODES)
        async for part in stream:
            # With more than one stream mode, LangGraph yields `(mode, chunk)` pairs.
            # The declared return type is broader than that, so the shape is checked
            # rather than assumed — an unexpected shape should not kill the stream.
            if not (isinstance(part, tuple) and len(part) == 2):
                continue
            stream_mode, chunk = part
            if stream_mode == "messages":
                message, metadata = chunk
                node = str((metadata or {}).get("langgraph_node", ""))
                # Only incremental chunks. LangGraph also emits the completed message
                # on the same channel, and forwarding both would render the answer
                # twice — once in pieces and once whole.
                streamable = node in STREAMING_NODES and isinstance(message, AIMessageChunk)
                if streamable and (text := content_text(getattr(message, "content", ""))):
                    yield SseEvent("token", {"text": text}).render()
                continue

            for node, update in (chunk or {}).items():
                if node == "__interrupt__":
                    status = "interrupted"
                    yield _interrupt_event(
                        update[0] if isinstance(update, list | tuple) and update else update
                    ).render()
                    continue

                if node not in seen_nodes:
                    seen_nodes.add(node)
                    yield SseEvent(
                        "step", {"node": node, "label": NODE_LABELS.get(node, node)}
                    ).render()

                if not isinstance(update, dict):
                    continue

                for event in _tool_events(update):
                    yield event.render()

                if answer := update.get("answer"):
                    yield SseEvent(
                        "message",
                        {
                            "message_id": f"msg_{trace_id}",
                            "content": answer,
                            "citations": update.get("citations") or [],
                        },
                    ).render()

    except Exception as exc:  # the stream must terminate cleanly, whatever happened
        log.exception("graph run failed", thread_id=thread_id)
        status = "error"
        yield SseEvent(
            "error",
            {
                "code": "graph_failed",
                "message": "The assistant could not complete this turn.",
                "trace_id": trace_id,
                "retryable": True,
                "kind": exc.__class__.__name__,
            },
        ).render()

    yield SseEvent("done", {"status": status}).render()
