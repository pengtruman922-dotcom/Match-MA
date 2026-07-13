"""buyer intent parser prompt v0.3

Revision ID: 20260608_0015
Revises: 20260608_0014
Create Date: 2026-06-08
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260608_0015"
down_revision: str | None = "20260608_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "015_buyer_intent_prompt_v03.sql")


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for prompt seed data.")
