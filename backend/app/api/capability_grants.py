import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models.identity import User
from app.services import capability_grants as grants_service

router = APIRouter(prefix="/v1/agent-versions/{agent_version_id}/capability-grants", tags=["capability-grants"])
revoke_router = APIRouter(prefix="/v1/capability-grants", tags=["capability-grants"])


class GrantCapabilityRequest(BaseModel):
    mcp_tool_id: uuid.UUID


def _grant_to_dict(grant) -> dict:
    return {
        "id": str(grant.id),
        "agent_version_id": str(grant.agent_version_id),
        "mcp_tool_id": str(grant.mcp_tool_id),
        "granted_by": str(grant.granted_by),
        "granted_at": grant.granted_at.isoformat(),
        "revoked_by": str(grant.revoked_by) if grant.revoked_by else None,
        "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None,
    }


@router.get("")
async def list_grants(
    agent_version_id: uuid.UUID,
    include_revoked: bool = Query(default=False),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    grants = await grants_service.list_grants(
        db, agent_version_id=agent_version_id, include_revoked=include_revoked
    )
    return [_grant_to_dict(g) for g in grants]


@router.post("", status_code=201)
async def grant_capability(
    agent_version_id: uuid.UUID,
    body: GrantCapabilityRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    grant = await grants_service.grant_capability(
        db, actor=user, agent_version_id=agent_version_id, mcp_tool_id=body.mcp_tool_id
    )
    return _grant_to_dict(grant)


@revoke_router.post("/{grant_id}/revoke")
async def revoke_capability(
    grant_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """No DELETE endpoint, deliberately - a grant is never removed, only
    marked revoked (revoked_by/revoked_at), so it stays visible in history
    alongside the AgentVersion it was ever active for. See
    docs/adrs/0014-capability-grant-reproducibility.md.
    """
    grant = await grants_service.revoke_capability(db, actor=user, grant_id=grant_id)
    return _grant_to_dict(grant)
