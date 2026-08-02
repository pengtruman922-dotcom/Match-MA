"""Reorganize buyer intent conditions into modules with their own "其他" blocks.

Revision ID: 20260802_0059
Revises: 20260730_0058
Create Date: 2026-08-02
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260802_0059"
down_revision: str | None = "20260730_0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "012_buyer_intent_modules.sql")


def downgrade() -> None:
    # 列能加回来，内容加不回来：它已经并进 entity_profile_section 的「其他」里，
    # 而那段文本此后可能被人编辑过，拆不回原来的四列。降级只恢复结构。
    op.execute(
        """
        alter table buyer_intent
          add column if not exists priority_summary text,
          add column if not exists preference_summary text,
          add column if not exists negative_summary text,
          add column if not exists unknown_summary text
        """
    )
    op.execute("delete from entity_profile_section where source_type = 'migrated_from_buyer_intent_columns'")
    op.execute("alter table entity_profile_section drop constraint if exists entity_profile_section_section_code_check")
    op.execute(
        """
        alter table entity_profile_section
          add constraint entity_profile_section_section_code_check
          check (section_code in (
            'identity', 'business_product', 'chain_position', 'tech_team',
            'ops_quality', 'deal_terms', 'sell_intent_risk'
          ))
        """
    )
