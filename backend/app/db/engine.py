"""Database connections and their pragmas — docs/04 §3.3, §3.4.

Access is **synchronous** on purpose. The corpus is ~10 MB and stays in page cache, so
queries are sub-millisecond; an async driver would buy nothing and would put an await
boundary between a tool and its transaction. FastAPI runs sync handlers in a threadpool
and LangChain runs sync tools in one, so nothing blocks the event loop. The one async
component is the checkpointer, which owns a separate file.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

log = logging.getLogger(__name__)

#: Applied to every connection. ``foreign_keys`` in particular defaults to OFF in
#: SQLite and must be set per connection, not once per database.
CONNECTION_PRAGMAS = (
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",
    "PRAGMA synchronous = FULL",
)

#: Persisted in the file itself, so setting it once is enough — but it is asserted on
#: every open because Litestream replicates the WAL and silently stops working without
#: it (ADR-007).
JOURNAL_PRAGMA = "PRAGMA journal_mode = WAL"


def _configure_connection(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        for pragma in CONNECTION_PRAGMAS:
            cursor.execute(pragma)
        cursor.execute(JOURNAL_PRAGMA)
    finally:
        cursor.close()


def create_db_engine(db_path: Path, *, echo: bool = False) -> Engine:
    """Build an engine for ``db_path``, creating parent directories if needed."""
    if db_path != Path(":memory:"):
        db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        f"sqlite+pysqlite:///{db_path}",
        echo=echo,
        future=True,
        # Tools run in LangChain's threadpool, so a connection may be used from a
        # thread other than the one that created it. Pooling keeps that safe.
        connect_args={"check_same_thread": False},
    )
    event.listen(engine, "connect", _configure_connection)
    return engine


class Database:
    """Owns one engine and hands out sessions.

    Constructed once in the FastAPI lifespan and once per test fixture. Nothing
    module-level, so tests never inherit another test's file.
    """

    def __init__(self, db_path: Path, *, echo: bool = False) -> None:
        self.path = db_path
        self.engine = create_db_engine(db_path, echo=echo)
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """A read session.

        Exits via ``close()`` and deliberately **not** ``rollback()``. Both release the
        connection, but ``rollback()`` also *expires* every loaded object, so any row
        read here would raise ``DetachedInstanceError`` the moment a caller touched it
        after the block. ``close()`` expunges instead, leaving already-loaded attributes
        readable — which is what lets a repository return rows it mapped inside the
        block without every method having to defensively copy.
        """
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """A write session.

        Every mutation goes through here, and the audit row is written inside the same
        block (docs/04 §3.6 rule 3) — committing a mutation without its audit entry is
        not expressible.
        """
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def quick_check(self) -> bool:
        """``PRAGMA quick_check`` — the readiness probe's integrity test.

        ``quick_check`` rather than ``integrity_check`` because cold start is already
        45–75 s and this runs on every boot (docs/15 §6 question 2).
        """
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("PRAGMA quick_check")).scalar_one()
            return str(result).lower() == "ok"
        except sqlite3.DatabaseError:
            return False

    def schema_version(self) -> str | None:
        """The applied Alembic revision, or ``None`` if migrations never ran."""
        try:
            with self.engine.connect() as conn:
                row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
            return str(row[0]) if row else None
        except Exception:  # noqa: BLE001 — a missing table is the expected "not migrated"
            return None

    def table_names(self) -> set[str]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'")).all()
        return {str(r[0]) for r in rows}

    def dispose(self) -> None:
        self.engine.dispose()


def load_vector_extension(connection: Any) -> bool:
    """Load ``sqlite-vec`` into a raw DBAPI connection.

    Returns ``False`` rather than raising when the extension is unavailable: vector
    search is the nice-to-have and must degrade, never block (docs/13 §3.6).
    """
    try:
        import sqlite_vec
    except ImportError:
        log.info("sqlite-vec is not installed; vector search unavailable")
        return False

    try:
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.enable_load_extension(False)
    except (AttributeError, sqlite3.OperationalError) as exc:
        # Python built without extension support, or a platform without a wheel.
        log.warning("sqlite-vec could not be loaded (%s); falling back to keyword search", exc)
        return False
    return True
