"""Phase 9 (ADR-0025): SkillVersionLifecycle, SkillReviewRequest,
SkillReviewDecision - a SkillVersion's own "recommended" concept and review
workflow, structurally parallel to AgentVersionLifecycle/PromotionRequest/
PromotionDecision but NOT a reuse of them: a SkillVersion has no automated
evaluation/gate step (no agent-eval integration for skills), so forcing it
through PromotionRequest would mean either fabricating fake evaluation rows
or loosening that table's currently-hard evaluation_run_reference_id/
evaluation_policy_id constraints.

skill_version_lifecycle: every existing SkillVersion is backfilled to
PUBLISHED so the new table is never left with a SkillVersion missing a
lifecycle row (application code always expects one to exist, mirroring
AgentVersionLifecycle).

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-12

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    skill_stage_enum = postgresql.ENUM("published", "recommended", "deprecated", name="skill_stage")
    skill_stage_enum.create(bind)
    skill_review_status_enum = postgresql.ENUM(
        "pending", "approved", "rejected", name="skill_review_request_status"
    )
    skill_review_status_enum.create(bind)
    skill_review_decision_enum = postgresql.ENUM("approve", "reject", name="skill_review_decision_type")
    skill_review_decision_enum.create(bind)

    op.create_table(
        "skill_version_lifecycle",
        sa.Column(
            "skill_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skill_versions.id"), primary_key=True
        ),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.id"), nullable=False),
        sa.Column(
            "stage",
            postgresql.ENUM("published", "recommended", "deprecated", name="skill_stage", create_type=False),
            nullable=False,
            server_default="published",
        ),
        sa.Column("entered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("entered_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
    )

    # One RECOMMENDED SkillVersion per Skill - the same invariant shape as
    # agent_version_lifecycle's uq_one_production_version_per_agent.
    op.create_index(
        "uq_one_recommended_version_per_skill",
        "skill_version_lifecycle",
        ["skill_id"],
        unique=True,
        postgresql_where=sa.text("stage = 'recommended'"),
    )

    # Backfill: every existing SkillVersion gets a PUBLISHED lifecycle row,
    # entered_by its own owner_user_id (the closest real "who published
    # this" fact already on the row) so no lifecycle row is ever left
    # without a real, attributable entered_by.
    op.execute(
        """
        INSERT INTO skill_version_lifecycle (skill_version_id, skill_id, stage, entered_by)
        SELECT id, skill_id, 'published', owner_user_id FROM skill_versions
        """
    )

    op.create_table(
        "skill_review_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "skill_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skill_versions.id"), nullable=False
        ),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM("pending", "approved", "rejected", name="skill_review_request_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("reason", sa.String, nullable=True),
    )

    op.create_table(
        "skill_review_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "skill_review_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skill_review_requests.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "decision",
            postgresql.ENUM("approve", "reject", name="skill_review_decision_type", create_type=False),
            nullable=False,
        ),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("comment", sa.String, nullable=True),
    )

    op.execute(
        """
        CREATE FUNCTION fn_reject_self_approval_skill_review() RETURNS trigger AS $$
        DECLARE
            v_requested_by uuid;
        BEGIN
            SELECT requested_by INTO v_requested_by
            FROM skill_review_requests
            WHERE id = NEW.skill_review_request_id;

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
        CREATE TRIGGER trg_reject_self_approval_skill_review
        BEFORE INSERT ON skill_review_decisions
        FOR EACH ROW EXECUTE FUNCTION fn_reject_self_approval_skill_review();
        """
    )

    # Grants, mirroring migrations 0008/0015 exactly:
    # skill_version_lifecycle is mutable (stage transitions), like
    # agent_version_lifecycle. skill_review_requests: status-only mutation.
    # skill_review_decisions: fully immutable once created.
    bind.exec_driver_sql("GRANT SELECT, INSERT, UPDATE, DELETE ON skill_version_lifecycle TO agent_platform_app")
    bind.exec_driver_sql("GRANT SELECT, INSERT ON skill_review_requests TO agent_platform_app")
    bind.exec_driver_sql("GRANT UPDATE (status) ON skill_review_requests TO agent_platform_app")
    bind.exec_driver_sql("GRANT SELECT, INSERT ON skill_review_decisions TO agent_platform_app")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("REVOKE SELECT, INSERT ON skill_review_decisions FROM agent_platform_app")
    bind.exec_driver_sql("REVOKE SELECT, INSERT, UPDATE ON skill_review_requests FROM agent_platform_app")
    bind.exec_driver_sql("REVOKE SELECT, INSERT, UPDATE, DELETE ON skill_version_lifecycle FROM agent_platform_app")

    op.execute("DROP TRIGGER IF EXISTS trg_reject_self_approval_skill_review ON skill_review_decisions")
    op.execute("DROP FUNCTION IF EXISTS fn_reject_self_approval_skill_review")
    op.drop_table("skill_review_decisions")
    op.drop_table("skill_review_requests")
    op.drop_index("uq_one_recommended_version_per_skill", table_name="skill_version_lifecycle")
    op.drop_table("skill_version_lifecycle")

    postgresql.ENUM(name="skill_review_decision_type").drop(bind)
    postgresql.ENUM(name="skill_review_request_status").drop(bind)
    postgresql.ENUM(name="skill_stage").drop(bind)
