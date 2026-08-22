"""Repositories — the only code that speaks SQL (docs/03 §3.3).

Grouped into one container so a tool, a router, or a test takes a single dependency
instead of assembling six. There is exactly one implementation; the
``repositories/postgres/`` package the migration path talks about does not exist and
the docs say so (docs/15 §3.6).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.db.engine import Database
from app.repositories.audit import AuditRepository
from app.repositories.claim import ClaimRepository
from app.repositories.customer import CustomerRepository
from app.repositories.interaction import InteractionRepository
from app.repositories.kb import KbRepository
from app.repositories.support_case import CaseRepository
from app.repositories.thread import ThreadRepository
from app.repositories.ticket import TicketRepository

__all__ = [
    "AuditRepository",
    "CaseRepository",
    "ClaimRepository",
    "CustomerRepository",
    "InteractionRepository",
    "KbRepository",
    "Repositories",
    "ThreadRepository",
    "TicketRepository",
]


@dataclass(frozen=True, slots=True)
class Repositories:
    db: Database
    customers: CustomerRepository
    claims: ClaimRepository
    interactions: InteractionRepository
    cases: CaseRepository
    tickets: TicketRepository
    kb: KbRepository
    audit: AuditRepository
    threads: ThreadRepository

    @classmethod
    def build(cls, db: Database) -> Repositories:
        return cls(
            db=db,
            customers=CustomerRepository(db),
            claims=ClaimRepository(db),
            interactions=InteractionRepository(db),
            cases=CaseRepository(db),
            tickets=TicketRepository(db),
            kb=KbRepository(db),
            audit=AuditRepository(db),
            threads=ThreadRepository(db),
        )
