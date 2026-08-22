"""Reading text out of a model message.

``AIMessage.content`` is not reliably a string. Gemini 3 returns a list of content
blocks — text parts alongside reasoning signatures and other provider metadata — and
``str(message.content)`` on that produces the *repr of a list*, which is how an
opaque base64 blob ends up in front of a support agent.

This module is the one place that knows the shape, so nothing downstream has to.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage

#: Block types that carry text. Anything else — reasoning signatures, tool-use blocks,
#: provider extras — is metadata and must not reach the user.
_TEXT_TYPES = frozenset({"text", "output_text"})


def _is_text_block(block: dict[str, Any]) -> bool:
    """A block carries text if it says so, or if it has text and no type at all."""
    return block.get("type") in _TEXT_TYPES or ("text" in block and "type" not in block)


def content_text(content: Any) -> str:
    """Flatten message content to the text a human should read."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and _is_text_block(block):
                parts.append(str(block.get("text", "")))
        return "\n".join(p for p in parts if p).strip()
    return str(content)


def message_text(message: BaseMessage) -> str:
    return content_text(message.content)
