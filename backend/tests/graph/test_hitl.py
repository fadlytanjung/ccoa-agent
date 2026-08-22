"""Human-in-the-loop — docs/05 §3.7.

The property under test is not "an approval modal appears". It is that a mutation
without approval is **unrepresentable**, that authorisation is checked on the resuming
actor, and that every outcome — approved, rejected, denied — leaves an audit row.
"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.domain.actor import Actor
from app.graph.builder import build_graph
from app.graph.deps import GraphDependencies
from app.graph.nodes.human import resolve_candidate
from app.graph.nodes.specialists import WIDE_READ_THRESHOLD, TicketDraft
from app.graph.state import initial_state
from tests.conftest import run_config
from tests.graph.test_graph import classification
from tests.stub_model import StubModel


def ticket_draft() -> TicketDraft:
    return TicketDraft(
        title="Manual document review for CLM-00000117",
        problem="The claim has failed submission three times with DOC_UNREADABLE.",
        next_action="Route to the Claims Document Support queue for manual review.",
        category="claim_issue",  # type: ignore[arg-type]
        priority="high",  # type: ignore[arg-type]
        already_attempted=["Re-upload after guidance"],
    )


def propose_ticket(
    deps: GraphDependencies, stub_model: StubModel, actor: Actor, thread: str
) -> tuple[Any, dict[str, Any], Any]:
    graph = build_graph(checkpointer=MemorySaver(), deps=deps)
    config = run_config(actor, thread)

    stub_model.script_structured(classification("customer_lookup", customer_hint="CUST-000042"))
    stub_model.script("Found them.")
    graph.invoke(initial_state("Show me CUST-000042."), config)

    stub_model.script_structured(
        classification("ticket_creation", case_hint="CASE-000008"), ticket_draft()
    )
    out = graph.invoke(initial_state("Create a ticket for this issue."), config)
    return graph, config, out


class TestResolveCandidate:
    @pytest.mark.parametrize(
        ("reply", "expected"),
        [
            ({"selection": "CUST-000091"}, "CUST-000091"),
            ({"text": "the one in Tampines, CUST-000042"}, "CUST-000042"),
            ({"text": "the second one"}, "CUST-000091"),
            ({"text": "who handled the last call?"}, None),
            ({}, None),
        ],
    )
    def test_matches_a_reply_to_a_candidate(
        self, reply: dict[str, Any], expected: str | None
    ) -> None:
        candidates = [{"customer_id": "CUST-000042"}, {"customer_id": "CUST-000091"}]
        assert resolve_candidate(reply, candidates) == expected


class TestClarify:
    def test_a_selection_resolves_and_the_specialist_resumes(
        self, deps: GraphDependencies, stub_model: StubModel, agent_actor: Actor
    ) -> None:
        graph = build_graph(checkpointer=MemorySaver(), deps=deps)
        config = run_config(agent_actor)

        stub_model.script_structured(classification("customer_lookup", customer_hint="John Tan"))
        graph.invoke(initial_state("Show me John Tan."), config)

        stub_model.script("John Tan, gold tier.")
        out = graph.invoke(Command(resume={"kind": "clarify", "selection": "CUST-000042"}), config)

        assert out["subject_customer_id"] == "CUST-000042"
        assert out["candidates"] == []
        assert out["answer"] == "John Tan, gold tier."

    def test_an_off_script_reply_is_a_conversation_not_an_error(
        self, deps: GraphDependencies, stub_model: StubModel, agent_actor: Actor
    ) -> None:
        graph = build_graph(checkpointer=MemorySaver(), deps=deps)
        config = run_config(agent_actor)

        stub_model.script_structured(classification("customer_lookup", customer_hint="John Tan"))
        graph.invoke(initial_state("Show me John Tan."), config)

        # Answering something else entirely must be handled, not rejected.
        stub_model.script_structured(classification("smalltalk"))
        stub_model.script("I can look up customers, history, and claims.")
        out = graph.invoke(
            Command(resume={"kind": "clarify", "text": "actually, what can you do?"}),
            config,
        )
        assert out["answer"] == "I can look up customers, history, and claims."


class TestApproval:
    def test_a_proposal_pauses_before_writing_anything(
        self, deps: GraphDependencies, stub_model: StubModel, agent_actor: Actor
    ) -> None:
        _, _, out = propose_ticket(deps, stub_model, agent_actor, "t-propose")

        interrupt = out["__interrupt__"][0].value
        assert interrupt["kind"] == "approve"
        assert interrupt["skippable"] is False
        assert interrupt["payload"]["customer_id"] == "CUST-000042"
        # Nothing has been written.
        assert deps.repos.tickets.list_for_case("CASE-000008") == []

    def test_approval_writes_the_ticket_and_the_audit_row(
        self, deps: GraphDependencies, stub_model: StubModel, agent_actor: Actor
    ) -> None:
        graph, config, _ = propose_ticket(deps, stub_model, agent_actor, "t-approve")

        stub_model.script("Ticket raised.")
        out = graph.invoke(
            Command(resume={"kind": "approve", "approved": True, "note": "confirmed"}),
            config,
        )

        tickets = deps.repos.tickets.list_for_case("CASE-000008")
        assert len(tickets) == 1
        assert tickets[0].created_via.value == "assistant"
        assert tickets[0].created_by == agent_actor.email

        audit = deps.repos.audit.for_trace("trace-t-approve")
        assert [(a.action, a.outcome) for a in audit] == [("create_ticket", "allowed")]
        assert audit[0].target_id == tickets[0].ticket_id
        assert out["approval"]["approved"] is True

    def test_what_was_shown_is_what_is_written(
        self, deps: GraphDependencies, stub_model: StubModel, agent_actor: Actor
    ) -> None:
        """The model is not consulted between approval and write."""
        graph, config, out = propose_ticket(deps, stub_model, agent_actor, "t-verbatim")
        shown = out["__interrupt__"][0].value["payload"]["description"]

        stub_model.script("Done.")
        graph.invoke(Command(resume={"kind": "approve", "approved": True}), config)

        written = deps.repos.tickets.list_for_case("CASE-000008")[0]
        assert written.description == shown

    def test_rejection_writes_nothing_and_returns_to_the_conversation(
        self, deps: GraphDependencies, stub_model: StubModel, agent_actor: Actor
    ) -> None:
        graph, config, _ = propose_ticket(deps, stub_model, agent_actor, "t-reject")

        stub_model.script("Understood — what should I change?")
        out = graph.invoke(
            Command(resume={"kind": "approve", "approved": False, "note": "priority is wrong"}),
            config,
        )

        assert deps.repos.tickets.list_for_case("CASE-000008") == []
        assert out["approval"]["approved"] is False
        assert out["proposal"] is None
        # Rejection routes back into conversation, not to a dead end.
        assert out["answer"] == "Understood — what should I change?"

    def test_a_second_resume_does_not_write_twice(
        self, deps: GraphDependencies, stub_model: StubModel, agent_actor: Actor
    ) -> None:
        graph, config, _ = propose_ticket(deps, stub_model, agent_actor, "t-double")

        stub_model.script("Done.")
        graph.invoke(Command(resume={"kind": "approve", "approved": True}), config)
        stub_model.script("Nothing further.")
        graph.invoke(Command(resume={"kind": "approve", "approved": True}), config)

        assert len(deps.repos.tickets.list_for_case("CASE-000008")) == 1


class TestAuthorisationOnResume:
    def test_an_agent_cannot_escalate(
        self, deps: GraphDependencies, stub_model: StubModel, agent_actor: Actor
    ) -> None:
        from app.graph.nodes.specialists import EscalationDraft

        graph = build_graph(checkpointer=MemorySaver(), deps=deps)
        config = run_config(agent_actor, "t-denied")

        stub_model.script_structured(classification("customer_lookup", customer_hint="CUST-000042"))
        stub_model.script("Found.")
        graph.invoke(initial_state("Show me CUST-000042."), config)

        stub_model.script_structured(
            classification("escalation", case_hint="CASE-000008"),
            EscalationDraft(
                reason="It has been open for three weeks with no progress at all.",
                decision_requested="Please assign an owner.",
                escalate_to="Tier 2 Support",
                steps_taken=["Advised re-upload"],
            ),
        )
        graph.invoke(initial_state("Escalate this case."), config)

        stub_model.script("You do not have permission for that.")
        out = graph.invoke(Command(resume={"kind": "approve", "approved": True}), config)

        case = deps.repos.cases.get("CASE-000008")
        assert case is not None
        assert case.status.value == "investigating"  # unchanged

        audit = deps.repos.audit.for_trace("trace-t-denied")
        assert [(a.action, a.outcome) for a in audit] == [("escalate_case", "denied")]
        assert "supervisor" in (out["answer"] or "")

    def test_a_supervisor_can_escalate(
        self, deps: GraphDependencies, stub_model: StubModel, supervisor_actor: Actor
    ) -> None:
        from app.graph.nodes.specialists import EscalationDraft

        graph = build_graph(checkpointer=MemorySaver(), deps=deps)
        config = run_config(supervisor_actor, "t-allowed")

        stub_model.script_structured(classification("customer_lookup", customer_hint="CUST-000042"))
        stub_model.script("Found.")
        graph.invoke(initial_state("Show me CUST-000042."), config)

        stub_model.script_structured(
            classification("escalation", case_hint="CASE-000008"),
            EscalationDraft(
                reason="It has been open for three weeks with no progress at all.",
                decision_requested="Please assign an owner.",
                escalate_to="Tier 2 Support",
                steps_taken=["Advised re-upload"],
            ),
        )
        graph.invoke(initial_state("Escalate this case."), config)

        stub_model.script("Escalated.")
        graph.invoke(Command(resume={"kind": "approve", "approved": True}), config)

        case = deps.repos.cases.get("CASE-000008")
        assert case is not None
        assert case.status.value == "escalated"
        assert case.escalated_to == "Tier 2 Support"

        audit = deps.repos.audit.for_trace("trace-t-allowed")
        assert [(a.action, a.outcome) for a in audit] == [("escalate_case", "allowed")]


class TestConfirm:
    def test_a_wide_read_asks_first_and_remembers(
        self, deps: GraphDependencies, stub_model: StubModel, agent_actor: Actor
    ) -> None:
        busy = next(
            customer_id
            for customer_id in (f"CUST-{n:06d}" for n in range(1, 121))
            if deps.repos.interactions.count_for_customer(customer_id) > WIDE_READ_THRESHOLD
        )

        graph = build_graph(checkpointer=MemorySaver(), deps=deps)
        config = run_config(agent_actor, "t-confirm")

        stub_model.script_structured(classification("interaction_review", customer_hint=busy))
        out = graph.invoke(initial_state("Summarise everything."), config)

        interrupt = out["__interrupt__"][0].value
        assert interrupt["kind"] == "confirm"
        # Confirm is skippable — approve never is.
        assert interrupt["skippable"] is True

        stub_model.script("Summary.", "Answer.")
        out = graph.invoke(
            Command(resume={"kind": "confirm", "approved": True, "remember": True}), config
        )
        assert out["preferences"]["skip_confirm_wide_reads"] is True
