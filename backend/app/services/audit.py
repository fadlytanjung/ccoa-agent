"""Audited mutation — docs/10 §7.

The point of this module is that **there is no way to perform a mutation without
writing its audit row**. The mutation runs inside a transaction this service opens, the
audit row is written into that same transaction, and both commit together. A caller
cannot forget the audit step because the caller never opens the transaction.

Failures and denials are audited too, in their own transaction, because "who tried to
do what and was refused" is exactly the question the log exists to answer.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.db.engine import Database
from app.domain.actor import Actor
from app.domain.enums import AuditOutcome
from app.repositories.audit import AuditRepository

log = logging.getLogger(__name__)

#: An operation receives the open session and returns ``(target_id, detail)``.
Operation = Callable[[Session], "tuple[str, dict[str, Any]]"]


class AuditService:
    def __init__(self, db: Database, audit: AuditRepository) -> None:
        self.db = db
        self.audit = audit

    def perform(
        self,
        operation: Operation,
        *,
        actor: Actor,
        action: str,
        target_type: str,
        trace_id: str,
        thread_id: str | None = None,
    ) -> str:
        """Run a mutation and its audit row in one transaction. Returns the target id."""
        try:
            with self.db.transaction() as session:
                target_id, detail = operation(session)
                self.audit.record(
                    session,
                    actor=actor,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    outcome=AuditOutcome.ALLOWED,
                    trace_id=trace_id,
                    thread_id=thread_id,
                    detail=detail,
                )
            return target_id
        except Exception as exc:
            # The mutation rolled back, so its audit row went with it. Record the
            # attempt separately — a failed write is still something someone did.
            self.record(
                actor=actor,
                action=action,
                target_type=target_type,
                outcome=AuditOutcome.FAILED,
                trace_id=trace_id,
                thread_id=thread_id,
                detail={"reason": exc.__class__.__name__},
            )
            raise

    def record(
        self,
        *,
        actor: Actor,
        action: str,
        target_type: str,
        outcome: AuditOutcome,
        trace_id: str,
        thread_id: str | None = None,
        target_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Write a standalone audit row — denials, failures, and read-side events."""
        try:
            with self.db.transaction() as session:
                self.audit.record(
                    session,
                    actor=actor,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    outcome=outcome,
                    trace_id=trace_id,
                    thread_id=thread_id,
                    detail=detail,
                )
        except Exception:  # losing the audit row must not mask the event itself
            log.exception(
                "failed to write audit row action=%s outcome=%s trace=%s",
                action,
                outcome.value,
                trace_id,
            )
