"""ocr attachment parser node v0.1

Revision ID: 20260603_0011
Revises: 20260602_0010
Create Date: 2026-06-03
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260603_0011"
down_revision: str | None = "20260602_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "011_ocr_attachment_parser_node_v01.sql")


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for OCR node seed data.")
