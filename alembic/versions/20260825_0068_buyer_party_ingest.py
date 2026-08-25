"""Buyer party ingest: parse, research and normalize proposals land on the party.

Revision ID: 20260825_0068
Revises: 20260824_0067
Create Date: 2026-08-25
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260825_0068"
down_revision: str | None = "20260824_0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "021_buyer_party_ingest.sql")


def downgrade() -> None:
    raise NotImplementedError(
        "Narrowing entity_type again would leave buyer_party proposals violating "
        "the constraint, and deleting them would discard reviewed evidence"
    )
