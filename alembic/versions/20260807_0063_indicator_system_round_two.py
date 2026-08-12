"""Swap the listing enum for exchanges, retire tech_team, drop four empty columns.

Revision ID: 20260807_0063
Revises: 20260806_0062
Create Date: 2026-08-07
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260807_0063"
down_revision: str | None = "20260806_0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "016_indicator_system_round_two.sql")


def downgrade() -> None:
    raise NotImplementedError(
        "domestic/overseas cannot be rebuilt from exchange codes, and the four "
        "dropped columns held no data to restore"
    )
