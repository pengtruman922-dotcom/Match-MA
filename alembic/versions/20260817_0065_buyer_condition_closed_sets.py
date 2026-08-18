"""Buyer-side closed sets: risk tolerance, transaction structure, ratio units.

Revision ID: 20260817_0065
Revises: 20260814_0064
Create Date: 2026-08-17
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260817_0065"
down_revision: str | None = "20260814_0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "018_buyer_condition_closed_sets.sql")


def downgrade() -> None:
    raise NotImplementedError(
        "transaction_types_json is rewritten from free tags to a closed set and "
        "the payment-method values it dropped only survive as joined prose in "
        "transaction_type, so the original arrays cannot be reconstructed"
    )
