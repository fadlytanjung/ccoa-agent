"""Prompt assembly — docs/05 §3.10.

No prompt *text* lives here. What lives here is the **order**: layers are concatenated
most-stable first, so the cacheable prefix stays byte-identical across turns. Anything
volatile — the brief, the evidence, the user's message — sits after the last stable
layer, and nothing interpolates a timestamp or a request id into layers 1–3.

The only strings below are structural markers a few words long. The behavioural text
comes from `SKILL.md` bodies and `tools.yaml`.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage

from app.agents.schema import Skill, SkillDescriptor
from app.graph.state import AgentState, latest_user_message

EVIDENCE_HEADING = "## EVIDENCE"
SPECIALISTS_HEADING = "## Available specialists"
BRIEF_HEADING = "## Delegation brief"
REPORTS_HEADING = "## Specialist reports"
REQUEST_HEADING = "## Current request"
FOCUS_HEADING = "## Conversational focus"
NO_EVIDENCE = "(no evidence gathered yet)"

#: Evidence results are truncated before they reach the prompt. A single `get_case` can
#: return a long event history, and thirty of those would crowd out the instructions.
MAX_RESULT_CHARS = 1200


def render_skill_menu(descriptors: list[SkillDescriptor]) -> str:
    """Tier 1 — the orchestrator's delegation menu. Deterministically ordered."""
    lines = [SPECIALISTS_HEADING, ""]
    lines.extend(f"- **{d.name}** — {' '.join(d.description.split())}" for d in descriptors)
    return "\n".join(lines)


def _compact(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return text[: MAX_RESULT_CHARS - 3] + "..."


def render_evidence(state: AgentState) -> str:
    """The grounding block. Everything the answer is permitted to assert."""
    items = state.get("evidence") or []
    if not items:
        return f"{EVIDENCE_HEADING}\n\n{NO_EVIDENCE}"

    lines = [EVIDENCE_HEADING, ""]
    for item in items:
        lines.append(f"### {item['ref']}")
        lines.append(f"source: {item['source']}")
        lines.append(_compact(item["result"]))
        lines.append("")
    return "\n".join(lines).rstrip()


def render_focus(state: AgentState) -> str:
    """Who and what the conversation is currently about.

    Without this the evidence block is ambiguous by construction: after a
    disambiguation the two candidate customers are both still in evidence, and nothing
    tells the model which one was chosen. The observable symptom is an assistant that
    re-asks a question the human already answered.
    """
    lines = []
    if subject := state.get("subject_customer_id"):
        lines.append(f"- subject customer: `customer:{subject}` (already confirmed)")
    if case_id := state.get("focus_case_id"):
        lines.append(f"- case in focus: `case:{case_id}`")
    if claim_id := state.get("focus_claim_id"):
        lines.append(f"- claim in focus: `claim:{claim_id}`")
    if not lines:
        return ""
    return "\n".join([FOCUS_HEADING, "", *lines])


def render_reports(state: AgentState) -> str:
    reports = state.get("agent_reports") or []
    if not reports:
        return ""
    lines = [REPORTS_HEADING, ""]
    for report in reports:
        status = "complete" if report["complete"] else "incomplete"
        lines.append(f"- **{report['agent']}** ({status}): {report['summary']}")
    return "\n".join(lines)


def specialist_prompt(
    skill: Skill,
    state: AgentState,
    *,
    brief: str | None = None,
) -> list[AnyMessage]:
    """Layers 1 and 5 for a specialist.

    A specialist sees its brief and the shared evidence — **never the raw conversation**.
    That boundary is what stops it being steered by text a customer wrote into a
    transcript three turns ago (docs/05 §3.1).
    """
    turn = [f"{BRIEF_HEADING}\n\n{brief or ''}".rstrip()]
    if focus := render_focus(state):
        turn.append(focus)
    turn.append(render_evidence(state))
    return [SystemMessage(content=skill.body), HumanMessage(content="\n\n".join(turn))]


def orchestrator_prompt(
    skill: Skill,
    descriptors: list[SkillDescriptor],
    state: AgentState,
    *,
    include_menu: bool = True,
) -> list[AnyMessage]:
    """Layers 1, 3 and 5 for the orchestrator.

    The conversation itself is passed through as messages rather than serialised into
    the turn block, so LangGraph's message reducer keeps ownership of history.
    """
    stable = [skill.body]
    if include_menu:
        stable.append(render_skill_menu(descriptors))

    turn_parts = []
    if focus := render_focus(state):
        turn_parts.append(focus)
    turn_parts.append(render_evidence(state))
    if reports := render_reports(state):
        turn_parts.append(reports)

    prompt: list[AnyMessage] = [SystemMessage(content="\n\n".join(stable))]
    prompt.extend(state.get("messages") or [])
    prompt.append(HumanMessage(content="\n\n".join(turn_parts)))
    return prompt


def classification_prompt(
    skill: Skill, descriptors: list[SkillDescriptor], state: AgentState
) -> list[AnyMessage]:
    """Classification sees the menu and the conversation, but not the evidence.

    Evidence is for answering, not for deciding what was asked — including it biases
    the classifier towards whatever was last fetched.
    """
    system = "\n\n".join([skill.body, render_skill_menu(descriptors)])
    prompt: list[AnyMessage] = [SystemMessage(content=system)]
    prompt.extend(state.get("messages") or [])
    prompt.append(HumanMessage(content=f"{REQUEST_HEADING}\n\n{latest_user_message(state)}"))
    return prompt
