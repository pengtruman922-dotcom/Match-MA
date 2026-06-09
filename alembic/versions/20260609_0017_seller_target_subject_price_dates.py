"""seller target subject and price dates

Revision ID: 20260609_0017
Revises: 20260608_0016
Create Date: 2026-06-09
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import load_migration_sql, split_sql_statements

revision: str = "20260609_0017"
down_revision: str | None = "20260608_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    sql = load_migration_sql("017_seller_target_subject_price_dates.sql")
    for statement in split_sql_statements(sql):
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for seller target field expansion.")
