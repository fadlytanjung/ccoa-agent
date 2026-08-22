"""Identifier allocation for the seed — docs/12 §3.3.

Identifiers are sequential so they are stable across runs and readable in a demo. The
complication is that docs/12 §3.4 *plants* specific identifiers — ``CLM-00000117`` must
be the failed claim, ``CASE-000008`` must be the case with no ticket — and those numbers
cannot be reached by hoping the generator's ratios land on them.

So numbers are **reserved up front and skipped by ordinary allocation**. Everything
stays sequential and dense; the reserved numbers are simply held back until the record
that owns them is generated. A ratio change elsewhere in the generator therefore cannot
silently move a planted record onto a different identifier.
"""

from __future__ import annotations

from app.domain.ids import format_id


class IdAllocator:
    """Hands out sequential identifiers for one prefix, honouring reservations."""

    def __init__(self, prefix: str, reserved: set[int] | None = None) -> None:
        self.prefix = prefix
        self._reserved = set(reserved or ())
        self._claimed: set[int] = set()
        self._cursor = 0

    def next(self) -> str:
        """The next unreserved, unclaimed number."""
        while True:
            self._cursor += 1
            if self._cursor not in self._reserved and self._cursor not in self._claimed:
                self._claimed.add(self._cursor)
                return format_id(self.prefix, self._cursor)

    def take(self, number: int) -> str:
        """Claim a specific reserved number.

        Raises if the number was never reserved or has already been taken — either
        would mean a planted scenario silently lost its identifier, which is exactly
        the failure this class exists to prevent.
        """
        if number not in self._reserved:
            raise ValueError(f"{self.prefix}-{number} was not reserved")
        if number in self._claimed:
            raise ValueError(f"{self.prefix}-{number} was already taken")
        self._claimed.add(number)
        return format_id(self.prefix, number)

    @property
    def count(self) -> int:
        return len(self._claimed)

    def unclaimed_reservations(self) -> set[int]:
        return self._reserved - self._claimed
