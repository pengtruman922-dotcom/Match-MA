"""Make buyer_party the single shared buyer-profile record.

Revision ID: 20260803_0060
Revises: 20260802_0059
Create Date: 2026-08-03
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260803_0060"
down_revision: str | None = "20260802_0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "013_buyer_party_profile.sql")


def downgrade() -> None:
    # The dropped legacy profile columns cannot be restored without inventing
    # values. Downgrades are unsupported for this one-way data-model change.
    raise NotImplementedError("buyer_party profile migration is irreversible")
