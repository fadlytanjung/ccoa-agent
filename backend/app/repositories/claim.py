"""Claim access — the investigation scenario's entry point (REQ-022)."""

from __future__ import annotations

from sqlalchemy import select

from app.db import schema
from app.domain.models import Claim
from app.repositories.base import Repository, clamp_limit


def to_claim(row: schema.Claim) -> Claim:
    return Claim(
        claim_id=row.claim_id,
        policy_id=row.policy_id,
        customer_id=row.customer_id,
        status=row.status,
        failure_code=row.failure_code,
        failure_detail=row.failure_detail,
        amount_cents=row.amount_cents,
        currency=row.currency,
        incident_date=row.incident_date,
        submitted_at=row.submitted_at,
        channel=row.channel,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ClaimRepository(Repository):
    def get(self, claim_id: str) -> Claim | None:
        with self.db.session() as s:
            row = s.get(schema.Claim, claim_id)
            return to_claim(row) if row else None

    def list_for_customer(
        self,
        customer_id: str,
        *,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[Claim]:
        stmt = select(schema.Claim).where(schema.Claim.customer_id == customer_id)
        if status:
            stmt = stmt.where(schema.Claim.status == status)
        stmt = stmt.order_by(schema.Claim.created_at.desc()).limit(clamp_limit(limit, default=20))

        with self.db.session() as s:
            return [to_claim(r) for r in s.scalars(stmt).all()]

    def list_for_policy(self, policy_id: str, limit: int | None = None) -> list[Claim]:
        stmt = (
            select(schema.Claim)
            .where(schema.Claim.policy_id == policy_id)
            .order_by(schema.Claim.created_at.desc())
            .limit(clamp_limit(limit, default=20))
        )
        with self.db.session() as s:
            return [to_claim(r) for r in s.scalars(stmt).all()]
