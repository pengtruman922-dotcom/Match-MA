"""撮合看板瘦端点（GET /relations/board）的取数契约守护。"""

from __future__ import annotations

from itertools import product
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from backend.app.api.authn import AuthContext, get_auth_context
from backend.app.api.routes import relations
from backend.app.api.routes.relations import (
    RelationBoardCardOut,
    _relation_base_where,
    _relation_board_columns,
    _relation_select_columns,
)
from backend.app.api.routes.utils import (
    relation_owner_sql,
    relation_sole_owner_sql,
    relation_visible_sql,
)
from backend.app.config import get_settings
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db
from backend.app.main import create_app


_USER = AuthContext(
    user_id=UUID("11111111-1111-1111-1111-111111111111"),
    role="consultant",
    name="看板验收顾问",
    username="board-acceptance",
)
_EXPECTED_BOARD_FIELDS = {
    "id",
    "seller_target_id",
    "buyer_intent_id",
    "status",
    "last_event_at",
    "last_activity_at",
    "seller_target_name",
    "buyer_intent_name",
    "buyer_name",
}
_FAT_ONLY_COLUMNS = (
    "last_event_type",
    "last_event_content",
    "last_event_next_step",
    "last_event_summary",
    "deep_progress_elsewhere",
    "metadata_json",
    "status_reason",
)


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows or []

    def mappings(self) -> _FakeResult:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def execute(self, statement: Any, params: dict[str, Any]) -> _FakeResult:
        self.calls.append((statement, dict(params)))
        return _FakeResult(self.rows)


def _board_app(db: _FakeSession) -> FastAPI:
    app = FastAPI()
    app.include_router(relations.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_auth_context] = lambda: _USER
    return app


def _board_row() -> dict[str, Any]:
    return {
        "id": UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        "seller_target_id": UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        "buyer_intent_id": UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        "status": "recommended",
        "last_event_at": None,
        "last_activity_at": "2026-07-26T00:00:00+00:00",
        "seller_target_name": "看板验收0726标的",
        "buyer_intent_name": "看板验收0726意向",
        "buyer_name": "看板验收0726买家",
    }


def test_board_columns_are_exactly_the_nine_slim_fields() -> None:
    expected_sql = """
      r.id, r.seller_target_id, r.buyer_intent_id, r.status,
      r.last_event_at::text as last_event_at,
      coalesce(r.last_event_at, r.updated_at, r.created_at)::text as last_activity_at,
      st.target_name as seller_target_name,
      bi.intent_name as buyer_intent_name,
      bp.buyer_name
    """
    columns = _relation_board_columns()

    assert " ".join(columns.split()) == " ".join(expected_sql.split())
    assert set(RelationBoardCardOut.model_fields) == _EXPECTED_BOARD_FIELDS
    assert "select" not in columns.lower()
    for column in _FAT_ONLY_COLUMNS:
        assert column not in columns


def test_board_route_wins_before_uuid_route_and_returns_exact_schema() -> None:
    db = _FakeSession([_board_row()])
    app = _board_app(db)
    client = TestClient(app)

    paths = list(app.openapi()["paths"])
    response = client.get("/api/v1/relations/board?limit=1")

    assert paths.index("/api/v1/relations/board") < paths.index("/api/v1/relations/{relation_id}")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert set(response.json()[0]) == _EXPECTED_BOARD_FIELDS
    assert response.json()[0]["last_activity_at"] is not None
    assert len(db.calls) == 1


@pytest.mark.parametrize(
    "query",
    (
        "ownership=invalid",
        "limit=0",
        "limit=5001",
        "offset=-1",
        f"q={'x' * 201}",
        "owner=not-a-uuid",
    ),
)
def test_board_route_rejects_invalid_query_without_hitting_db(query: str) -> None:
    db = _FakeSession()
    client = TestClient(_board_app(db))

    response = client.get(f"/api/v1/relations/board?{query}")

    assert response.status_code == 422
    assert db.calls == []


@pytest.mark.parametrize(
    ("owner_scope_enforced", "ownership", "visible_count", "sole_count"),
    (
        (False, "all", 0, 0),
        (False, "involved", 1, 0),
        (False, "sole", 0, 1),
        (True, "all", 1, 0),
        (True, "involved", 1, 0),
        (True, "sole", 1, 1),
    ),
)
def test_board_sql_scope_matrix_and_bind_params(
    owner_scope_enforced: bool,
    ownership: str,
    visible_count: int,
    sole_count: int,
) -> None:
    db = _FakeSession()

    with patch.object(relations, "owner_scope_required", return_value=owner_scope_enforced):
        result = relations.list_relations_board(
            current_user=_USER,
            db=db,
            ownership=ownership,
            q=None,
            limit=2000,
            offset=0,
        )

    statement, params = db.calls[0]
    sql = str(statement)
    assert result == []
    assert sql.count("from seller_target scope_st") == visible_count
    assert sql.count("from seller_target sole_st") == sole_count
    assert ("scope_user_id" in params) is bool(visible_count or sole_count)
    assert set(statement._bindparams) == set(params)
    assert sql.count("(") == sql.count(")")


