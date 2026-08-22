"""Orchestrator and response nodes — docs/05 §3.1, §3.4.

The orchestrator owns the conversation. It classifies, delegates, absorbs specialist
reports, and decides when the human should be involved. Specialists report back to it;
they never hand off to each other and never talk to the user.

Routing decisions the model does not get a vote on live in :func:`decide` — low
confidence never silently guesses a workflow, and a mutation with no established subject
is a non-starter.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.agents.registry import SkillRegistry
from app.domain import clock, ids
from app.graph import prompts
from app.graph.deps import GraphDependencies
from app.graph.messages import message_text
from app.graph.state import (
    INTENT_TO_AGENT,
    RESET,
    AgentState,
    HumanAsk,
    Intent,
    ToolErrorState,
    evidence_refs,
    latest_user_message,
)

log = logging.getLogger(__name__)

ORCHESTRATOR_SKILL = "orchestrator"


class Classification(BaseModel):
    """Structured output, not free text — so routing is on a value, not on a parse."""

    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    customer_hint: str | None = Field(
        default=None, description="Name, email, or customer ID mentioned in the request."
    )
    case_hint: str | None = Field(default=None, description="Case or claim ID mentioned.")
    brief: str = Field(description="What the specialist should do, and for whom.")
    rationale: str = Field(description="Why this intent, in one sentence.")


def _clarify_ask(question: str, options: list[dict[str, str]] | None = None) -> HumanAsk:
    ask = HumanAsk(kind="clarify", question=question, skippable=False)
    if options:
        ask["options"] = options
    return ask


def decide(state: AgentState, *, min_confidence: float) -> str:
    """Where to go next. Pure, so the routing rules are unit-testable (docs/05 §3.12)."""
    if state.get("error"):
        return "error_handler"

    # A decided approval means commit already ran, or the human said no. Either way the
    # next thing that happens is an answer, not more work.
    if state.get("approval") is not None:
        return "respond"

    if state.get("proposal") is not None:
        return "human"

    if state.get("pending_ask") is not None:
        return "human"

    if state.get("agent_reports"):
        return "respond"

    intent = state.get("intent")
    if intent in (None, "smalltalk", "unknown"):
        return "respond"

    if (state.get("intent_confidence") or 0.0) < min_confidence:
        return "clarify"

    # "Create a ticket for this issue" is only meaningful with a subject already in
    # state from an earlier turn — the reference scenario's exact sequence.
    if intent in ("ticket_creation", "escalation") and not state.get("subject_customer_id"):
        return "clarify"

    return INTENT_TO_AGENT.get(str(intent), "respond")


def _hint_updates(classification: Classification, state: AgentState) -> dict[str, Any]:
    """Promote identifiers the model spotted into conversational focus."""
    updates: dict[str, Any] = {}

    hint = (classification.customer_hint or "").strip()
    if hint:
        if ids.is_valid(hint, "CUST"):
            updates["subject_customer_id"] = hint
        else:
            # A name or an email is a *search term*, not a subject. Keeping the two
            # apart is what lets the profile specialist search for "John Tan" and then
            # ask which one, rather than treating the name as an established identity.
            updates["customer_hint"] = hint

    case_hint = (classification.case_hint or "").strip()
    if case_hint:
        if ids.is_valid(case_hint, "CASE"):
            updates["focus_case_id"] = case_hint
        elif ids.is_valid(case_hint, "CLM"):
            updates["focus_claim_id"] = case_hint

    # Focus persists across turns unless replaced, which is what lets "create a ticket
    # for this issue" resolve without repeating who or what.
    for key in ("subject_customer_id", "focus_case_id", "focus_claim_id"):
        updates.setdefault(key, state.get(key))
    return updates


def build_orchestrator(
    deps: GraphDependencies,
) -> Callable[[AgentState, RunnableConfig], Command[Any]]:
    registry: SkillRegistry = deps.registry
    min_confidence = deps.settings.min_intent_confidence

    def orchestrator(state: AgentState, config: RunnableConfig) -> Command[Any]:
        del config  # actor and trace id are read by nodes that need them

        # Already classified this turn, or nothing to classify: route on what is there.
        if state.get("intent") is not None or state.get("error") or state.get("agent_reports"):
            return Command(goto=decide(state, min_confidence=min_confidence))

        skill = registry.get(ORCHESTRATOR_SKILL)
        model = deps.model_factory(
            model=skill.frontmatter.model,
            temperature=skill.frontmatter.temperature,
            max_output_tokens=skill.frontmatter.max_output_tokens,
        )

        try:
            classification = model.with_structured_output(Classification).invoke(
                prompts.classification_prompt(skill, registry.descriptions(), state)
            )
        except Exception as exc:  # noqa: BLE001 — classified and routed, never raised
            log.warning("classification failed: %s", exc)
            return Command(
                goto="error_handler",
                update={
                    "error": ToolErrorState(
                        error_class="transient",
                        code="classification_failed",
                        message=str(exc),
                        node="orchestrator",
                    ),
                    "attempts": {"orchestrator": 1},
                },
            )

        assert isinstance(classification, Classification)
        hints = _hint_updates(classification, state)
        update: dict[str, Any] = {
            "intent": classification.intent,
            "intent_confidence": classification.confidence,
            "rationale": classification.rationale,
            "delegation_brief": classification.brief,
            **hints,
        }

        # Switching customers mid-thread invalidates everything gathered about the
        # previous one. Leaving it would let an answer cite the wrong person's claim
        # while looking perfectly grounded (docs/05 §6 question 3).
        previous = state.get("subject_customer_id")
        if previous and hints.get("subject_customer_id") not in (previous, None):
            log.info("subject changed from %s; clearing evidence", previous)
            update["evidence"] = RESET

        target = decide({**state, **update}, min_confidence=min_confidence)  # type: ignore[typeddict-item]
        if target == "clarify":
            update["pending_ask"] = _clarify_ask(_clarify_question(state, classification))
            target = "human"
        else:
            update["active_agent"] = target if target in INTENT_TO_AGENT.values() else None

        log.info(
            "classified intent=%s confidence=%.2f -> %s",
            classification.intent,
            classification.confidence,
            target,
        )
        return Command(goto=target, update=update)

    return orchestrator


def _clarify_question(state: AgentState, classification: Classification) -> str:
    """Ask about the thing that is actually missing.

    A generic "could you clarify?" costs a turn and gets a repeat of the same sentence.
    """
    if classification.intent in ("ticket_creation", "escalation") and not state.get(
        "subject_customer_id"
    ):
        return "Which customer is this for? I do not have one established in this conversation yet."
    return (
        f"I read that as {classification.intent.replace('_', ' ')}, but I am not "
        f"confident. What would you like me to do?"
    )


def build_respond(
    deps: GraphDependencies,
) -> Callable[[AgentState, RunnableConfig], dict[str, Any]]:
    """Compose the grounded answer — the only node that writes user-facing prose."""
    registry = deps.registry

    def respond(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        del config

        if error := state.get("error"):
            # A guard rejection or a terminal failure is answered without a model call:
            # there is nothing to compose, and spending a call to phrase an error is
            # latency the user pays for nothing.
            return {
                "answer": error.get("message", ""),
                "citations": [],
                "messages": [AIMessage(content=error.get("message", ""))],
                "error": None,
            }

        skill = registry.get(ORCHESTRATOR_SKILL)
        model = deps.model_factory(
            model=skill.frontmatter.model,
            # A little warmth in the final answer; nothing factual depends on sampling
            # because the facts come from the evidence block (docs/05 §3.9).
            temperature=0.3,
            max_output_tokens=skill.frontmatter.max_output_tokens,
        )

        try:
            message = model.invoke(
                prompts.orchestrator_prompt(
                    skill, registry.descriptions(), state, include_menu=False
                )
            )
            answer = message_text(message)
        except Exception as exc:  # noqa: BLE001 — degrade to the evidence, never fail
            log.warning("response composition failed: %s", exc)
            answer = _fallback_answer(state)

        return {
            "answer": answer,
            # Citations are computed from what the answer actually mentions and
            # intersected with the evidence, so a hallucinated identifier cannot become
            # a citation (docs/05 §3.2).
            "citations": _citations(answer, state),
            "messages": [AIMessage(content=answer)],
            "active_agent": None,
            "delegation_brief": None,
        }

    return respond


def _citations(answer: str, state: AgentState) -> list[str]:
    gathered = set(evidence_refs(state))
    cited: list[str] = []
    for identifier in ids.extract_ids(answer):
        ref = ids.to_ref(identifier)
        if ref and ref in gathered and ref not in cited:
            cited.append(ref)
    return cited


def _fallback_answer(state: AgentState) -> str:
    """If the model fails after evidence was gathered, show the evidence.

    Degradation is preferred to failure, and the user is told which they got — a
    silently degraded answer is a correctness bug, not a resilience feature.
    """
    refs = evidence_refs(state)
    reports = state.get("agent_reports") or []
    lines = ["I could not compose a written answer, so here is what I found."]
    lines.extend(f"- {report['summary']}" for report in reports)
    if refs:
        lines.append("")
        lines.append("Records: " + ", ".join(f"`{ref}`" for ref in refs))
    if not reports and not refs:
        lines.append(f"Nothing was found for: {latest_user_message(state)[:200]}")
    lines.append("")
    lines.append(f"_Composed without the model at {clock.now()}._")
    return "\n".join(lines)
