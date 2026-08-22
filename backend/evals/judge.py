"""The LLM that scores rubric-based and judged metrics — docs/19 §3.8.

DeepEval ships a native `GeminiModel`, and the obvious thing is to use it. It works for
`GEval`, and it **fails** for the conversational, safety, and agentic metrics: those
build a response schema containing a mapping, which serialises with
`additionalProperties`, and the Gemini API rejects that field outright:

    400 INVALID_ARGUMENT — Unknown name "additional_properties" at
    'generation_config.response_schema'

That is a provider incompatibility in DeepEval's Gemini path, not something wrong with
the metrics or with this agent. Every affected metric fails identically and immediately,
which is at least an honest failure rather than a wrong score.

The way around it is DeepEval's own **non-native** model path. When a metric is given a
custom `DeepEvalBaseLLM`, it stops asking the provider for schema-constrained output and
instead parses JSON out of the response — and its prompts already ask for JSON, because
that path is a supported one. So this adapter deliberately does *not* accept a `schema`
keyword: the base class tries it, gets a `TypeError`, and falls through to plain text.

The cost of the trade is real and worth stating: without provider-enforced schemas, a
malformed judge response becomes a parse error instead of being impossible. In practice
that shows up as a metric error, not a silent wrong score.
"""

from __future__ import annotations

from typing import Any

from deepeval.models import DeepEvalBaseLLM
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import Settings
from app.graph.messages import message_text


class GeminiJudge(DeepEvalBaseLLM):
    """A Gemini judge that returns text, and lets DeepEval do the parsing."""

    def __init__(
        self, settings: Settings, *, model: str | None = None, temperature: float = 0.0
    ) -> None:
        self._settings = settings
        self._temperature = temperature
        # The judge does not have to be the model under test. It is scoring, not being
        # scored, so a cheaper and less contended model here is a straight saving.
        self._model_name = model or settings.gemini_model
        super().__init__(model=self._model_name)

    def load_model(self, *args: Any, **kwargs: Any) -> ChatGoogleGenerativeAI:
        del args, kwargs
        return ChatGoogleGenerativeAI(
            model=self._model_name,
            google_api_key=self._settings.gemini_api_key.get_secret_value(),
            # Zero, so a re-run of the same trace scores the same way. Judge variance is
            # already the noisiest part of this suite; sampling would compound it.
            temperature=self._temperature,
            max_output_tokens=4096,
            timeout=self._settings.gemini_timeout_seconds,
            max_retries=1,
        )

    # Note the signature: no `schema` keyword, deliberately. See the module docstring.
    def generate(self, prompt: str, *args: Any, **kwargs: Any) -> str:
        del args, kwargs
        return message_text(self.model.invoke(prompt))

    async def a_generate(self, prompt: str, *args: Any, **kwargs: Any) -> str:
        del args, kwargs
        return message_text(await self.model.ainvoke(prompt))

    def get_model_name(self, *args: Any, **kwargs: Any) -> str:
        del args, kwargs
        return f"{self._model_name} (judge)"

    def supports_structured_outputs(self) -> bool:
        """False by design — this is the whole point of the adapter."""
        return False
