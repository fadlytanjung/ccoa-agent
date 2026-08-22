"""Audit log — append-only, one row per mutating tool call (docs/10 §7).

The write method takes a ``Session`` rather than opening its own. That is the whole
mechanism behind "every mutation is audited": the audit row is written inside the same
transaction as the mutation, so a committed write without its audit entry is not
something the code can express.

Denials and failures are audited too. An attempt that was refused is exactly the event
a reviewer wants to find, and logging only successes would make the trail useless for
the question it exists to answer.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import schema
from app.domain import clock
from app.domain.actor import Actor
from app.domain.enums import AuditOutcome
from app.domain.models import AuditEntry
from app.repositories.base import Repository, clamp_limit


def _to_entry(row: schema.AuditLog) -> AuditEntry:
    return AuditEntry(
        audit_id=row.audit_id,
        trace_id=row.trace_id,
        thread_id=row.thread_id,
        actor_sub=row.actor_sub,
        actor_email=row.actor_email,
        actor_groups=row.actor_groups,
        action=row.action,
        target_type=row.target_type,
        target_id=row.target_id,
        outcome=row.outcome,
        detail=row.detail,
        occurred_at=row.occurred_at,
    )


class AuditRepository(Repository):
    def record(
        self,
        session: Session,
        *,
        actor: Actor,
        action: str,
        target_type: str,
        outcome: AuditOutcome,
        trace_id: str,
        thread_id: str | None = None,
        target_id: str | None = None,
        detail: dict[str, object] | None = None,
    ) -> None:
        """Append one row. Never updates, never deletes."""
        session.add(
            schema.AuditLog(
                trace_id=trace_id,
                thread_id=thread_id,
                actor_sub=actor.sub,
                actor_email=actor.email,
                actor_groups=",".join(actor.groups),
                action=action,
                target_type=target_type,
                target_id=target_id,
                outcome=outcome.value,
                # ``detail`` carries operational context only. Nothing here may contain
                # transcript text or customer PII — docs/04 §3.8.
                detail=json.dumps(detail, sort_keys=True) if detail else None,
                occurred_at=clock.now(),
            )
        )

    def for_trace(self, trace_id: str) -> list[AuditEntry]:
        with self.db.session() as s:
            rows = s.scalars(
                select(schema.AuditLog)
                .where(schema.AuditLog.trace_id == trace_id)
                .order_by(schema.AuditLog.audit_id)
            ).all()
        return [_to_entry(r) for r in rows]

    def recent(self, limit: int | None = None) -> list[AuditEntry]:
        stmt = (
            select(schema.AuditLog)
            .order_by(schema.AuditLog.audit_id.desc())
            .limit(clamp_limit(limit, default=20))
        )
        with self.db.session() as s:
            return [_to_entry(r) for r in s.scalars(stmt).all()]
