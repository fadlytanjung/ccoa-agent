"""Retrieval over interactions and knowledge-base articles — docs/13.

Semantic search is the nice-to-have. Everything here is written so that it improves
results when available and is invisible when not: the required path never depends on it,
and every result carries the method that produced it so a degraded answer can say so.
"""

from __future__ import annotations

import logging
from typing import Literal

from sqlalchemy import text as sql_text

from app.config import Settings
from app.db.engine import Database
from app.domain.models import ArticleHit, InteractionHit
from app.repositories import Repositories
from app.services.embeddings import DIMENSIONS, EmbeddingError, EmbeddingService, serialize

log = logging.getLogger(__name__)

Method = Literal["semantic", "keyword"]


class RetrievalService:
    """Chooses between semantic and keyword retrieval, and reports which it used."""

    def __init__(
        self,
        db: Database,
        repos: Repositories,
        settings: Settings,
        embeddings: EmbeddingService | None = None,
    ) -> None:
        self.db = db
        self.repos = repos
        self.settings = settings
        self.embeddings = embeddings or EmbeddingService(settings)
        self._semantic_enabled = settings.enable_vector_search and self._index_is_usable()
        if settings.enable_vector_search and not self._semantic_enabled:
            log.warning("vector search requested but unusable; keyword search will be used")

    @property
    def method(self) -> Method:
        return "semantic" if self._semantic_enabled else "keyword"

    def _index_is_usable(self) -> bool:
        """Check the index exists and was built by the configured model.

        A stale index is worse than none: it returns confident nonsense rather than
        nothing, so a mismatch forces the flag off (docs/13 §3.6).
        """
        try:
            tables = self.db.table_names()
        except Exception:  # noqa: BLE001 — an unreadable database means no vector search
            return False

        if not {"vec_interaction", "vec_kb", "vec_meta"} <= tables:
            log.info("vector tables absent; this image was built without an index")
            return False

        with self.db.session() as session:
            rows = session.execute(
                sql_text("SELECT table_name, model, dimensions FROM vec_meta")
            ).all()

        if not rows:
            log.warning("vec_meta is empty; treating the index as unbuilt")
            return False

        for table_name, model, dimensions in rows:
            if model != self.settings.gemini_embedding_model or int(dimensions) != DIMENSIONS:
                log.warning(
                    "vector index %s was built with %s/%s, configured for %s/%s — disabling",
                    table_name,
                    model,
                    dimensions,
                    self.settings.gemini_embedding_model,
                    DIMENSIONS,
                )
                return False
        return True

    # -- interactions ------------------------------------------------------
    def search_interactions(
        self, customer_id: str, query: str, limit: int = 5
    ) -> tuple[list[InteractionHit], Method]:
        """Find a customer's interactions about a topic.

        Always scoped to one customer. There is no cross-customer semantic search, so a
        query cannot surface another customer's transcript by construction rather than
        by filter discipline (docs/13 §3.5).
        """
        if self._semantic_enabled:
            try:
                hits = self._semantic_interactions(customer_id, query, limit)
            except EmbeddingError as exc:
                log.warning("embedding failed at query time (%s); falling back", exc)
            else:
                if hits:
                    return hits, "semantic"

        rows = self.repos.interactions.keyword_search(customer_id, query, limit=limit)
        return (
            [
                InteractionHit(
                    interaction_id=row.interaction_id,
                    subject=row.subject,
                    summary=row.summary,
                    occurred_at=row.occurred_at,
                    score=0.0,
                    method="keyword",
                )
                for row in rows
            ],
            "keyword",
        )

    def _semantic_interactions(
        self, customer_id: str, query: str, limit: int
    ) -> list[InteractionHit]:
        vector = serialize(self.embeddings.embed_query(query))
        with self.db.session() as session:
            rows = session.execute(
                sql_text(
                    """
                    SELECT i.interaction_id, i.subject, i.summary, i.occurred_at, v.distance
                    FROM vec_interaction v
                    JOIN interaction i ON i.interaction_id = v.interaction_id
                    WHERE v.embedding MATCH :vector AND k = :k
                      AND i.customer_id = :customer_id
                    ORDER BY v.distance
                    """
                ),
                {"vector": vector, "k": limit, "customer_id": customer_id},
            ).all()

        return [
            InteractionHit(
                interaction_id=row[0],
                subject=row[1],
                summary=row[2],
                occurred_at=row[3],
                score=round(1.0 - float(row[4]), 4),
                method="semantic",
            )
            for row in rows
        ]

    # -- knowledge base ----------------------------------------------------
    def search_kb(self, query: str, limit: int = 5) -> tuple[list[ArticleHit], Method]:
        if self._semantic_enabled:
            try:
                hits = self._semantic_kb(query, limit)
            except EmbeddingError as exc:
                log.warning("embedding failed at query time (%s); falling back", exc)
            else:
                if hits:
                    return hits, "semantic"

        return self.repos.kb.search(query, limit=limit), "keyword"

    def _semantic_kb(self, query: str, limit: int) -> list[ArticleHit]:
        from app.repositories.base import parse_failure_codes

        vector = serialize(self.embeddings.embed_query(query))
        with self.db.session() as session:
            rows = session.execute(
                sql_text(
                    """
                    SELECT a.article_id, a.title, a.body, a.applies_to, v.distance
                    FROM vec_kb v
                    JOIN kb_article a ON a.article_id = v.article_id
                    WHERE v.embedding MATCH :vector AND k = :k
                    ORDER BY v.distance
                    """
                ),
                {"vector": vector, "k": limit},
            ).all()

        return [
            ArticleHit(
                article_id=row[0],
                title=row[1],
                excerpt=" ".join(str(row[2]).split())[:320],
                applies_to=parse_failure_codes(row[3]),
                score=round(1.0 - float(row[4]), 4),
                method="semantic",
            )
            for row in rows
        ]
