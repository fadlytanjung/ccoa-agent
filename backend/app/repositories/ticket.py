"""Ticket access and the ticket write — REQ-023."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import schema
from app.domain import clock
from app.domain.enums import CreatedVia, TicketStatus
from app.domain.ids import format_id
from app.domain.models import NewTicket, Ticket, TicketDetail, TicketEvent
from app.repositories.base import Repository, clamp_limit


def _to_ticket(row: schema.Ticket) -> Ticket:
    return Ticket(
        ticket_id=row.ticket_id,
        customer_id=row.customer_id,
        case_id=row.case_id,
        title=row.title,
        description=row.description,
        category=row.category,
        priority=row.priority,
        status=row.status,
        assignee=row.assignee,
        created_by=row.created_by,
        created_via=row.created_via,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_event(row: schema.TicketEvent) -> TicketEvent:
    return TicketEvent(
        event_id=row.event_id,
        ticket_id=row.ticket_id,
        event_type=row.event_type,
        detail=row.detail,
        actor=row.actor,
        occurred_at=row.occurred_at,
    )


class TicketRepository(Repository):
    def get(self, ticket_id: str) -> Ticket | None:
        with self.db.session() as s:
            row = s.get(schema.Ticket, ticket_id)
            return _to_ticket(row) if row else None

    def detail(self, ticket_id: str) -> TicketDetail | None:
        with self.db.session() as s:
            row = s.get(schema.Ticket, ticket_id)
            if row is None:
                return None
            events = s.scalars(
                select(schema.TicketEvent)
                .where(schema.TicketEvent.ticket_id == ticket_id)
                .order_by(schema.TicketEvent.occurred_at, schema.TicketEvent.event_id)
            ).all()
            return TicketDetail(ticket=_to_ticket(row), events=tuple(_to_event(e) for e in events))

    def list_for_customer(self, customer_id: str, limit: int | None = None) -> list[Ticket]:
        stmt = (
            select(schema.Ticket)
            .where(schema.Ticket.customer_id == customer_id)
            .order_by(schema.Ticket.created_at.desc())
            .limit(clamp_limit(limit, default=20))
        )
        with self.db.session() as s:
            return [_to_ticket(r) for r in s.scalars(stmt).all()]

    def list_for_case(self, case_id: str) -> list[Ticket]:
        stmt = (
            select(schema.Ticket)
            .where(schema.Ticket.case_id == case_id)
            .order_by(schema.Ticket.created_at)
        )
        with self.db.session() as s:
            return [_to_ticket(r) for r in s.scalars(stmt).all()]

    # -- writes ------------------------------------------------------------
    def next_id(self, session: Session) -> str:
        """Continue the seeded sequence rather than starting a fresh range.

        A ticket created during a session is visibly the next number, which is what an
        agent would expect. Provenance is carried by ``created_via``, not by the
        identifier (docs/12 §6 question 3).
        """
        highest = session.scalar(select(func.max(schema.Ticket.ticket_id)))
        nth = int(str(highest).split("-")[1]) if highest else 0
        return format_id("TKT", nth + 1)

    def create(
        self,
        session: Session,
        payload: NewTicket,
        *,
        created_by: str,
        created_via: CreatedVia = CreatedVia.ASSISTANT,
    ) -> Ticket:
        """Insert a ticket. Called only from ``commit``, inside its transaction."""
        stamp = clock.now()
        ticket_id = self.next_id(session)
        row = schema.Ticket(
            ticket_id=ticket_id,
            customer_id=payload.customer_id,
            case_id=payload.case_id,
            title=payload.title,
            description=payload.description,
            category=payload.category.value,
            priority=payload.priority.value,
            status=TicketStatus.OPEN.value,
            assignee=payload.assignee,
            created_by=created_by,
            created_via=created_via.value,
            created_at=stamp,
            updated_at=stamp,
        )
        session.add(row)
        session.add(
            schema.TicketEvent(
                ticket_id=ticket_id,
                event_type="created",
                detail=f"Opened via {created_via.value}",
                actor=created_by,
                occurred_at=stamp,
            )
        )
        if payload.case_id:
            session.add(
                schema.CaseEvent(
                    case_id=payload.case_id,
                    event_type="ticket_linked",
                    detail=f"Ticket {ticket_id} raised",
                    actor=created_by,
                    occurred_at=stamp,
                )
            )
        session.flush()
        return _to_ticket(row)
