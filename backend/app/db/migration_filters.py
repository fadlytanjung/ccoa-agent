"""Which database objects Alembic may look at — docs/04 §3.7, docs/13 §3.1.

Here rather than in ``alembic/env.py`` because that file runs migrations at import time
and therefore cannot be imported by a test. The rules are small but load-bearing, and
both of them exist for the same pair of tables.

``vec_interaction`` and ``vec_kb`` are ``vec0`` **virtual** tables, created by migration
SQL rather than by a SQLAlchemy model. Two consequences:

* autogenerate would propose dropping them on every run, because nothing in the metadata
  claims them — that is what :func:`include_object` prevents;
* reflecting one issues ``PRAGMA table_xinfo``, which fails with ``no such module: vec0``
  on a connection that has not loaded the sqlite-vec extension. Alembic's connection has
  not. That is what :func:`include_name` prevents, and it has to be a separate filter
  because ``include_object`` is only consulted *after* reflection has already happened.

The second only shows up where the virtual tables actually exist, which is anywhere
sqlite-vec loads — CI, and the container. On a machine where the extension is missing the
migration skips them and everything appears fine, so this is precisely the class of defect
that reaches CI green from a laptop.
"""

from __future__ import annotations

#: The plain, modelled companion table. It stays in scope for both filters.
VECTOR_META_TABLE = "vec_meta"

#: Prefix shared by the virtual tables and their metadata companion.
VECTOR_PREFIX = "vec_"


def is_virtual_vector_table(name: str | None, type_: str) -> bool:
    """True for a ``vec0`` virtual table, false for everything else including `vec_meta`."""
    if type_ != "table" or name is None:
        return False
    return name.startswith(VECTOR_PREFIX) and name != VECTOR_META_TABLE
