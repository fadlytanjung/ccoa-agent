"""Conversation routes — docs/06 §3.2, §3.4, §3.5."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.api.deps import AgentActor
from app.api.sse import stream_turn
from app.domain.actor import Actor
from app.domain.errors import Conflict, NotFound
from app.domain.models import DomainModel
from app.graph.messages import content_text
from app.graph.state import initial_state
from app.repositories import Repositories
from app.repositories.thread import DEFAULT_PAGE, UNTITLED, Thread
from app.telemetry import get_logger, get_trace_id

log = get_logger(__name__)
router = APIRouter(prefix="/threads", tags=["threads"])

#: Heartbeat interval. The ALB idle timeout is raised to 120 s, but a long investigation
#: can still out-wait a default, and a silent stream looks like a hang (docs/06 §3.4).
PING_SECONDS = 15

MAX_MESSAGE_CHARS = 4000


class CreateThreadRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class MessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class ResumeRequest(BaseModel):
    """Free-form by design — a resume payload is a conversation, not a boolean.

    ``approved`` is only meaningful for an ``approve`` or ``confirm`` checkpoint; a
    ``clarify`` reply carries ``text`` or ``selection`` (docs/05 §3.7).
    """

    kind: str = "approve"
    approved: bool | None = None
    note: str | None = Field(default=None, max_length=2000)
    text: str | None = Field(default=None, max_length=MAX_MESSAGE_CHARS)
    selection: str | None = Field(default=None, max_length=64)
    remember: bool = False


class ThreadSummary(DomainModel):
    """What the list view shows. Deliberately without ``owner_sub`` — the caller is the
    owner by construction, and echoing another identifier back adds nothing."""

    thread_id: str
    title: str
    subject_customer_id: str | None = None
    message_count: int
    created_at: str
    updated_at: str


class ThreadListResponse(DomainModel):
    """A page of conversations.

    An envelope rather than a bare array: the cursor has to travel with the page, and a
    JSON array has nowhere to put it. Response headers were the alternative and are
    worse — they do not survive the generated TypeScript client, so the SPA would have
    had to reach around its own API layer to paginate.
    """

    items: list[ThreadSummary]
    next_cursor: str | None = None


class MessageView(DomainModel):
    role: str
    content: str


class ThreadState(DomainModel):
    thread_id: str
    messages: list[MessageView]
    subject_customer_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    pending_ask: dict[str, Any] | None = None
    intent: str | None = None


def _repos(request: Request) -> Repositories:
    return request.app.state.repos  # type: ignore[no-any-return]


def _graph(request: Request) -> CompiledStateGraph[Any, Any, Any, Any]:
    return request.app.state.graph  # type: ignore[no-any-return]


def _summary(thread: Thread) -> ThreadSummary:
    return ThreadSummary(
        thread_id=thread.thread_id,
        title=thread.title,
        subject_customer_id=thread.subject_customer_id,
        message_count=thread.message_count,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )


def _owned(request: Request, thread_id: str, actor: Actor) -> Thread:
    thread = _repos(request).threads.get_owned(thread_id, actor.sub)
    if thread is None:
        # 404 rather than 403: a 403 would confirm the thread exists (docs/06 §3.3).
        raise NotFound("thread_not_found", f"No thread {thread_id} for this user.")
    return thread


def _config(request: Request, thread_id: str, actor: Actor) -> RunnableConfig:
    del request
    return RunnableConfig(
        configurable={
            "thread_id": thread_id,
            "actor": actor.to_config(),
            "trace_id": get_trace_id(),
        }
    )


@router.post("", status_code=201)
def create_thread(request: Request, body: CreateThreadRequest, actor: AgentActor) -> ThreadSummary:
    thread_id = f"th_{uuid.uuid4().hex[:24]}"
    repos = _repos(request)
    with repos.db.transaction() as session:
        thread = repos.threads.create(
            session,
            thread_id=thread_id,
            owner_sub=actor.sub,
            title=(body.title or UNTITLED).strip() or UNTITLED,
        )
    log.info("thread created", thread_id=thread_id)
    return _summary(thread)


@router.get("")
def list_threads(
    request: Request,
    actor: AgentActor,
    limit: Annotated[int, Query(ge=1, le=100)] = DEFAULT_PAGE,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
) -> ThreadListResponse:
    """List the caller's conversations, newest activity first.

    Paginated with an opaque ``cursor`` rather than a page number — see
    ``ThreadRepository.page_for_owner`` for why an offset silently loses rows here.
    Follow ``next_cursor`` until it is ``null``.
    """
    page = _repos(request).threads.page_for_owner(actor.sub, limit=limit, cursor=cursor)
    return ThreadListResponse(
        items=[_summary(row) for row in page.items], next_cursor=page.next_cursor
    )


@router.get("/{thread_id}")
async def get_thread(request: Request, thread_id: str, actor: AgentActor) -> ThreadState:
    _owned(request, thread_id, actor)
    return await _read_state(request, thread_id, actor)


@router.get("/{thread_id}/state")
async def get_thread_state(request: Request, thread_id: str, actor: AgentActor) -> ThreadState:
    _owned(request, thread_id, actor)
    return await _read_state(request, thread_id, actor)


async def _read_state(request: Request, thread_id: str, actor: Actor) -> ThreadState:
    # `aget_state`, not `get_state`: the checkpointer is an AsyncSqliteSaver and
    # refuses synchronous access from the event loop's own thread.
    snapshot = await _graph(request).aget_state(_config(request, thread_id, actor))
    values = snapshot.values or {}
    return ThreadState(
        thread_id=thread_id,
        messages=[
            MessageView(role=m.type, content=content_text(m.content))
            for m in values.get("messages", [])
            if m.type in ("human", "ai")
        ],
        subject_customer_id=values.get("subject_customer_id"),
        evidence_refs=[e["ref"] for e in values.get("evidence") or []],
        pending_ask=values.get("pending_ask"),
        intent=values.get("intent"),
    )


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(request: Request, thread_id: str, actor: AgentActor) -> None:
    """Delete a conversation **and the graph state behind it**.

    Both halves matter. The ``thread`` row is what the sidebar lists, but the conversation
    itself — every message, every tool result, every customer record the graph pulled into
    state — lives in the checkpointer's own database. Deleting only the row removes the
    conversation from view while leaving its contents on disk indefinitely, which is not
    what "delete" means to the person who asked for it, and is the wrong answer for records
    that Litestream then replicates to S3.

    Ownership is checked first, so a caller cannot erase graph state for a thread that is
    not theirs by racing the row lookup.
    """
    repos = _repos(request)
    _owned(request, thread_id, actor)

    with repos.db.transaction() as session:
        if not repos.threads.delete(session, thread_id, actor.sub):
            raise NotFound("thread_not_found", f"No thread {thread_id} for this user.")

    checkpointer = getattr(request.app.state, "checkpointer", None)
    if checkpointer is not None:
        # After the row, not before: if this fails the thread is already gone from the
        # listing and the orphan is recoverable, whereas the reverse would leave a
        # conversation whose state had been erased under it.
        await checkpointer.adelete_thread(thread_id)

    log.info("thread deleted", thread_id=thread_id)


@router.post("/{thread_id}/messages")
async def send_message(
    request: Request, thread_id: str, body: MessageRequest, actor: AgentActor
) -> EventSourceResponse:
    _owned(request, thread_id, actor)
    repos = _repos(request)

    with repos.db.transaction() as session:
        repos.threads.touch(session, thread_id, title=body.content[:120])

    return EventSourceResponse(
        stream_turn(
            _graph(request),
            initial_state(body.content),
            _config(request, thread_id, actor),
            thread_id=thread_id,
        ),
        ping=PING_SECONDS,
        headers={
            # No intermediary may buffer the stream, or the progress events arrive all
            # at once at the end and the indicator is worse than useless.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Trace-Id": get_trace_id(),
        },
    )


@router.post("/{thread_id}/resume")
async def resume_thread(
    request: Request, thread_id: str, body: ResumeRequest, actor: AgentActor
) -> EventSourceResponse:
    _owned(request, thread_id, actor)
    config = _config(request, thread_id, actor)

    snapshot = await _graph(request).aget_state(config)
    if not snapshot.interrupts:
        # Idempotent, not a double-write: a second resume for one interrupt is a
        # conflict, not an error to retry (docs/06 §3.5).
        raise Conflict("no_pending_approval", "This thread has no pending question.")

    payload = body.model_dump(exclude_none=True)
    log.info("resuming thread", thread_id=thread_id, kind=body.kind)

    return EventSourceResponse(
        stream_turn(_graph(request), Command(resume=payload), config, thread_id=thread_id),
        ping=PING_SECONDS,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Trace-Id": get_trace_id(),
        },
    )
