"""R4e relation event audit fields and event codes.

Revision ID: 20260723_0050
Revises: 20260723_0049
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql


revision: str = "20260723_0050"
down_revision: str | None = "20260723_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "003_relation_event_audit.sql")


def downgrade() -> None:
    raise NotImplementedError("Production migrations are forward-only.")
