"""seed defaults

Revision ID: 20260527_0002
Revises: 20260527_0001
Create Date: 2026-05-27
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260527_0002"
down_revision: str | None = "20260527_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "002_seed_defaults.sql")


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for seed data.")
