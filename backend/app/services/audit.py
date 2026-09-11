"""docs/audit-model.md's transactional guarantee, as code: this function
never commits. Every service function below calls it in the middle of its
own unit-of-work and commits once, at the end, itself - so the domain write
and its audit record are always the same INSERT...COMMIT boundary. If
anything after this call raises, the caller's rollback takes the audit
row with it. See tests/test_audit_transaction.py, which proves this by
forcing a failure between the two writes and confirming neither persists.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent


def record_audit_event(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID,
    event_type: str,
    entity_type: str,
    entity_id: uuid.UUID,
    payload: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        id=uuid.uuid4(),
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor_id,
        payload=payload or {},
    )
    db.add(event)
    return event


async def list_audit_events(
    db: AsyncSession,
    *,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[AuditEvent]:
    """Phase 5: the frontend's Activity page and dashboard recent-activity
    feed need to read the real AuditEvent trail - view access is universal
    (any authenticated user - docs/auth-and-approval-model.md), matching
    every other read endpoint in this platform.
    """
    stmt = select(AuditEvent)
    if entity_type is not None:
        stmt = stmt.where(AuditEvent.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    stmt = stmt.order_by(AuditEvent.occurred_at.desc()).limit(min(limit, 200))
    result = await db.execute(stmt)
    return list(result.scalars().all())
