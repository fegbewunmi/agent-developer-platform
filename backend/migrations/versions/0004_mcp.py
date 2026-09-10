"""mcp_servers, mcp_tools, agent_capability_grants

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-09

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    postgresql.ENUM("read", "write", name="mcp_classification").create(op.get_bind())
    postgresql.ENUM(
        "healthy", "degraded", "unavailable", "unknown", name="mcp_health_status"
    ).create(op.get_bind())

    op.create_table(
        "mcp_servers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String, nullable=False, unique=True),
        sa.Column("environment", sa.String, nullable=False),
        sa.Column("owner_team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("connection_ref", sa.String, nullable=False),
        sa.Column(
            "health_status",
            postgresql.ENUM(
                "healthy", "degraded", "unavailable", "unknown", name="mcp_health_status", create_type=False
            ),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "mcp_tools",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "mcp_server_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_servers.id"), nullable=False
        ),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("description", sa.String, nullable=True),
        sa.Column("io_schema", postgresql.JSONB, nullable=True),
        sa.Column(
            "classification",
            postgresql.ENUM("read", "write", name="mcp_classification", create_type=False),
            nullable=False,
        ),
        sa.Column("requires_approval", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("mcp_server_id", "name", name="uq_mcp_tool_name"),
    )

    op.create_table(
        "agent_capability_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "mcp_tool_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_tools.id"), nullable=False
        ),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("agent_capability_grants")
    op.drop_table("mcp_tools")
    op.drop_table("mcp_servers")
    postgresql.ENUM(name="mcp_health_status").drop(op.get_bind())
    postgresql.ENUM(name="mcp_classification").drop(op.get_bind())
