"""Conversation threads — docs/04 §3.4a.

Ownership is enforced by returning ``None`` for a thread the caller does not own, rather
than by returning it with a flag. The API turns that into a ``404``: a ``403`` would
confirm the thread exists (docs/06 §3.3).
"""

from __future__ import annotations

import base64
import binascii

from sqlalchemy import delete, literal, select, tuple_
from sqlalchemy.orm import Session

from app.db import schema
from app.domain import clock
from app.domain.models import DomainModel
from app.repositories.base import Repository, clamp_limit

#: A conversation list is browsed, not paged through in bulk; 30 fills a sidebar.
DEFAULT_PAGE = 30

#: Separator for the encoded cursor. Neither an ISO-8601 timestamp nor a ``th_``-prefixed
#: hex id can contain it, so splitting is unambiguous.
_CURSOR_SEPARATOR = "|"


def encode_cursor(updated_at: str, thread_id: str) -> str:
    """Encode a keyset anchor.

    Base64 rather than the raw pair, to make it plain that the value is **opaque**.
    Clients that parse a cursor become dependent on the sort key, and then the sort key
    can never change; an unreadable string is the cheapest way to keep that door shut.
    It is not a security measure — it encodes only data the caller already has.
    """
    raw = f"{updated_at}{_CURSOR_SEPARATOR}{thread_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[str, str] | None:
    """Decode a cursor, treating anything malformed as "start from the beginning".

    A cursor arrives from a URL, so it can be truncated, stale, or hand-edited. None of
    that warrants a 400: the honest response to an uninterpretable position is the first
    page, which is exactly what a client with a bad cursor needs to recover.
    """
    if not cursor:
        return None
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    updated_at, separator, thread_id = raw.partition(_CURSOR_SEPARATOR)
    if not separator or not updated_at or not thread_id:
        return None
    return updated_at, thread_id


class Thread(DomainModel):
    thread_id: str
    owner_sub: str
    title: str
    subject_customer_id: str | None = None
    message_count: int = 0
    created_at: str
    updated_at: str


class ThreadPage(DomainModel):
    """One page, plus where to continue from.

    ``next_cursor is None`` means the last page — the client stops on that rather than on
    a short page, which under a keyset scheme is not the same thing.
    """

    items: list[Thread]
    next_cursor: str | None = None


def _to_thread(row: schema.Thread) -> Thread:
    return Thread(
        thread_id=row.thread_id,
        owner_sub=row.owner_sub,
        title=row.title,
        subject_customer_id=row.subject_customer_id,
        message_count=row.message_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ThreadRepository(Repository):
    def create(self, session: Session, *, thread_id: str, owner_sub: str, title: str) -> Thread:
        stamp = clock.now()
        row = schema.Thread(
            thread_id=thread_id,
            owner_sub=owner_sub,
            title=title,
            subject_customer_id=None,
            message_count=0,
            created_at=stamp,
            updated_at=stamp,
        )
        session.add(row)
        session.flush()
        return _to_thread(row)

    def get_owned(self, thread_id: str, owner_sub: str) -> Thread | None:
        with self.db.session() as s:
            row = s.get(schema.Thread, thread_id)
            if row is None or row.owner_sub != owner_sub:
                return None
            return _to_thread(row)

    def list_for_owner(self, owner_sub: str, limit: int | None = None) -> list[Thread]:
        return self.page_for_owner(owner_sub, limit=limit).items

    def page_for_owner(
        self, owner_sub: str, *, limit: int | None = None, cursor: str | None = None
    ) -> ThreadPage:
        """One page of the owner's threads, newest activity first.

        **Keyset, not offset.** The sort key is ``updated_at``, and sending a message
        rewrites it — so between two requests a thread the user is actively working in
        jumps to the front and pushes every later row down one. With ``OFFSET`` that row
        shift is invisible and lossy: page 2 silently skips whatever slid across the
        boundary. Anchoring to the last row the client actually received cannot skip,
        because the anchor moves with the data.

        ``updated_at`` alone is not unique — seeded threads share a timestamp to the
        microsecond — so ``thread_id`` breaks the tie in both the ordering and the
        comparison. Without it, a page boundary landing inside a group of equal
        timestamps drops the rest of that group.
        """
        size = clamp_limit(limit, default=DEFAULT_PAGE)
        stmt = (
            select(schema.Thread)
            .where(schema.Thread.owner_sub == owner_sub)
            .order_by(schema.Thread.updated_at.desc(), schema.Thread.thread_id.desc())
            # One extra row is what tells us whether a next page exists, without a
            # second COUNT query that could disagree with this one under concurrency.
            .limit(size + 1)
        )
        anchor = decode_cursor(cursor)
        if anchor is not None:
            updated_at, thread_id = anchor
            stmt = stmt.where(
                tuple_(schema.Thread.updated_at, schema.Thread.thread_id)
                < tuple_(literal(updated_at), literal(thread_id))
            )

        with self.db.session() as s:
            rows = [_to_thread(r) for r in s.scalars(stmt).all()]

        has_more = len(rows) > size
        items = rows[:size]
        next_cursor = (
            encode_cursor(items[-1].updated_at, items[-1].thread_id) if has_more and items else None
        )
        return ThreadPage(items=items, next_cursor=next_cursor)

    def touch(
        self,
        session: Session,
        thread_id: str,
        *,
        subject_customer_id: str | None = None,
        title: str | None = None,
        increment: int = 1,
    ) -> None:
        row = session.get(schema.Thread, thread_id)
        if row is None:
            return
        row.updated_at = clock.now()
        row.message_count += increment
        if subject_customer_id:
            row.subject_customer_id = subject_customer_id
        # The title is set from the first message and then left alone: a list that
        # renames itself as the conversation drifts is harder to navigate, not easier.
        if title and row.title == UNTITLED:
            row.title = title

    def delete(self, session: Session, thread_id: str, owner_sub: str) -> bool:
        row = session.get(schema.Thread, thread_id)
        if row is None or row.owner_sub != owner_sub:
            return False
        session.execute(delete(schema.Thread).where(schema.Thread.thread_id == thread_id))
        return True


UNTITLED = "New conversation"
