"""Case access, including the escalation write — docs/04 §3.4.

A *case* is the customer's problem; a *ticket* is a unit of work. They are separate
tables because REQ-022 (investigate) and REQ-023 (create ticket) are separate
operations, and conflating them would make one indistinguishable from the other.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import schema
from app.domain import clock
from app.domain.enums import CaseStatus
from app.domain.models import CaseDetail, CaseEscalation, CaseEvent, SupportCase
from app.repositories.base import Repository, clamp_limit

OPEN_STATUSES = (
    CaseStatus.OPEN,
    CaseStatus.INVESTIGATING,
    CaseStatus.PENDING_CUSTOMER,
    CaseStatus.ESCALATED,
)


def _to_case(row: schema.SupportCase) -> SupportCase:
    return SupportCase(
        case_id=row.case_id,
        customer_id=row.customer_id,
        claim_id=row.claim_id,
        title=row.title,
        category=row.category,
        status=row.status,
        priority=row.priority,
        summary=row.summary,
        owner=row.owner,
        escalated_to=row.escalated_to,
        opened_at=row.opened_at,
        resolved_at=row.resolved_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_event(row: schema.CaseEvent) -> CaseEvent:
    return CaseEvent(
        event_id=row.event_id,
        case_id=row.case_id,
        event_type=row.event_type,
        detail=row.detail,
        actor=row.actor,
        occurred_at=row.occurred_at,
    )


class CaseRepository(Repository):
    def get(self, case_id: str) -> SupportCase | None:
        with self.db.session() as s:
            row = s.get(schema.SupportCase, case_id)
            return _to_case(row) if row else None

    def detail(self, case_id: str) -> CaseDetail | None:
        with self.db.session() as s:
            row = s.get(schema.SupportCase, case_id)
            if row is None:
                return None
            events = s.scalars(
                select(schema.CaseEvent)
                .where(schema.CaseEvent.case_id == case_id)
                .order_by(schema.CaseEvent.occurred_at, schema.CaseEvent.event_id)
            ).all()
            ticket_ids = s.scalars(
                select(schema.Ticket.ticket_id)
                .where(schema.Ticket.case_id == case_id)
                .order_by(schema.Ticket.created_at)
            ).all()
            interaction_ids = s.scalars(
                select(schema.Interaction.interaction_id)
                .where(schema.Interaction.case_id == case_id)
                .order_by(schema.Interaction.occurred_at)
            ).all()
            return CaseDetail(
                case=_to_case(row),
                events=tuple(_to_event(e) for e in events),
                ticket_ids=tuple(ticket_ids),
                interaction_ids=tuple(interaction_ids),
            )

    def list_for_customer(
        self, customer_id: str, *, status: str | None = None, limit: int | None = None
    ) -> list[SupportCase]:
        stmt = select(schema.SupportCase).where(schema.SupportCase.customer_id == customer_id)
        if status == "open":
            stmt = stmt.where(schema.SupportCase.status.in_([s.value for s in OPEN_STATUSES]))
        elif status:
            stmt = stmt.where(schema.SupportCase.status == status)
        stmt = stmt.order_by(schema.SupportCase.opened_at.desc()).limit(
            clamp_limit(limit, default=20)
        )

        with self.db.session() as s:
            return [_to_case(r) for r in s.scalars(stmt).all()]

    def list_for_claim(self, claim_id: str) -> list[SupportCase]:
        stmt = (
            select(schema.SupportCase)
            .where(schema.SupportCase.claim_id == claim_id)
            .order_by(schema.SupportCase.opened_at.desc())
        )
        with self.db.session() as s:
            return [_to_case(r) for r in s.scalars(stmt).all()]

    # -- writes ------------------------------------------------------------
    def escalate(
        self, session: Session, payload: CaseEscalation, *, actor_label: str
    ) -> SupportCase:
        """Escalate a case. Called only from ``commit``, inside its transaction.

        The session is passed in rather than opened here so the mutation and its audit
        row share one transaction — docs/04 §3.6 rule 3.
        """
        row = session.get(schema.SupportCase, payload.case_id)
        if row is None:
            raise LookupError(f"case {payload.case_id} does not exist")

        stamp = clock.now()
        row.status = CaseStatus.ESCALATED.value
        row.escalated_to = payload.escalated_to
        row.priority = payload.priority.value
        row.updated_at = stamp
        session.add(
            schema.CaseEvent(
                case_id=payload.case_id,
                event_type="escalated",
                detail=payload.reason,
                actor=actor_label,
                occurred_at=stamp,
            )
        )
        session.flush()
        return _to_case(row)
