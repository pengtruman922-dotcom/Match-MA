"""drop the unused research retry backoff column

Revision ID: 20260721_0047
Revises: 20260721_0046
Create Date: 2026-07-21
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260721_0047"
down_revision: str | None = "20260721_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "047_drop_research_retry_after.sql")


def downgrade() -> None:
    op.execute("alter table seller_target add column if not exists research_retry_after timestamptz")
