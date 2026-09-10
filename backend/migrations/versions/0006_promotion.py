"""promotion_requests, promotion_decisions, no-self-approval trigger

decided_by != requested_by is enforced here at the DB level via a trigger,
not only in application code - see docs/adrs/0009-no-self-approval.md. A
CHECK constraint can't reference another table's column, so this needs a
trigger rather than a constraint.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-09

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    postgresql.ENUM(
        "pending", "approved", "rejected", "withdrawn", name="promotion_request_status"
    ).create(op.get_bind())
    postgresql.ENUM("approve", "reject", name="promotion_decision_type").create(op.get_bind())

    op.create_table(
        "promotion_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "from_stage",
            postgresql.ENUM(
                "draft", "evaluating", "candidate", "production", "retired", name="stage", create_type=False
            ),
            nullable=False,
        ),
        sa.Column(
            "to_stage",
            postgresql.ENUM(
                "draft", "evaluating", "candidate", "production", "retired", name="stage", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "evaluation_run_reference_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evaluation_run_references.id"),
            nullable=True,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending", "approved", "rejected", "withdrawn", name="promotion_request_status", create_type=False
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("reason", sa.String, nullable=True),
    )

    op.create_table(
        "promotion_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "promotion_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("promotion_requests.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "decision",
            postgresql.ENUM("approve", "reject", name="promotion_decision_type", create_type=False),
            nullable=False,
        ),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("comment", sa.String, nullable=True),
    )

    op.execute(
        """
        CREATE FUNCTION fn_reject_self_approval() RETURNS trigger AS $$
        DECLARE
            v_requested_by uuid;
        BEGIN
            SELECT requested_by INTO v_requested_by
            FROM promotion_requests
            WHERE id = NEW.promotion_request_id;

            IF v_requested_by = NEW.decided_by THEN
                RAISE EXCEPTION
                    'self-approval is not allowed: decided_by (%) matches the request''s requested_by',
                    NEW.decided_by
                    USING ERRCODE = '23514';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_reject_self_approval
        BEFORE INSERT ON promotion_decisions
        FOR EACH ROW EXECUTE FUNCTION fn_reject_self_approval();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_reject_self_approval ON promotion_decisions")
    op.execute("DROP FUNCTION IF EXISTS fn_reject_self_approval")
    op.drop_table("promotion_decisions")
    op.drop_table("promotion_requests")
    postgresql.ENUM(name="promotion_decision_type").drop(op.get_bind())
    postgresql.ENUM(name="promotion_request_status").drop(op.get_bind())
