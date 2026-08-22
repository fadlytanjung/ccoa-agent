"""A scripted model — docs/05 §3.12.

The suite is deterministic and offline because the model is injected, exactly as the
checkpointer is. This stub implements only the three methods the graph actually calls
(``invoke``, ``with_structured_output``, ``bind_tools``), which keeps it small enough to
read and prevents it from quietly diverging into a second implementation of LangChain.

Scripting is explicit: a test says what the model returns, in order. Anything not
scripted falls back to a harmless default, so a test only has to describe the part of
the conversation it cares about.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel

DEFAULT_TEXT = "Stubbed answer."


class _StructuredView:
    """What ``with_structured_output(schema)`` returns."""

    def __init__(self, parent: StubModel, schema: type[BaseModel]) -> None:
        self._parent = parent
        self._schema = schema

    def invoke(self, messages: list[BaseMessage], **_: Any) -> BaseModel:
        self._parent.prompts.append(messages)
        queue = self._parent.structured[self._schema]
        if queue:
            return queue.popleft()
        raise AssertionError(
            f"StubModel has no scripted {self._schema.__name__}; "
            f"call stub.script_structured(...) in the test"
        )


class StubModel:
    """Stands in for ``BaseChatModel`` wherever the graph binds one."""

    def __init__(self) -> None:
        self.messages: deque[AIMessage] = deque()
        self.structured: defaultdict[type[BaseModel], deque[BaseModel]] = defaultdict(deque)
        #: Every prompt the graph built, for assertions about layering and grounding.
        self.prompts: list[list[BaseMessage]] = []
        self.bound_tools: list[str] = []

    # -- scripting ---------------------------------------------------------
    def script(self, *messages: AIMessage | str) -> StubModel:
        for message in messages:
            self.messages.append(
                AIMessage(content=message) if isinstance(message, str) else message
            )
        return self

    def script_structured(self, *values: BaseModel) -> StubModel:
        for value in values:
            self.structured[type(value)].append(value)
        return self

    def script_tool_call(
        self, name: str, args: dict[str, Any], *, call_id: str = "call-1"
    ) -> StubModel:
        self.messages.append(
            AIMessage(
                content="",
                tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
            )
        )
        return self

    # -- the surface the graph uses ---------------------------------------
    def invoke(self, messages: list[BaseMessage], **_: Any) -> AIMessage:
        self.prompts.append(messages)
        if self.messages:
            return self.messages.popleft()
        return AIMessage(content=DEFAULT_TEXT)

    def with_structured_output(self, schema: type[BaseModel], **_: Any) -> _StructuredView:
        return _StructuredView(self, schema)

    def bind_tools(self, tools: list[Any], **_: Any) -> StubModel:
        self.bound_tools = [getattr(tool, "name", str(tool)) for tool in tools]
        return self

    # -- assertions helpers ------------------------------------------------
    def last_prompt_text(self) -> str:
        if not self.prompts:
            return ""
        return "\n".join(str(m.content) for m in self.prompts[-1])

    def all_prompt_text(self) -> str:
        return "\n".join(str(m.content) for prompt in self.prompts for m in prompt)
