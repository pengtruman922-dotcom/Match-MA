"""Add target-side risk and transaction-structure closed lists; drop the pseudo-enum.

Revision ID: 20260806_0062
Revises: 20260803_0061
Create Date: 2026-08-06
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260806_0062"
down_revision: str | None = "20260803_0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "015_target_risk_and_structure_facts.sql")


def downgrade() -> None:
    raise NotImplementedError("operation_stability_status values are not recoverable")
