"""MCP server/tool registry. See docs/mcp-governance.md for what this
platform does and does not claim about MCP tool execution and approval -
registering a tool here is a governance declaration, never a runtime
enforcement guarantee. See that doc's three-layer breakdown of
`create_ticket`'s real confirm-gate before assuming anything about what
`requires_approval` actually enforces at call time.
"""
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import MCPClassification, MCPHealthStatus
from app.models.identity import Team, User
from app.models.mcp import MCPServer, MCPTool
from app.services import permissions
from app.services.audit import record_audit_event
from app.services.errors import ConflictError, NotFoundError, PermissionDeniedError


async def register_mcp_server(
    db: AsyncSession,
    *,
    actor: User,
    name: str,
    environment: str,
    owner_team_id: uuid.UUID,
    connection_ref: str,
) -> MCPServer:
    if not permissions.can_manage_mcp_registry(actor):
        raise PermissionDeniedError("only Admins may register MCP servers")

    team = (await db.execute(select(Team).where(Team.id == owner_team_id))).scalar_one_or_none()
    if team is None:
        raise NotFoundError(f"no team with id {owner_team_id}")

    existing = (await db.execute(select(MCPServer.id).where(MCPServer.name == name))).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"an MCP server named {name!r} is already registered")

    server = MCPServer(
        id=uuid.uuid4(),
        name=name,
        environment=environment,
        owner_team_id=owner_team_id,
        connection_ref=connection_ref,
        health_status=MCPHealthStatus.UNKNOWN,
    )
    db.add(server)
    await db.flush()

    record_audit_event(
        db,
        actor_id=actor.id,
        event_type="mcp_server.registered",
        entity_type="mcp_server",
        entity_id=server.id,
        payload={"name": name, "environment": environment, "connection_ref": connection_ref},
    )
    await db.commit()
    await db.refresh(server)
    return server


async def update_mcp_server_connection(
    db: AsyncSession, *, actor: User, server_id: uuid.UUID, connection_ref: str
) -> MCPServer:
    """Phase 6: connection_ref is set once at registration time and, until now,
    had no update path - fine in local dev, but a real deployment can genuinely
    need to repoint a server at its actual reachable address (see phase-6 notes:
    incident-operations was registered with a local-dev placeholder). Same
    admin-only authorization and audit trail as registration itself.
    """
    if not permissions.can_manage_mcp_registry(actor):
        raise PermissionDeniedError("only Admins may update MCP server registration")

    server = await get_mcp_server(db, server_id)
    previous_connection_ref = server.connection_ref
    server.connection_ref = connection_ref
    server.health_status = MCPHealthStatus.UNKNOWN
    server.last_health_check_at = None

    record_audit_event(
        db,
        actor_id=actor.id,
        event_type="mcp_server.connection_updated",
        entity_type="mcp_server",
        entity_id=server.id,
        payload={"previous_connection_ref": previous_connection_ref, "connection_ref": connection_ref},
    )
    await db.commit()
    await db.refresh(server)
    return server


async def list_mcp_servers(db: AsyncSession) -> list[MCPServer]:
    result = await db.execute(select(MCPServer).order_by(MCPServer.name))
    return list(result.scalars().all())


async def get_mcp_server(db: AsyncSession, server_id: uuid.UUID) -> MCPServer:
    server = (await db.execute(select(MCPServer).where(MCPServer.id == server_id))).scalar_one_or_none()
    if server is None:
        raise NotFoundError(f"no MCP server with id {server_id}")
    return server


async def register_mcp_tool(
    db: AsyncSession,
    *,
    actor: User,
    server_id: uuid.UUID,
    name: str,
    description: str | None,
    io_schema: dict | None,
    classification: MCPClassification,
    requires_approval: bool,
) -> MCPTool:
    """Registration is explicit and source-attested, not auto-discovered -
    see docs/mcp-governance.md's "Real MCP integration" note on why: the
    Incident Operations MCP server runs over stdio, spawned per client, with
    no HTTP introspection endpoint - there is nothing this control plane can
    poll to "discover" tools. Every seeded tool here was read directly out
    of mcp_server/server.py in ai-operations, not invented.
    """
    server = await get_mcp_server(db, server_id)

    if not permissions.can_manage_mcp_registry(actor):
        raise PermissionDeniedError("only Admins may register MCP tools")

    existing = (
        await db.execute(select(MCPTool.id).where(MCPTool.mcp_server_id == server_id, MCPTool.name == name))
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"server {server.name!r} already has a tool named {name!r}")

    tool = MCPTool(
        id=uuid.uuid4(),
        mcp_server_id=server_id,
        name=name,
        description=description,
        io_schema=io_schema,
        classification=classification,
        requires_approval=requires_approval,
    )
    db.add(tool)
    await db.flush()

    record_audit_event(
        db,
        actor_id=actor.id,
        event_type="mcp_tool.registered",
        entity_type="mcp_tool",
        entity_id=tool.id,
        payload={
            "mcp_server_id": str(server_id),
            "name": name,
            "classification": classification.value,
            "requires_approval": requires_approval,
        },
    )
    await db.commit()
    await db.refresh(tool)
    return tool


async def list_mcp_tools(db: AsyncSession, server_id: uuid.UUID) -> list[MCPTool]:
    await get_mcp_server(db, server_id)
    result = await db.execute(select(MCPTool).where(MCPTool.mcp_server_id == server_id).order_by(MCPTool.name))
    return list(result.scalars().all())


async def get_mcp_tool(db: AsyncSession, tool_id: uuid.UUID) -> MCPTool:
    tool = (await db.execute(select(MCPTool).where(MCPTool.id == tool_id))).scalar_one_or_none()
    if tool is None:
        raise NotFoundError(f"no MCP tool with id {tool_id}")
    return tool


async def check_server_health(db: AsyncSession, server_id: uuid.UUID) -> MCPServer:
    """A real HTTP call, not a simulated one. The Incident Operations MCP
    server itself has no HTTP surface to check (stdio only) - this checks
    the backing FastAPI service it wraps (connection_ref), which does expose
    a real `/health` endpoint (confirmed live during Phase 2 verification).
    Health is availability, not authorization (docs/mcp-governance.md) -
    this never touches capability grants.
    """
    server = await get_mcp_server(db, server_id)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{server.connection_ref}/health")
        server.health_status = (
            MCPHealthStatus.HEALTHY if response.status_code == 200 else MCPHealthStatus.DEGRADED
        )
    except httpx.HTTPError:
        server.health_status = MCPHealthStatus.UNAVAILABLE

    server.last_health_check_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(server)
    return server
