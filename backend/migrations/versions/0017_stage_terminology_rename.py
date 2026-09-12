"""Phase 8 product correction (ADR-0023): rename Stage enum values away from
deployment language. "production" specifically implied Orion managed
deployment/traffic, which it never has and no longer will - Orion is a
registry/review platform, not a deployment platform. The state machine and
every invariant (one RECOMMENDED version per Agent, no-self-approval, hard
gates) are completely unchanged - this renames labels on the existing enum
type in place (ALTER TYPE ... RENAME VALUE), so every existing row keeps
its same underlying value and needs no data migration at all.

  candidate  -> evaluated
  production -> recommended
  retired    -> deprecated

draft/evaluating are unchanged.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-11

"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE stage RENAME VALUE 'candidate' TO 'evaluated'")
        op.execute("ALTER TYPE stage RENAME VALUE 'production' TO 'recommended'")
        op.execute("ALTER TYPE stage RENAME VALUE 'retired' TO 'deprecated'")

    # Cosmetic only - the partial unique index's predicate (`stage = 'production'`,
    # migration 0002) already continues to enforce correctly against the renamed
    # label with zero index rebuild needed (Postgres resolves enum literals by
    # OID, not text, and pg_get_indexdef always displays the CURRENT label).
    # Renaming the index itself just keeps its name legible for anyone reading
    # \d or pg_indexes going forward.
    op.execute(
        "ALTER INDEX uq_one_production_version_per_agent RENAME TO uq_one_recommended_version_per_agent"
    )


def downgrade() -> None:
    op.execute(
        "ALTER INDEX uq_one_recommended_version_per_agent RENAME TO uq_one_production_version_per_agent"
    )
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE stage RENAME VALUE 'evaluated' TO 'candidate'")
        op.execute("ALTER TYPE stage RENAME VALUE 'recommended' TO 'production'")
        op.execute("ALTER TYPE stage RENAME VALUE 'deprecated' TO 'retired'")
