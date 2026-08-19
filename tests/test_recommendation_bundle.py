from uuid import UUID

from backend.app.api.authn import AuthContext
from backend.app.api.routes.recommendations import (
    RecommendationCandidateOut,
    _enrich_candidates_with_selection,
    _extract_recommendation_candidate_sets,
    _optional_uuid,
    _with_frontend_candidate_fields,
)
from backend.app.services.recommendation_flow import (
    _annotate_candidate_ownership,
)
from backend.app.services.relation_flow import DEEP_PROGRESS_STATUSES


SELLER_TARGET_ID = "5e415f59-79ba-44b3-9d48-519092ffa07b"
BUYER_INTENT_ID = "8ff4bc53-047c-47be-b9b8-a3c465a519a1"


def test_candidate_response_contract_keeps_scenario_matching_metadata() -> None:
    expected_fields = {
        "match_state",
        "known_count",
        "missing_dimensions",
        "best_scenario_id",
        "best_scenario_label",
        "matched_scenarios",
        "matched_scenario_labels",
    }

    assert expected_fields <= set(RecommendationCandidateOut.model_fields)


def test_extract_candidate_sets_prefers_explicit_message_types() -> None:
    messages = [
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "content_type": "json",
            "content": (
                '{"message_type":"initial_candidates","candidates":'
                '[{"rank":1,"score":60,"seller_target_id":"%s","buyer_intent_id":"%s"}]}'
            )
            % (SELLER_TARGET_ID, BUYER_INTENT_ID),
            "metadata_json": {"message_type": "initial_candidates"},
            "created_at": "2026-06-02 10:00:00+00",
        },
        {
            "id": "00000000-0000-0000-0000-000000000002",
            "content_type": "json",
            "content": (
                '{"message_type":"reranked_candidates","candidates":'
                '[{"rank":1,"score":75,"seller_target_id":"%s","buyer_intent_id":"%s",'
                '"evidence_json":{"score":{"rerank_score":0.9}}}]}'
            )
            % (SELLER_TARGET_ID, BUYER_INTENT_ID),
            "metadata_json": {"message_type": "reranked_candidates"},
            "created_at": "2026-06-02 10:01:00+00",
        },
    ]

    candidate_sets = _extract_recommendation_candidate_sets(messages)

    assert candidate_sets["initial_candidates"][0]["score"] == 60
    assert candidate_sets["reranked_candidates"][0]["score"] == 75
    assert candidate_sets["reranked_message_id"] == "00000000-0000-0000-0000-000000000002"
    assert candidate_sets["reranked_at"] == "2026-06-02 10:01:00+00"


def test_extract_candidate_sets_infers_legacy_rerank_message() -> None:
    messages = [
        {
            "id": "00000000-0000-0000-0000-000000000003",
            "content_type": "json",
            "content": (
                '{"candidates":[{"rank":1,"score":75,"seller_target_id":"%s",'
                '"buyer_intent_id":"%s","evidence_json":{"score":{"rerank_score":0.9}}}]}'
            )
            % (SELLER_TARGET_ID, BUYER_INTENT_ID),
            "metadata_json": {},
            "created_at": "2026-06-02 10:01:00+00",
        },
    ]

    candidate_sets = _extract_recommendation_candidate_sets(messages)

    assert candidate_sets["initial_candidates"] == []
    assert candidate_sets["reranked_candidates"][0]["score"] == 75


def test_enrich_candidates_with_active_selection() -> None:
    candidates = [
        {
            "mode": "buyer_to_target",
            "seller_target_id": SELLER_TARGET_ID,
            "seller_target_name": "浙江医疗器械标的",
            "buyer_intent_id": BUYER_INTENT_ID,
            "buyer_intent_name": "医药健康并表需求",
            "buyer_name": None,
            "score": 75,
            "recommendation_level": "recommended",
            "evidence_json": {"score": {"final_score": 75}},
        }
    ]
    selected_items = [
        {
            "id": UUID("00000000-0000-0000-0000-000000000004"),
            "seller_target_id": UUID(SELLER_TARGET_ID),
            "buyer_intent_id": UUID(BUYER_INTENT_ID),
            "selected_at": "2026-06-02 10:02:00+00",
            "canceled_at": None,
        }
    ]

    enriched = _enrich_candidates_with_selection(candidates, selected_items)

    assert enriched[0]["selected"] is True
    assert enriched[0]["selected_item_id"] == UUID("00000000-0000-0000-0000-000000000004")
    assert enriched[0]["selected_at"] == "2026-06-02 10:02:00+00"
    assert enriched[0]["display_title"] == "浙江医疗器械标的"
    assert enriched[0]["card_json"]["action_label"] == "add_target_to_recommendation"


def test_deep_progress_prompt_only_covers_active_deep_stages() -> None:
    assert set(DEEP_PROGRESS_STATUSES) == {"due_diligence", "agreement"}


