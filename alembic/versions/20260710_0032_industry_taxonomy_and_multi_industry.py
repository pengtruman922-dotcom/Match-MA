"""industry taxonomy and multi-industry intent fields

Revision ID: 20260710_0032
Revises: 20260709_0031
Create Date: 2026-07-10
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260710_0032"
down_revision: str | None = "20260709_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "032_industry_taxonomy_and_multi_industry.sql")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("alter table buyer_intent drop column if exists excluded_industries_json")
    bind.exec_driver_sql("alter table buyer_intent drop column if exists industries_json")
    bind.exec_driver_sql("alter table seller_target drop column if exists industry_l1")
    bind.exec_driver_sql("drop table if exists industry_taxonomy")
