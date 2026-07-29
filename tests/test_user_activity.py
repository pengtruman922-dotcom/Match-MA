"""账号管理「最近活跃」的口径守护（数据看板拆除后的落点）。

旧的 /users/activity-summary 把 seller_target / buyer_party / buyer_intent 的
``updated_at`` 算进活跃度，而 field_writer 每次写字段都会刷新它——AI 解析和
调研回填于是被记成负责人的活跃。这里把「只统计人主动做的事」钉死。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text

from backend.app.api.routes import users as users_route
from backend.app.api.routes.users import (
    USER_ACTIVITY_SOURCES,
    USER_LIST_SQL,
    UserOut,
    _latest_activity_sql,
    _user_row,
)

REPO = Path(__file__).resolve().parents[1]
USERS_ROUTE = REPO / "backend/app/api/routes/users.py"
FRONTEND = REPO / "frontend/src"


def test_activity_sources_are_human_actions_only() -> None:
    assert {table for table, *_ in USER_ACTIVITY_SOURCES} == {
        "business_update",
        "relation_event",
        "action_application_log",
        "recommendation_message",
    }


def test_automatic_parse_and_research_logs_are_attributed_to_system_user() -> None:
    """机器可以写 action_application_log，但不能冒充发起调研的顾问。"""
    automatic_paths = (
        REPO / "backend/app/services/extracted_action_apply.py",
        REPO / "backend/app/jobs/handlers/seller_target_parse.py",
        REPO / "backend/app/jobs/handlers/buyer_intent_parse.py",
        REPO / "backend/app/jobs/handlers/research.py",
    )
    sources = "\n".join(path.read_text(encoding="utf-8") for path in automatic_paths)

    assert "actor_user_id=SYSTEM_USER_ID" in sources
    assert '"applied_by": SYSTEM_USER_ID' in sources
    assert "user_id=SYSTEM_USER_ID" in sources

    extracted_tree = ast.parse(
        (REPO / "backend/app/services/extracted_action_apply.py").read_text(encoding="utf-8")
    )
    audit_calls = [
        node
        for node in ast.walk(extracted_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "write_action_logs_for_diff"
    ]
    assert audit_calls
    for call in audit_calls:
        applied_by = next((kw.value for kw in call.keywords if kw.arg == "applied_by"), None)
        assert isinstance(applied_by, ast.Name) and applied_by.id == "SYSTEM_USER_ID"


def test_owned_object_updated_at_is_not_an_activity_signal() -> None:
    sql = USER_LIST_SQL.lower()
    activity = sql[sql.index("as latest_activity_at") - 2000 : sql.index("as latest_activity_at")]
    for table in ("seller_target", "buyer_party", "buyer_intent"):
        assert f"max({table}.updated_at)" not in activity
    assert "updated_at" not in activity


def test_soft_deleted_relation_events_do_not_count() -> None:
    generated = _latest_activity_sql("u.id")
    relation_clause = next(
        part for part in generated.split("coalesce(") if "relation_event" in part
    )
    assert "deleted_at is null" in relation_clause


def test_activity_sql_accepts_a_bound_parameter_expression() -> None:
    """_owned_counts 复用同一段 SQL，但主体是 :user_id 而不是 u.id。"""
    generated = _latest_activity_sql(":user_id")

    assert generated.count(":user_id") == len(USER_ACTIVITY_SOURCES)
    assert "u.id" not in generated


def test_latest_activity_picks_the_newest_human_action() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    # sqlite 没有 greatest()，注册一个同名函数，让被测 SQL 一个字都不用改写。
    @event.listens_for(engine, "connect")
    def _register_greatest(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.create_function("greatest", -1, lambda *values: max(values))

    schema = (
        "create table business_update (created_by text, created_at text)",
        "create table relation_event (created_by text, created_at text, deleted_at text)",
        "create table action_application_log (applied_by text, applied_at text)",
        "create table recommendation_message (created_by text, created_at text)",
    )
    actor = "11111111-1111-1111-1111-111111111111"
    idle = "22222222-2222-2222-2222-222222222222"

    with engine.begin() as connection:
        for statement in schema:
            connection.execute(text(statement))
        connection.execute(
            text("insert into business_update values (:by, :at)"),
            [{"by": actor, "at": "2026-07-20T09:00:00"}],
        )
        connection.execute(
            text("insert into relation_event values (:by, :at, :deleted_at)"),
            [
                {"by": actor, "at": "2026-07-22T09:00:00", "deleted_at": None},
                # 撤回的动态不能继续算活跃。
                {"by": actor, "at": "2026-07-28T09:00:00", "deleted_at": "2026-07-28"},
            ],
        )
        connection.execute(
            text("insert into action_application_log values (:by, :at)"),
            [{"by": actor, "at": "2026-07-25T09:00:00"}],
        )
        connection.execute(
            text("insert into recommendation_message values (:by, :at)"),
            [{"by": actor, "at": "2026-07-21T09:00:00"}],
        )

        # sqlite 没有 timestamptz，把地板换成一个可比较的字符串。
        expression = (
            _latest_activity_sql(":user_id")
            .replace("'-infinity'::timestamptz", "''")
            .replace("::text", "")
        )
        rows = {
            user: connection.execute(
                text(f"select {expression} as latest"), {"user_id": user}
            ).scalar_one()
            for user in (actor, idle)
        }

    assert rows[actor] == "2026-07-25T09:00:00"
    assert rows[idle] == ""


def test_never_acted_account_is_reported_as_null() -> None:
    assert _user_row({"latest_activity_at": "-infinity"})["latest_activity_at"] is None
    assert _user_row({"latest_activity_at": "2026-07-25T09:00:00"})["latest_activity_at"] == (
        "2026-07-25T09:00:00"
    )


def test_user_out_carries_latest_activity() -> None:
    payload: dict[str, Any] = {
        "id": UUID("11111111-1111-1111-1111-111111111111"),
        "username": "zhangsan",
        "name": "张三",
        "role": "consultant",
        "status": "active",
        "created_at": "2026-01-01T00:00:00",
        "owned_seller_targets": 3,
        "owned_buyer_parties": 1,
        "owned_buyer_intents": 2,
        "latest_activity_at": None,
    }

    assert UserOut(**payload).latest_activity_at is None


def _strip_prose(source: str, suffix: str) -> str:
    if suffix == ".py":
        source = re.sub(r'"""(?:.|\n)*?"""', "", source)
        source = re.sub(r"#[^\n]*", "", source)
    else:
        source = re.sub(r"/\*(?:.|\n)*?\*/", "", source)
        source = re.sub(r"//[^\n]*", "", source)
    return source


def test_activity_summary_endpoint_is_gone_everywhere() -> None:
    offenders: list[str] = []
    code = _strip_prose(USERS_ROUTE.read_text(encoding="utf-8"), ".py")
    if "activity-summary" in code or "UserActivitySummaryOut" in code:
        offenders.append(USERS_ROUTE.relative_to(REPO).as_posix())
    for path in FRONTEND.rglob("*"):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        code = _strip_prose(path.read_text(encoding="utf-8"), path.suffix)
        if "activity-summary" in code or "AppUserActivitySummary" in code:
            offenders.append(path.relative_to(REPO).as_posix())

    assert offenders == [], f"人员活跃度表已下线，不应再有引用：{sorted(offenders)}"


def test_retired_activity_summary_path_returns_404() -> None:
    app = FastAPI()
    app.include_router(users_route.router, prefix="/api/v1")

    with TestClient(app) as client:
        response = client.get("/api/v1/users/activity-summary")

    assert response.status_code == 404


def test_dashboard_page_no_longer_fetches_user_statistics() -> None:
    source = (FRONTEND / "pages/Dashboard.tsx").read_text(encoding="utf-8")

    assert "users" not in _strip_prose(source, ".tsx")
    assert "isAdmin" not in source, "数据看板改为全员可见"
