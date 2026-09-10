"""evaluation_policies: revoke UPDATE/DELETE for agent_platform_app.

Mirrors migrations/versions/0008_immutability_roles.py exactly - "favor
reproducibility" (Phase 3 brief) means a policy edit is a new (name, version)
row, never a patch, enforced at the DB level the same way agent_versions and
skill_versions already are. See docs/adrs/0015-evaluation-policy-immutability.md.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-10

"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        "REVOKE UPDATE, DELETE ON evaluation_policies FROM agent_platform_app"
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "GRANT UPDATE, DELETE ON evaluation_policies TO agent_platform_app"
    )
