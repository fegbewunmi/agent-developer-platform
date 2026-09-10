"""immutability enforcement: restrict the agent_platform_app runtime role

Implements ADR-0002's amendment and docs/audit-model.md's immutability
guarantee as real DB privileges, not just an omitted API endpoint. The
running application connects only as agent_platform_app (see
app/config.py's database_url) - Alembic migrations run as the privileged
owner role instead (database_url_migrations), so this REVOKE genuinely
applies to every write the application can make, with no code-level bypass
possible.

- agent_versions, skill_versions: UPDATE and DELETE revoked - write-once,
  full stop (docs/adrs/0002-immutable-versioned-artifacts.md).
- audit_events: UPDATE and DELETE revoked - insert-only
  (docs/audit-model.md).

Every other table gets ordinary SELECT/INSERT/UPDATE/DELETE, since their
mutability is the point (e.g. agent_version_lifecycle.stage, or
agent_capability_grants' revocation columns).

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-09

"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

ALL_TABLES = [
    "teams",
    "users",
    "agents",
    "agent_versions",
    "agent_version_lifecycle",
    "skills",
    "skill_versions",
    "agent_version_skills",
    "mcp_servers",
    "mcp_tools",
    "agent_capability_grants",
    "evaluation_policies",
    "evaluation_run_references",
    "evaluation_gate_results",
    "promotion_requests",
    "promotion_decisions",
    "audit_events",
]

WRITE_ONCE_TABLES = ["agent_versions", "skill_versions", "audit_events"]


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("GRANT USAGE ON SCHEMA public TO agent_platform_app")
    for table in ALL_TABLES:
        bind.exec_driver_sql(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO agent_platform_app"
        )
    for table in WRITE_ONCE_TABLES:
        bind.exec_driver_sql(f"REVOKE UPDATE, DELETE ON {table} FROM agent_platform_app")


def downgrade() -> None:
    bind = op.get_bind()
    for table in WRITE_ONCE_TABLES:
        bind.exec_driver_sql(f"GRANT UPDATE, DELETE ON {table} TO agent_platform_app")
    for table in ALL_TABLES:
        bind.exec_driver_sql(
            f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {table} FROM agent_platform_app"
        )
    bind.exec_driver_sql("REVOKE USAGE ON SCHEMA public FROM agent_platform_app")