def test_board_owner_filter_is_absent_unless_requested() -> None:
    """没传 owner 就一个字节的负责人谓词都不该进 SQL。

    owner 用的是裸 None 默认值——若换成 Query(default=None)，直接调用本函数时
    默认值是 FieldInfo 而非 None，这条断言会立刻挂。
    """
    db = _FakeSession()

    with patch.object(relations, "owner_scope_required", return_value=False):
        relations.list_relations_board(
            current_user=_USER,
            db=db,
            ownership="all",
            q=None,
            limit=2000,
            offset=0,
        )

    statement, params = db.calls[0]
    assert "owner_user_id" not in str(statement)
    assert "owner_user_id" not in params


def test_board_owner_filter_binds_its_own_param_and_ands_with_scope() -> None:
    """负责人筛选与权限地板必须是两个独立参数，否则后写的值会盖掉地板。"""
    db = _FakeSession()
    picked = UUID("22222222-2222-2222-2222-222222222222")

    with patch.object(relations, "owner_scope_required", return_value=True):
        relations.list_relations_board(
            current_user=_USER,
            db=db,
            ownership="sole",
            owner=picked,
            q=None,
            limit=2000,
            offset=0,
        )

    statement, params = db.calls[0]
    sql = str(statement)
    assert params["owner_user_id"] == picked
    assert params["scope_user_id"] == _USER.user_id
    assert sql.count("from seller_target owner_st") == 1
    assert sql.count("from seller_target scope_st") == 1
    assert sql.count("from seller_target sole_st") == 1
    assert set(statement._bindparams) == set(params)
    assert sql.count("(") == sql.count(")")


def test_owner_predicate_selects_relations_on_any_side() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    schema = (
        "create table seller_target (id text primary key, owner_user_id text, deleted_at text)",
        "create table buyer_party (id text primary key, owner_user_id text, deleted_at text)",
        "create table buyer_intent ("
        "id text primary key, buyer_party_id text, owner_user_id text, deleted_at text)",
        "create table buyer_seller_relation ("
        "id text primary key, seller_target_id text, buyer_intent_id text, buyer_party_id text)",
    )
    picked = "22222222-2222-2222-2222-222222222222"
    other = "33333333-3333-3333-3333-333333333333"

    with engine.begin() as connection:
        for statement in schema:
            connection.execute(text(statement))
        connection.execute(
            text("insert into seller_target values (:id, :owner, :deleted_at)"),
            [
                {"id": "st-picked", "owner": picked, "deleted_at": None},
                {"id": "st-other", "owner": other, "deleted_at": None},
                {"id": "st-picked-deleted", "owner": picked, "deleted_at": "2026-07-29"},
            ],
        )
        connection.execute(
            text("insert into buyer_party values (:id, :owner, null)"),
            [
                {"id": "bp-picked", "owner": picked},
                {"id": "bp-other", "owner": other},
            ],
        )
        connection.execute(
            text("insert into buyer_intent values (:id, :party, :owner, null)"),
            [
                {"id": "bi-picked", "party": "bp-other", "owner": picked},
                {"id": "bi-other", "party": "bp-other", "owner": other},
                {"id": "bi-party-picked", "party": "bp-picked", "owner": other},
            ],
        )
        connection.execute(
            text("insert into buyer_seller_relation values (:id, :target, :intent, :party)"),
            [
                {"id": "target-side", "target": "st-picked", "intent": "bi-other", "party": None},
                {"id": "intent-side", "target": "st-other", "intent": "bi-picked", "party": None},
                {"id": "party-side", "target": "st-other", "intent": "bi-party-picked", "party": None},
                {"id": "none-side", "target": "st-other", "intent": "bi-other", "party": None},
                # 软删的标的不能把关系带进来——否则被删对象会从筛选器漏出。
                {"id": "deleted-target", "target": "st-picked-deleted", "intent": "bi-other", "party": None},
            ],
        )
        rows = connection.execute(
            text(
                f"select r.id from buyer_seller_relation r where {relation_owner_sql('r')}"
            ),
            {"owner_user_id": picked},
        )
        matched = set(rows.scalars())

    assert matched == {"target-side", "intent-side", "party-side"}


