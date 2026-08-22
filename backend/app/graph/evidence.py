"""Turning tool results into evidence — docs/05 §3.2.

Evidence is stored **per record**, not per tool call. A `search_customer` that returns
two people produces two evidence entries, so the answer can cite one of them without
implicitly citing the other, and so the de-duplicating reducer can tell that a customer
already fetched by `get_customer` is the same record.
"""

from __future__ import annotations

from typing import Any

from app.domain import clock
from app.graph.state import Evidence
from app.graph.tools.result import ToolResult

#: Keys that hold a record's identifier, so an entry can be matched to its ref.
_ID_KEYS = (
    "customer_id",
    "policy_id",
    "claim_id",
    "interaction_id",
    "case_id",
    "ticket_id",
    "article_id",
)


def _find_record(payload: Any, identifier: str) -> dict[str, Any] | None:
    """Depth-first search for the dict that *is* the record with this identifier."""
    if isinstance(payload, dict):
        for key in _ID_KEYS:
            if payload.get(key) == identifier:
                return payload
        for value in payload.values():
            if found := _find_record(value, identifier):
                return found
    elif isinstance(payload, list):
        for item in payload:
            if found := _find_record(item, identifier):
                return found
    return None


def from_result(source: str, args: dict[str, Any], result: ToolResult) -> list[Evidence]:
    """Build evidence entries for one tool call.

    A failed call produces none: an error is something the graph routes on, not a fact
    the answer may assert.
    """
    if not result.ok or result.data is None:
        return []

    at = clock.now()
    if not result.refs:
        return []

    entries: list[Evidence] = []
    for ref in result.refs:
        identifier = ref.split(":", 1)[1] if ":" in ref else ref
        record = _find_record(result.data, identifier)
        entries.append(
            Evidence(
                ref=ref,
                source=source,
                args=dict(args),
                # Falling back to the whole payload keeps the citation honest when the
                # ref names something the result does not carry as its own record —
                # a reference document, for instance.
                result=record if record is not None else result.data,
                at=at,
            )
        )
    return entries


def summarise_args(args: dict[str, Any]) -> str:
    """A short, PII-free rendering for the SSE `tool` event and the log.

    Identifiers and enumerations are safe to show; a free-text query may contain a
    customer's name, so it is reduced to its length (docs/04 §3.8).
    """
    parts: list[str] = []
    for key, value in sorted(args.items()):
        if value is None:
            continue
        if key in _ID_KEYS or key in ("status", "channel", "skill", "path", "limit"):
            parts.append(f"{key}={value}")
        elif isinstance(value, str):
            parts.append(f"{key}=<{len(value)} chars>")
        else:
            parts.append(f"{key}={value}")
    return ", ".join(parts)
