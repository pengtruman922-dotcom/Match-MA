"""Refine target information groups and support multi-industry facts.

Revision ID: 20260723_0051
Revises: 20260723_0050
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260723_0051"
down_revision: str | None = "20260723_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "004_information_refinement.sql")


def downgrade() -> None:
    raise NotImplementedError("R5 data consolidation is intentionally forward-only.")
