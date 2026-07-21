"""buyer intent scenarios: global conditions AND (scenario OR scenario)

Revision ID: 20260721_0043
Revises: 20260720_0042
Create Date: 2026-07-21
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260721_0043"
down_revision: str | None = "20260720_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "043_buyer_intent_scenarios.sql")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("drop index if exists idx_buyer_intent_scenario_intent")
    bind.exec_driver_sql("drop table if exists buyer_intent_scenario")
