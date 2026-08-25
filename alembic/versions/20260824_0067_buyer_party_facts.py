"""Buyer party facts: what the buyer itself does becomes structured.

Revision ID: 20260824_0067
Revises: 20260819_0066
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260824_0067"
down_revision: str | None = "20260819_0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "020_buyer_party_facts.sql")


def downgrade() -> None:
    raise NotImplementedError(
        "region_province/region_city are merged into location_* and the two "
        "industry columns collapse into business_tags_json, so the way back "
        "cannot tell a migrated value from one a consultant typed afterwards"
    )
