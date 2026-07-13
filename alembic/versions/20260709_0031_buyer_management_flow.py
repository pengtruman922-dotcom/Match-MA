"""buyer management flow refinements

Revision ID: 20260709_0031
Revises: 20260709_0030
Create Date: 2026-07-09
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260709_0031"
down_revision: str | None = "20260709_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "031_buyer_management_flow.sql")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("alter table buyer_party drop column if exists notes")
    bind.exec_driver_sql("alter table buyer_intent drop constraint if exists buyer_intent_status_check")
    bind.exec_driver_sql(
        """
        alter table buyer_intent
          add constraint buyer_intent_status_check
          check (status in ('active', 'paused'))
        """
    )
