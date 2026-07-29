"""Add the found_but_rejected research outcome.

Revision ID: 20260728_0055
Revises: 20260728_0054
Create Date: 2026-07-28
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260728_0055"
down_revision: str | None = "20260728_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "008_research_outcome_found_but_rejected.sql")


def downgrade() -> None:
    op.execute("alter table seller_target drop constraint if exists chk_seller_target_research_outcome")
    op.execute(
        "alter table seller_target add constraint chk_seller_target_research_outcome "
        "check (research_last_outcome is null or research_last_outcome = any ("
        "array['found'::text, 'no_public_information'::text, 'failed'::text]))"
    )
