"""The human checkpoint and the commit node — docs/05 §3.7.

One ``interrupt()``, four kinds of ask. The pause is a **checkpoint, not a held
connection**: the SSE stream closes, the browser can be refreshed and the task replaced,
and the pending ask still resolves against persisted state.

``commit`` is the only node in the graph that writes. Everything that mutates funnels
through here, which means there is exactly one place to authorise and exactly one place
to audit, however many specialists exist.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt

from app.domain import clock
from app.domain.actor import Actor
from app.graph.deps import GraphDependencies
from app.graph.evidence import from_result
from app.graph.state import AgentState, ApprovalDecision, Evidence, ToolErrorState
from app.graph.tools.mutations import MUTATIONS

log = logging.getLogger(__name__)

CONFIRMED_WIDE_READ = "confirmed_wide_read"


def _actor(config: RunnableConfig) -> Actor:
    raw = (config.get("configurable") or {}).get("actor")
    return Actor.from_config(raw) or Actor(sub="unknown")


def _trace_id(config: RunnableConfig) -> str:
    return str((config.get("configurable") or {}).get("trace_id") or "unknown")


def _thread_id(config: RunnableConfig) -> str | None:
    value = (config.get("configurable") or {}).get("thread_id")
    return str(value) if value else None


def resolve_candidate(reply: dict[str, Any], candidates: list[dict[str, Any]]) -> str | None:
    """Match a free-form reply to one of the offered candidates.

    Accepts an explicit selection, a customer ID typed out, or an ordinal ("the second
    one"). Returns ``None`` when the reply does not resolve — which is not an error:
    the human said something else, and that is allowed (docs/05 §3.7 rule 1).
    """
    if not candidates:
        return None

    ids_ = [str(c.get("customer_id")) for c in candidates]

    selection = str(reply.get("selection") or "").strip()
    if selection in ids_:
        return selection

    text = str(reply.get("text") or "").strip()
    if not text:
        return None

    for customer_id in ids_:
        if customer_id.lower() in text.lower():
            return customer_id

    lowered = text.lower()
    for index, word in enumerate(("first", "second", "third", "fourth")):
        if word in lowered and index < len(ids_):
            return ids_[index]

    return None


def build_human(deps: GraphDependencies) -> Callable[[AgentState, RunnableConfig], Command[Any]]:
    del deps  # the checkpoint needs no dependencies; that is the point

    def human(state: AgentState, config: RunnableConfig) -> Command[Any]:
        del config
        ask = state.get("pending_ask")
        if ask is None:
            # Nothing to ask. Reachable if a specialist routed here without setting an
            # ask; falling through to the orchestrator beats deadlocking the thread.
            return Command(goto="orchestrator")

        reply = interrupt(
            {
                "kind": ask.get("kind"),
                "question": ask.get("question"),
                "options": ask.get("options"),
                "payload": ask.get("payload"),
                "evidence_refs": ask.get("evidence_refs")
                or [item["ref"] for item in state.get("evidence") or []],
                "skippable": bool(ask.get("skippable")),
            }
        )

        payload = reply if isinstance(reply, dict) else {"text": str(reply)}
        kind = str(payload.get("kind") or ask.get("kind") or "clarify")
        log.info("human replied to a %s checkpoint", kind)

        if kind == "approve":
            return _handle_approval(state, payload)
        if kind == "confirm":
            return _handle_confirm(state, payload)
        return _handle_free_reply(state, payload)

    return human


def _handle_approval(state: AgentState, payload: dict[str, Any]) -> Command[Any]:
    approved = bool(payload.get("approved"))
    decision = ApprovalDecision(
        approved=approved,
        note=str(payload.get("note") or ""),
        at=clock.now(),
    )
    if approved:
        return Command(goto="commit", update={"approval": decision, "pending_ask": None})

    # Rejection routes back into the conversation, not to a dead end: the human usually
    # says why, and the next thing they want is a redraft (docs/05 §3.7 rule 4).
    note = str(payload.get("note") or "").strip()
    update: dict[str, Any] = {
        "approval": decision,
        "pending_ask": None,
        "proposal": None,
        "agent_reports": [
            {
                "agent": "resolution",
                "summary": f"The proposal was rejected. {note}".strip(),
                "complete": True,
                "refs": [],
            }
        ],
    }
    if note:
        update["messages"] = [HumanMessage(content=note)]
    return Command(goto="orchestrator", update=update)


def _handle_confirm(state: AgentState, payload: dict[str, Any]) -> Command[Any]:
    approved = bool(payload.get("approved"))
    preferences: dict[str, bool] = {CONFIRMED_WIDE_READ: approved}

    # "Don't ask me that again" is thread-scoped and remembered. Someone handling forty
    # calls a day should not answer the same question forty times (docs/05 §3.7 rule 2).
    if payload.get("remember"):
        preferences["skip_confirm_wide_reads"] = True

    update: dict[str, Any] = {"pending_ask": None, "preferences": preferences}
    if text := str(payload.get("text") or "").strip():
        update["messages"] = [HumanMessage(content=text)]

    return Command(goto=state.get("active_agent") or "orchestrator", update=update)


def _handle_free_reply(state: AgentState, payload: dict[str, Any]) -> Command[Any]:
    """A ``clarify`` or ``steer`` reply — free text, possibly a selection."""
    text = str(payload.get("text") or "").strip()
    update: dict[str, Any] = {"pending_ask": None}
    if text:
        update["messages"] = [HumanMessage(content=text)]

    if chosen := resolve_candidate(payload, state.get("candidates") or []):
        # The ambiguity is settled; go straight back to the specialist that asked.
        update["subject_customer_id"] = chosen
        update["candidates"] = []
        return Command(goto=state.get("active_agent") or "orchestrator", update=update)

    # Anything else is treated as a fresh turn. Clearing the intent means the reply is
    # classified on its own terms, so answering an unrelated question mid-checkpoint
    # gets an answer rather than a validation error.
    update["intent"] = None
    update["intent_confidence"] = 0.0
    update["agent_reports"] = []
    return Command(goto="orchestrator", update=update)


def build_commit(deps: GraphDependencies) -> Callable[[AgentState, RunnableConfig], Command[Any]]:
    """The only writer. Authorise, mutate, and audit, in one transaction."""

    def commit(state: AgentState, config: RunnableConfig) -> Command[Any]:
        proposal = state.get("proposal")
        if proposal is None:
            return Command(goto="orchestrator", update={"pending_ask": None})

        actor = _actor(config)
        action = proposal["action"]
        mutate = MUTATIONS[action]

        # Authorisation is re-checked here, on the **resuming** actor. The proposer's
        # identity does not carry over — that is why the actor lives in config rather
        # than in checkpointed state (docs/05 §3.2).
        result = mutate(
            deps.toolbox.ctx,
            deps.audit,
            actor=actor,
            trace_id=_trace_id(config),
            thread_id=_thread_id(config),
            payload=dict(proposal["payload"]),
        )

        if not result.ok:
            error = result.error
            assert error is not None
            return Command(
                goto="respond",
                update={
                    "proposal": None,
                    "error": ToolErrorState(
                        error_class=error.error_class.value,
                        code=error.code,
                        message=error.message,
                        node="commit",
                    ),
                },
            )

        evidence: list[Evidence] = from_result(action, dict(proposal["payload"]), result)
        target = result.refs[0] if result.refs else action
        return Command(
            goto="orchestrator",
            update={
                "proposal": None,
                "evidence": evidence,
                "agent_reports": [
                    {
                        "agent": "commit",
                        "summary": f"{action} completed: {target}",
                        "complete": True,
                        "refs": list(result.refs),
                    }
                ],
            },
        )

    return commit
