"""SQLAlchemy models — the single source of truth for the schema (docs/04 §3.4).

Alembic autogenerates against this metadata and ``alembic check`` compares the two, so
a model change without a migration fails CI rather than surfacing as a missing column
at runtime.

Repositories query these tables through ``select()`` rather than SQL strings. That is
not stylistic: a parameterised expression cannot be string-interpolated by accident,
which matters for a service whose checkpointer already carries a SQL-injection CVE
(docs/02 §4.2).
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.enums import (
    AuditOutcome,
    CaseStatus,
    Category,
    ClaimChannel,
    ClaimStatus,
    CreatedVia,
    CustomerStatus,
    CustomerTier,
    Direction,
    FailureCode,
    InteractionChannel,
    PolicyProduct,
    PolicyStatus,
    Priority,
    Sentiment,
    TicketStatus,
)

#: Deterministic constraint names so Alembic's batch operations (which recreate tables
#: on SQLite) can find and reproduce them. Without this every batch migration would
#: silently drop unnamed constraints.
NAMING_CONVENTION = {
    "ix": "idx_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _one_of(column: str, enum: type[StrEnum]) -> str:
    """Render a ``CHECK (col IN (...))`` clause from a ``StrEnum``.

    Generating this from the enum is what keeps docs/04's constraints and
    ``app.domain.enums`` from drifting apart — there is only one list, and adding a
    member to it changes the constraint that Alembic then asks you to migrate.
    """
    members = ", ".join(f"'{m.value}'" for m in enum)
    return f"{column} IN ({members})"


class Customer(Base):
    __tablename__ = "customer"

    customer_id: Mapped[str] = mapped_column(String, primary_key=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    date_of_birth: Mapped[str] = mapped_column(Text, nullable=False)
    address_line1: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    postal_code: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False, server_default="SG")
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_lang: Mapped[str] = mapped_column(Text, nullable=False, server_default="en")
    risk_flag: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(_one_of("tier", CustomerTier), name="tier"),
        CheckConstraint(_one_of("status", CustomerStatus), name="status"),
        CheckConstraint("risk_flag IN (0,1)", name="risk_flag"),
        Index("idx_customer_name", "full_name"),
        Index("idx_customer_email", "email"),
    )


class Policy(Base):
    __tablename__ = "policy"

    policy_id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customer.customer_id", ondelete="CASCADE"), nullable=False
    )
    product: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    premium_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="SGD")
    effective_from: Mapped[str] = mapped_column(Text, nullable=False)
    effective_to: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(_one_of("product", PolicyProduct), name="product"),
        CheckConstraint(_one_of("status", PolicyStatus), name="status"),
        CheckConstraint("premium_cents >= 0", name="premium_cents"),
        Index("idx_policy_customer", "customer_id"),
    )


class Claim(Base):
    __tablename__ = "claim"

    claim_id: Mapped[str] = mapped_column(String, primary_key=True)
    policy_id: Mapped[str] = mapped_column(
        ForeignKey("policy.policy_id", ondelete="CASCADE"), nullable=False
    )
    # Denormalised from policy: removes a join from the hottest query path
    # (claims by customer). Enforced at write time — docs/04 §4.
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customer.customer_id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    failure_code: Mapped[str | None] = mapped_column(Text)
    failure_detail: Mapped[str | None] = mapped_column(Text)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="SGD")
    incident_date: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_at: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(_one_of("status", ClaimStatus), name="status"),
        CheckConstraint(_one_of("failure_code", FailureCode), name="failure_code"),
        CheckConstraint(_one_of("channel", ClaimChannel), name="channel"),
        CheckConstraint("amount_cents >= 0", name="amount_cents"),
        Index("idx_claim_customer", "customer_id", "created_at"),
        Index("idx_claim_status", "status"),
    )


class SupportCase(Base):
    __tablename__ = "case"

    case_id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customer.customer_id", ondelete="CASCADE"), nullable=False
    )
    claim_id: Mapped[str | None] = mapped_column(ForeignKey("claim.claim_id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str | None] = mapped_column(Text)
    escalated_to: Mapped[str | None] = mapped_column(Text)
    opened_at: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(_one_of("category", Category), name="category"),
        CheckConstraint(_one_of("status", CaseStatus), name="status"),
        CheckConstraint(_one_of("priority", Priority), name="priority"),
        Index("idx_case_customer", "customer_id", "opened_at"),
        Index("idx_case_status", "status", "priority"),
    )


class Interaction(Base):
    __tablename__ = "interaction"

    interaction_id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customer.customer_id", ondelete="CASCADE"), nullable=False
    )
    # Nullable by design: most contacts belong to no case, and finding the ones that
    # do *is* the investigation task — docs/04 §3.1.
    case_id: Mapped[str | None] = mapped_column(ForeignKey("case.case_id", ondelete="SET NULL"))
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment: Mapped[str] = mapped_column(Text, nullable=False)
    handled_by: Mapped[str] = mapped_column(Text, nullable=False)
    duration_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(_one_of("channel", InteractionChannel), name="channel"),
        CheckConstraint(_one_of("direction", Direction), name="direction"),
        CheckConstraint(_one_of("sentiment", Sentiment), name="sentiment"),
        CheckConstraint("duration_sec >= 0", name="duration_sec"),
        Index("idx_interaction_customer", "customer_id", "occurred_at"),
        Index("idx_interaction_case", "case_id"),
    )


class Ticket(Base):
    __tablename__ = "ticket"

    ticket_id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customer.customer_id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[str | None] = mapped_column(ForeignKey("case.case_id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    assignee: Mapped[str | None] = mapped_column(Text)
    # Provenance: 'assistant' rows are always human-approved (docs/05 §3.7) and always
    # have a matching audit_log entry.
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_via: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(_one_of("category", Category), name="category"),
        CheckConstraint(_one_of("priority", Priority), name="priority"),
        CheckConstraint(_one_of("status", TicketStatus), name="status"),
        CheckConstraint(_one_of("created_via", CreatedVia), name="created_via"),
        Index("idx_ticket_customer", "customer_id", "created_at"),
        Index("idx_ticket_case", "case_id"),
    )


class CaseEvent(Base):
    __tablename__ = "case_event"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("case.case_id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("idx_case_event_case", "case_id", "occurred_at"),)


class TicketEvent(Base):
    __tablename__ = "ticket_event"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("ticket.ticket_id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("idx_ticket_event_ticket", "ticket_id", "occurred_at"),)


class KbArticle(Base):
    __tablename__ = "kb_article"

    article_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    applies_to: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class Thread(Base):
    """A conversation, owned by exactly one agent — docs/04 §3.9.

    The *content* of a thread lives in the checkpointer's own database, which this
    service does not own and must not query. This table holds only what the API needs
    and the checkpointer cannot answer: who created the thread, so ownership can be
    enforced, and enough metadata to render a list without loading any checkpoints.
    """

    __tablename__ = "thread"

    thread_id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_sub: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    subject_customer_id: Mapped[str | None] = mapped_column(Text)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("idx_thread_owner", "owner_sub", "updated_at"),)


class VecMeta(Base):
    """Provenance for the vector index — docs/13 §3.3.

    A plain table, so it is modelled here and created by every run of revision 0002.
    The ``vec_*`` virtual tables it describes are not modelled: SQLAlchemy cannot
    represent a ``vec0`` table, and autogenerate would propose dropping them forever
    (``alembic/env.py`` filters them out for the same reason).

    It exists so a mismatch between the configured embedding model and the one that
    produced the index is caught at boot, rather than silently returning nonsense
    similarity scores.
    """

    __tablename__ = "vec_meta"

    table_name: Mapped[str] = mapped_column(String, primary_key=True)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    indexed_at: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)


class AuditLog(Base):
    """Append-only. Every mutating tool call writes exactly one row — docs/10 §7."""

    __tablename__ = "audit_log"

    audit_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(Text, nullable=False)
    thread_id: Mapped[str | None] = mapped_column(Text)
    actor_sub: Mapped[str] = mapped_column(Text, nullable=False)
    actor_email: Mapped[str] = mapped_column(Text, nullable=False)
    actor_groups: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(_one_of("outcome", AuditOutcome), name="outcome"),
        Index("idx_audit_trace", "trace_id"),
        Index("idx_audit_actor", "actor_sub", "occurred_at"),
        Index("idx_audit_target", "target_type", "target_id"),
    )
