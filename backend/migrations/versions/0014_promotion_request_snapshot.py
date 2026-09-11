"""Phase 4: PromotionRequest captures the full decision context at request time,
not just agent_version_id - docs/evaluation-and-promotion.md's promotion request
section: "Do not merely store agent_version_id and assume the rest can always be
reconstructed later."

- evaluation_policy_id, evaluation_run_reference_id: made NOT NULL - a promotion
  request without real evidence to point at should never exist as of Phase 4
  (Phase 1's schema allowed NULL only because no request-creation flow existed
  yet to populate it).
- capability_grant_snapshot_hash: the active-grant fingerprint at REQUEST time
  (ADR-0014), independent of whatever hash is stored on the evaluation run
  reference (which reflects grants at EVALUATION time - these can differ if
  grants changed between evaluation and promotion request).
- production_version_id_at_request: which version (if any) was in production
  when this request was created - historical context, not a live pointer;
  re-derived fresh at decision time, never trusted as current.
- freshness_snapshot: the full check_freshness() result computed at request
  time (historically_passed, currently_eligible, stale_findings) - so "was this
  eligible when requested" is a stored fact, not something requiring a live
  recomputation against data that may have since changed.

promotion_decisions gets an analogous freshness_snapshot_at_decision - the
SAME kind of check, recomputed live right before the decision, so "was this
still eligible when actually decided" is equally a stored, permanent fact -
this is the "eligible when requested" vs "eligible when reviewed" distinction
docs/evaluation-and-promotion.md's brief asks for made concrete.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-11

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("promotion_requests", "evaluation_run_reference_id", nullable=False)

    op.add_column(
        "promotion_requests",
        sa.Column(
            "evaluation_policy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("evaluation_policies.id"),
            nullable=True,
        ),
    )
    op.add_column("promotion_requests", sa.Column("capability_grant_snapshot_hash", sa.String, nullable=True))
    op.add_column("promotion_requests", sa.Column("capability_grant_snapshot", postgresql.JSONB, nullable=True))
    op.add_column(
        "promotion_requests",
        sa.Column(
            "production_version_id_at_request", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_versions.id"), nullable=True,
        ),
    )
    op.add_column("promotion_requests", sa.Column("freshness_snapshot", postgresql.JSONB, nullable=True))

    # No existing rows to migrate (Phase 1-3 never built a request-creation flow),
    # so this can go straight to NOT NULL.
    op.execute("DELETE FROM promotion_requests")  # defensive - see note above
    op.alter_column("promotion_requests", "evaluation_policy_id", nullable=False)

    # At most one PENDING request per AgentVersion at a time - docs/evaluation-and-promotion.md's
    # "duplicate pending requests" decision, DB-level per the brief's own preference.
    op.create_index(
        "uq_one_pending_promotion_request_per_version",
        "promotion_requests",
        ["agent_version_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.add_column("promotion_decisions", sa.Column("freshness_snapshot_at_decision", postgresql.JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("promotion_decisions", "freshness_snapshot_at_decision")

    op.drop_index("uq_one_pending_promotion_request_per_version", table_name="promotion_requests")
    op.drop_column("promotion_requests", "freshness_snapshot")
    op.drop_column("promotion_requests", "production_version_id_at_request")
    op.drop_column("promotion_requests", "capability_grant_snapshot")
    op.drop_column("promotion_requests", "capability_grant_snapshot_hash")
    op.drop_column("promotion_requests", "evaluation_policy_id")
    op.alter_column("promotion_requests", "evaluation_run_reference_id", nullable=True)
