"""Add buyer-intent review and scenario confirmation fields.

Revision ID: 20260729_0057
Revises: 20260728_0056
Create Date: 2026-07-29
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260729_0057"
down_revision: str | None = "20260728_0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "010_buyer_intent_review.sql")


def downgrade() -> None:
    op.execute("drop index if exists idx_buyer_intent_review_pending")
    op.execute("alter table buyer_intent_scenario drop column if exists needs_confirmation_json")
    op.execute("alter table buyer_intent drop constraint if exists buyer_intent_reviewed_by_fkey")
    op.execute("alter table buyer_intent drop column if exists reviewed_by")
    op.execute("alter table buyer_intent drop column if exists reviewed_at")
    op.execute("alter table buyer_intent drop column if exists needs_confirmation_json")
