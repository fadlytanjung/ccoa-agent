"""Shared repository plumbing — docs/04 §3.6.

Repositories are the only code that speaks SQL, and they return Pydantic models rather
than rows. Three rules from the spec are implemented here rather than left to
discipline:

1. **Search returns candidates, never a guess.** Enforced by the return types —
   ``search_by_name`` returns a list, and nothing in the layer picks a winner.
2. **Reads are bounded by an explicit limit**, clamped by :func:`clamp_limit` so a
   chatty customer cannot flood the model's context.
3. **Writes go through a transaction that also writes the audit row** — see
   :class:`app.repositories.audit.AuditRepository` and ``Database.transaction``.
"""

from __future__ import annotations

from typing import Final

from app.db.engine import Database
from app.domain.enums import FailureCode

#: Read defaults. Small on purpose: an agent asking "what happened recently" wants the
#: last handful, and the model pays for every row it is shown.
DEFAULT_LIMIT: Final = 10
MAX_LIMIT: Final = 100


def clamp_limit(limit: int | None, *, default: int = DEFAULT_LIMIT) -> int:
    """Coerce a caller-supplied limit into ``1..MAX_LIMIT``.

    Clamped rather than rejected: a model that asks for 5000 interactions has made a
    judgement error, not an input error, and failing the tool call would cost a turn to
    recover from something the graph can simply bound.
    """
    if limit is None:
        return default
    return max(1, min(int(limit), MAX_LIMIT))


def parse_failure_codes(raw: str | None) -> tuple[FailureCode, ...]:
    """Parse ``kb_article.applies_to`` — a comma-separated failure-code list.

    Unknown values are dropped rather than raising: a KB article referencing a retired
    code should still be readable.
    """
    if not raw:
        return ()
    codes = []
    for part in raw.split(","):
        token = part.strip()
        if token in FailureCode.__members__.values():
            codes.append(FailureCode(token))
    return tuple(codes)


def format_failure_codes(codes: tuple[FailureCode, ...]) -> str | None:
    return ",".join(c.value for c in codes) if codes else None


class Repository:
    """Base for every repository: holds the database, nothing else."""

    def __init__(self, db: Database) -> None:
        self.db = db
