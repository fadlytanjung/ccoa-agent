"""Reducers and routing predicates — pure functions, no I/O (docs/05 §3.12)."""

from __future__ import annotations

from app.graph.nodes.errors import should_retry
from app.graph.nodes.orchestrator import decide
from app.graph.state import (
    RESET,
    AgentState,
    Evidence,
    ToolErrorState,
    append_evidence,
    merge_attempt_counts,
    merge_reports,
    replace_preferences,
)


def evidence(ref: str, source: str = "get_customer") -> Evidence:
    return Evidence(ref=ref, source=source, args={}, result={"id": ref}, at="2026-08-21T00:00:00Z")


class TestAppendEvidence:
    def test_appends(self) -> None:
        result = append_evidence([evidence("customer:CUST-000001")], [evidence("claim:CLM-1")])
        assert [item["ref"] for item in result] == ["customer:CUST-000001", "claim:CLM-1"]

    def test_deduplicates_by_ref_keeping_the_first(self) -> None:
        first = evidence("customer:CUST-000001", source="search_customer")
        second = evidence("customer:CUST-000001", source="get_customer")
        result = append_evidence([first], [second])
        assert len(result) == 1
        # First-wins: the earliest fetch is what the rest of the reasoning was built on.
        assert result[0]["source"] == "search_customer"

    def test_reset_clears(self) -> None:
        assert append_evidence([evidence("customer:CUST-000001")], RESET) == []


class TestMergeReports:
    def test_accumulates_within_a_turn(self) -> None:
        first = [{"agent": "profile", "summary": "a", "complete": True, "refs": []}]
        second = [{"agent": "history", "summary": "b", "complete": True, "refs": []}]
        assert len(merge_reports(first, second)) == 2  # type: ignore[arg-type]

    def test_reset_clears_between_turns(self) -> None:
        existing = [{"agent": "profile", "summary": "a", "complete": True, "refs": []}]
        # Without this, turn two sees turn one's work already done and never delegates.
        assert merge_reports(existing, RESET) == []  # type: ignore[arg-type]


class TestMergeAttemptCounts:
    def test_sums_per_node(self) -> None:
        assert merge_attempt_counts({"profile": 1}, {"profile": 1, "history": 2}) == {
            "profile": 2,
            "history": 2,
        }

    def test_budget_survives_a_loop(self) -> None:
        counts: dict[str, int] = {}
        for _ in range(3):
            counts = merge_attempt_counts(counts, {"investigator": 1})
        assert counts["investigator"] == 3


def test_replace_preferences_merges_per_key() -> None:
    assert replace_preferences({"a": True}, {"b": False}) == {"a": True, "b": False}
    assert replace_preferences({"a": True}, {"a": False}) == {"a": False}


class TestRouting:
    def test_error_wins(self) -> None:
        state = AgentState(error=ToolErrorState(code="x"), intent="customer_lookup")
        assert decide(state, min_confidence=0.6) == "error_handler"

    def test_low_confidence_never_guesses(self) -> None:
        state = AgentState(intent="case_investigation", intent_confidence=0.4)
        assert decide(state, min_confidence=0.6) == "clarify"

    def test_mutation_without_a_subject_is_a_non_starter(self) -> None:
        state = AgentState(intent="ticket_creation", intent_confidence=1.0)
        assert decide(state, min_confidence=0.6) == "clarify"

    def test_mutation_with_a_subject_proceeds(self) -> None:
        state = AgentState(
            intent="ticket_creation", intent_confidence=1.0, subject_customer_id="CUST-000042"
        )
        assert decide(state, min_confidence=0.6) == "resolution"

    def test_intents_map_to_specialists(self) -> None:
        cases = {
            "customer_lookup": "profile",
            "interaction_review": "history",
            "case_investigation": "investigator",
        }
        for intent, node in cases.items():
            state = AgentState(
                intent=intent,  # type: ignore[typeddict-item]
                intent_confidence=1.0,
                subject_customer_id="CUST-000042",
            )
            assert decide(state, min_confidence=0.6) == node

    def test_a_finished_specialist_routes_to_the_answer(self) -> None:
        state = AgentState(
            intent="customer_lookup",
            intent_confidence=1.0,
            agent_reports=[{"agent": "profile", "summary": "s", "complete": True, "refs": []}],
        )
        assert decide(state, min_confidence=0.6) == "respond"

    def test_a_proposal_always_goes_to_the_human(self) -> None:
        state = AgentState(
            intent="ticket_creation",
            intent_confidence=1.0,
            subject_customer_id="CUST-000042",
            proposal={  # type: ignore[typeddict-item]
                "action": "create_ticket",
                "summary": "s",
                "rendered": "r",
                "payload": {},
                "required_group": "agent",
                "evidence_refs": [],
            },
        )
        assert decide(state, min_confidence=0.6) == "human"


class TestRetryPolicy:
    def test_transient_retries_within_budget(self) -> None:
        state = AgentState(
            error=ToolErrorState(error_class="transient", node="profile"),
            attempts={"profile": 1},
        )
        assert should_retry(state) is True

    def test_transient_stops_at_the_budget(self) -> None:
        state = AgentState(
            error=ToolErrorState(error_class="transient", node="profile"),
            attempts={"profile": 3},
        )
        assert should_retry(state) is False

    def test_not_found_is_never_retried(self) -> None:
        state = AgentState(
            error=ToolErrorState(error_class="not_found", node="profile"), attempts={}
        )
        assert should_retry(state) is False

    def test_forbidden_is_never_retried(self) -> None:
        state = AgentState(
            error=ToolErrorState(error_class="forbidden", node="commit"), attempts={}
        )
        assert should_retry(state) is False
