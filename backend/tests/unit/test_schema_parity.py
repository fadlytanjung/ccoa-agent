"""Schema, enums, and migrations stay in step — docs/04 §3.3, §3.7.

Enumerations exist twice: as `CHECK` constraints in the database and as `StrEnum`s in
Python. A value added to one and forgotten in the other fails a write at runtime, in
front of a user. These tests read the constraint text back out of `sqlite_master` and
compare it to the members, so the mismatch fails the build instead.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text

from app.db.engine import Database
from app.db.migration_filters import is_virtual_vector_table
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

CONSTRAINTS = [
    ("customer", "tier", CustomerTier),
    ("customer", "status", CustomerStatus),
    ("policy", "product", PolicyProduct),
    ("policy", "status", PolicyStatus),
    ("claim", "status", ClaimStatus),
    ("claim", "failure_code", FailureCode),
    ("claim", "channel", ClaimChannel),
    ("case", "category", Category),
    ("case", "status", CaseStatus),
    ("case", "priority", Priority),
    ("interaction", "channel", InteractionChannel),
    ("interaction", "direction", Direction),
    ("interaction", "sentiment", Sentiment),
    ("ticket", "category", Category),
    ("ticket", "priority", Priority),
    ("ticket", "status", TicketStatus),
    ("ticket", "created_via", CreatedVia),
    ("audit_log", "outcome", AuditOutcome),
]


def table_sql(db: Database, table: str) -> str:
    with db.engine.connect() as conn:
        row = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name = :name"),
            {"name": table},
        ).first()
    assert row is not None, f"table {table} does not exist"
    return str(row[0])


@pytest.mark.parametrize(("table", "column", "enum"), CONSTRAINTS)
def test_check_constraints_match_the_enum(
    db: Database, table: str, column: str, enum: type
) -> None:
    sql = table_sql(db, table)
    match = re.search(rf"{column} IN \(([^)]*)\)", sql)
    assert match, f"no CHECK constraint found for {table}.{column}"

    in_database = {value.strip().strip("'") for value in match.group(1).split(",")}
    in_python = {member.value for member in enum}  # type: ignore[attr-defined]
    assert in_database == in_python


class TestPragmas:
    def test_foreign_keys_are_enforced(self, db: Database) -> None:
        # SQLite defaults this OFF, per connection. Every repository read and write
        # depends on it being set.
        with db.engine.connect() as conn:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 1

    def test_wal_is_active(self, db: Database) -> None:
        # WAL is what Litestream replicates; without it, durability silently stops.
        with db.engine.connect() as conn:
            assert str(conn.execute(text("PRAGMA journal_mode")).scalar_one()).lower() == "wal"

    def test_integrity_and_referential_checks_pass(self, db: Database) -> None:
        assert db.quick_check() is True
        with db.engine.connect() as conn:
            assert conn.execute(text("PRAGMA foreign_key_check")).all() == []


class TestMigrations:
    def test_the_applied_revision_is_head(self, db: Database) -> None:
        from app.api.v1.health import EXPECTED_HEAD

        assert db.schema_version() == EXPECTED_HEAD

    def test_every_expected_table_exists(self, db: Database) -> None:
        assert db.table_names() >= {
            "customer",
            "policy",
            "claim",
            "case",
            "interaction",
            "ticket",
            "case_event",
            "ticket_event",
            "kb_article",
            "audit_log",
            "thread",
            "vec_meta",
        }


class TestAuditIsAppendOnly:
    def test_a_denial_is_recorded(self, db: Database) -> None:
        from app.domain.actor import Actor
        from app.domain.enums import AuditOutcome as Outcome
        from app.repositories.audit import AuditRepository
        from app.services.audit import AuditService

        repo = AuditRepository(db)
        service = AuditService(db, repo)
        actor = Actor(sub="u", email="u@example.com", groups=("agent",))

        service.record(
            actor=actor,
            action="escalate_case",
            target_type="case",
            outcome=Outcome.DENIED,
            trace_id="t-1",
            detail={"required_group": "supervisor"},
        )

        rows = repo.for_trace("t-1")
        assert [(r.action, r.outcome) for r in rows] == [("escalate_case", "denied")]

    def test_a_failed_mutation_is_still_audited(self, db: Database) -> None:
        from app.domain.actor import Actor
        from app.repositories.audit import AuditRepository
        from app.services.audit import AuditService

        service = AuditService(db, AuditRepository(db))
        actor = Actor(sub="u", email="u@example.com", groups=("agent",))

        def exploding(_session: object) -> tuple[str, dict[str, object]]:
            raise RuntimeError("write failed")

        with pytest.raises(RuntimeError):
            service.perform(
                exploding,  # type: ignore[arg-type]
                actor=actor,
                action="create_ticket",
                target_type="ticket",
                trace_id="t-2",
            )

        rows = AuditRepository(db).for_trace("t-2")
        assert [(r.action, r.outcome) for r in rows] == [("create_ticket", "failed")]


class TestVirtualTableFilters:
    """The two alembic filters — docs/13 §3.1, docs/04 §3.7.

    `vec_interaction` and `vec_kb` are `vec0` virtual tables created by migration SQL,
    not by SQLAlchemy models. They must be invisible to autogenerate, and — the part that
    actually broke CI — invisible to *reflection*, because reflecting a virtual table
    issues `PRAGMA table_xinfo` and that fails with `no such module: vec0` on any
    connection without the extension loaded. Alembic's connection is one of those.
    """

    def test_include_name_hides_virtual_tables_before_reflection(self) -> None:
        assert is_virtual_vector_table("vec_interaction", "table") is True
        assert is_virtual_vector_table("vec_kb", "table") is True

    def test_include_name_keeps_the_modelled_companion(self) -> None:
        # `vec_meta` is an ordinary table with a model, so it stays in scope; excluding it
        # would make autogenerate propose dropping it on every run.
        assert is_virtual_vector_table("vec_meta", "table") is False

    def test_include_name_keeps_ordinary_tables(self) -> None:
        for name in ("customer", "policy", "ticket", "thread"):
            assert is_virtual_vector_table(name, "table") is False

    def test_include_name_only_filters_tables(self) -> None:
        # An index or column called `vec_something` is not a virtual table.
        assert is_virtual_vector_table("vec_interaction", "column") is False
