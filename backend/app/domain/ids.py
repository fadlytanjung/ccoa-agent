"""Human-readable prefixed identifiers — docs/04 §3.2.

Agents read these aloud on calls and the model quotes them in answers, so they are
formatted for people rather than for uniqueness. Validation lives here so a malformed
identifier is rejected at the boundary and never reaches a query.
"""

from __future__ import annotations

import re
from typing import Annotated, Final

from pydantic import StringConstraints

CUSTOMER_ID_PATTERN: Final = r"^CUST-[0-9]{6}$"
POLICY_ID_PATTERN: Final = r"^POL-[0-9]{8}$"
CLAIM_ID_PATTERN: Final = r"^CLM-[0-9]{8}$"
INTERACTION_ID_PATTERN: Final = r"^INT-[0-9]{8}$"
CASE_ID_PATTERN: Final = r"^CASE-[0-9]{6}$"
TICKET_ID_PATTERN: Final = r"^TKT-[0-9]{6}$"
ARTICLE_ID_PATTERN: Final = r"^KB-[0-9]{4}$"

CustomerId = Annotated[str, StringConstraints(pattern=CUSTOMER_ID_PATTERN)]
PolicyId = Annotated[str, StringConstraints(pattern=POLICY_ID_PATTERN)]
ClaimId = Annotated[str, StringConstraints(pattern=CLAIM_ID_PATTERN)]
InteractionId = Annotated[str, StringConstraints(pattern=INTERACTION_ID_PATTERN)]
CaseId = Annotated[str, StringConstraints(pattern=CASE_ID_PATTERN)]
TicketId = Annotated[str, StringConstraints(pattern=TICKET_ID_PATTERN)]
ArticleId = Annotated[str, StringConstraints(pattern=ARTICLE_ID_PATTERN)]

#: prefix -> (width, compiled pattern). Ordered longest-prefix-first so ``CASE-`` is
#: never shadowed by a shorter prefix during detection.
_SPECS: Final[dict[str, tuple[int, re.Pattern[str]]]] = {
    "CUST": (6, re.compile(CUSTOMER_ID_PATTERN)),
    "POL": (8, re.compile(POLICY_ID_PATTERN)),
    "CLM": (8, re.compile(CLAIM_ID_PATTERN)),
    "INT": (8, re.compile(INTERACTION_ID_PATTERN)),
    "CASE": (6, re.compile(CASE_ID_PATTERN)),
    "TKT": (6, re.compile(TICKET_ID_PATTERN)),
    "KB": (4, re.compile(ARTICLE_ID_PATTERN)),
}

#: Maps an identifier prefix to the evidence/citation ``ref`` namespace (docs/05 §3.2).
REF_NAMESPACE: Final[dict[str, str]] = {
    "CUST": "customer",
    "POL": "policy",
    "CLM": "claim",
    "INT": "interaction",
    "CASE": "case",
    "TKT": "ticket",
    "KB": "kb",
}

_ANY_ID = re.compile(r"\b(CUST|POL|CLM|INT|CASE|TKT|KB)-[0-9]{4,8}\b")


def format_id(prefix: str, number: int) -> str:
    """Render ``number`` as an identifier of the given prefix.

    >>> format_id("CUST", 42)
    'CUST-000042'
    """
    try:
        width, _ = _SPECS[prefix]
    except KeyError:
        raise ValueError(f"unknown identifier prefix: {prefix!r}") from None
    if number < 0:
        raise ValueError(f"identifier number must be non-negative, got {number}")
    if len(str(number)) > width:
        raise ValueError(f"{number} does not fit in {width} digits for prefix {prefix!r}")
    return f"{prefix}-{number:0{width}d}"


def is_valid(value: str, prefix: str) -> bool:
    """True when ``value`` is a well-formed identifier of the given prefix."""
    spec = _SPECS.get(prefix)
    return spec is not None and spec[1].match(value) is not None


def detect_prefix(value: str) -> str | None:
    """Return the prefix of a well-formed identifier, or ``None``.

    Used by ``search_customer`` to decide whether free text is an identifier or a name.
    """
    for prefix, (_, pattern) in _SPECS.items():
        if pattern.match(value):
            return prefix
    return None


def to_ref(value: str) -> str | None:
    """Convert an identifier to its evidence ``ref``, e.g. ``customer:CUST-000042``."""
    prefix = detect_prefix(value)
    return f"{REF_NAMESPACE[prefix]}:{value}" if prefix else None


def extract_ids(text: str) -> list[str]:
    """Every well-formed identifier appearing in free text, in order of appearance.

    The grounding test uses this to assert that each identifier an answer mentions was
    actually gathered as evidence (docs/05 §3.12).
    """
    return [m.group(0) for m in _ANY_ID.finditer(text) if detect_prefix(m.group(0))]
