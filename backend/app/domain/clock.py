"""Time formatting — docs/04 §3.3.

Timestamps are ISO-8601 UTC strings with a ``Z`` suffix. SQLite has no date type; this
format sorts correctly as text and stays readable in the file.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def now() -> str:
    """Current instant, UTC, second precision."""
    return datetime.now(UTC).strftime(ISO_FORMAT)


def to_iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime(ISO_FORMAT)


def parse(value: str) -> datetime:
    """Parse a stored timestamp. Accepts the ``Z`` suffix that ``fromisoformat``
    only learned to handle in 3.11 — kept explicit so the contract is obvious."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def days_ago(value: str, *, reference: datetime | None = None) -> int:
    ref = reference or datetime.now(UTC)
    return max(0, (ref - parse(value)).days)


def shift(value: datetime, *, days: int = 0, hours: int = 0, minutes: int = 0) -> datetime:
    return value + timedelta(days=days, hours=hours, minutes=minutes)
