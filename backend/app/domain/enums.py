"""Enumerations mirroring the schema's ``CHECK`` constraints — docs/04 §3.3.

Each of these has a matching ``CHECK`` in ``alembic/versions/0001_initial.py``. They are
kept in step by ``tests/unit/test_schema_parity.py``, which reads the constraint text out
of ``sqlite_master`` and compares it to the members here — so a value added in one place
and forgotten in the other fails the build instead of failing a write at runtime.
"""

from __future__ import annotations

from enum import StrEnum


class CustomerTier(StrEnum):
    STANDARD = "standard"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"


class CustomerStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class PolicyProduct(StrEnum):
    MOTOR = "motor"
    HEALTH = "health"
    TRAVEL = "travel"
    HOME = "home"
    LIFE = "life"


class PolicyStatus(StrEnum):
    ACTIVE = "active"
    LAPSED = "lapsed"
    CANCELLED = "cancelled"
    PENDING = "pending"


class ClaimStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    SUBMISSION_FAILED = "submission_failed"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"
    WITHDRAWN = "withdrawn"


class FailureCode(StrEnum):
    """Populated only when a claim is ``submission_failed`` — the investigation
    scenario (REQ-022) keys off this column."""

    DOC_MISSING = "DOC_MISSING"
    DOC_UNREADABLE = "DOC_UNREADABLE"
    POLICY_LAPSED = "POLICY_LAPSED"
    DUPLICATE = "DUPLICATE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    GATEWAY_TIMEOUT = "GATEWAY_TIMEOUT"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"


class ClaimChannel(StrEnum):
    WEB = "web"
    MOBILE = "mobile"
    AGENT = "agent"
    BROKER = "broker"


class InteractionChannel(StrEnum):
    VOICE = "voice"
    CHAT = "chat"
    EMAIL = "email"
    CALLBACK = "callback"


class Direction(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class Sentiment(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class Category(StrEnum):
    """Shared by ``case`` and ``ticket`` — a ticket inherits its case's category."""

    CLAIM_ISSUE = "claim_issue"
    BILLING = "billing"
    COVERAGE_QUERY = "coverage_query"
    COMPLAINT = "complaint"
    POLICY_CHANGE = "policy_change"
    TECHNICAL = "technical"


class CaseStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    PENDING_CUSTOMER = "pending_customer"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    PENDING = "pending"
    RESOLVED = "resolved"
    CLOSED = "closed"


class CreatedVia(StrEnum):
    ASSISTANT = "assistant"
    AGENT_MANUAL = "agent_manual"
    SYSTEM = "system"


class AuditOutcome(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    FAILED = "failed"


class Group(StrEnum):
    """Cognito groups — docs/10 §3. Authorisation is by group membership only."""

    AGENT = "agent"
    SUPERVISOR = "supervisor"
