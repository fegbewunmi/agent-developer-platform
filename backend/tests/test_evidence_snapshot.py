"""ADR-0014's capability-grant evidence snapshot - proves the fingerprint is
deterministic, changes when grants change, and ignores revoked grants.
"""
import uuid

from app.models.agent import Agent, AgentVersion, AgentVersionLifecycle
from app.models.enums import MCPClassification, Stage
from app.models.mcp import AgentCapabilityGrant, MCPServer, MCPTool
from app.services.evidence_snapshot import take_capability_grant_snapshot


async def _make_agent_version(db_session, org):
    agent = Agent(id=uuid.uuid4(), name=f"agent-{uuid.uuid4().hex[:8]}", team_id=org["team_a"].id)
    db_session.add(agent)
    await db_session.flush()
    version = AgentVersion(
        id=uuid.uuid4(), agent_id=agent.id, version_label="1.0.0", manifest={}, content_hash="h",
        created_by=org["builder"].id,
    )
    db_session.add(version)
    await db_session.flush()
    db_session.add(
        AgentVersionLifecycle(agent_version_id=version.id, agent_id=agent.id, stage=Stage.DRAFT, entered_by=org["builder"].id)
    )
    await db_session.commit()
    return version


async def _make_tool(db_session, org, classification=MCPClassification.READ):
    server = MCPServer(
        id=uuid.uuid4(), name=f"server-{uuid.uuid4().hex[:8]}", environment="development",
        owner_team_id=org["team_a"].id, connection_ref="http://x",
    )
    db_session.add(server)
    await db_session.flush()
    tool = MCPTool(id=uuid.uuid4(), mcp_server_id=server.id, name=f"tool-{uuid.uuid4().hex[:8]}", classification=classification)
    db_session.add(tool)
    await db_session.commit()
    return tool


async def test_snapshot_is_empty_with_no_grants(db_session, org):
    version = await _make_agent_version(db_session, org)
    snap = await take_capability_grant_snapshot(db_session, version.id)
    assert snap.snapshot["active_grants"] == []


async def test_snapshot_includes_active_grants(db_session, org):
    version = await _make_agent_version(db_session, org)
    tool = await _make_tool(db_session, org)
    db_session.add(AgentCapabilityGrant(id=uuid.uuid4(), agent_version_id=version.id, mcp_tool_id=tool.id, granted_by=org["builder"].id))
    await db_session.commit()

    snap = await take_capability_grant_snapshot(db_session, version.id)
    assert len(snap.snapshot["active_grants"]) == 1
    assert snap.snapshot["active_grants"][0]["mcp_tool_id"] == str(tool.id)


async def test_snapshot_hash_is_deterministic_and_stable(db_session, org):
    version = await _make_agent_version(db_session, org)
    tool = await _make_tool(db_session, org)
    db_session.add(AgentCapabilityGrant(id=uuid.uuid4(), agent_version_id=version.id, mcp_tool_id=tool.id, granted_by=org["builder"].id))
    await db_session.commit()

    snap1 = await take_capability_grant_snapshot(db_session, version.id)
    snap2 = await take_capability_grant_snapshot(db_session, version.id)
    assert snap1.hash == snap2.hash


async def test_snapshot_hash_changes_when_a_grant_is_added(db_session, org):
    version = await _make_agent_version(db_session, org)
    tool1 = await _make_tool(db_session, org)
    db_session.add(AgentCapabilityGrant(id=uuid.uuid4(), agent_version_id=version.id, mcp_tool_id=tool1.id, granted_by=org["builder"].id))
    await db_session.commit()
    snap_before = await take_capability_grant_snapshot(db_session, version.id)

    tool2 = await _make_tool(db_session, org)
    db_session.add(AgentCapabilityGrant(id=uuid.uuid4(), agent_version_id=version.id, mcp_tool_id=tool2.id, granted_by=org["builder"].id))
    await db_session.commit()
    snap_after = await take_capability_grant_snapshot(db_session, version.id)

    assert snap_before.hash != snap_after.hash


async def test_snapshot_hash_changes_when_a_grant_is_revoked(db_session, org):
    version = await _make_agent_version(db_session, org)
    tool = await _make_tool(db_session, org)
    grant = AgentCapabilityGrant(id=uuid.uuid4(), agent_version_id=version.id, mcp_tool_id=tool.id, granted_by=org["builder"].id)
    db_session.add(grant)
    await db_session.commit()
    snap_before = await take_capability_grant_snapshot(db_session, version.id)

    from datetime import datetime, timezone

    grant.revoked_by = org["admin"].id
    grant.revoked_at = datetime.now(timezone.utc)
    await db_session.commit()
    snap_after = await take_capability_grant_snapshot(db_session, version.id)

    assert snap_before.hash != snap_after.hash
    assert snap_after.snapshot["active_grants"] == []
