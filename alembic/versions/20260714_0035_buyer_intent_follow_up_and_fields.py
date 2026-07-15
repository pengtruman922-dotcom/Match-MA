"""buyer intent follow-up and parser fields

Revision ID: 20260714_0035
Revises: 20260710_0034
Create Date: 2026-07-14
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260714_0035"
down_revision: str | None = "20260710_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "035_buyer_intent_follow_up_and_fields.sql")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("drop table if exists buyer_intent_follow_up")
    for column in (
        "industry_focus_tags_json",
        "min_gross_margin",
        "min_net_margin",
        "max_ps",
        "min_valuation_yuan",
    ):
        bind.exec_driver_sql(f"alter table buyer_intent drop column if exists {column}")
