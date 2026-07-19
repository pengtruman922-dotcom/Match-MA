"""recommendation session condition overrides and query parser node

Revision ID: 20260719_0041
Revises: 20260715_0040
Create Date: 2026-07-19
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260719_0041"
down_revision: str | None = "20260715_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "041_recommendation_condition_overrides.sql")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("alter table recommendation_session drop column if exists condition_overrides_json")
    bind.exec_driver_sql("delete from prompt_template where node_name = 'recommendation_query_parser'")
    bind.exec_driver_sql("delete from model_node_config where node_name = 'recommendation_query_parser'")
