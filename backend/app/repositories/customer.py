"""Customer and policy access — docs/04 §3.6."""

from __future__ import annotations

from sqlalchemy import func, select

from app.db import schema
from app.domain.enums import CaseStatus
from app.domain.ids import detect_prefix
from app.domain.models import Customer, CustomerMatch, CustomerProfile, Policy
from app.repositories.base import Repository, clamp_limit


def _to_customer(row: schema.Customer) -> Customer:
    return Customer(
        customer_id=row.customer_id,
        full_name=row.full_name,
        email=row.email,
        phone=row.phone,
        date_of_birth=row.date_of_birth,
        address_line1=row.address_line1,
        city=row.city,
        postal_code=row.postal_code,
        country=row.country,
        tier=row.tier,
        status=row.status,
        preferred_lang=row.preferred_lang,
        risk_flag=bool(row.risk_flag),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_policy(row: schema.Policy) -> Policy:
    return Policy(
        policy_id=row.policy_id,
        customer_id=row.customer_id,
        product=row.product,
        status=row.status,
        premium_cents=row.premium_cents,
        currency=row.currency,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        created_at=row.created_at,
    )


class CustomerRepository(Repository):
    def get(self, customer_id: str) -> Customer | None:
        with self.db.session() as s:
            row = s.get(schema.Customer, customer_id)
            return _to_customer(row) if row else None

    def get_by_email(self, email: str) -> Customer | None:
        with self.db.session() as s:
            row = s.scalars(
                select(schema.Customer).where(func.lower(schema.Customer.email) == email.lower())
            ).first()
            return _to_customer(row) if row else None

    def search(self, query: str, limit: int | None = None) -> list[CustomerMatch]:
        """Find candidates by identifier, email, or name — **all** of them.

        Returning every match is the point: two people named John Tan produce two
        results, and the graph asks the human which one. Silently taking the first is
        how an assistant ends up discussing the wrong person's medical claim
        (docs/04 §3.6 rule 1).
        """
        term = query.strip()
        if not term:
            return []

        bound = clamp_limit(limit)
        policy_count = (
            select(schema.Policy.customer_id, func.count().label("n"))
            .group_by(schema.Policy.customer_id)
            .subquery()
        )
        stmt = select(schema.Customer, func.coalesce(policy_count.c.n, 0)).join(
            policy_count,
            policy_count.c.customer_id == schema.Customer.customer_id,
            isouter=True,
        )

        if detect_prefix(term) == "CUST":
            stmt = stmt.where(schema.Customer.customer_id == term)
        elif "@" in term:
            stmt = stmt.where(func.lower(schema.Customer.email) == term.lower())
        else:
            # LIKE with escaped wildcards: a query containing '%' must match a literal
            # percent sign, not every customer in the corpus.
            pattern = f"%{term.replace('!', '!!').replace('%', '!%').replace('_', '!_')}%"
            stmt = stmt.where(schema.Customer.full_name.like(pattern, escape="!"))

        stmt = stmt.order_by(schema.Customer.full_name, schema.Customer.customer_id).limit(bound)

        with self.db.session() as s:
            return [
                CustomerMatch(
                    customer_id=row.customer_id,
                    full_name=row.full_name,
                    email=row.email,
                    city=row.city,
                    tier=row.tier,
                    status=row.status,
                    policy_count=int(count),
                )
                for row, count in s.execute(stmt).all()
            ]

    def profile(self, customer_id: str) -> CustomerProfile | None:
        """Customer plus the context an agent needs on a live call, in one call."""
        with self.db.session() as s:
            row = s.get(schema.Customer, customer_id)
            if row is None:
                return None

            policies = s.scalars(
                select(schema.Policy)
                .where(schema.Policy.customer_id == customer_id)
                .order_by(schema.Policy.effective_from.desc())
            ).all()

            open_cases = s.scalar(
                select(func.count())
                .select_from(schema.SupportCase)
                .where(
                    schema.SupportCase.customer_id == customer_id,
                    schema.SupportCase.status.notin_(
                        [CaseStatus.RESOLVED.value, CaseStatus.CLOSED.value]
                    ),
                )
            )
            interactions = s.scalar(
                select(func.count())
                .select_from(schema.Interaction)
                .where(schema.Interaction.customer_id == customer_id)
            )

            return CustomerProfile(
                customer=_to_customer(row),
                policies=tuple(_to_policy(p) for p in policies),
                open_case_count=int(open_cases or 0),
                recent_interaction_count=int(interactions or 0),
            )

    def list_policies(self, customer_id: str) -> list[Policy]:
        with self.db.session() as s:
            rows = s.scalars(
                select(schema.Policy)
                .where(schema.Policy.customer_id == customer_id)
                .order_by(schema.Policy.effective_from.desc())
            ).all()
            return [_to_policy(r) for r in rows]

    def exists(self, customer_id: str) -> bool:
        with self.db.session() as s:
            return s.get(schema.Customer, customer_id) is not None
