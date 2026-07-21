"""matching dimension alignment: industry L2 screening and buyer-side counterparts

Revision ID: 20260720_0042
Revises: 20260719_0041
Create Date: 2026-07-20
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260720_0042"
down_revision: str | None = "20260719_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "042_matching_dimension_alignment.sql")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "alter table buyer_intent drop constraint if exists chk_buyer_intent_requirement_strength"
    )
    bind.exec_driver_sql(
        "alter table buyer_intent drop constraint if exists chk_buyer_intent_listing_market_region"
    )
    bind.exec_driver_sql(
        "alter table seller_target drop constraint if exists chk_seller_target_listing_market_region"
    )
    for column in (
        "industry_l2_json",
        "acceptable_cash_flow_status_json",
        "acceptable_profitability_status_json",
        "requires_relocation",
        "relocation_target_regions_json",
        "requires_return_investment",
        "return_investment_multiple",
        "requires_team_retention",
        "earnout_requirement",
        "listing_market_region",
        "budget_min_yuan",
        "budget_max_yuan",
    ):
        bind.exec_driver_sql(f"alter table buyer_intent drop column if exists {column}")
    bind.exec_driver_sql("drop index if exists idx_seller_target_industry_l2")
    bind.exec_driver_sql("alter table seller_target drop column if exists industry_l2")
    bind.exec_driver_sql("alter table seller_target drop column if exists listing_market_region")