def test_owner_filter_is_an_intersection_and_cannot_bypass_scope() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    schema = (
        "create table seller_target (id text primary key, owner_user_id text, deleted_at text)",
        "create table buyer_party (id text primary key, owner_user_id text, deleted_at text)",
        "create table buyer_intent ("
        "id text primary key, buyer_party_id text, owner_user_id text, deleted_at text)",
        "create table buyer_seller_relation ("
        "id text primary key, seller_target_id text, buyer_intent_id text, buyer_party_id text)",
    )
    current = "11111111-1111-1111-1111-111111111111"
    picked = "22222222-2222-2222-2222-222222222222"

    with engine.begin() as connection:
        for statement in schema:
            connection.execute(text(statement))
        connection.execute(
            text("insert into seller_target values (:id, :owner, null)"),
            [
                {"id": "st-current", "owner": current},
                {"id": "st-picked", "owner": picked},
            ],
        )
        connection.execute(
            text("insert into buyer_party values (:id, :owner, null)"),
            [
                {"id": "bp-current", "owner": current},
                {"id": "bp-picked", "owner": picked},
            ],
        )
        connection.execute(
            text("insert into buyer_intent values (:id, :party, :owner, null)"),
            [
                {"id": "bi-current", "party": "bp-current", "owner": current},
                {"id": "bi-picked", "party": "bp-picked", "owner": picked},
            ],
        )
        connection.execute(
            text("insert into buyer_seller_relation values (:id, :target, :intent, null)"),
            [
                # 同时命中权限地板和指定负责人，允许返回。
                {"id": "intersection", "target": "st-current", "intent": "bi-picked"},
                # 只命中 owner，不能绕过当前顾问的权限地板。
                {"id": "picked-only", "target": "st-picked", "intent": "bi-picked"},
                # 只命中 scope，也不符合指定负责人筛选。
                {"id": "current-only", "target": "st-current", "intent": "bi-current"},
            ],
        )
        rows = connection.execute(
            text(
                f"select r.id from buyer_seller_relation r "
                f"where {relation_visible_sql('r')} and {relation_owner_sql('r')}"
            ),
            {"scope_user_id": current, "owner_user_id": picked},
        )
        matched = set(rows.scalars())

    assert matched == {"intersection"}


def test_sole_is_a_data_level_subset_of_involved() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    schema = (
        "create table seller_target (id text primary key, owner_user_id text, deleted_at text)",
        "create table buyer_party (id text primary key, owner_user_id text, deleted_at text)",
        "create table buyer_intent ("
        "id text primary key, buyer_party_id text, owner_user_id text, deleted_at text)",
        "create table buyer_seller_relation ("
        "id text primary key, seller_target_id text, buyer_intent_id text, buyer_party_id text)",
    )
    me = str(_USER.user_id)
    other = "22222222-2222-2222-2222-222222222222"

    with engine.begin() as connection:
        for statement in schema:
            connection.execute(text(statement))
        connection.execute(
            text("insert into seller_target values (:id, :owner, null)"),
            [
                {"id": "st-mine", "owner": me},
                {"id": "st-other", "owner": other},
            ],
        )
        connection.execute(
            text("insert into buyer_party values (:id, :owner, null)"),
            [
                {"id": "bp-mine", "owner": me},
                {"id": "bp-other", "owner": other},
            ],
        )
        connection.execute(
            text("insert into buyer_intent values (:id, :party, :owner, null)"),
            [
                {"id": "bi-mine", "party": "bp-other", "owner": me},
                {"id": "bi-other", "party": "bp-other", "owner": other},
                {"id": "bi-party-mine", "party": "bp-mine", "owner": other},
            ],
        )
        connection.execute(
            text("insert into buyer_seller_relation values (:id, :target, :intent, :party)"),
            [
                {"id": "both-intent", "target": "st-mine", "intent": "bi-mine", "party": None},
                {"id": "target-only", "target": "st-mine", "intent": "bi-other", "party": None},
                {"id": "buyer-only", "target": "st-other", "intent": "bi-mine", "party": None},
                {"id": "both-party", "target": "st-mine", "intent": "bi-party-mine", "party": None},
                {"id": "neither", "target": "st-other", "intent": "bi-other", "party": None},
            ],
        )

        def ids_for(predicate: str) -> set[str]:
            rows = connection.execute(
                text(f"select r.id from buyer_seller_relation r where {predicate}"),
                {"scope_user_id": me},
            )
            return set(rows.scalars())

        involved = ids_for(relation_visible_sql("r"))
        sole = ids_for(relation_sole_owner_sql("r"))

    assert involved == {"both-intent", "target-only", "buyer-only", "both-party"}
    assert sole == {"both-intent", "both-party"}
    assert sole < involved


