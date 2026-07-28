"""Guards for the consolidated seller_target status model (施工单 0727 · T1).

``recommendation_status`` is retired at runtime. A target now has exactly two orthogonal
statuses: ``lifecycle_status`` (交易状态, human-owned) and ``information_status``
(AI 处理进度, system-owned). These tests pin the removal so the coupling that
silently kept 8 production targets out of the recommendation pool cannot come
back through any of the paths that used to write the column.
"""

import re
from pathlib import Path

import pytest

from backend.app.registry.indicators import SELLER_TARGET_INDICATORS, indicator_by_column
from backend.app.api.routes.seller_targets import SellerTargetCreate, SellerTargetUpdate
from backend.app.services.relation_flow import _seller_target_deal_closed_changes

REPO = Path(__file__).resolve().parents[1]
RECOMMENDATION_FLOW = REPO / "backend/app/services/recommendation_flow.py"
SELLER_TARGETS_ROUTE = REPO / "backend/app/api/routes/seller_targets.py"
SEARCH_DOCS_ROUTE = REPO / "backend/app/api/routes/search_docs.py"
PARSE_HANDLER = REPO / "backend/app/jobs/handlers/seller_target_parse.py"
ACTION_APPLY = REPO / "backend/app/services/extracted_action_apply.py"
STATUS_MIGRATION = REPO / "database/migrations/005_target_status_consolidation.sql"
DROP_STATUS_MIGRATION = REPO / "database/migrations/006_drop_target_recommendation_status.sql"

# 只有 baseline 允许保留历史列名（它是地板，不可改）。
SOURCE_ROOTS = ("backend/app", "frontend/src")


def test_public_models_do_not_expose_retired_information_status_writes() -> None:
    assert SellerTargetCreate(target_name="新标的").information_status == "insufficient"
    assert "pending_review" not in str(SellerTargetCreate.model_fields["information_status"].annotation)
    assert "information_status" not in SellerTargetUpdate.model_fields


def test_deal_closed_changes_only_lifecycle_and_for_sale() -> None:
    changes = _seller_target_deal_closed_changes(
        {"lifecycle_status": "active", "is_for_sale": "yes"}
    )
    assert set(changes) == {"lifecycle_status", "is_for_sale"}
    assert changes["lifecycle_status"] == "sold"
    assert changes["is_for_sale"] == "no"


def test_deal_closed_changes_are_idempotent() -> None:
    assert _seller_target_deal_closed_changes(
        {"lifecycle_status": "sold", "is_for_sale": "no"}
    ) == {}


def test_registry_no_longer_declares_recommendation_status() -> None:
    with pytest.raises(KeyError):
        indicator_by_column("seller_target", "recommendation_status")
    assert "recommendation_status" not in {ind.column for ind in SELLER_TARGET_INDICATORS}


def test_recommendation_screening_uses_lifecycle_only() -> None:
    source = RECOMMENDATION_FLOW.read_text(encoding="utf-8")
    assert "st.lifecycle_status = 'active'" in source
    assert "recommendation_status" not in source


def test_search_doc_backfill_scopes_by_lifecycle() -> None:
    source = SEARCH_DOCS_ROUTE.read_text(encoding="utf-8")
    assert "st.lifecycle_status = 'active'" in source
    assert "recommendation_status" not in source


def test_display_status_is_pure_trade_lifecycle() -> None:
    """列表「状态」列只表达交易状态，不再混入解析进度或推荐闸门。"""
    source = SELLER_TARGETS_ROUTE.read_text(encoding="utf-8")
    block = re.search(
        r"SELLER_TARGET_DISPLAY_STATUS_SQL = \"\"\"(.*?)\"\"\"", source, re.S
    )
    assert block, "未找到 SELLER_TARGET_DISPLAY_STATUS_SQL"
    body = block.group(1)
    assert "recommendation_status" not in body
    assert "information_status" not in body
    for value in ("sold", "off_market", "active"):
        assert value in body


def test_post_parse_status_promotion_is_gone() -> None:
    """解析/采纳不再翻转任何状态闸门——这正是旧缺陷的根。"""
    for path in (PARSE_HANDLER, ACTION_APPLY):
        source = path.read_text(encoding="utf-8")
        assert "_seller_target_changes_with_post_parse_status" not in source, (
            f"{path.name} 仍保留 post-parse 状态翻转"
        )


def _strip_prose(source: str, suffix: str) -> str:
    """Drop comments and docstrings so only executable references remain.

    The removal is documented in several comments that name the retired column
    on purpose; those must not read as violations.
    """
    if suffix == ".py":
        source = re.sub(r'"""(?:.|\n)*?"""', "", source)
        source = re.sub(r"#[^\n]*", "", source)
    else:
        source = re.sub(r"/\*(?:.|\n)*?\*/", "", source)
        source = re.sub(r"//[^\n]*", "", source)
    return source


def test_runtime_has_no_recommendation_status_references() -> None:
    offenders: list[str] = []
    for root in SOURCE_ROOTS:
        for path in (REPO / root).rglob("*"):
            if path.suffix not in {".py", ".ts", ".tsx"} or "__pycache__" in path.parts:
                continue
            code = _strip_prose(path.read_text(encoding="utf-8"), path.suffix)
            if "recommendation_status" in code:
                offenders.append(path.relative_to(REPO).as_posix())
    assert offenders == [], f"阶段 B 后运行时代码不得再引用旧列：{sorted(offenders)}"


def test_phase_a_migration_keeps_column_and_adds_new_scope_index() -> None:
    sql = STATUS_MIGRATION.read_text(encoding="utf-8").lower()
    assert "drop column recommendation_status" not in sql
    assert "drop constraint" not in sql
    assert "drop index" not in sql
    assert "idx_seller_target_lifecycle_scope" in sql
    assert "lifecycle_status, information_status" in sql
    assert "add column if not exists last_parse_at timestamptz" in sql


def test_migration_backfills_pending_review() -> None:
    sql = STATUS_MIGRATION.read_text(encoding="utf-8").lower()
    assert "information_status = 'pending_review'" in sql
    assert "set information_status = 'normal'" in sql


def test_phase_b_migration_drops_legacy_objects_before_column() -> None:
    sql = DROP_STATUS_MIGRATION.read_text(encoding="utf-8").lower()
    drop_index = sql.index("drop index if exists idx_seller_target_scope")
    drop_check = sql.index(
        "drop constraint if exists seller_target_recommendation_status_check"
    )
    drop_column = sql.index("drop column if exists recommendation_status")
    rename_index = sql.index(
        "alter index if exists idx_seller_target_lifecycle_scope"
    )
    assert drop_index < drop_column
    assert drop_check < drop_column
    assert drop_column < rename_index
    assert "rename to idx_seller_target_scope" in sql


def test_phase_b_alembic_revision_follows_phase_a() -> None:
    source = (
        REPO / "alembic/versions/20260727_0053_drop_target_recommendation_status.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "20260727_0053"' in source
    assert 'down_revision: str | None = "20260727_0052"' in source
    assert (
        'run_migration_sql(op.get_bind(), "006_drop_target_recommendation_status.sql")'
        in source
    )
