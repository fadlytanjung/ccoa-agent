"""Load a generated corpus into the database.

Insertion order follows the foreign keys: customers, then policies, then claims, then
cases (which reference claims), then interactions (which reference cases), then tickets
and their events. ``PRAGMA foreign_keys = ON`` is active, so getting this wrong fails
loudly rather than producing dangling references.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, insert

from app.db import schema
from app.db.engine import Database
from app.seed.generator import Corpus

log = logging.getLogger(__name__)

#: Reverse dependency order, for ``--reset``.
_CLEAR_ORDER = (
    schema.TicketEvent,
    schema.CaseEvent,
    schema.Ticket,
    schema.Interaction,
    schema.SupportCase,
    schema.Claim,
    schema.Policy,
    schema.Customer,
    schema.KbArticle,
)


def clear(db: Database) -> None:
    """Remove all business rows. Leaves the schema and the audit log alone.

    The audit log is deliberately untouched: it is append-only security evidence, and a
    reseed is not a reason to erase the record of who did what (docs/04 §3.8).
    """
    with db.transaction() as session:
        for model in _CLEAR_ORDER:
            session.execute(delete(model))


def write(db: Database, corpus: Corpus) -> None:
    """Insert the whole corpus in one transaction."""
    if db.schema_version() is None:
        raise RuntimeError(
            "the database has no alembic_version table — run 'alembic upgrade head' first"
        )

    batches = (
        (schema.Customer, corpus.customers),
        (schema.Policy, corpus.policies),
        (schema.Claim, corpus.claims),
        (schema.SupportCase, corpus.cases),
        (schema.Interaction, corpus.interactions),
        (schema.Ticket, corpus.tickets),
        (schema.CaseEvent, corpus.case_events),
        (schema.TicketEvent, corpus.ticket_events),
        (schema.KbArticle, corpus.kb_articles),
    )

    with db.transaction() as session:
        for model, rows in batches:
            if rows:
                session.execute(insert(model), rows)

    log.info("seeded %s rows into %s", corpus.total_rows(), db.path)
