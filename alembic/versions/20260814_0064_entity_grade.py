"""Add target_grade / intent_grade with the grade-reason invariant (phase A).

Revision ID: 20260814_0064
Revises: 20260807_0063
Create Date: 2026-08-14
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260814_0064"
down_revision: str | None = "20260807_0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "017_entity_grade.sql")


def downgrade() -> None:
    raise NotImplementedError(
        "A-D collapses to 'active' on the way back, so the grades a consultant "
        "set by hand cannot be restored from lifecycle_status alone"
    )
