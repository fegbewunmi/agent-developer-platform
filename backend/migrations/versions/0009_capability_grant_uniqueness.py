"""agent_capability_grants: at most one active grant per (agent_version, tool)

Phase 2 addition. Without this, granting the same MCPTool to the same
AgentVersion twice silently created two live grants - revoking one would
leave the other still active, which is not the "grant/revoke" semantics
docs/mcp-governance.md describes. A grant can still be re-created after a
prior one is revoked (that's a new row, old one stays revoked history) -
this index only forbids two *simultaneously active* rows.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-10

"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_one_active_grant_per_version_tool",
        "agent_capability_grants",
        ["agent_version_id", "mcp_tool_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_one_active_grant_per_version_tool", table_name="agent_capability_grants")
