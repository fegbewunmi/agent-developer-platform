import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models.agent import Agent, AgentVersion
from app.models.enums import MCPClassification
from app.models.identity import User
from app.services import capability_grants as grants_service
from app.services import mcp as mcp_service

router = APIRouter(prefix="/v1/mcp-servers", tags=["mcp"])
tools_router = APIRouter(prefix="/v1/mcp-tools", tags=["mcp"])


class RegisterServerRequest(BaseModel):
    name: str
    environment: str
    owner_team_id: uuid.UUID
    connection_ref: str


class RegisterToolRequest(BaseModel):
    name: str
    description: str | None = None
    io_schema: dict | None = None
    classification: MCPClassification
    requires_approval: bool = False


def _server_to_dict(server) -> dict:
    return {
        "id": str(server.id),
        "name": server.name,
        "environment": server.environment,
        "owner_team_id": str(server.owner_team_id),
        "connection_ref": server.connection_ref,
        "health_status": server.health_status.value,
        "last_health_check_at": server.last_health_check_at.isoformat()
        if server.last_health_check_at
        else None,
    }


def _grant_dict_for_tool(grant) -> dict:
    return {
        "id": str(grant.id),
        "agent_version_id": str(grant.agent_version_id),
        "granted_by": str(grant.granted_by),
        "granted_at": grant.granted_at.isoformat(),
        "revoked_by": str(grant.revoked_by) if grant.revoked_by else None,
        "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None,
    }


def _tool_to_dict(tool) -> dict:
    return {
        "id": str(tool.id),
        "mcp_server_id": str(tool.mcp_server_id),
        "name": tool.name,
        "description": tool.description,
        "io_schema": tool.io_schema,
        "classification": tool.classification.value,
        "requires_approval": tool.requires_approval,
    }


@router.get("")
async def list_servers(
    _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    return [_server_to_dict(s) for s in await mcp_service.list_mcp_servers(db)]


@router.post("", status_code=201)
async def register_server(
    body: RegisterServerRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    server = await mcp_service.register_mcp_server(
        db,
        actor=user,
        name=body.name,
        environment=body.environment,
        owner_team_id=body.owner_team_id,
        connection_ref=body.connection_ref,
    )
    return _server_to_dict(server)


@router.get("/{server_id}")
async def get_server(
    server_id: uuid.UUID, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    return _server_to_dict(await mcp_service.get_mcp_server(db, server_id))


@router.post("/{server_id}/health-check")
async def check_server_health(
    server_id: uuid.UUID, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """A real HTTP call against connection_ref, not a simulated status flip
    - see app/services/mcp.py::check_server_health. Open to any authenticated
    user: health is availability, not authorization
    (docs/mcp-governance.md), so this doesn't need elevated permission.
    """
    return _server_to_dict(await mcp_service.check_server_health(db, server_id))


@router.get("/{server_id}/tools")
async def list_tools(
    server_id: uuid.UUID, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    return [_tool_to_dict(t) for t in await mcp_service.list_mcp_tools(db, server_id)]


@router.post("/{server_id}/tools", status_code=201)
async def register_tool(
    server_id: uuid.UUID,
    body: RegisterToolRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tool = await mcp_service.register_mcp_tool(
        db,
        actor=user,
        server_id=server_id,
        name=body.name,
        description=body.description,
        io_schema=body.io_schema,
        classification=body.classification,
        requires_approval=body.requires_approval,
    )
    return _tool_to_dict(tool)


@tools_router.get("/{tool_id}")
async def get_tool(
    tool_id: uuid.UUID, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    return _tool_to_dict(await mcp_service.get_mcp_tool(db, tool_id))


@tools_router.get("/{tool_id}/grants")
async def list_grants_for_tool(
    tool_id: uuid.UUID,
    include_revoked: bool = Query(default=False),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Phase 5: the MCP registry page's "which AgentVersions have a grant
    for this tool" reverse lookup - mirrors
    GET /v1/skill-versions/{id}/agent-versions on the Skills side."""
    grants = await grants_service.list_grants_for_tool(db, mcp_tool_id=tool_id, include_revoked=include_revoked)
    if not grants:
        return []
    version_ids = {g.agent_version_id for g in grants}
    rows = (
        await db.execute(
            select(AgentVersion, Agent).join(Agent, Agent.id == AgentVersion.agent_id).where(AgentVersion.id.in_(version_ids))
        )
    ).all()
    context = {v.id: {"agent_id": str(a.id), "agent_name": a.name, "version_label": v.version_label} for v, a in rows}
    result = []
    for g in grants:
        entry = _grant_dict_for_tool(g)
        entry.update(context.get(g.agent_version_id, {}))
        result.append(entry)
    return result
