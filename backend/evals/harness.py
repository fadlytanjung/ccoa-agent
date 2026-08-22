"""Running an eval case against the real agent — docs/19 §3.4.

The harness replaces the throwaway scripts that were previously used to check agent
behaviour by hand. It runs a scripted conversation against the **real model** and the
**real seeded corpus**, and returns a `Trace` — everything an assertion or a judge could
want to look at.

Running against the real model is the point. A stubbed model tells you the graph is
wired correctly, which `tests/` already covers; only a real one tells you the agent is
any good.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.config import Settings
from app.db.engine import Database
from app.domain import ids
from app.domain.actor import Actor
from app.domain.enums import Group
from app.graph.builder import build_graph
from app.graph.deps import GraphDependencies
from app.graph.state import initial_state
from app.graph.tools import ToolBox
from app.repositories import Repositories
from evals.goldens import Golden


@dataclass(frozen=True, slots=True)
class Exchange:
    """One turn of the conversation, in DeepEval's `Turn` vocabulary.

    Captured as the conversation happens rather than reconstructed at the end: a turn
    that ends on a checkpoint has no answer, and its *question* is what the human
    actually saw. Reading only the final state would lose every intermediate turn.
    """

    role: str
    content: str
    tools: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RecordedCall:
    name: str
    args: dict[str, Any]
    ok: bool
    refs: tuple[str, ...]


class RecordingToolBox:
    """Wraps the toolbox so the harness sees exactly which tools ran.

    Reconstructing this from evidence would be wrong in the case that matters most: a
    tool that returns nothing — a search with no matches — produces no evidence, and
    "did it even look?" is precisely the question an eval needs to answer.
    """

    def __init__(self, inner: ToolBox) -> None:
        self._inner = inner
        self.calls: list[RecordedCall] = []

    @property
    def ctx(self) -> Any:
        return self._inner.ctx

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._inner, name)
        if not callable(attribute):
            return attribute

        def recorded(*args: Any, **kwargs: Any) -> Any:
            result = attribute(*args, **kwargs)
            self.calls.append(
                RecordedCall(
                    name=name,
                    args=dict(kwargs),
                    ok=bool(getattr(result, "ok", False)),
                    refs=tuple(getattr(result, "refs", ())),
                )
            )
            return result

        return recorded


class CountingModelFactory:
    """Counts model calls, so `min_model_calls: 0` is assertable.

    That expectation exists for one case — the guard must reject an injection attempt
    *without spending a model call* — and there is no other way to observe it.
    """

    def __init__(self, build: Callable[..., BaseChatModel]) -> None:
        self._build = build
        self.calls = 0

    def __call__(self, **kwargs: Any) -> BaseChatModel:
        self.calls += 1
        return self._build(**kwargs)


@dataclass
class Trace:
    """Everything one eval case produced."""

    case: str
    answer: str
    citations: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    #: Every identifier the agent was actually shown — the refs *and* the identifiers
    #: carried inside the records themselves. An interaction record names its case, so
    #: quoting that case is grounded even though the case was never fetched in its own
    #: right. Checking only refs would score honest answers as hallucinations.
    evidence_identifiers: set[str] = field(default_factory=set)
    tools_called: list[RecordedCall] = field(default_factory=list)
    turns: list[Exchange] = field(default_factory=list)
    interrupt: dict[str, Any] | None = None
    tickets_created: list[str] = field(default_factory=list)
    escalated_cases: list[str] = field(default_factory=list)
    audit: list[tuple[str, str]] = field(default_factory=list)
    model_calls: int = 0
    duration_seconds: float = 0.0
    state: dict[str, Any] = field(default_factory=dict)

    @property
    def tool_names(self) -> list[str]:
        return [call.name for call in self.tools_called]

    @property
    def interrupt_kind(self) -> str:
        return str(self.interrupt.get("kind")) if self.interrupt else "none"

    @property
    def wrote(self) -> str:
        if self.tickets_created:
            return "ticket"
        if self.escalated_cases:
            return "escalation"
        return "none"

    def judged_output(self) -> str:
        """What a rubric should actually be shown.

        A turn that ends on a checkpoint produces no answer — the agent asked a
        question instead. Judging `answer` there hands the rubric an empty string and
        scores a correct pause as a total failure, which is how an eval suite teaches
        you to stop asking the human.
        """
        if self.interrupt:
            parts = [str(self.interrupt.get("question", ""))]
            for option in self.interrupt.get("options") or []:
                parts.append(f"- {option.get('label', option)}")
            if payload := self.interrupt.get("payload"):
                parts.append(str(payload.get("description", "")))
            return "\n".join(p for p in parts if p).strip()
        return self.answer

    def summary(self) -> str:
        """One line for the eval report."""
        return (
            f"{self.case}: interrupt={self.interrupt_kind} "
            f"tools={','.join(self.tool_names) or '-'} "
            f"writes={self.wrote} model_calls={self.model_calls} "
            f"{self.duration_seconds:.1f}s"
        )


def _render_resume(resume: dict[str, Any] | None) -> str:
    """A resume payload, as the human's side of the conversation.

    Judged conversationally, `{"selection": "CUST-000042"}` is not a sentence. Rendering
    it as one is what lets a knowledge-retention metric see that the human answered.
    """
    payload = resume or {}
    if text := str(payload.get("text") or "").strip():
        return text
    if selection := payload.get("selection"):
        return f"That one — {selection}."
    if "approved" in payload:
        note = str(payload.get("note") or "").strip()
        decision = "Yes, go ahead." if payload.get("approved") else "No, do not do that."
        return f"{decision} {note}".strip()
    return str(payload)


def _turn_output(result: dict[str, Any]) -> str:
    """What the assistant said this turn — the answer, or the question it asked."""
    if answer := result.get("answer"):
        return str(answer)

    interrupts = result.get("__interrupt__") or []
    if interrupts:
        value = interrupts[0].value
        parts = [str(value.get("question", ""))]
        parts += [f"- {o.get('label', o)}" for o in value.get("options") or []]
        return "\n".join(p for p in parts if p).strip()
    return ""


ACTORS = {
    "agent": Actor(sub="eval-agent", email="agent@example.com", groups=(Group.AGENT,)),
    "supervisor": Actor(
        sub="eval-supervisor",
        email="supervisor@example.com",
        groups=(Group.AGENT, Group.SUPERVISOR),
    ),
}


def run_case(
    case: Golden,
    *,
    settings: Settings,
    db_path: Path,
    model_factory: Callable[..., BaseChatModel],
) -> Trace:
    """Run one scripted conversation and capture what the agent did."""
    database = Database(db_path)
    try:
        repos = Repositories.build(database)
        base = GraphDependencies.build(settings, database=database)
        recorder = RecordingToolBox(base.toolbox)
        counter = CountingModelFactory(model_factory)
        deps = replace(base, toolbox=recorder, model_factory=counter)  # type: ignore[arg-type]

        graph = build_graph(checkpointer=MemorySaver(), deps=deps)
        actor = ACTORS[case.actor]
        trace_id = f"eval-{case.name}"
        config = {
            "configurable": {
                "thread_id": trace_id,
                "actor": actor.to_config(),
                "trace_id": trace_id,
            }
        }

        tickets_before = {t.ticket_id for t in repos.tickets.list_for_customer("CUST-000042")}

        started = time.monotonic()
        result: dict[str, Any] = {}
        turns: list[Exchange] = []
        seen_calls = 0

        for step in case.conversation:
            if step.message is not None:
                payload: Any = initial_state(step.message)
                turns.append(Exchange(role="user", content=step.message))
            else:
                payload = Command(resume=step.resume)
                turns.append(Exchange(role="user", content=_render_resume(step.resume)))

            result = graph.invoke(payload, config)

            # Tools attributed to the turn that actually ran them.
            new_calls = tuple(c.name for c in recorder.calls[seen_calls:])
            seen_calls = len(recorder.calls)
            turns.append(Exchange(role="assistant", content=_turn_output(result), tools=new_calls))
        duration = time.monotonic() - started

        evidence = result.get("evidence") or []
        shown = set(ids.extract_ids(json.dumps(evidence, default=str)))

        interrupts = result.get("__interrupt__") or []
        interrupt = dict(interrupts[0].value) if interrupts else None

        tickets_after = {t.ticket_id for t in repos.tickets.list_for_customer("CUST-000042")}
        escalated = [
            c.case_id
            for c in repos.cases.list_for_customer("CUST-000042")
            if c.status.value == "escalated"
        ]

        return Trace(
            case=case.name,
            answer=result.get("answer") or "",
            citations=list(result.get("citations") or []),
            evidence_refs=[e["ref"] for e in evidence],
            evidence_identifiers=shown,
            tools_called=recorder.calls,
            turns=turns,
            interrupt=interrupt,
            tickets_created=sorted(tickets_after - tickets_before),
            escalated_cases=escalated,
            audit=[(a.action, a.outcome) for a in repos.audit.for_trace(trace_id)],
            model_calls=counter.calls,
            duration_seconds=duration,
            state={
                "subject_customer_id": result.get("subject_customer_id"),
                "intent": result.get("intent"),
            },
        )
    finally:
        database.dispose()
