"""R4a target information model.

Revision ID: 20260723_0049
Revises: 20260722_0048
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql


revision: str = "20260723_0049"
down_revision: str | None = "20260722_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "002_target_information_model.sql")


def downgrade() -> None:
    raise NotImplementedError("Production migrations are forward-only.")
