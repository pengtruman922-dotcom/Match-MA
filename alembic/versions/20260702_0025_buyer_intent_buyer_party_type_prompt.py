"""buyer intent buyer party type prompt tuning

Revision ID: 20260702_0025
Revises: 20260702_0024
Create Date: 2026-07-02
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260702_0025"
down_revision: str | None = "20260702_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "025_buyer_intent_buyer_party_type_prompt.sql")


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for prompt seed data.")
