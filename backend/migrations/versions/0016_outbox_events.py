"""Phase 4: outbox_events - the transactional outbox for lifecycle events fanned
out beyond this DB (Pub/Sub), distinct from audit_events (this platform's own
permanent, always-directly-queryable history) - see
docs/adrs/0020-promotion-lifecycle-event-outbox.md.

Written in the same transaction as the domain change it describes; published to
Pub/Sub only as a separate, best-effort step after that transaction commits
(app/services/event_publisher.py) - never before.

Immutable except `published_at`/`publish_error` (column-level GRANT), the same
pattern as promotion_requests.status (migration 0015).

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-11

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String, nullable=False),
        sa.Column("entity_type", sa.String, nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_error", sa.String, nullable=True),
    )
    op.create_index("ix_outbox_events_unpublished", "outbox_events", ["created_at"], postgresql_where=sa.text("published_at IS NULL"))

    # Explicit grants, not relied-on defaults: a real gap found while writing
    # this migration - every other table's agent_platform_app grants trace
    # back to a one-time, untracked `GRANT ALL ON ALL TABLES IN SCHEMA public`
    # run directly against the DB during an earlier phase, not to any
    # `ALTER DEFAULT PRIVILEGES`. A brand-new table (this one) got nothing
    # until granted here explicitly - confirmed by querying
    # information_schema.role_table_grants right after `op.create_table`
    # above returned zero rows for agent_platform_app. Earlier migrations
    # were not retroactively fixed (out of scope, risk of rewriting applied
    # history) - see docs/phase-notes/phase-4.md.
    bind = op.get_bind()
    bind.exec_driver_sql("GRANT SELECT, INSERT ON outbox_events TO agent_platform_app")
    bind.exec_driver_sql("GRANT UPDATE (published_at, publish_error) ON outbox_events TO agent_platform_app")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("REVOKE UPDATE (published_at, publish_error) ON outbox_events FROM agent_platform_app")
    bind.exec_driver_sql("REVOKE SELECT, INSERT ON outbox_events FROM agent_platform_app")
    op.drop_index("ix_outbox_events_unpublished", table_name="outbox_events")
    op.drop_table("outbox_events")
