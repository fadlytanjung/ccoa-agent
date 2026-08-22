"""Input guard — the cheapest node in the graph, and the first.

Rejects malformed or hostile input **before spending a model call**. Heuristics only:
docs/05 §6 question 1 records the decision not to spend a classifier call on every turn
for injection detection, and that decision stands until a demo shows real attempts
mattering.

The heuristics are deliberately narrow. A guard that blocks anything resembling an
instruction would block a support agent typing "ignore the closed cases and show me the
open one", which is a normal thing to say.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Final

from app.graph.state import (
    TURN_SCOPED_RESET,
    AgentState,
    ToolErrorState,
    latest_user_message,
)

log = logging.getLogger(__name__)

MAX_MESSAGE_CHARS: Final = 4000
MIN_MESSAGE_CHARS: Final = 1

#: Control characters other than tab and newline. Their presence in a chat message is
#: not a typing accident.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

#: Markers that attempt to redefine the system's instructions. Matched as phrases, not
#: as individual words, so ordinary imperative English passes.
_INJECTION_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"ignore (?:all |any |the )?(?:previous|prior|above) instructions", re.I),
    re.compile(r"disregard (?:all |any |the )?(?:previous|prior|above)", re.I),
    re.compile(r"you are now (?:a|an|the)\b", re.I),
    re.compile(r"\bsystem prompt\b", re.I),
    re.compile(r"reveal (?:your|the) (?:instructions|prompt|rules)", re.I),
    re.compile(r"<\s*/?\s*(?:system|assistant)\s*>", re.I),
)


def _rejection(code: str, message: str) -> ToolErrorState:
    return ToolErrorState(error_class="invalid_input", code=code, message=message, node="guard")


def check(text: str) -> ToolErrorState | None:
    """Return a rejection, or ``None`` when the input is acceptable."""
    stripped = text.strip()

    if len(stripped) < MIN_MESSAGE_CHARS:
        return _rejection("empty_message", "The message is empty.")

    if len(stripped) > MAX_MESSAGE_CHARS:
        return _rejection(
            "message_too_long",
            f"The message is {len(stripped)} characters; the limit is {MAX_MESSAGE_CHARS}.",
        )

    if _CONTROL.search(text):
        return _rejection("invalid_characters", "The message contains control characters.")

    for pattern in _INJECTION_PATTERNS:
        if pattern.search(stripped):
            # Logged without the message body: the text is the customer's or the
            # agent's, and PII never reaches the log (docs/04 §3.8).
            log.warning("guard rejected a message matching %s", pattern.pattern)
            return _rejection(
                "rejected_input",
                "That message looks like an attempt to change how this assistant works, "
                "so it was not processed.",
            )

    return None


def guard(state: AgentState) -> dict[str, Any]:
    """Validate the incoming message and reset everything that is turn-scoped.

    The reset belongs here rather than in the caller because ``guard`` is the only node
    guaranteed to run exactly once per turn — resume re-enters at ``human``, not at
    ``START``, so a reset in the API layer would wipe a pending approval.
    """
    return {**TURN_SCOPED_RESET, "error": check(latest_user_message(state))}


def route_guard(state: AgentState) -> str:
    """Rejected input skips straight to the response — no model call is made."""
    return "respond" if state.get("error") else "orchestrator"
