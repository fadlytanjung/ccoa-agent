"""Interaction access — docs/04 §3.4.

Summaries are the default shape and transcripts are fetched only on demand. That is a
context-budget decision, not a privacy one: a 2 KB transcript per row would fill the
model's window with ten interactions, and the summary carries the signal
(docs/05 §3.8).
"""

from __future__ import annotations

from sqlalchemy import select

from app.db import schema
from app.domain.models import Interaction, InteractionSummary
from app.repositories.base import Repository, clamp_limit


def _to_summary(row: schema.Interaction) -> InteractionSummary:
    return InteractionSummary(
        interaction_id=row.interaction_id,
        customer_id=row.customer_id,
        case_id=row.case_id,
        channel=row.channel,
        direction=row.direction,
        subject=row.subject,
        summary=row.summary,
        sentiment=row.sentiment,
        handled_by=row.handled_by,
        duration_sec=row.duration_sec,
        occurred_at=row.occurred_at,
    )


def _to_full(row: schema.Interaction) -> Interaction:
    return Interaction(
        **_to_summary(row).model_dump(),
        transcript=row.transcript,
        created_at=row.created_at,
    )


class InteractionRepository(Repository):
    def get(
        self, interaction_id: str, *, include_transcript: bool = False
    ) -> InteractionSummary | None:
        with self.db.session() as s:
            row = s.get(schema.Interaction, interaction_id)
            if row is None:
                return None
            return _to_full(row) if include_transcript else _to_summary(row)

    def list_for_customer(
        self,
        customer_id: str,
        *,
        limit: int | None = None,
        since: str | None = None,
        channel: str | None = None,
    ) -> list[InteractionSummary]:
        stmt = select(schema.Interaction).where(schema.Interaction.customer_id == customer_id)
        if since:
            stmt = stmt.where(schema.Interaction.occurred_at >= since)
        if channel:
            stmt = stmt.where(schema.Interaction.channel == channel)
        stmt = stmt.order_by(schema.Interaction.occurred_at.desc()).limit(clamp_limit(limit))

        with self.db.session() as s:
            return [_to_summary(r) for r in s.scalars(stmt).all()]

    def count_for_customer(self, customer_id: str) -> int:
        from sqlalchemy import func

        with self.db.session() as s:
            return int(
                s.scalar(
                    select(func.count())
                    .select_from(schema.Interaction)
                    .where(schema.Interaction.customer_id == customer_id)
                )
                or 0
            )

    def list_for_case(self, case_id: str, limit: int | None = None) -> list[InteractionSummary]:
        stmt = (
            select(schema.Interaction)
            .where(schema.Interaction.case_id == case_id)
            .order_by(schema.Interaction.occurred_at)
            .limit(clamp_limit(limit, default=20))
        )
        with self.db.session() as s:
            return [_to_summary(r) for r in s.scalars(stmt).all()]

    def keyword_search(
        self, customer_id: str, query: str, limit: int | None = None
    ) -> list[InteractionSummary]:
        """Fallback retrieval when semantic search is unavailable — docs/13 §3.6.

        Always scoped to one customer, so a query cannot surface another customer's
        transcript by construction rather than by filter discipline.
        """
        term = query.strip()
        if not term:
            return []
        pattern = f"%{term.replace('!', '!!').replace('%', '!%').replace('_', '!_')}%"
        stmt = (
            select(schema.Interaction)
            .where(
                schema.Interaction.customer_id == customer_id,
                schema.Interaction.summary.like(pattern, escape="!")
                | schema.Interaction.subject.like(pattern, escape="!"),
            )
            .order_by(schema.Interaction.occurred_at.desc())
            .limit(clamp_limit(limit, default=5))
        )
        with self.db.session() as s:
            return [_to_summary(r) for r in s.scalars(stmt).all()]
