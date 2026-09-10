"""skills, skill_versions, agent_version_skills

skill_versions is immutable once published, same enforcement class as
agent_versions - see 0008_immutability_roles.py.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-09

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String, nullable=False, unique=True),
        sa.Column("owner_team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("description", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "skill_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.id"), nullable=False),
        sa.Column("version", sa.String, nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("purpose", sa.String, nullable=False),
        sa.Column("input_contract", sa.String, nullable=True),
        sa.Column("output_contract", sa.String, nullable=True),
        sa.Column("implementation_ref", sa.String, nullable=True),
        sa.Column("compatible_frameworks", postgresql.ARRAY(sa.String), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("skill_id", "version", name="uq_skill_version"),
    )

    op.create_table(
        "agent_version_skills",
        sa.Column(
            "agent_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_versions.id"),
            primary_key=True,
        ),
        sa.Column(
            "skill_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skill_versions.id"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("agent_version_skills")
    op.drop_table("skill_versions")
    op.drop_table("skills")
