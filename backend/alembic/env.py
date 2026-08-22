"""Alembic environment — docs/04 §3.7.

Two things here do real work:

* ``render_as_batch=True`` so autogenerate emits ``batch_alter_table``. SQLite cannot
  drop or alter a column and cannot add or remove a ``CHECK`` constraint; this schema
  leans on ``CHECK`` for every enumeration, so most changes need the copy-and-move
  dance that batch mode performs.
* The URL is resolved at runtime, never from ``alembic.ini``, so one revision set runs
  against the local file, the CI scratch database, and the container.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, event, pool

from app.db.schema import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.db.migration_filters import is_virtual_vector_table  # noqa: E402

target_metadata = Base.metadata


def _database_url() -> str:
    """``DATABASE_URL`` wins; otherwise the configured SQLite path.

    ``DATABASE_URL`` is a documented escape hatch, not an implemented second backend
    (ADR-006 §1a) — it exists so a migration can be pointed at a scratch database in CI.
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    from app.config import get_settings

    return f"sqlite+pysqlite:///{get_settings().db_path}"


def include_name(
    name: str | None,
    type_: str,
    parent_names: dict[str, str | None],
) -> bool:
    """Keep ``vec0`` virtual tables out of **reflection** — app.db.migration_filters."""
    del parent_names
    return not is_virtual_vector_table(name, type_)


def include_object(
    _object: object, name: str | None, type_: str, _reflected: bool, _compare_to: object
) -> bool:
    """Hide ``vec0`` virtual tables from autogenerate.

    SQLAlchemy cannot model a virtual table, so every ``alembic check`` would otherwise
    propose dropping ``vec_interaction`` and ``vec_kb``. Their plain-table companion
    ``vec_meta`` *is* modelled and stays in scope.
    """
    return not is_virtual_vector_table(name, type_)


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
        include_object=include_object,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    # SQLite defaults foreign_keys OFF; a migration that reshapes a table with batch
    # mode must have them enforced or it can leave dangling references.
    #
    # This is a *connect-time* listener rather than a statement on the connection for a
    # reason worth keeping: issuing any statement before ``context.configure`` opens an
    # implicit transaction, and since Alembic treats SQLite DDL as non-transactional,
    # the schema would commit while the ``alembic_version`` insert rolled back — a
    # migrated database that reports itself un-migrated.
    if connectable.dialect.name == "sqlite":

        @event.listens_for(connectable, "connect")
        def _enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            try:
                cursor.execute("PRAGMA foreign_keys = ON")
            finally:
                cursor.close()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
            include_object=include_object,
            include_name=include_name,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
