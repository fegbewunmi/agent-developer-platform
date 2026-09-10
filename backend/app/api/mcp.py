import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models.enums import MCPClassification
from app.models.identity import User
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
