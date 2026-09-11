"""Phase 4: promotion_requests/promotion_decisions immutability, matching
AgentVersion/SkillVersion/EvaluationPolicy's DB-level pattern -
docs/adrs/0018-promotion-request-immutability.md.

promotion_requests: everything is a frozen snapshot of the decision context
at request time EXCEPT `status`, which genuinely needs to transition
pending -> approved/rejected. Column-level GRANT is used (Postgres supports
per-column UPDATE grants) so the restriction is real, not a convention - the
agent_platform_app role can UPDATE only the `status` column, nothing else.

promotion_decisions: fully immutable once created, like audit_events - a
decision, once made, is never edited. No UPDATE/DELETE grant at all.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-11

"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("REVOKE UPDATE, DELETE ON promotion_requests FROM agent_platform_app")
    bind.exec_driver_sql("GRANT UPDATE (status) ON promotion_requests TO agent_platform_app")
    bind.exec_driver_sql("REVOKE UPDATE, DELETE ON promotion_decisions FROM agent_platform_app")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("GRANT UPDATE, DELETE ON promotion_decisions TO agent_platform_app")
    bind.exec_driver_sql("REVOKE UPDATE (status) ON promotion_requests FROM agent_platform_app")
    bind.exec_driver_sql("GRANT UPDATE, DELETE ON promotion_requests TO agent_platform_app")
