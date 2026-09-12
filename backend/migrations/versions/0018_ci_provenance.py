"""Phase 8 (ADR-0023, ADR-0024): real source provenance for CI-integrated
agents. Two additive, nullable/defaulted columns - every existing row stays
valid with no data migration:

- agents.requires_ci_provenance (bool, default false): when true, manual
  AgentVersion creation via the human API is rejected outright
  (app/services/agents.py::create_agent_version) - only the CI-publisher
  machine identity (app/auth/ci_publisher.py) may create versions for this
  Agent.
- agent_versions.provenance (JSONB, nullable): git_repo/git_commit_sha/
  git_ref/publisher/published_at/image_digest - set once at creation,
  covered by the SAME table-level immutability grant agent_versions already
  has (migration 0008 revoked UPDATE/DELETE for agent_platform_app on this
  table; a new column inherits that with no additional grant needed).

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-12

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("requires_ci_provenance", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "agent_versions",
        sa.Column("provenance", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_versions", "provenance")
    op.drop_column("agents", "requires_ci_provenance")
