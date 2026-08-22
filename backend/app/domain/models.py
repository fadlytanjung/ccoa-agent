"""Domain models — docs/04 §3.4.

Repositories return these, never ``sqlite3.Row``. Tools return these, never SQL. The
model therefore only ever sees business language: no table names, no joins, no columns
it was not meant to reason about.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
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
from app.domain.ids import (
    ArticleId,
    CaseId,
    ClaimId,
    CustomerId,
    InteractionId,
    PolicyId,
    TicketId,
)


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Customer and policies
# ---------------------------------------------------------------------------
class Customer(DomainModel):
    customer_id: CustomerId
    full_name: str
    email: str
    phone: str
    date_of_birth: str
    address_line1: str
    city: str
    postal_code: str
    country: str = "SG"
    tier: CustomerTier
    status: CustomerStatus
    preferred_lang: str = "en"
    risk_flag: bool = False
    created_at: str
    updated_at: str


class CustomerMatch(DomainModel):
    """A search candidate. ``search_customer`` returns *all* of these — never a guess.

    The distinguishing fields exist so the human can tell two people apart when the
    graph asks (docs/04 §3.6 rule 1).
    """

    customer_id: CustomerId
    full_name: str
    email: str
    city: str
    tier: CustomerTier
    status: CustomerStatus
    policy_count: int = 0


class Policy(DomainModel):
    policy_id: PolicyId
    customer_id: CustomerId
    product: PolicyProduct
    status: PolicyStatus
    premium_cents: int = Field(ge=0)
    currency: str = "SGD"
    effective_from: str
    effective_to: str | None = None
    created_at: str


class CustomerProfile(DomainModel):
    """What ``get_customer`` returns: the customer plus the context an agent needs
    on a live call, without a second round trip."""

    customer: Customer
    policies: tuple[Policy, ...] = ()
    open_case_count: int = 0
    recent_interaction_count: int = 0


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------
class Claim(DomainModel):
    claim_id: ClaimId
    policy_id: PolicyId
    customer_id: CustomerId
    status: ClaimStatus
    failure_code: FailureCode | None = None
    failure_detail: str | None = None
    amount_cents: int = Field(ge=0)
    currency: str = "SGD"
    incident_date: str
    submitted_at: str | None = None
    channel: ClaimChannel
    created_at: str
    updated_at: str

    @property
    def has_failed(self) -> bool:
        return self.status == ClaimStatus.SUBMISSION_FAILED


# ---------------------------------------------------------------------------
# Interactions
# ---------------------------------------------------------------------------
class InteractionSummary(DomainModel):
    """The default shape. Transcripts are fetched only on demand — docs/05 §3.8."""

    interaction_id: InteractionId
    customer_id: CustomerId
    case_id: CaseId | None = None
    channel: InteractionChannel
    direction: Direction
    subject: str
    summary: str
    sentiment: Sentiment
    handled_by: str
    duration_sec: int = Field(ge=0)
    occurred_at: str


class Interaction(InteractionSummary):
    transcript: str
    created_at: str


# ---------------------------------------------------------------------------
# Cases and tickets
# ---------------------------------------------------------------------------
class CaseEvent(DomainModel):
    event_id: int
    case_id: CaseId
    event_type: str
    detail: str
    actor: str
    occurred_at: str


class SupportCase(DomainModel):
    """The customer's problem. Named ``SupportCase`` because ``case`` is a SQL
    reserved word and ``Case`` reads as a builtin at the call site — the *table* keeps
    the domain name (docs/04 §3.4)."""

    case_id: CaseId
    customer_id: CustomerId
    claim_id: ClaimId | None = None
    title: str
    category: Category
    status: CaseStatus
    priority: Priority
    summary: str
    owner: str | None = None
    escalated_to: str | None = None
    opened_at: str
    resolved_at: str | None = None
    created_at: str
    updated_at: str


class CaseDetail(DomainModel):
    case: SupportCase
    events: tuple[CaseEvent, ...] = ()
    ticket_ids: tuple[TicketId, ...] = ()
    interaction_ids: tuple[InteractionId, ...] = ()


class TicketEvent(DomainModel):
    event_id: int
    ticket_id: TicketId
    event_type: str
    detail: str
    actor: str
    occurred_at: str


class Ticket(DomainModel):
    ticket_id: TicketId
    customer_id: CustomerId
    case_id: CaseId | None = None
    title: str
    description: str
    category: Category
    priority: Priority
    status: TicketStatus
    assignee: str | None = None
    created_by: str
    created_via: CreatedVia
    created_at: str
    updated_at: str


class TicketDetail(DomainModel):
    ticket: Ticket
    events: tuple[TicketEvent, ...] = ()


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------
class Article(DomainModel):
    article_id: ArticleId
    title: str
    category: str
    body: str
    applies_to: tuple[FailureCode, ...] = ()
    updated_at: str


class ArticleHit(DomainModel):
    """A KB search result. ``score`` is a similarity when semantic search ran and a
    keyword-overlap rank otherwise; ``method`` says which, because a silently degraded
    answer is a correctness bug (docs/05 §3.11)."""

    article_id: ArticleId
    title: str
    excerpt: str
    applies_to: tuple[FailureCode, ...] = ()
    score: float = 0.0
    method: str = "keyword"


class InteractionHit(DomainModel):
    interaction_id: InteractionId
    subject: str
    summary: str
    occurred_at: str
    score: float = 0.0
    method: str = "keyword"


# ---------------------------------------------------------------------------
# Write payloads — the exact shape ``commit`` persists (docs/05 §3.7)
# ---------------------------------------------------------------------------
class NewTicket(BaseModel):
    """What an approved ticket proposal turns into. Validated before the human sees
    it, so approving cannot approve something unwritable."""

    model_config = ConfigDict(extra="forbid")

    customer_id: CustomerId
    case_id: CaseId | None = None
    title: str = Field(min_length=4, max_length=200)
    description: str = Field(min_length=10, max_length=8000)
    category: Category
    priority: Priority
    assignee: str | None = None


class CaseEscalation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: CaseId
    escalated_to: str = Field(min_length=2, max_length=120)
    reason: str = Field(min_length=10, max_length=4000)
    priority: Priority = Priority.HIGH


class AuditEntry(DomainModel):
    audit_id: int
    trace_id: str
    thread_id: str | None
    actor_sub: str
    actor_email: str
    actor_groups: str
    action: str
    target_type: str
    target_id: str | None
    outcome: str
    detail: str | None
    occurred_at: str
