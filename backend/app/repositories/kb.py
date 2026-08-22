"""Knowledge-base access — the remediation half of an investigation."""

from __future__ import annotations

import re

from sqlalchemy import select

from app.db import schema
from app.domain.models import Article, ArticleHit
from app.repositories.base import Repository, clamp_limit, parse_failure_codes

_WORD = re.compile(r"[A-Za-z0-9_]+")
#: Words too common to discriminate between 40 articles.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "can",
        "does",
        "do",
        "for",
        "how",
        "in",
        "is",
        "my",
        "of",
        "on",
        "or",
        "our",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "with",
    }
)


def _to_article(row: schema.KbArticle) -> Article:
    return Article(
        article_id=row.article_id,
        title=row.title,
        category=row.category,
        body=row.body,
        applies_to=parse_failure_codes(row.applies_to),
        updated_at=row.updated_at,
    )


def _excerpt(body: str, limit: int = 320) -> str:
    text = " ".join(body.split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


class KbRepository(Repository):
    def get(self, article_id: str) -> Article | None:
        with self.db.session() as s:
            row = s.get(schema.KbArticle, article_id)
            return _to_article(row) if row else None

    def for_failure_code(self, code: str) -> list[Article]:
        """Articles whose ``applies_to`` contains ``code``.

        This is the highest-value hop in the investigation flow: a failed claim has a
        code, and the code has a remediation article (docs/12 §3.5).
        """
        with self.db.session() as s:
            rows = s.scalars(
                select(schema.KbArticle)
                .where(schema.KbArticle.applies_to.like(f"%{code}%"))
                .order_by(schema.KbArticle.article_id)
            ).all()
        # The LIKE above is a prefilter; substring matching would make DOC_MISSING
        # match a hypothetical DOC_MISSING_PAGES, so membership is re-checked exactly.
        articles = [_to_article(r) for r in rows]
        return [a for a in articles if code in {c.value for c in a.applies_to}]

    def search(self, query: str, limit: int | None = None) -> list[ArticleHit]:
        """Keyword search over titles, bodies, and failure codes.

        Ranking is deliberately simple — term overlap, weighted towards the title, with
        an exact failure-code match dominating. At 40 articles anything cleverer would
        be untestable ceremony; semantic search is the upgrade path (docs/13 §3.7).
        """
        term = query.strip()
        if not term:
            return []
        bound = clamp_limit(limit, default=5)

        tokens = {w.lower() for w in _WORD.findall(term)} - _STOPWORDS
        upper = term.upper()

        with self.db.session() as s:
            rows = s.scalars(select(schema.KbArticle)).all()

        scored: list[tuple[float, ArticleHit]] = []
        for row in rows:
            article = _to_article(row)
            codes = {c.value for c in article.applies_to}
            score = 0.0

            # An exact failure code is not a keyword match, it is the answer.
            if any(code in upper for code in codes):
                score += 10.0

            title_words = {w.lower() for w in _WORD.findall(article.title)}
            body_words = {w.lower() for w in _WORD.findall(article.body)}
            score += 2.0 * len(tokens & title_words)
            score += 1.0 * len(tokens & body_words)

            if score > 0:
                scored.append(
                    (
                        score,
                        ArticleHit(
                            article_id=article.article_id,
                            title=article.title,
                            excerpt=_excerpt(article.body),
                            applies_to=article.applies_to,
                            score=score,
                            method="keyword",
                        ),
                    )
                )

        scored.sort(key=lambda pair: (-pair[0], pair[1].article_id))
        return [hit for _, hit in scored[:bound]]

    def all_articles(self) -> list[Article]:
        """Every article, ordered. Used by the seed verifier and the vector indexer."""
        with self.db.session() as s:
            rows = s.scalars(select(schema.KbArticle).order_by(schema.KbArticle.article_id)).all()
        return [_to_article(r) for r in rows]
