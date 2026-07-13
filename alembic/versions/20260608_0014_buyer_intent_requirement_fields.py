"""buyer intent requirement fields

Revision ID: 20260608_0014
Revises: 20260608_0013
Create Date: 2026-06-08
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260608_0014"
down_revision: str | None = "20260608_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "014_buyer_intent_requirement_fields.sql")


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for buyer intent field expansion.")