def test_frontend_candidate_fields_include_rule_and_deep_eval_breakdown() -> None:
    candidate = _with_frontend_candidate_fields(
        {
            "mode": "buyer_to_target",
            "seller_target_id": SELLER_TARGET_ID,
            "seller_target_name": "浙江医疗器械标的",
            "buyer_intent_id": BUYER_INTENT_ID,
            "buyer_intent_name": "医药健康并表需求",
            "score": 90,
            "recommendation_level": "strong",
            "selected": False,
            "evidence_json": {
                "score": {
                    "rule_score": 80,
                    "rerank_score": 0.9,
                    "final_score": 90,
                }
            },
        }
    )

    assert candidate["primary_entity_type"] == "seller_target"
    assert candidate["display_title"] == "浙江医疗器械标的"
    assert candidate["display_subtitle"] == "医药健康并表需求"
    assert candidate["score_breakdown"]["rule_score"] == 80
    assert "embedding" not in candidate["display_badges"]
    assert "reranked" in candidate["display_badges"]


def test_optional_uuid_accepts_uuid_and_string() -> None:
    value = UUID(SELLER_TARGET_ID)

    assert _optional_uuid(value) == value
    assert _optional_uuid(SELLER_TARGET_ID) == value
    assert _optional_uuid("not-a-uuid") is None


def test_annotate_marks_existing_relation_and_deep_progress_elsewhere() -> None:
    from backend.app.services.recommendation_flow import _annotate_candidate_relations

    intent = BUYER_INTENT_ID
    paired_target = "11111111-1111-1111-1111-111111111111"
    busy_target = "22222222-2222-2222-2222-222222222222"
    other_intent = "33333333-3333-3333-3333-333333333333"
    relation_id = "44444444-4444-4444-4444-444444444444"
    other_target = "55555555-5555-5555-5555-555555555555"

    result = {
        "candidates": [
            {"buyer_intent_id": intent, "seller_target_id": paired_target},
            {"buyer_intent_id": intent, "seller_target_id": busy_target},
        ]
    }

    class _Rel:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    class _Db:
        statements: list[str] = []

        def execute(self, *args, **kwargs):
            statement = str(args[0])
            self.statements.append(statement)
            if "status in (__[POSTCOMPILE_deep_statuses])" in statement and "seller_target_id in" in statement:
                # 别的买家正对 busy_target 尽调；深度查询不得受 intent_ids 限制。
                return _Rel([{"buyer_intent_id": other_intent, "seller_target_id": busy_target}])
            if "status in (__[POSTCOMPILE_deep_statuses])" in statement and "buyer_intent_id in" in statement:
                # 当前买家需求同时与候选集之外的另一个标的深入推进。
                return _Rel([{"buyer_intent_id": intent, "seller_target_id": other_target}])
            # 精确关系查询只能返回当前候选意向的 relation。
            return _Rel([{"id": relation_id, "buyer_intent_id": intent, "seller_target_id": paired_target, "status": "interested"}])

    db = _Db()
    annotated = _annotate_candidate_relations(db, result, mode="buyer_to_target")
    by_target = {c["seller_target_id"]: c for c in annotated["candidates"]}

    # 精确查询和深度推进查询的语义分离：后者只按标的筛，不得按候选意向筛。
    assert len(db.statements) == 3
    assert "buyer_intent_id in (__[POSTCOMPILE_intent_ids])" in db.statements[0]
    assert "seller_target_id in (__[POSTCOMPILE_target_ids])" in db.statements[0]
    assert "buyer_intent_id in (__[POSTCOMPILE_intent_ids])" not in db.statements[1]
    assert "seller_target_id in (__[POSTCOMPILE_target_ids])" in db.statements[1]
    assert "seller_target_id in (__[POSTCOMPILE_target_ids])" not in db.statements[2]
    assert "buyer_intent_id in (__[POSTCOMPILE_intent_ids])" in db.statements[2]

    assert by_target[paired_target]["relation_status"] == "interested"
    assert by_target[paired_target]["relation_id"] == relation_id
    assert by_target[paired_target]["deep_progress_elsewhere"] is False
    assert by_target[paired_target]["seller_target_has_other_deep_progress"] is False
    assert by_target[paired_target]["buyer_intent_has_other_deep_progress"] is True
    # busy_target 没和本意向建关系，但别人在尽调 → 标注、不给关系状态
    assert by_target[busy_target]["relation_status"] is None
    assert by_target[busy_target]["deep_progress_elsewhere"] is True
    assert by_target[busy_target]["seller_target_has_other_deep_progress"] is True
    assert by_target[busy_target]["buyer_intent_has_other_deep_progress"] is True

    reverse_result = {
        "candidates": [
            {"buyer_intent_id": intent, "seller_target_id": paired_target},
            {"buyer_intent_id": intent, "seller_target_id": busy_target},
        ]
    }
    reverse = _annotate_candidate_relations(_Db(), reverse_result, mode="target_to_buyer")
    reverse_by_target = {c["seller_target_id"]: c for c in reverse["candidates"]}
    assert reverse_by_target[paired_target]["deep_progress_elsewhere"] is True


