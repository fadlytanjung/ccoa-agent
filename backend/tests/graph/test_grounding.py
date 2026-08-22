"""Grounding — REQ-090, docs/05 §3.2.

Runtime grounding is best-effort prompt adherence; what is *enforced* is that a citation
can only name a record the graph actually fetched. These tests hold that line, and they
check that the prompt the model receives really does carry the evidence and the focus
it is told to rely on.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.domain import ids
from app.graph import prompts
from app.graph.builder import build_graph
from app.graph.deps import GraphDependencies
from app.graph.state import initial_state
from tests.conftest import run_config
from tests.graph.test_graph import classification
from tests.stub_model import StubModel


def run(deps: GraphDependencies, message: str, actor: Any, thread: str = "g") -> Any:
    graph = build_graph(checkpointer=MemorySaver(), deps=deps)
    return graph.invoke(initial_state(message), run_config(actor, thread))


class TestCitations:
    def test_citations_are_a_subset_of_gathered_evidence(
        self, deps: GraphDependencies, stub_model: StubModel, agent_actor: Any
    ) -> None:
        stub_model.script_structured(classification("customer_lookup", customer_hint="CUST-000042"))
        stub_model.script("John Tan (`customer:CUST-000042`) holds `policy:POL-00000073`.")

        out = run(deps, "Show me CUST-000042.", agent_actor)
        gathered = {e["ref"] for e in out["evidence"]}
        assert set(out["citations"]) <= gathered
        assert "customer:CUST-000042" in out["citations"]

    def test_an_invented_identifier_never_becomes_a_citation(
        self, deps: GraphDependencies, stub_model: StubModel, agent_actor: Any
    ) -> None:
        stub_model.script_structured(classification("customer_lookup", customer_hint="CUST-000042"))
        # The model asserts a claim that was never fetched.
        stub_model.script("John Tan (`customer:CUST-000042`) has claim `claim:CLM-99999999` open.")

        out = run(deps, "Show me CUST-000042.", agent_actor)
        assert "claim:CLM-99999999" not in out["citations"]
        assert "customer:CUST-000042" in out["citations"]

    def test_every_identifier_in_an_answer_is_traceable(
        self, deps: GraphDependencies, stub_model: StubModel, agent_actor: Any
    ) -> None:
        """The check CI would run against a real transcript."""
        stub_model.script_structured(classification("customer_lookup", customer_hint="CUST-000042"))
        stub_model.script(
            "John Tan (`customer:CUST-000042`) holds `policy:POL-00000073` and "
            "`policy:POL-00000081`."
        )

        out = run(deps, "Show me CUST-000042.", agent_actor)
        gathered = {e["ref"] for e in out["evidence"]}
        for identifier in ids.extract_ids(out["answer"]):
            assert ids.to_ref(identifier) in gathered

    def test_no_evidence_means_no_citations(
        self, deps: GraphDependencies, stub_model: StubModel, agent_actor: Any
    ) -> None:
        stub_model.script_structured(classification("smalltalk"))
        stub_model.script("I can look up customers and claims.")
        out = run(deps, "what can you do?", agent_actor)
        assert out["citations"] == []
        assert out["evidence"] == []


class TestPromptAssembly:
    def test_the_evidence_block_reaches_the_model(
        self, deps: GraphDependencies, stub_model: StubModel, agent_actor: Any
    ) -> None:
        stub_model.script_structured(classification("customer_lookup", customer_hint="CUST-000042"))
        stub_model.script("Answer.")
        run(deps, "Show me CUST-000042.", agent_actor)

        text = stub_model.all_prompt_text()
        assert prompts.EVIDENCE_HEADING in text
        assert "customer:CUST-000042" in text

    def test_the_focus_block_names_the_confirmed_subject(
        self, deps: GraphDependencies, stub_model: StubModel, agent_actor: Any
    ) -> None:
        """Without this, a disambiguated answer re-offers the rejected candidate."""
        stub_model.script_structured(classification("customer_lookup", customer_hint="CUST-000042"))
        stub_model.script("Answer.")
        run(deps, "Show me CUST-000042.", agent_actor)

        assert "already confirmed" in stub_model.all_prompt_text()

    def test_classification_does_not_see_the_evidence(
        self, deps: GraphDependencies, stub_model: StubModel, agent_actor: Any
    ) -> None:
        """Evidence is for answering, not for deciding what was asked."""
        stub_model.script_structured(classification("customer_lookup", customer_hint="CUST-000042"))
        stub_model.script("Answer.")
        run(deps, "Show me CUST-000042.", agent_actor)

        first_prompt = "\n".join(str(m.content) for m in stub_model.prompts[0])
        assert prompts.EVIDENCE_HEADING not in first_prompt
        assert prompts.SPECIALISTS_HEADING in first_prompt

    def test_a_specialist_never_sees_the_conversation(
        self, deps: GraphDependencies, stub_model: StubModel, agent_actor: Any
    ) -> None:
        """The injection boundary: a specialist reads its brief, not the chat."""
        secret = "zzz-unique-phrase-from-the-user"
        stub_model.script_structured(
            classification("interaction_review", customer_hint="CUST-000042")
        )
        stub_model.script("Specialist summary.", "Answer.")
        run(deps, f"Summarise their contacts. {secret}", agent_actor)

        # The history specialist's prompt is the second one built.
        specialist_prompt = "\n".join(str(m.content) for m in stub_model.prompts[1])
        assert prompts.BRIEF_HEADING in specialist_prompt
        assert secret not in specialist_prompt


class TestEvidenceConstruction:
    def test_evidence_is_stored_per_record(
        self, deps: GraphDependencies, stub_model: StubModel, agent_actor: Any
    ) -> None:
        stub_model.script_structured(classification("customer_lookup", customer_hint="John Tan"))
        out = run(deps, "Show me John Tan.", agent_actor)

        refs = [e["ref"] for e in out["evidence"]]
        assert refs == ["customer:CUST-000042", "customer:CUST-000091"]
        # Each entry holds its own record, so citing one does not implicitly cite both.
        assert out["evidence"][0]["result"]["customer_id"] == "CUST-000042"
        assert out["evidence"][1]["result"]["customer_id"] == "CUST-000091"

    def test_a_refetched_record_does_not_duplicate(
        self, deps: GraphDependencies, stub_model: StubModel, agent_actor: Any
    ) -> None:
        stub_model.script_structured(classification("customer_lookup", customer_hint="John Tan"))
        graph = build_graph(checkpointer=MemorySaver(), deps=deps)
        config = run_config(agent_actor, "dedupe")
        graph.invoke(initial_state("Show me John Tan."), config)

        stub_model.script("Answer.")
        out = graph.invoke(Command(resume={"kind": "clarify", "selection": "CUST-000042"}), config)

        refs = [e["ref"] for e in out["evidence"]]
        assert refs.count("customer:CUST-000042") == 1

    def test_a_failed_tool_call_produces_no_evidence(self, toolbox: Any) -> None:
        from app.graph.evidence import from_result

        result = toolbox.get_customer("CUST-999999")
        assert from_result("get_customer", {"customer_id": "CUST-999999"}, result) == []

    def test_arguments_are_summarised_without_free_text(self) -> None:
        from app.graph.evidence import summarise_args

        summary = summarise_args({"customer_id": "CUST-000042", "query": "John Tan"})
        assert "CUST-000042" in summary
        # A free-text query can contain a customer's name; it is never echoed.
        assert "John Tan" not in summary
