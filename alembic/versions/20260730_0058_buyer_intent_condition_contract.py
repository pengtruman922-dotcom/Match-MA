"""Add the unified buyer-intent condition contract fields.

Revision ID: 20260730_0058
Revises: 20260729_0057
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260730_0058"
down_revision: str | None = "20260729_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "011_buyer_intent_condition_contract.sql")


def downgrade() -> None:
    op.execute("alter table buyer_intent_scenario drop constraint if exists chk_buyer_intent_scenario_condition_effects_json")
    op.execute("alter table buyer_intent_scenario drop column if exists condition_effects_json")
    op.execute("alter table buyer_intent drop constraint if exists chk_buyer_intent_condition_effects_json")
    op.execute("alter table buyer_intent drop constraint if exists chk_buyer_intent_acceptable_listed_status_json")
    op.execute("alter table buyer_intent drop column if exists condition_effects_json")
    op.execute("alter table buyer_intent drop column if exists acceptable_listed_status_json")
    op.execute(
        """
        alter table buyer_intent
          drop constraint if exists buyer_intent_preferred_listed_status_check,
          add constraint buyer_intent_preferred_listed_status_check
          check (
            preferred_listed_status = any (
              array['listed'::text, 'preparing_listing'::text, 'pre_ipo'::text,
                    'unlisted'::text, 'any'::text, 'unknown'::text]
            )
          )
        """
    )
