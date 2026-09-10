"""add 'dispatched' to evaluation_run_status enum

ALTER TYPE ... ADD VALUE cannot run inside the same transaction as other DDL
in Postgres < 12 semantics for some drivers; alembic handles this by running
autocommit for this statement specifically.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-10

"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE evaluation_run_status ADD VALUE IF NOT EXISTS 'dispatched'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums; downgrading this is a no-op by design
    # (matches the pattern - removing an enum value safely requires rebuilding the
    # type, not attempted here since no other migration in this repo does it either).
    pass
