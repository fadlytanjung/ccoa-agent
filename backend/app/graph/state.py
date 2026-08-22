"""Graph state and its reducers — docs/05 §3.2.

The field that does the most work is ``evidence``. Every tool result lands there with a
stable ``ref``, and the answer may assert nothing that is not in it. That is what turns
"the assistant should not make things up" from an instruction into something a test can
check.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

Intent = Literal[
    "customer_lookup",
    "interaction_review",
    "case_investigation",
    "ticket_creation",
    "escalation",
    "smalltalk",
    "unknown",
]

AskKind = Literal["clarify", "confirm", "approve", "steer"]

#: Which specialist handles each intent. The graph owns this mapping, not the model —
#: docs/05 §3.4.
INTENT_TO_AGENT: dict[str, str] = {
    "customer_lookup": "profile",
    "interaction_review": "history",
    "case_investigation": "investigator",
    "ticket_creation": "resolution",
    "escalation": "resolution",
}


class Evidence(TypedDict):
    """One fact the answer is allowed to assert."""

    ref: str
    source: str
    args: dict[str, Any]
    result: dict[str, Any]
    at: str


class AgentReport(TypedDict):
    """What a specialist hands back to the orchestrator."""

    agent: str
    summary: str
    complete: bool
    refs: list[str]


class HumanAsk(TypedDict, total=False):
    """A pending question for the human. One at a time."""

    kind: AskKind
    question: str
    options: list[dict[str, str]]
    payload: dict[str, Any]
    evidence_refs: list[str]
    skippable: bool


class Proposal(TypedDict):
    """A drafted mutation, awaiting approval.

    ``rendered`` is what the human sees and what ``commit`` writes — the model is not
    consulted between approval and write, so it cannot alter what was agreed.
    """

    action: Literal["create_ticket", "escalate_case"]
    summary: str
    rendered: str
    payload: dict[str, Any]
    required_group: str
    evidence_refs: list[str]


class ApprovalDecision(TypedDict, total=False):
    approved: bool
    note: str
    actor_sub: str
    at: str


class ToolErrorState(TypedDict, total=False):
    error_class: str
    code: str
    message: str
    node: str
    retry_after_seconds: float


#: Reducer convention: an explicit ``None`` **resets** the field, while ``[]`` is a
#: no-op append. Accumulating reducers otherwise have no way to be cleared — assigning
#: an empty list just appends nothing — and a field that cannot be cleared is a field
#: that leaks across conversation turns.
RESET = None


def append_evidence(
    existing: list[Evidence] | None, incoming: list[Evidence] | None
) -> list[Evidence]:
    """Append, de-duplicating by ``ref``, keeping the first occurrence.

    De-duplication is not tidiness. A customer re-fetched three times during an
    investigation would otherwise appear three times in the prompt, inflating context
    and making the grounding block harder for the model to read. First-wins because the
    earliest fetch is the one the rest of the reasoning was built on.
    """
    if incoming is RESET:
        return []
    merged = list(existing or [])
    seen = {item["ref"] for item in merged}
    for item in incoming or []:
        if item["ref"] not in seen:
            seen.add(item["ref"])
            merged.append(item)
    return merged


def merge_reports(
    existing: list[AgentReport] | None, incoming: list[AgentReport] | None
) -> list[AgentReport]:
    """Accumulate specialist reports within a turn; reset between turns.

    This reducer is the reason ``guard`` exists as more than a validator. With plain
    concatenation, reports from turn one survive into turn two, the orchestrator sees
    work already done, and every later turn short-circuits to an answer without ever
    delegating. That failure is silent and looks like a bad model.
    """
    if incoming is RESET:
        return []
    return [*(existing or []), *incoming]


def merge_attempt_counts(
    existing: dict[str, int] | None, incoming: dict[str, int] | None
) -> dict[str, int]:
    """Sum per-node retry counters.

    Summed rather than replaced so a retry budget survives a loop back through the
    orchestrator — otherwise a node could retry twice, route away, come back, and retry
    twice more, forever.
    """
    merged = dict(existing or {})
    for node, count in (incoming or {}).items():
        merged[node] = merged.get(node, 0) + count
    return merged


def replace_preferences(
    existing: dict[str, bool] | None, incoming: dict[str, bool] | None
) -> dict[str, bool]:
    """Thread-scoped preferences, last write wins per key."""
    return {**(existing or {}), **(incoming or {})}


class AgentState(TypedDict, total=False):
    """The whole conversation, as the graph sees it.

    Note what is *absent*: the actor and the trace id. Those are properties of the
    caller, not of the conversation, and live in ``config["configurable"]`` so a resumed
    run cannot inherit a stale identity (docs/05 §3.2).
    """

    messages: Annotated[list[AnyMessage], add_messages]

    intent: Intent | None
    intent_confidence: float
    rationale: str

    # Conversational focus. Carried across turns, which is what lets "create a ticket
    # for this issue" resolve without repeating who the customer is.
    subject_customer_id: str | None
    focus_case_id: str | None
    focus_claim_id: str | None
    #: The raw name or email the classifier spotted, kept separately from
    #: ``subject_customer_id`` because "John Tan" is a search term, not a subject.
    customer_hint: str | None
    #: Candidate matches awaiting disambiguation. Non-empty means the graph asked.
    candidates: list[dict[str, Any]]

    evidence: Annotated[list[Evidence], append_evidence]

    active_agent: str | None
    delegation_brief: str | None
    agent_reports: Annotated[list[AgentReport], merge_reports]

    pending_ask: HumanAsk | None
    human_reply: dict[str, Any] | None
    proposal: Proposal | None
    approval: ApprovalDecision | None
    preferences: Annotated[dict[str, bool], replace_preferences]

    error: ToolErrorState | None
    attempts: Annotated[dict[str, int], merge_attempt_counts]

    # Set once the answer has been composed, so the API can emit it as a `message`
    # event with its citations attached.
    answer: str | None
    citations: list[str]


def initial_state(message: str) -> AgentState:
    """The input for a new turn: the message, and nothing else.

    Per-turn fields are reset by the ``guard`` node rather than here, so a caller that
    forgets to reset something cannot corrupt the turn — see :func:`merge_reports`.
    """
    from langchain_core.messages import HumanMessage

    return AgentState(messages=[HumanMessage(content=message)])


#: Cleared at the start of every turn by ``guard``. Conversational focus
#: (``subject_customer_id``, ``focus_case_id``, ``preferences``) is deliberately *not*
#: here: carrying it is what lets "create a ticket for this issue" resolve without
#: repeating who the customer is.
TURN_SCOPED_RESET: dict[str, Any] = {
    "intent": None,
    "intent_confidence": 0.0,
    "rationale": "",
    "agent_reports": RESET,
    "active_agent": None,
    "delegation_brief": None,
    "customer_hint": None,
    "pending_ask": None,
    "human_reply": None,
    "proposal": None,
    "approval": None,
    "error": None,
    "answer": None,
    "citations": [],
}


def evidence_refs(state: AgentState) -> list[str]:
    return [item["ref"] for item in state.get("evidence") or []]


def latest_user_message(state: AgentState) -> str:
    """The most recent thing the human said, or an empty string."""
    for message in reversed(state.get("messages") or []):
        if message.type == "human":
            return str(message.content)
    return ""
