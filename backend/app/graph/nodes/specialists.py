"""The four specialists — docs/05 §3.3.

Each reads its ``delegation_brief`` and the shared evidence, appends its own findings,
and returns an ``AgentReport`` to the orchestrator. None of them sees the raw message
history, and none of them talks to the user.

The split between deterministic and model-driven is the point (docs/05 §3.6): a customer
lookup has a known plan and does not need a model to invent one, while an investigation's
plan depends on what it finds.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.domain.enums import Category, Priority
from app.graph import evidence as evidence_builder
from app.graph import prompts
from app.graph.deps import GraphDependencies
from app.graph.messages import message_text
from app.graph.state import (
    AgentReport,
    AgentState,
    Evidence,
    HumanAsk,
    Proposal,
    ToolErrorState,
)
from app.graph.tools import ToolResult, bind_tools_for, dispatch
from app.graph.tools.mutations import REQUIRED_GROUP

log = logging.getLogger(__name__)

#: Above this, reading a customer's whole history is worth a sentence of confirmation
#: first. Below it, asking costs more than it saves.
#:
#: Ten, not twenty: the corpus's long tail peaks at twelve contacts per customer
#: (docs/12 §3.5), so a threshold of twenty made this checkpoint unreachable — a
#: declared behaviour that could never fire. `tests/graph/test_hitl.py` exercises it.
WIDE_READ_THRESHOLD = 10
CONFIRMED_WIDE_READ = "confirmed_wide_read"

#: How many times one tool may run in a single investigation. Deduplicating identical
#: calls is not enough: the observed failure was the same search repeated with reworded
#: queries, which is thrash that looks like progress. Two, because a genuine
#: investigation searches the knowledge base once per failure code and a second call is
#: already a rephrase.
MAX_CALLS_PER_TOOL = 2


def _report(agent: str, summary: str, refs: list[str], *, complete: bool = True) -> AgentReport:
    return AgentReport(agent=agent, summary=summary, complete=complete, refs=refs)


def _run(
    deps: GraphDependencies, name: str, args: dict[str, Any]
) -> tuple[ToolResult, list[Evidence]]:
    result = dispatch(deps.toolbox, name, args)
    return result, evidence_builder.from_result(name, args, result)


def _needs_subject(agent: str) -> Command[Any]:
    """Every specialist except profile needs a subject before it can do anything."""
    return Command(
        goto="human",
        update={
            "pending_ask": HumanAsk(
                kind="clarify",
                question="Which customer is this about?",
                skippable=False,
            ),
            "active_agent": agent,
        },
    )


# ---------------------------------------------------------------------------
# profile — deterministic
# ---------------------------------------------------------------------------
def build_profile(deps: GraphDependencies) -> Callable[[AgentState, RunnableConfig], Command[Any]]:
    def profile(state: AgentState, config: RunnableConfig) -> Command[Any]:
        del config
        evidence: list[Evidence] = []
        subject = state.get("subject_customer_id")

        if not subject:
            query = (state.get("customer_hint") or state.get("delegation_brief") or "").strip()
            if not query:
                return _needs_subject("profile")

            result, found = _run(deps, "search_customer", {"query": query})
            evidence.extend(found)
            if not result.ok:
                return _fail("profile", result, evidence)

            matches = (result.data or {}).get("matches", [])
            if not matches:
                return Command(
                    goto="orchestrator",
                    update={
                        "evidence": evidence,
                        "agent_reports": [
                            _report(
                                "profile",
                                f"No customer matches {query!r}.",
                                [],
                            )
                        ],
                    },
                )

            if len(matches) > 1:
                # Never auto-select. Two people named John Tan is the reason this
                # branch exists, and picking the richer record would be a guess
                # dressed as helpfulness (docs/04 §3.6 rule 1).
                return Command(
                    goto="human",
                    update={
                        "evidence": evidence,
                        "candidates": matches,
                        "active_agent": "profile",
                        "pending_ask": _disambiguation_ask(query, matches),
                    },
                )

            subject = str(matches[0]["customer_id"])

        result, found = _run(deps, "get_customer", {"customer_id": subject})
        evidence.extend(found)
        if not result.ok:
            return _fail("profile", result, evidence)

        data = result.data or {}
        customer = data.get("customer", {})
        policies = data.get("policies", [])
        active = [p for p in policies if p.get("status") == "active"]
        summary = (
            f"{customer.get('full_name')} ({subject}), {customer.get('tier')} tier, "
            f"{customer.get('status')}. {len(policies)} polic"
            f"{'y' if len(policies) == 1 else 'ies'}, {len(active)} active. "
            f"{data.get('open_case_count', 0)} open case(s)."
        )

        return Command(
            goto="orchestrator",
            update={
                "evidence": evidence,
                "subject_customer_id": subject,
                "candidates": [],
                "agent_reports": [_report("profile", summary, [e["ref"] for e in evidence])],
            },
        )

    return profile


def _disambiguation_ask(query: str, matches: list[dict[str, Any]]) -> HumanAsk:
    options = [
        {
            "value": str(m["customer_id"]),
            # The distinguishing detail is what makes this answerable in one word.
            "label": (
                f"{m['full_name']} — {m['customer_id']}, {m['tier']} tier, "
                f"{m['city']}, {m['policy_count']} polic"
                f"{'y' if m['policy_count'] == 1 else 'ies'}"
            ),
        }
        for m in matches
    ]
    return HumanAsk(
        kind="clarify",
        question=f"{len(matches)} customers match {query!r}. Which one is on the call?",
        options=options,
        skippable=False,
    )


def _fail(agent: str, result: ToolResult, evidence: list[Evidence]) -> Command[Any]:
    error = result.error
    assert error is not None
    return Command(
        goto="error_handler",
        update={
            "evidence": evidence,
            "error": ToolErrorState(
                error_class=error.error_class.value,
                code=error.code,
                message=error.message,
                node=agent,
            ),
            "attempts": {agent: 1},
        },
    )


# ---------------------------------------------------------------------------
# history — deterministic retrieval, model summarisation
# ---------------------------------------------------------------------------
def build_history(deps: GraphDependencies) -> Callable[[AgentState, RunnableConfig], Command[Any]]:
    registry = deps.registry

    def history(state: AgentState, config: RunnableConfig) -> Command[Any]:
        del config
        subject = state.get("subject_customer_id")
        if not subject:
            return _needs_subject("history")

        skill = registry.get("history")
        preferences = state.get("preferences") or {}
        total = deps.repos.interactions.count_for_customer(subject)

        if (
            total > WIDE_READ_THRESHOLD
            and not preferences.get(CONFIRMED_WIDE_READ)
            and skill.checkpoint_for("confirm") is not None
        ):
            return Command(
                goto="human",
                update={
                    "active_agent": "history",
                    "pending_ask": HumanAsk(
                        kind="confirm",
                        question=(
                            f"This customer has {total} recorded contacts. "
                            f"Shall I read all of them, or just the recent ones?"
                        ),
                        options=[
                            {"value": "all", "label": f"Read all {total}"},
                            {"value": "recent", "label": "Just the last 10"},
                        ],
                        # Skippable: an agent handling forty calls a day should be able
                        # to say "stop asking" and have it stick (docs/05 §3.7).
                        skippable=True,
                    ),
                },
            )

        limit = 50 if preferences.get(CONFIRMED_WIDE_READ) else 10
        brief = state.get("delegation_brief") or ""
        topic = _topic_from(brief)

        if topic:
            result, evidence = _run(
                deps,
                "search_interactions",
                {"customer_id": subject, "query": topic, "limit": min(limit, 10)},
            )
        else:
            result, evidence = _run(
                deps, "list_interactions", {"customer_id": subject, "limit": limit}
            )

        if not result.ok:
            return _fail("history", result, evidence)

        method = (result.data or {}).get("retrieval_method", "chronological")
        summary = _summarise(deps, skill, state, evidence, brief)

        return Command(
            goto="orchestrator",
            update={
                "evidence": evidence,
                "agent_reports": [
                    _report(
                        "history",
                        summary,
                        [e["ref"] for e in evidence],
                    )
                ],
                "preferences": {"retrieval_degraded": method == "keyword"},
            },
        )

    return history


def _already_gathered(name: str, gathered: list[Evidence]) -> ToolResult:
    """Answer a capped tool with what it has already produced.

    Returned as a *successful* result rather than an error: the model has not done
    anything wrong, it has simply asked again, and an error would invite a retry.
    """
    refs = [e["ref"] for e in gathered if e["source"] == name]
    return ToolResult.success(
        {
            "capped": True,
            "tool": name,
            "already_found": refs,
            "note": "This tool has already run enough times in this investigation. "
            "Use what you have, or say what you could not determine.",
        }
    )


def _topic_from(brief: str) -> str | None:
    """Extract a topic from the brief, if the orchestrator named one.

    Deliberately crude: a brief that mentions a subject worth searching for says so in
    plain words, and guessing harder produces worse queries, not better ones.
    """
    lowered = brief.lower()
    for marker in (" about ", " regarding ", " concerning ", " related to "):
        if marker in lowered:
            topic = brief[lowered.index(marker) + len(marker) :].strip(" .")
            return topic or None
    return None


def _summarise(
    deps: GraphDependencies,
    skill: Any,
    state: AgentState,
    evidence: list[Evidence],
    brief: str,
) -> str:
    """One model call, using the history skill, to turn rows into a briefing."""
    model = deps.model_factory(
        model=skill.frontmatter.model,
        temperature=skill.frontmatter.temperature,
        max_output_tokens=skill.frontmatter.max_output_tokens,
    )
    scoped: AgentState = {**state, "evidence": evidence}
    try:
        message = model.invoke(prompts.specialist_prompt(skill, scoped, brief=brief))
        return message_text(message).strip()
    except Exception as exc:  # noqa: BLE001 — degrade to counts, never lose the retrieval
        log.warning("history summarisation failed: %s", exc)
        return f"Retrieved {len(evidence)} interactions; could not summarise them ({exc})."


# ---------------------------------------------------------------------------
# investigator — bounded agentic loop
# ---------------------------------------------------------------------------
def build_investigator(
    deps: GraphDependencies,
) -> Callable[[AgentState, RunnableConfig], Command[Any]]:
    registry = deps.registry

    def investigator(state: AgentState, config: RunnableConfig) -> Command[Any]:
        del config
        subject = state.get("subject_customer_id")
        if not subject:
            return _needs_subject("investigator")

        skill = registry.get("investigator")
        limits = skill.frontmatter.limits
        model = deps.model_factory(
            model=skill.frontmatter.model,
            temperature=skill.frontmatter.temperature,
            max_output_tokens=skill.frontmatter.max_output_tokens,
        ).bind_tools(bind_tools_for(deps.toolbox, skill.tools, skill="investigator"))

        gathered: list[Evidence] = []
        distinct_tools: set[str] = set()
        # Identical calls are answered from what was already fetched. Without this the
        # model re-runs the same search two or three times inside one investigation,
        # spending iterations from a budget of six on results it has already seen.
        answered: dict[str, ToolResult] = {}
        calls_per_tool: dict[str, int] = {}
        started = time.monotonic()
        conversation = list(
            prompts.specialist_prompt(skill, state, brief=state.get("delegation_brief") or "")
        )
        summary = ""
        complete = False

        for iteration in range(limits.max_iterations):
            elapsed = time.monotonic() - started
            if elapsed > limits.wall_clock_seconds:
                log.info("investigation budget spent after %.1fs", elapsed)
                break

            try:
                message = model.invoke(conversation)
            except Exception as exc:  # noqa: BLE001 — partial findings beat a failure
                log.warning("investigator model call failed: %s", exc)
                summary = f"The investigation stopped early: {exc}"
                break

            conversation.append(message)
            calls = getattr(message, "tool_calls", None) or []

            if not calls:
                summary = message_text(message).strip()
                complete = True
                break

            # Parallel fan-out is useful; unbounded fan-out is not.
            for call in calls[: limits.max_parallel_tools]:
                name = str(call.get("name"))
                args = dict(call.get("args") or {})

                # The bound `StructuredTool` is only how the model learns the schema —
                # execution comes back through this loop, so anything the graph injects
                # has to be injected *here* as well. Binding it in one place and not the
                # other is what made every `read_reference` call fail with a missing
                # argument while the binding itself tested fine in isolation.
                if name == "read_reference":
                    args.setdefault("skill", "investigator")

                signature = f"{name}:{sorted(args.items())}"

                found: list[Evidence]
                if calls_per_tool.get(name, 0) >= MAX_CALLS_PER_TOOL:
                    log.info("tool %s hit its per-investigation cap", name)
                    result, found = _already_gathered(name, gathered), []
                elif signature in answered:
                    log.info("repeat tool call %s answered from earlier result", name)
                    result, found = answered[signature], []
                else:
                    result, found = _run(deps, name, args)
                    answered[signature] = result
                    calls_per_tool[name] = calls_per_tool.get(name, 0) + 1
                gathered.extend(found)
                distinct_tools.add(name)
                conversation.append(
                    ToolMessage(
                        content=str(result.as_payload()),
                        tool_call_id=str(call.get("id") or f"{name}-{iteration}"),
                    )
                )

            if len(distinct_tools) >= deps.settings.max_distinct_tools:
                # Re-querying the same surface with tweaked arguments is thrashing, not
                # investigating. Force a summary rather than letting it continue.
                log.info("forcing summarisation after %d distinct tools", len(distinct_tools))
                conversation.append(HumanMessage(content=_FORCE_SUMMARY))
                try:
                    final = model.invoke(conversation)
                    summary = message_text(final).strip()
                    complete = True
                except Exception as exc:  # noqa: BLE001
                    log.warning("forced summarisation failed: %s", exc)
                break

        if not summary:
            summary = (
                f"The investigation did not reach a conclusion within its budget. "
                f"{len(gathered)} records were gathered."
            )

        # An incomplete investigation is reported as incomplete. A partial answer with
        # its gaps named is useful; a partial answer presented as whole is not.
        return Command(
            goto="orchestrator",
            update={
                "evidence": gathered,
                "agent_reports": [
                    _report(
                        "investigator",
                        summary,
                        [e["ref"] for e in gathered],
                        complete=complete,
                    )
                ],
            },
        )

    return investigator


#: Short instruction, not a prompt: it names a stopping condition the graph enforces.
_FORCE_SUMMARY = "Stop gathering. State what you found and what you could not determine."


# ---------------------------------------------------------------------------
# resolution — drafts, never writes
# ---------------------------------------------------------------------------
class TicketDraft(BaseModel):
    title: str = Field(min_length=4, max_length=200)
    problem: str = Field(min_length=20)
    next_action: str = Field(min_length=10)
    category: Category
    priority: Priority
    already_attempted: list[str] = Field(default_factory=list)


class EscalationDraft(BaseModel):
    reason: str = Field(min_length=20)
    decision_requested: str = Field(min_length=10)
    escalate_to: str = Field(min_length=2, max_length=120)
    priority: Priority = Priority.HIGH
    steps_taken: list[str] = Field(default_factory=list)


def build_resolution(
    deps: GraphDependencies,
) -> Callable[[AgentState, RunnableConfig], Command[Any]]:
    registry = deps.registry

    def resolution(state: AgentState, config: RunnableConfig) -> Command[Any]:
        actor_email = _actor_email(config)
        subject = state.get("subject_customer_id")
        if not subject:
            return _needs_subject("resolution")

        skill = registry.get("resolution")
        evidence: list[Evidence] = []

        customer_result, found = _run(deps, "get_customer", {"customer_id": subject})
        evidence.extend(found)
        if not customer_result.ok:
            return _fail("resolution", customer_result, evidence)
        customer = (customer_result.data or {}).get("customer", {})

        case, case_evidence = _resolve_case(deps, state, subject)
        evidence.extend(case_evidence)

        claim, claim_evidence = _resolve_claim(deps, state, case)
        evidence.extend(claim_evidence)

        escalating = state.get("intent") == "escalation"
        model = deps.model_factory(
            model=skill.frontmatter.model,
            temperature=skill.frontmatter.temperature,
            max_output_tokens=skill.frontmatter.max_output_tokens,
        )
        merged = [*(state.get("evidence") or []), *evidence]
        scoped: AgentState = {**state, "evidence": merged}
        messages = prompts.specialist_prompt(
            skill, scoped, brief=state.get("delegation_brief") or ""
        )

        try:
            if escalating:
                proposal = _draft_escalation(
                    deps, model, skill, messages, customer, case, evidence, actor_email
                )
            else:
                proposal = _draft_ticket(
                    deps, model, skill, messages, customer, case, claim, evidence, actor_email
                )
        except _DraftError as exc:
            return Command(
                goto="orchestrator",
                update={
                    "evidence": evidence,
                    "agent_reports": [_report("resolution", str(exc), [], complete=False)],
                },
            )

        return Command(
            goto="human",
            update={
                "evidence": evidence,
                "active_agent": "resolution",
                "proposal": proposal,
                "pending_ask": HumanAsk(
                    kind="approve",
                    question=proposal["summary"],
                    payload=dict(proposal["payload"]),
                    evidence_refs=proposal["evidence_refs"],
                    skippable=False,
                ),
            },
        )

    return resolution


class _DraftError(RuntimeError):
    """The draft could not be produced. Reported, never raised into the graph."""


def _actor_email(config: RunnableConfig) -> str:
    actor = (config.get("configurable") or {}).get("actor") or {}
    return str(actor.get("email") or actor.get("sub") or "unknown")


def _resolve_case(
    deps: GraphDependencies, state: AgentState, subject: str
) -> tuple[dict[str, Any] | None, list[Evidence]]:
    """Find the case this is about — the focused one, or the single open one."""
    if case_id := state.get("focus_case_id"):
        result, evidence = _run(deps, "get_case", {"case_id": case_id})
        return ((result.data or {}).get("case") if result.ok else None), evidence

    result, evidence = _run(deps, "list_cases", {"customer_id": subject, "status": "open"})
    cases = (result.data or {}).get("cases", []) if result.ok else []
    # Exactly one open case is unambiguous. Two is a question, and the orchestrator's
    # clarify path is the right place for it, not a guess here.
    return (cases[0] if len(cases) == 1 else None), evidence


def _resolve_claim(
    deps: GraphDependencies, state: AgentState, case: dict[str, Any] | None
) -> tuple[dict[str, Any] | None, list[Evidence]]:
    claim_id = state.get("focus_claim_id") or (case or {}).get("claim_id")
    if not claim_id:
        return None, []
    result, evidence = _run(deps, "get_claim", {"claim_id": claim_id})
    return (result.data if result.ok else None), evidence


def _draft_ticket(
    deps: GraphDependencies,
    model: Any,
    skill: Any,
    messages: list[Any],
    customer: dict[str, Any],
    case: dict[str, Any] | None,
    claim: dict[str, Any] | None,
    evidence: list[Evidence],
    actor_email: str,
) -> Proposal:
    try:
        draft = model.with_structured_output(TicketDraft).invoke(messages)
    except Exception as exc:
        raise _DraftError(f"I could not draft a ticket: {exc}") from exc
    assert isinstance(draft, TicketDraft)

    rendered = deps.registry.render(
        "resolution",
        "templates/ticket-draft.md.j2",
        {
            "customer": customer,
            "case": case,
            "claim": claim,
            "priority": draft.priority.value,
            "category": draft.category.value,
            "problem": draft.problem,
            "next_action": draft.next_action,
            "already_attempted": draft.already_attempted,
            "evidence": _evidence_lines(evidence),
            "actor_email": actor_email,
        },
    )

    payload = {
        "customer_id": customer.get("customer_id"),
        "case_id": (case or {}).get("case_id"),
        "title": draft.title,
        # The description the human approves is the description that gets written.
        "description": rendered,
        "category": draft.category.value,
        "priority": draft.priority.value,
    }
    return Proposal(
        action="create_ticket",
        summary=f"Create a {draft.priority.value} ticket: {draft.title}",
        rendered=rendered,
        payload=payload,
        required_group=REQUIRED_GROUP["create_ticket"],
        evidence_refs=[e["ref"] for e in evidence],
    )


def _draft_escalation(
    deps: GraphDependencies,
    model: Any,
    skill: Any,
    messages: list[Any],
    customer: dict[str, Any],
    case: dict[str, Any] | None,
    evidence: list[Evidence],
    actor_email: str,
) -> Proposal:
    if not case:
        raise _DraftError("There is no single open case to escalate — which one did you mean?")

    try:
        draft = model.with_structured_output(EscalationDraft).invoke(messages)
    except Exception as exc:
        raise _DraftError(f"I could not draft an escalation: {exc}") from exc
    assert isinstance(draft, EscalationDraft)

    rendered = deps.registry.render(
        "resolution",
        "templates/escalation-brief.md.j2",
        {
            "customer": customer,
            "case": case,
            "escalate_to": draft.escalate_to,
            "priority": draft.priority.value,
            "reason": draft.reason,
            "steps_taken": draft.steps_taken,
            "decision_requested": draft.decision_requested,
            "evidence": _evidence_lines(evidence),
            "actor_email": actor_email,
        },
    )

    return Proposal(
        action="escalate_case",
        summary=f"Escalate {case['case_id']} to {draft.escalate_to}",
        rendered=rendered,
        payload={
            "case_id": case["case_id"],
            "escalated_to": draft.escalate_to,
            "reason": draft.reason,
            "priority": draft.priority.value,
        },
        required_group=REQUIRED_GROUP["escalate_case"],
        evidence_refs=[e["ref"] for e in evidence],
    )


def _evidence_lines(evidence: list[Evidence]) -> list[dict[str, str]]:
    lines: list[dict[str, str]] = []
    for item in evidence:
        record = item["result"]
        label = (
            record.get("summary")
            or record.get("title")
            or record.get("full_name")
            or record.get("status")
            or item["source"]
        )
        lines.append({"ref": item["ref"], "summary": str(label)[:200]})
    return lines


def build_specialists(
    deps: GraphDependencies,
) -> dict[str, Callable[[AgentState, RunnableConfig], Command[Any]]]:
    return {
        "profile": build_profile(deps),
        "history": build_history(deps),
        "investigator": build_investigator(deps),
        "resolution": build_resolution(deps),
    }


__all__ = [
    "EscalationDraft",
    "TicketDraft",
    "build_history",
    "build_investigator",
    "build_profile",
    "build_resolution",
    "build_specialists",
]
