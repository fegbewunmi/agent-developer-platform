"""agents, agent_versions, agent_version_lifecycle

AgentVersion is fully immutable (see 0008_immutability_roles for the DB-level
enforcement). Stage lives on the separate agent_version_lifecycle table, not
on agent_versions itself - docs/agent-versioning.md#the-stage-vs-content-split.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-09

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

stage_enum_ref = postgresql.ENUM(
    "draft", "evaluating", "candidate", "production", "retired", name="stage", create_type=False
)


def upgrade() -> None:
    postgresql.ENUM(
        "draft", "evaluating", "candidate", "production", "retired", name="stage"
    ).create(op.get_bind())

    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String, nullable=False, unique=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("description", sa.String, nullable=True),
        sa.Column("is_representative_data", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "agent_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("version_label", sa.String, nullable=False),
        sa.Column("manifest", postgresql.JSONB, nullable=False),
        sa.Column("content_hash", sa.String, nullable=False),
        sa.Column("source_ref", sa.String, nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("agent_id", "version_label", name="uq_agent_version_label"),
    )

    op.create_table(
        "agent_version_lifecycle",
        sa.Column(
            "agent_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_versions.id"),
            primary_key=True,
        ),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("stage", stage_enum_ref, nullable=False, server_default="draft"),
        sa.Column("entered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("entered_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
    )

    # The single-production-version-per-agent invariant (docs/failure-modes.md,
    # ADR-0007): at most one lifecycle row per agent_id may have stage='production'.
    op.create_index(
        "uq_one_production_version_per_agent",
        "agent_version_lifecycle",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("stage = 'production'"),
    )


def downgrade() -> None:
    op.drop_index("uq_one_production_version_per_agent", table_name="agent_version_lifecycle")
    op.drop_table("agent_version_lifecycle")
    op.drop_table("agent_versions")
    op.drop_table("agents")
    stage_enum_ref.drop(op.get_bind())