def test_candidate_ownership_uses_primary_entity_and_current_user() -> None:
    current_user_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    other_user_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    class _Rows:
        def mappings(self):
            return self

        def all(self):
            return [{"entity_id": BUYER_INTENT_ID, "owner_user_id": other_user_id, "owner_name": "其他顾问"}]

    class _Db:
        statement = ""

        def execute(self, statement, _params):
            self.statement = str(statement)
            return _Rows()

    db = _Db()
    annotated = _annotate_candidate_ownership(
        db,
        {"candidates": [{"buyer_intent_id": BUYER_INTENT_ID, "buyer_party_id": "party-owner-must-not-win"}]},
        mode="target_to_buyer",
        current_user=AuthContext(user_id=current_user_id, role="consultant", name="当前顾问"),
    )["candidates"][0]

    assert "from buyer_intent entity" in db.statement
    assert annotated["buyer_intent_owner_user_id"] == other_user_id
    assert annotated["buyer_intent_owner_name"] == "其他顾问"
    assert annotated["buyer_intent_owned_by_current_user"] is False
    assert annotated["buyer_intent_operation_allowed"] is False

    admin_result = _annotate_candidate_ownership(
        _Db(),
        {"candidates": [{"buyer_intent_id": BUYER_INTENT_ID}]},
        mode="target_to_buyer",
        current_user=AuthContext(user_id=current_user_id, role="admin", name="管理员"),
    )["candidates"][0]
    assert admin_result["buyer_intent_operation_allowed"] is True
    assert admin_result["buyer_intent_owned_by_current_user"] is False


def _pool_db(rows: list[dict], scenarios: list[dict] | None = None) -> object:
    """Stub that answers by query shape: candidate pool vs scenario lookup."""

    class _Result:
        def __init__(self, payload):
            self._payload = payload

        def mappings(self):
            return self

        def all(self):
            return self._payload

    class _Db:
        statement = ""

        def execute(self, statement, params=None):
            self.statement = str(statement)
            if "buyer_intent_scenario" in self.statement:
                return _Result(scenarios or [])
            if "industry_taxonomy" in self.statement:
                return _Result([])
            if "buyer_seller_relation" in self.statement:
                # 无既有关系：候选全部是新候选（关系接线在别处测）
                return _Result([])
            return _Result(rows)

    return _Db()


def _target_row(**overrides) -> dict:
    row = {
        "seller_target_id": SELLER_TARGET_ID,
        "seller_target_name": "标的",
        "industry_l1": "制造与工业",
        "listed_status": "unlisted",
        "current_net_profit_yuan": 300_000_000,
        "risk_summary": None,
        "gap_summary": None,
        "is_excluded": False,
    }
    row.update(overrides)
    return row


def _reverse_pool_db(rows: list[dict], scenarios: list[dict] | None = None) -> object:
    class _Result:
        def __init__(self, payload):
            self._payload = payload

        def mappings(self):
            return self

        def all(self):
            return self._payload

    class _Db:
        statements: list[str]
        candidate_params: dict

        def __init__(self):
            self.statements = []
            self.candidate_params = {}

        def execute(self, statement, params=None):
            sql = str(statement)
            self.statements.append(sql)
            if "from buyer_intent_scenario" in sql and "bis_prefilter" not in sql:
                return _Result(scenarios or [])
            if "industry_taxonomy" in sql or "buyer_seller_relation" in sql:
                return _Result([])
            if "from buyer_intent bi" in sql:
                self.candidate_params = params or {}
            return _Result(rows)

    return _Db()


def _intent_row(intent_id: str, name: str, min_revenue: int | None, *, pending=False) -> dict:
    return {
        "buyer_intent_id": intent_id,
        "buyer_intent_name": name,
        "buyer_party_id": None,
        "buyer_name": name,
        "industries_json": ["医药与健康"],
        "industry_l2_json": [],
        "excluded_industries_json": [],
        "min_revenue_yuan": min_revenue,
        "requires_control": "yes",
        "accepts_minority_investment": "unknown",
        "needs_confirmation_json": (
            [{"field": "min_revenue_yuan", "reason": "单位待确认"}] if pending else []
        ),
        "is_excluded": False,
    }


def _scenario_row(scenario_id: str, label: str, **fields) -> dict:
    return {"id": scenario_id, "label": label, "sort_order": 0, "fields_json": fields}


SCENARIO_LISTED = "aaaaaaaa-0000-0000-0000-000000000001"
SCENARIO_UNLISTED = "aaaaaaaa-0000-0000-0000-000000000002"


