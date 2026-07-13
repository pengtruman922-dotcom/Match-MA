"""allow target_follow_up in extracted_action type check

Revision ID: 20260708_0029
Revises: 20260708_0028
Create Date: 2026-07-08
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260708_0029"
down_revision: str | None = "20260708_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "029_extracted_action_type_target_follow_up.sql")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("alter table extracted_action drop constraint if exists chk_extracted_action_type")
    bind.exec_driver_sql(
        """
        alter table extracted_action
          add constraint chk_extracted_action_type check (action_type in (
            'seller_fact_update',
            'seller_event',
            'buyer_seller_relation_update',
            'buyer_intent_target_exclusion',
            'buyer_intent_update',
            'buyer_level_blacklist_suggestion',
            'internal_note',
            'unresolved_item'
          ))
        """
    )
