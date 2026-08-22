"""The single place a model handle is constructed — docs/05 §3.9.

Every model in the system comes from here. Swapping to Bedrock (ADR-001) or Vertex AI
touches this file and nothing else, which is the only thing that makes "the LLM is
swappable" more than a claim.
"""

from __future__ import annotations

import logging
from typing import Protocol

from langchain_core.language_models import BaseChatModel

from app.config import Settings

log = logging.getLogger(__name__)


class ModelFactory(Protocol):
    """Builds a model handle for a skill's settings.

    A Protocol rather than a concrete class so tests inject a stub that returns scripted
    tool calls — the same injection rule as the checkpointer (docs/14 §3.1).
    """

    def __call__(
        self,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_output_tokens: int = 2048,
    ) -> BaseChatModel: ...


class GeminiModelFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cache: dict[tuple[str, float, int], BaseChatModel] = {}

    def __call__(
        self,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_output_tokens: int = 2048,
    ) -> BaseChatModel:
        key = (model or self._settings.gemini_model, temperature, max_output_tokens)
        if key not in self._cache:
            self._cache[key] = self._build(*key)
        return self._cache[key]

    def _build(self, model: str, temperature: float, max_output_tokens: int) -> BaseChatModel:
        from langchain_google_genai import ChatGoogleGenerativeAI

        api_key = self._settings.gemini_api_key.get_secret_value()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set; the graph cannot call a model")

        log.info("binding model %s temperature=%s", model, temperature)
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            timeout=self._settings.gemini_timeout_seconds,
            # Retry policy lives in the graph's error handler, where it can be
            # observed, budgeted, and tested. A retry hidden inside the client is
            # none of those (docs/05 §3.9).
            max_retries=0,
        )


def build_model_factory(settings: Settings) -> ModelFactory:
    return GeminiModelFactory(settings)
