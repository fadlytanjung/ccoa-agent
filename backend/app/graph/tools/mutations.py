"""The only two operations that write — docs/05 §3.8.

These are **not bound to any model**. They are invoked from the ``commit`` node after a
human approved a rendered proposal, and they check the resuming actor's groups before
doing anything. There is therefore no prompt that can talk the model into writing a
ticket: the capability is absent, not merely discouraged.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.domain.actor import Actor
from app.domain.enums import AuditOutcome, CreatedVia, Group
from app.domain.errors import invalid_input, not_found
from app.domain.models import CaseEscalation, NewTicket
from app.graph.tools.result import ToolResult
from app.graph.tools.toolbox import ToolContext, authorise, tool_boundary
from app.services.audit import AuditService

log = logging.getLogger(__name__)

#: action -> Cognito group required to perform it (docs/10 §3).
REQUIRED_GROUP: dict[str, str] = {
    "create_ticket": Group.AGENT.value,
    "escalate_case": Group.SUPERVISOR.value,
}


@tool_boundary
def create_ticket(
    ctx: ToolContext,
    audit: AuditService,
    *,
    actor: Actor,
    trace_id: str,
    thread_id: str | None,
    payload: dict[str, Any],
) -> ToolResult:
    """Create a ticket from an approved proposal."""
    if error := authorise(actor.groups, "create_ticket", REQUIRED_GROUP["create_ticket"]):
        audit.record(
            actor=actor,
            action="create_ticket",
            target_type="ticket",
            outcome=AuditOutcome.DENIED,
            trace_id=trace_id,
            thread_id=thread_id,
            detail={"required_group": REQUIRED_GROUP["create_ticket"]},
        )
        return ToolResult.failure(error)

    try:
        ticket = NewTicket.model_validate(payload)
    except ValidationError as exc:
        return ToolResult.failure(
            invalid_input("the approved ticket payload is not valid", reason=str(exc.errors()))
        )

    if not ctx.repos.customers.exists(ticket.customer_id):
        return ToolResult.failure(not_found("customer", ticket.customer_id))
    if ticket.case_id and ctx.repos.cases.get(ticket.case_id) is None:
        return ToolResult.failure(not_found("case", ticket.case_id))

    created: dict[str, Any] = {}

    def operation(session: Session) -> tuple[str, dict[str, Any]]:
        row = ctx.repos.tickets.create(
            session,
            ticket,
            created_by=actor.email or actor.sub,
            created_via=CreatedVia.ASSISTANT,
        )
        created.update(row.model_dump(mode="json"))
        # Detail carries operational context only — never the description body, which
        # can quote a customer (docs/04 §3.8).
        return row.ticket_id, {
            "customer_id": row.customer_id,
            "case_id": row.case_id,
            "priority": row.priority.value,
            "category": row.category.value,
        }

    ticket_id = audit.perform(
        operation,
        actor=actor,
        action="create_ticket",
        target_type="ticket",
        trace_id=trace_id,
        thread_id=thread_id,
    )
    log.info("ticket created %s by %s trace=%s", ticket_id, actor.sub, trace_id)
    return ToolResult.success({"ticket": created}, refs=(f"ticket:{ticket_id}",))


@tool_boundary
def escalate_case(
    ctx: ToolContext,
    audit: AuditService,
    *,
    actor: Actor,
    trace_id: str,
    thread_id: str | None,
    payload: dict[str, Any],
) -> ToolResult:
    """Escalate a case from an approved proposal."""
    if error := authorise(actor.groups, "escalate_case", REQUIRED_GROUP["escalate_case"]):
        audit.record(
            actor=actor,
            action="escalate_case",
            target_type="case",
            outcome=AuditOutcome.DENIED,
            trace_id=trace_id,
            thread_id=thread_id,
            target_id=str(payload.get("case_id") or "") or None,
            detail={"required_group": REQUIRED_GROUP["escalate_case"]},
        )
        return ToolResult.failure(error)

    try:
        escalation = CaseEscalation.model_validate(payload)
    except ValidationError as exc:
        return ToolResult.failure(
            invalid_input("the approved escalation payload is not valid", reason=str(exc.errors()))
        )

    if ctx.repos.cases.get(escalation.case_id) is None:
        return ToolResult.failure(not_found("case", escalation.case_id))

    updated: dict[str, Any] = {}

    def operation(session: Session) -> tuple[str, dict[str, Any]]:
        row = ctx.repos.cases.escalate(session, escalation, actor_label=actor.email or actor.sub)
        updated.update(row.model_dump(mode="json"))
        return row.case_id, {
            "escalated_to": escalation.escalated_to,
            "priority": escalation.priority.value,
        }

    case_id = audit.perform(
        operation,
        actor=actor,
        action="escalate_case",
        target_type="case",
        trace_id=trace_id,
        thread_id=thread_id,
    )
    log.info("case escalated %s by %s trace=%s", case_id, actor.sub, trace_id)
    return ToolResult.success({"case": updated}, refs=(f"case:{case_id}",))


#: Dispatch table for ``commit``. Keyed by the proposal's action.
MUTATIONS = {
    "create_ticket": create_ticket,
    "escalate_case": escalate_case,
}
