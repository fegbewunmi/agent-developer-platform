import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models.identity import User
from app.services import audit as audit_service

router = APIRouter(prefix="/v1/audit-events", tags=["audit"])


def _event_to_dict(e) -> dict:
    return {
        "id": str(e.id),
        "event_type": e.event_type,
        "entity_type": e.entity_type,
        "entity_id": str(e.entity_id),
        "actor": str(e.actor),
        "occurred_at": e.occurred_at.isoformat(),
        "payload": e.payload,
    }


@router.get("")
async def list_audit_events(
    entity_type: str | None = Query(default=None),
    entity_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    events = await audit_service.list_audit_events(db, entity_type=entity_type, entity_id=entity_id, limit=limit)
    return [_event_to_dict(e) for e in events]
