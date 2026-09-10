"""evaluation_policies, evaluation_run_references, evaluation_gate_results

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-09

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    postgresql.ENUM("requested", "completed", "failed", name="evaluation_run_status").create(op.get_bind())

    op.create_table(
        "evaluation_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("version", sa.String, nullable=False),
        sa.Column("required_evaluator_keys", postgresql.JSONB, nullable=False),
        sa.Column("thresholds", postgresql.JSONB, nullable=False),
        sa.Column("zero_new_regressions", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("dataset_key", sa.String, nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name", "version", name="uq_evaluation_policy_version"),
    )

    op.create_table(
        "evaluation_run_references",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "evaluation_policy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evaluation_policies.id"),
            nullable=False,
        ),
        sa.Column("external_run_id", sa.String, nullable=True),
        sa.Column("external_agent_version_id", sa.String, nullable=True),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "requested", "completed", "failed", name="evaluation_run_status", create_type=False
            ),
            nullable=False,
            server_default="requested",
        ),
        sa.Column("dataset_snapshot_hash", sa.String, nullable=True),
        sa.Column("evaluator_versions", postgresql.JSONB, nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "evaluation_gate_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "evaluation_run_reference_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evaluation_run_references.id"),
            nullable=False,
        ),
        sa.Column(
            "evaluation_policy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evaluation_policies.id"),
            nullable=False,
        ),
        sa.Column("criterion", sa.String, nullable=False),
        sa.Column("expected", sa.String, nullable=False),
        sa.Column("actual", sa.String, nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("evaluation_gate_results")
    op.drop_table("evaluation_run_references")
    op.drop_table("evaluation_policies")
    postgresql.ENUM(name="evaluation_run_status").drop(op.get_bind())
