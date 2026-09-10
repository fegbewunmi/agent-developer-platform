"""Phase 3: evaluation policy immutability, capability-grant evidence snapshot,
summary evidence storage, and richer gate-result evidence.

- evaluation_policies: immutable at the DB level like agent_versions/skill_versions
  (revoke UPDATE/DELETE for agent_platform_app in 0011) - "favor reproducibility"
  per the Phase 3 brief; editing a policy means publishing a new (name, version) row,
  never patching one in place. See docs/adrs/0015-evaluation-policy-immutability.md.
- evaluation_run_references: adds dataset_id/evaluator_ids actually submitted to
  agent-eval, dimension_stats/case summary counts (summary evidence only - never
  full case-level results, per docs/control-plane-boundaries.md), the capability
  grant evidence snapshot (ADR-0014), and an error_message for failed runs.
- evaluation_gate_results: adds gate_type, reason, and evidence_ref for inspectable,
  non-opaque gate results (docs/evaluation-and-promotion.md).

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-10

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- evaluation_policies: replace the single zero_new_regressions bool with a
    # richer, still-reproducible gate spec. thresholds/required_evaluator_keys already
    # support arbitrary per-dimension/per-evaluator detail as JSONB (unchanged).
    op.add_column(
        "evaluation_policies",
        sa.Column("max_new_regressions", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column(
        "evaluation_policies",
        sa.Column("zero_failure_tags", postgresql.ARRAY(sa.String), nullable=False, server_default="{}"),
    )
    op.add_column(
        "evaluation_policies",
        sa.Column("min_completion_rate", sa.Numeric(4, 3), nullable=False, server_default="1.0"),
    )
    op.drop_column("evaluation_policies", "zero_new_regressions")

    # --- evaluation_run_references: what was actually submitted + summary evidence
    # external_agent_version_id was optional in Phase 1's schema (no request flow existed
    # yet); Phase 3's integration always requires an explicit agent-eval identity link
    # (docs/evaluation-and-promotion.md's integration contract), so it becomes required.
    # No existing rows to migrate - Phase 1/2 never populated this table.
    op.alter_column("evaluation_run_references", "external_agent_version_id", nullable=False)
    op.add_column("evaluation_run_references", sa.Column("external_dataset_id", sa.String, nullable=True))
    op.add_column(
        "evaluation_run_references",
        sa.Column("external_evaluator_ids", postgresql.JSONB, nullable=True),
    )
    op.add_column("evaluation_run_references", sa.Column("dimension_stats", postgresql.JSONB, nullable=True))
    op.add_column("evaluation_run_references", sa.Column("n_cases_total", sa.Integer, nullable=True))
    op.add_column("evaluation_run_references", sa.Column("n_cases_success", sa.Integer, nullable=True))
    op.add_column("evaluation_run_references", sa.Column("n_cases_error", sa.Integer, nullable=True))
    op.add_column("evaluation_run_references", sa.Column("error_message", sa.String, nullable=True))

    # ADR-0014: capability grant evidence snapshot - a fingerprint, not a row dump.
    op.add_column(
        "evaluation_run_references", sa.Column("capability_grant_snapshot_hash", sa.String, nullable=True)
    )
    op.add_column(
        "evaluation_run_references", sa.Column("capability_grant_snapshot", postgresql.JSONB, nullable=True)
    )

    # Idempotency: a caller-supplied (or system-generated) key so a retried request
    # to trigger the same evaluation doesn't create a second reference/run - see
    # docs/failure-modes.md's "evaluation task retried" / "duplicate callback" handling.
    op.add_column("evaluation_run_references", sa.Column("idempotency_key", sa.String, nullable=True))
    op.create_index(
        "uq_evaluation_run_reference_idempotency_key",
        "evaluation_run_references",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    # --- evaluation_gate_results: non-opaque, inspectable evidence
    op.add_column("evaluation_gate_results", sa.Column("gate_type", sa.String, nullable=True))
    op.add_column("evaluation_gate_results", sa.Column("reason", sa.String, nullable=True))
    op.add_column("evaluation_gate_results", sa.Column("evidence_ref", postgresql.JSONB, nullable=True))
    op.execute("UPDATE evaluation_gate_results SET gate_type = 'unknown' WHERE gate_type IS NULL")
    op.alter_column("evaluation_gate_results", "gate_type", nullable=False)


def downgrade() -> None:
    op.alter_column("evaluation_run_references", "external_agent_version_id", nullable=True)
    op.drop_column("evaluation_gate_results", "evidence_ref")
    op.drop_column("evaluation_gate_results", "reason")
    op.drop_column("evaluation_gate_results", "gate_type")

    op.drop_index("uq_evaluation_run_reference_idempotency_key", table_name="evaluation_run_references")
    op.drop_column("evaluation_run_references", "idempotency_key")
    op.drop_column("evaluation_run_references", "capability_grant_snapshot")
    op.drop_column("evaluation_run_references", "capability_grant_snapshot_hash")
    op.drop_column("evaluation_run_references", "error_message")
    op.drop_column("evaluation_run_references", "n_cases_error")
    op.drop_column("evaluation_run_references", "n_cases_success")
    op.drop_column("evaluation_run_references", "n_cases_total")
    op.drop_column("evaluation_run_references", "dimension_stats")
    op.drop_column("evaluation_run_references", "external_evaluator_ids")
    op.drop_column("evaluation_run_references", "external_dataset_id")

    op.add_column(
        "evaluation_policies", sa.Column("zero_new_regressions", sa.Boolean, nullable=False, server_default="true")
    )
    op.drop_column("evaluation_policies", "min_completion_rate")
    op.drop_column("evaluation_policies", "zero_failure_tags")
    op.drop_column("evaluation_policies", "max_new_regressions")
