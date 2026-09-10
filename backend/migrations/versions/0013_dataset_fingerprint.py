"""evaluation_run_references: dataset_case_set_fingerprint

A distinctly-named proxy for dataset freshness, deliberately NOT called
dataset_snapshot_hash (that column already holds agent-eval's own hash, computed
server-side over case content this platform cannot see). See
app/services/freshness.py's module docstring for the exact, honest limitation of
this fingerprint - it catches cases added/removed/renamed/re-tagged, not in-place
content edits to an existing case.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-10

"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "evaluation_run_references", sa.Column("dataset_case_set_fingerprint", sa.String, nullable=True)
    )


def downgrade() -> None:
    op.drop_column("evaluation_run_references", "dataset_case_set_fingerprint")