def test_both_routes_call_the_shared_base_where(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    original = relations._relation_base_where

    def spy(params: dict[str, Any], **kwargs: Any) -> list[str]:
        calls.append(dict(kwargs))
        return original(params, **kwargs)

    monkeypatch.setattr(relations, "_relation_base_where", spy)
    monkeypatch.setattr(relations, "owner_scope_required", lambda _user: False)
    db = _FakeSession()
    target_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    intent_id = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    party_id = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")

    relations.list_relations(
        current_user=_USER,
        db=db,
        seller_target_id=target_id,
        buyer_intent_id=intent_id,
        buyer_party_id=party_id,
        status_filter="due_diligence",
        q="红禾",
        limit=50,
        offset=0,
    )
    relations.list_relations_board(
        current_user=_USER,
        db=db,
        ownership="all",
        q="红禾",
        limit=2000,
        offset=0,
    )

    assert calls == [
        {
            "seller_target_id": target_id,
            "buyer_intent_id": intent_id,
            "buyer_party_id": party_id,
            "status_filter": "due_diligence",
            "q": "红禾",
        },
        {"q": "红禾"},
    ]


def test_base_where_builds_active_entity_guards_and_all_filter_combinations() -> None:
    values = {
        "seller_target_id": UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        "buyer_intent_id": UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        "buyer_party_id": UUID("dddddddd-dddd-dddd-dddd-dddddddddddd"),
        "status_filter": "due_diligence",
        "q": "红禾",
    }

    def expected(params: dict[str, Any], enabled: dict[str, Any]) -> list[str]:
        where = [
            "r.team_id = :team_id",
            "r.workspace_id = :workspace_id",
            "r.deleted_at is null",
            "st.deleted_at is null",
            "bi.deleted_at is null",
            "(r.buyer_party_id is null or bp.deleted_at is null)",
        ]
        params.update({"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID})
        for key in ("seller_target_id", "buyer_intent_id", "buyer_party_id"):
            if enabled[key]:
                where.append(f"r.{key} = :{key}")
                params[key] = enabled[key]
        if enabled["status_filter"]:
            where.append("r.status = :status")
            params["status"] = enabled["status_filter"]
        if enabled["q"]:
            where.append(
                """
                (
                  st.target_name ilike :q or bi.intent_name ilike :q or bp.buyer_name ilike :q
                  or r.last_event_summary ilike :q or r.status_reason ilike :q
                )
                """
            )
            params["q"] = f"%{enabled['q']}%"
        return where

    keys = tuple(values)
    for switches in product((False, True), repeat=len(keys)):
        enabled = {key: values[key] if switch else None for key, switch in zip(keys, switches)}
        expected_params: dict[str, Any] = {"limit": 50, "offset": 0}
        new_params: dict[str, Any] = {"limit": 50, "offset": 0}

        expected_where = expected(expected_params, enabled)
        new_where = _relation_base_where(new_params, **enabled)

        assert [" ".join(clause.split()) for clause in new_where] == [
            " ".join(clause.split()) for clause in expected_where
        ]
        assert new_params == expected_params


def test_base_where_excludes_relations_with_soft_deleted_entities() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    schema = (
        "create table seller_target (id text primary key, deleted_at text)",
        "create table buyer_intent (id text primary key, deleted_at text)",
        "create table buyer_party (id text primary key, deleted_at text)",
        "create table buyer_seller_relation ("
        "id text primary key, team_id text, workspace_id text, deleted_at text, "
        "seller_target_id text, buyer_intent_id text, buyer_party_id text)",
    )

    with engine.begin() as connection:
        for statement in schema:
            connection.execute(text(statement))
        connection.execute(
            text("insert into seller_target values (:id, :deleted_at)"),
            [
                {"id": "st-live", "deleted_at": None},
                {"id": "st-deleted", "deleted_at": "2026-07-27"},
            ],
        )
        connection.execute(
            text("insert into buyer_intent values (:id, :deleted_at)"),
            [
                {"id": "bi-live", "deleted_at": None},
                {"id": "bi-deleted", "deleted_at": "2026-07-27"},
            ],
        )
        connection.execute(
            text("insert into buyer_party values (:id, :deleted_at)"),
            [
                {"id": "bp-live", "deleted_at": None},
                {"id": "bp-deleted", "deleted_at": "2026-07-27"},
            ],
        )
        relation_rows = [
            {"id": "live", "deleted_at": None, "target": "st-live", "intent": "bi-live", "party": "bp-live"},
            {"id": "live-no-party", "deleted_at": None, "target": "st-live", "intent": "bi-live", "party": None},
            {"id": "relation-deleted", "deleted_at": "2026-07-27", "target": "st-live", "intent": "bi-live", "party": "bp-live"},
            {"id": "target-deleted", "deleted_at": None, "target": "st-deleted", "intent": "bi-live", "party": "bp-live"},
            {"id": "intent-deleted", "deleted_at": None, "target": "st-live", "intent": "bi-deleted", "party": "bp-live"},
            {"id": "party-deleted", "deleted_at": None, "target": "st-live", "intent": "bi-live", "party": "bp-deleted"},
        ]
        connection.execute(
            text(
                "insert into buyer_seller_relation values "
                "(:id, :team_id, :workspace_id, :deleted_at, :target, :intent, :party)"
            ),
            [
                {
                    **row,
                    "team_id": str(DEFAULT_TEAM_ID),
                    "workspace_id": str(DEFAULT_WORKSPACE_ID),
                }
                for row in relation_rows
            ],
        )

        params: dict[str, Any] = {}
        where = _relation_base_where(params)
        params["team_id"] = str(params["team_id"])
        params["workspace_id"] = str(params["workspace_id"])
        rows = connection.execute(
            text(
                f"""
                select r.id
                from buyer_seller_relation r
                join seller_target st on st.id = r.seller_target_id
                join buyer_intent bi on bi.id = r.buyer_intent_id
                left join buyer_party bp on bp.id = r.buyer_party_id
                where {' and '.join(where)}
                order by r.id
                """
            ),
            params,
        )

    assert set(rows.scalars()) == {"live", "live-no-party"}


def test_board_activity_alias_and_order_by_are_the_same_expression() -> None:
    db = _FakeSession()

    with patch.object(relations, "owner_scope_required", return_value=False):
        relations.list_relations_board(
            current_user=_USER,
            db=db,
            ownership="all",
            q=None,
            limit=2000,
            offset=0,
        )

    sql = " ".join(str(db.calls[0][0]).split())
    expression = "coalesce(r.last_event_at, r.updated_at, r.created_at)"
    assert f"{expression}::text as last_activity_at" in " ".join(_relation_board_columns().split())
    assert f"order by {expression} desc" in sql


def test_existing_relations_route_keeps_the_full_field_set() -> None:
    columns = _relation_select_columns()

    for column in _FAT_ONLY_COLUMNS:
        assert column in columns


def test_full_app_gzip_round_trips_json_pdf_and_chinese_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    with monkeypatch.context() as env:
        env.setenv("AUTH_ENABLED", "false")
        get_settings.cache_clear()
        app = create_app()

        @app.get("/__board_acceptance/json")
        def json_probe() -> dict[str, str]:
            return {"message": "中文撮合看板" * 100}

        @app.get("/__board_acceptance/pdf")
        def pdf_probe() -> Response:
            return Response(b"%PDF-1.4\n" + bytes(range(256)) * 8 + b"\n%%EOF", media_type="application/pdf")

        @app.get("/__board_acceptance/csv")
        def csv_probe() -> Response:
            payload = ("标的,买家,状态\r\n" + "华阳集团,测试买家,尽调\r\n" * 80).encode("utf-8-sig")
            return Response(payload, media_type="text/csv; charset=utf-8")

        middleware = [item.cls.__name__ for item in app.user_middleware]
        assert middleware == [
            "CORSMiddleware",
            "GZipMiddleware",
            "AdminAuthMiddleware",
            "Utf8JsonMiddleware",
        ]

        client = TestClient(app)
        expected = {
            "json": None,
            "pdf": b"%PDF-1.4\n" + bytes(range(256)) * 8 + b"\n%%EOF",
            "csv": ("标的,买家,状态\r\n" + "华阳集团,测试买家,尽调\r\n" * 80).encode("utf-8-sig"),
        }
        for kind, expected_bytes in expected.items():
            gzip_response = client.get(
                f"/__board_acceptance/{kind}",
                headers={"Accept-Encoding": "gzip"},
            )
            identity_response = client.get(
                f"/__board_acceptance/{kind}",
                headers={"Accept-Encoding": "identity"},
            )
            assert gzip_response.status_code == 200
            assert gzip_response.headers["content-encoding"] == "gzip"
            assert "Accept-Encoding" in gzip_response.headers["vary"]
            assert "content-encoding" not in identity_response.headers
            if kind == "json":
                assert gzip_response.json() == identity_response.json() == {"message": "中文撮合看板" * 100}
            else:
                assert gzip_response.content == identity_response.content == expected_bytes

    get_settings.cache_clear()
