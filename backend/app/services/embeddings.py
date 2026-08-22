"""Gemini embeddings — docs/13 §3.2.

Asymmetric task types matter: embedding a short query as ``RETRIEVAL_QUERY`` and a long
summary as ``RETRIEVAL_DOCUMENT`` measurably beats using one type for both, and costs
nothing extra.
"""

from __future__ import annotations

import logging
import struct
from typing import Final

from app.config import Settings

log = logging.getLogger(__name__)

#: Truncated from the model's native output. Recall at ~650 documents is
#: indistinguishable, and storage and scan cost drop proportionally (docs/13 §3.2).
DIMENSIONS: Final = 768

TASK_DOCUMENT: Final = "RETRIEVAL_DOCUMENT"
TASK_QUERY: Final = "RETRIEVAL_QUERY"


class EmbeddingError(RuntimeError):
    """The embedding call failed. Callers degrade; they do not propagate."""


def serialize(vector: list[float]) -> bytes:
    """Pack a vector into the little-endian float32 blob ``sqlite-vec`` expects."""
    return struct.pack(f"<{len(vector)}f", *vector)


def l2_normalise(vector: list[float]) -> list[float]:
    """Normalise so cosine distance reduces to a dot product at query time."""
    magnitude = sum(component * component for component in vector) ** 0.5
    if magnitude == 0:
        return vector
    return [component / magnitude for component in vector]


class EmbeddingService:
    """Wraps the Gemini embedding model.

    Constructed lazily: a process with vector search disabled — which is the default,
    and the whole of CI — never builds a client and never needs a key.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: object | None = None

    def _ensure_client(self) -> object:
        if self._client is None:
            key = self._settings.gemini_api_key.get_secret_value()
            if not key:
                raise EmbeddingError("no Gemini API key configured")
            try:
                from langchain_google_genai import GoogleGenerativeAIEmbeddings
            except ImportError as exc:  # pragma: no cover - dependency is pinned
                raise EmbeddingError(f"embedding library unavailable: {exc}") from exc

            self._client = GoogleGenerativeAIEmbeddings(
                model=self._settings.gemini_embedding_model,
                google_api_key=key,
            )
        return self._client

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text, TASK_QUERY)

    def embed_document(self, text: str) -> list[float]:
        return self._embed(text, TASK_DOCUMENT)

    def embed_documents(self, texts: list[str], *, batch_size: int = 100) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            vectors.extend(self._embed(text, TASK_DOCUMENT) for text in batch)
        return vectors

    def _embed(self, text: str, task_type: str) -> list[float]:
        client = self._ensure_client()
        try:
            raw = client.embed_query(text, task_type=task_type)  # type: ignore[attr-defined]
        except TypeError:
            # Older bindings do not accept task_type. Symmetric embedding is worse but
            # still works, so this degrades rather than failing the query.
            log.debug("embedding binding does not support task_type; using symmetric")
            raw = client.embed_query(text)  # type: ignore[attr-defined]
        except Exception as exc:  # network, quota, and auth all degrade the same way
            raise EmbeddingError(str(exc)) from exc

        vector = [float(value) for value in raw][:DIMENSIONS]
        if len(vector) < DIMENSIONS:
            raise EmbeddingError(f"expected at least {DIMENSIONS} dimensions, got {len(vector)}")
        return l2_normalise(vector)
