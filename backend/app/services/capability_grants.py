"""AgentCapabilityGrant: explicit, inspectable, revocable authorization from
an AgentVersion to an MCPTool - deliberately separate from the immutable
manifest. See docs/adrs/0004-mcp-capability-grant-model.md and
docs/adrs/0014-capability-grant-reproducibility.md for the reproducibility
tradeoff this creates and why it's accepted rather than "solved" by making
grants immutable too.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent, AgentVersion
from app.models.identity import User
from app.models.mcp import AgentCapabilityGrant, MCPTool
from app.services import permissions
from app.services.audit import record_audit_event
from app.services.errors import ConflictError, NotFoundError, PermissionDeniedError


async def _get_agent_version_and_owning_agent(
    db: AsyncSession, agent_version_id: uuid.UUID
) -> tuple[AgentVersion, Agent]:
    version = (
        await db.execute(select(AgentVersion).where(AgentVersion.id == agent_version_id))
    ).scalar_one_or_none()
    if version is None:
        raise NotFoundError(f"no agent version with id {agent_version_id}")
    agent = (await db.execute(select(Agent).where(Agent.id == version.agent_id))).scalar_one()
    return version, agent


async def grant_capability(
    db: AsyncSession, *, actor: User, agent_version_id: uuid.UUID, mcp_tool_id: uuid.UUID
) -> AgentCapabilityGrant:
    version, agent = await _get_agent_version_and_owning_agent(db, agent_version_id)

    tool = (await db.execute(select(MCPTool).where(MCPTool.id == mcp_tool_id))).scalar_one_or_none()
    if tool is None:
        raise NotFoundError(f"no MCP tool with id {mcp_tool_id}")

    if not permissions.can_grant_mcp_tool(
        actor, agent.team_id, tool.classification, tool.requires_approval
    ) or not permissions.demo_containment_ok(actor, agent.team_id):
        raise PermissionDeniedError(
            "not authorized to grant this tool - write-capable and approval-required tools require "
            "Reviewer or Admin (docs/mcp-governance.md)"
        )

    existing_active = (
        await db.execute(
            select(AgentCapabilityGrant.id).where(
                AgentCapabilityGrant.agent_version_id == agent_version_id,
                AgentCapabilityGrant.mcp_tool_id == mcp_tool_id,
                AgentCapabilityGrant.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing_active is not None:
        raise ConflictError(
            f"agent version {agent_version_id} already has an active grant for tool {tool.name!r}"
        )

    grant = AgentCapabilityGrant(
        id=uuid.uuid4(),
        agent_version_id=agent_version_id,
        mcp_tool_id=mcp_tool_id,
        granted_by=actor.id,
    )
    db.add(grant)
    await db.flush()

    record_audit_event(
        db,
        actor_id=actor.id,
        event_type="capability.granted",
        entity_type="agent_capability_grant",
        entity_id=grant.id,
        payload={
            "agent_version_id": str(agent_version_id),
            "mcp_tool_id": str(mcp_tool_id),
            "mcp_tool_name": tool.name,
            "classification": tool.classification.value,
            "requires_approval": tool.requires_approval,
        },
    )
    await db.commit()
    await db.refresh(grant)
    return grant


async def revoke_capability(db: AsyncSession, *, actor: User, grant_id: uuid.UUID) -> AgentCapabilityGrant:
    if not permissions.can_revoke_capability_grant(actor):
        raise PermissionDeniedError("only Reviewer or Admin may revoke a capability grant")

    grant = (
        await db.execute(select(AgentCapabilityGrant).where(AgentCapabilityGrant.id == grant_id))
    ).scalar_one_or_none()
    if grant is None:
        raise NotFoundError(f"no capability grant with id {grant_id}")
    if grant.revoked_at is not None:
        raise ConflictError(f"grant {grant_id} was already revoked at {grant.revoked_at.isoformat()}")

    _, owning_agent = await _get_agent_version_and_owning_agent(db, grant.agent_version_id)
    if not permissions.demo_containment_ok(actor, owning_agent.team_id):
        raise PermissionDeniedError("only Reviewer or Admin may revoke a capability grant")

    grant.revoked_by = actor.id
    grant.revoked_at = datetime.now(timezone.utc)

    record_audit_event(
        db,
        actor_id=actor.id,
        event_type="capability.revoked",
        entity_type="agent_capability_grant",
        entity_id=grant.id,
        payload={
            "agent_version_id": str(grant.agent_version_id),
            "mcp_tool_id": str(grant.mcp_tool_id),
            "granted_by": str(grant.granted_by),
            "granted_at": grant.granted_at.isoformat(),
        },
    )
    await db.commit()
    await db.refresh(grant)
    return grant


async def list_grants(
    db: AsyncSession, *, agent_version_id: uuid.UUID, include_revoked: bool = False
) -> list[AgentCapabilityGrant]:
    await _get_agent_version_and_owning_agent(db, agent_version_id)
    stmt = select(AgentCapabilityGrant).where(AgentCapabilityGrant.agent_version_id == agent_version_id)
    if not include_revoked:
        stmt = stmt.where(AgentCapabilityGrant.revoked_at.is_(None))
    result = await db.execute(stmt.order_by(AgentCapabilityGrant.granted_at))
    return list(result.scalars().all())


async def list_grants_for_tool(
    db: AsyncSession, *, mcp_tool_id: uuid.UUID, include_revoked: bool = False
) -> list[AgentCapabilityGrant]:
    """Phase 5: the MCP registry page's reverse lookup ("which AgentVersions
    have a grant for this tool") - mirrors
    app/services/skills.py::list_agent_versions_using_skill_version's
    existing pattern for the same kind of question on the Skills side."""
    tool = (await db.execute(select(MCPTool).where(MCPTool.id == mcp_tool_id))).scalar_one_or_none()
    if tool is None:
        raise NotFoundError(f"no MCP tool with id {mcp_tool_id}")
    stmt = select(AgentCapabilityGrant).where(AgentCapabilityGrant.mcp_tool_id == mcp_tool_id)
    if not include_revoked:
        stmt = stmt.where(AgentCapabilityGrant.revoked_at.is_(None))
    result = await db.execute(stmt.order_by(AgentCapabilityGrant.granted_at))
    return list(result.scalars().all())
