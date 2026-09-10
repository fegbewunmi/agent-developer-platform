"""The capability-grant evidence fingerprint - docs/adrs/0014-capability-grant-reproducibility.md's
recommendation, built in Phase 3. Captures enough to know what authorization state
existed when an evaluation ran, without duplicating every grant row.

Deliberately NOT a duplicate of AgentCapabilityGrant rows: the snapshot is small
(active grant IDs + the MCP tool identity/classification each grants access to),
and its hash is what actually gets compared for freshness - the JSON body itself is
kept alongside purely so a human/audit reader can see what the hash means without
re-deriving it from historical grant timestamps.
"""
import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mcp import AgentCapabilityGrant, MCPTool


@dataclass(frozen=True)
class CapabilityGrantSnapshot:
    snapshot: dict
    hash: str


async def take_capability_grant_snapshot(
    db: AsyncSession, agent_version_id: uuid.UUID
) -> CapabilityGrantSnapshot:
    result = await db.execute(
        select(AgentCapabilityGrant, MCPTool)
        .join(MCPTool, MCPTool.id == AgentCapabilityGrant.mcp_tool_id)
        .where(
            AgentCapabilityGrant.agent_version_id == agent_version_id,
            AgentCapabilityGrant.revoked_at.is_(None),
        )
        .order_by(AgentCapabilityGrant.id)
    )
    rows = result.all()

    grants = [
        {
            "grant_id": str(grant.id),
            "mcp_tool_id": str(tool.id),
            "mcp_tool_name": tool.name,
            "classification": tool.classification.value,
            "requires_approval": tool.requires_approval,
            "granted_at": grant.granted_at.isoformat(),
        }
        for grant, tool in rows
    ]
    # Sort by grant_id so the snapshot (and therefore its hash) is deterministic
    # regardless of DB row-fetch order.
    grants.sort(key=lambda g: g["grant_id"])

    snapshot = {"agent_version_id": str(agent_version_id), "active_grants": grants}
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    snapshot_hash = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()

    return CapabilityGrantSnapshot(snapshot=snapshot, hash=snapshot_hash)
