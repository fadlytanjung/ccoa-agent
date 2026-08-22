"""The tool surface — docs/05 §3.8.

Two contracts are worth more than the rest and are tested hardest: a tool never raises,
and a search never guesses.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.domain.errors import ErrorClass
from app.graph.tools import ToolBox, dispatch
from app.graph.tools.toolbox import MUTATING_TOOL_NAMES, READ_TOOL_NAMES


class TestSearchReturnsCandidates:
    def test_an_ambiguous_name_returns_every_match(self, toolbox: ToolBox) -> None:
        result = toolbox.search_customer("John Tan")
        assert result.ok
        assert result.data is not None
        assert result.data["match_count"] == 2
        assert result.data["ambiguous"] is True
        assert {m["customer_id"] for m in result.data["matches"]} == {
            "CUST-000042",
            "CUST-000091",
        }

    def test_matches_carry_the_details_that_distinguish_them(self, toolbox: ToolBox) -> None:
        matches = (toolbox.search_customer("John Tan").data or {})["matches"]
        for match in matches:
            assert match["tier"] and match["city"]
            assert match["policy_count"] >= 0

    def test_an_identifier_search_returns_one(self, toolbox: ToolBox) -> None:
        result = toolbox.search_customer("CUST-000042")
        assert (result.data or {})["match_count"] == 1

    def test_no_match_is_a_valid_answer_not_an_error(self, toolbox: ToolBox) -> None:
        result = toolbox.search_customer("Nobody Whatsoever")
        assert result.ok
        assert (result.data or {})["match_count"] == 0

    def test_a_wildcard_is_matched_literally(self, toolbox: ToolBox) -> None:
        # Without escaping, '%' would match every customer in the corpus.
        result = toolbox.search_customer("%")
        assert (result.data or {})["match_count"] == 0


class TestIdentifierValidation:
    @pytest.mark.parametrize(
        ("tool", "args"),
        [
            ("get_customer", {"customer_id": "nope"}),
            ("get_customer", {"customer_id": "CUST-42"}),
            ("get_claim", {"claim_id": "CLM-123"}),
            ("get_case", {"case_id": "CASE-1"}),
            ("list_claims", {"customer_id": "12345"}),
        ],
    )
    def test_a_malformed_identifier_never_reaches_a_query(
        self, toolbox: ToolBox, tool: str, args: dict[str, Any]
    ) -> None:
        result = dispatch(toolbox, tool, args)
        assert not result.ok
        assert result.error is not None
        assert result.error.error_class is ErrorClass.INVALID_INPUT

    def test_a_well_formed_but_absent_identifier_is_not_found(self, toolbox: ToolBox) -> None:
        result = toolbox.get_customer("CUST-999999")
        assert not result.ok
        assert result.error is not None
        assert result.error.error_class is ErrorClass.NOT_FOUND
        assert result.error.retryable is False


class TestReads:
    def test_get_customer_includes_policies(self, toolbox: ToolBox) -> None:
        result = toolbox.get_customer("CUST-000042")
        assert result.ok
        data = result.data or {}
        assert data["customer"]["full_name"] == "John Tan"
        assert len(data["policies"]) == 2
        assert "policy:POL-00000073" in result.refs

    def test_interactions_report_the_window(self, toolbox: ToolBox) -> None:
        result = toolbox.list_interactions("CUST-000042", limit=3)
        data = result.data or {}
        assert data["returned"] == 3
        assert data["total_available"] == 7
        # The model must know it is looking at a window, or it will summarise three of
        # seven contacts as though they were all of them.
        assert data["truncated"] is True

    def test_interactions_omit_transcripts_by_default(self, toolbox: ToolBox) -> None:
        rows = (toolbox.list_interactions("CUST-000042").data or {})["interactions"]
        assert rows and all("transcript" not in row for row in rows)

    def test_the_failed_claim_carries_its_code(self, toolbox: ToolBox) -> None:
        data = toolbox.get_claim("CLM-00000117").data or {}
        assert data["status"] == "submission_failed"
        assert data["failure_code"] == "DOC_UNREADABLE"
        assert data["failure_detail"]

    def test_a_case_states_whether_it_has_tickets(self, toolbox: ToolBox) -> None:
        data = toolbox.get_case("CASE-000008").data or {}
        assert data["has_tickets"] is False
        assert len(data["interaction_ids"]) == 3

    def test_kb_search_finds_the_remediation_article(self, toolbox: ToolBox) -> None:
        data = toolbox.search_kb("DOC_UNREADABLE").data or {}
        assert data["articles"][0]["article_id"] == "KB-0031"
        assert data["retrieval_method"] == "keyword"

    def test_search_is_scoped_to_one_customer(self, toolbox: ToolBox) -> None:
        data = toolbox.search_interactions("CUST-000091", "upload").data or {}
        # Cross-customer leakage is impossible by construction, not by filtering.
        assert all(h["interaction_id"] for h in data["hits"])
        assert data["customer_id"] == "CUST-000091"

    def test_retrieval_method_is_always_reported(self, toolbox: ToolBox) -> None:
        data = toolbox.search_interactions("CUST-000042", "upload").data or {}
        assert data["retrieval_method"] in ("keyword", "semantic")


class TestToolBoundary:
    def test_a_tool_returns_errors_rather_than_raising(self, toolbox: ToolBox) -> None:
        class Exploding:
            def search(self, *_: Any, **__: Any) -> None:
                raise RuntimeError("the database fell over")

        object.__setattr__(toolbox.ctx.repos, "customers", Exploding())
        result = toolbox.search_customer("anything")
        assert not result.ok
        assert result.error is not None
        assert result.error.error_class is ErrorClass.INTERNAL

    def test_dispatch_refuses_an_unknown_tool(self, toolbox: ToolBox) -> None:
        result = dispatch(toolbox, "definitely_not_a_tool", {})
        assert not result.ok

    def test_dispatch_refuses_a_mutating_tool(self, toolbox: ToolBox) -> None:
        """Mutating tools are unreachable from the model's dispatch path."""
        for name in MUTATING_TOOL_NAMES:
            result = dispatch(toolbox, name, {})
            assert not result.ok

    def test_mutations_are_never_bindable(self) -> None:
        assert not (READ_TOOL_NAMES & MUTATING_TOOL_NAMES)


class TestReferences:
    def test_a_skill_can_read_its_own_reference(self, toolbox: ToolBox) -> None:
        result = toolbox.read_reference("investigator", "references/failure-codes.md")
        assert result.ok
        assert "GATEWAY_TIMEOUT" in (result.data or {})["content"]

    def test_traversal_is_refused_and_reported(self, toolbox: ToolBox) -> None:
        result = toolbox.read_reference("investigator", "../../secrets")
        assert not result.ok
        assert result.error is not None
        assert result.error.code == "reference_unavailable"
