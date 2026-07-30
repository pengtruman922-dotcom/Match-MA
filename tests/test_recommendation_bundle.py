from uuid import UUID

from backend.app.api.routes.recommendations import (
    DEEP_EVAL_CANDIDATE_LIMIT,
    RecommendationCandidateOut,
    _build_recommendation_rerank_status,
    _candidate_targets_for_intent,
    _enqueue_recommendation_rerank_job,
    _enrich_candidates_with_selection,
    _extract_recommendation_candidate_sets,
    _optional_uuid,
    _score_target_against_intent,
    _with_frontend_candidate_fields,
)
from backend.app.services.recommendation_flow import (
    OTHER_BUYER_PROGRESS_STATUSES,
    _apply_semantic_keyword_match,
    _candidate_intents_for_target,
    _score_against_scenarios,
    _semantic_query_terms,
)


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


def test_semantic_keyword_recall_reads_business_supplement_text() -> None:
    """A niche business only in “其他” must enter keyword recommendation recall."""
    candidate = {
        "score": 70.0,
        "recommendation_level": "possible",
        "match_summary": "具备初步匹配基础",
        "evidence_json": {"score": {"rule_score": 70.0, "final_score": 70.0}},
    }

    _apply_semantic_keyword_match(
        candidate,
        terms=_semantic_query_terms(["殡葬墓地"]),
        searchable_text="其他：提供殡葬服务及墓园运营。",
    )

    assert "殡葬" in candidate["semantic_keyword_matches"]
    assert "关键词命中：殡葬" in candidate["match_summary"]
    assert candidate["score"] == 82.0
    assert candidate["evidence_json"]["score"]["semantic_keyword_boost"] == 12.0


def test_other_buyer_progress_prompt_covers_every_active_stage() -> None:
    assert set(OTHER_BUYER_PROGRESS_STATUSES) == {
        "recommended", "interested", "in_discussion", "due_diligence", "agreement",
    }


def test_candidate_pool_prioritizes_a_keyword_only_in_profile_supplement() -> None:
    funeral_id = "11111111-1111-1111-1111-111111111112"
    rows = [
        _target_row(seller_target_name="普通食品企业"),
        _target_row(
            seller_target_id=funeral_id,
            seller_target_name="福成五丰",
            profile_supplement_text="业务补充：同时经营殡葬服务及墓园运营。",
        ),
    ]

    result = _candidate_targets_for_intent(
        _pool_db(rows),
        {"id": BUYER_INTENT_ID, "intent_name": "关键词检索"},
        20,
        semantic_query_lines=["殡葬墓地"],
    )

    assert result["candidates"][0]["seller_target_id"] == funeral_id
    assert "关键词命中：殡葬" in result["candidates"][0]["match_summary"]


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


def test_deep_eval_job_uses_llm_queue_and_caps_candidates_at_the_budget() -> None:
    class _Result:
        def mappings(self):
            return self

        def one(self):
            return {"id": UUID("00000000-0000-0000-0000-000000000099")}

    class _Db:
        statement = ""
        params = {}

        def execute(self, statement, params):
            self.statement = str(statement)
            self.params = params
            return _Result()

    db = _Db()
    job_id = _enqueue_recommendation_rerank_job(
        db,
        session_id=UUID("00000000-0000-0000-0000-000000000098"),
        mode="buyer_to_target",
        anchor={"id": BUYER_INTENT_ID, "intent_name": "测试需求"},
        candidates=[{"rank": index + 1} for index in range(80)],
    )

    assert str(job_id).endswith("0099")
    assert "'recommendation_deep_eval'" in db.statement
    assert "'llm'" in db.statement
    assert len(db.params["payload_json"]["candidates"]) == DEEP_EVAL_CANDIDATE_LIMIT


def test_score_target_against_intent_uses_expanded_buyer_filters() -> None:
    score, evidence, gaps, meta = _score_target_against_intent(
        {
            "industry_l1": "医药与健康",
            "industry_l2": "医药健康",
            "location_province": "浙江省",
            "current_net_profit_yuan": 30_000_000,
            "pe_ratio": 12,
            "valuation_yuan": 800_000_000,
            "market_cap_yuan": 1_200_000_000,
            "current_debt_ratio": 55,
            "can_consolidate": "yes",
            "listed_status": "pre_ipo",
        },
        {
            "industries_json": ["医药与健康"],
            "industry_primary": "医药健康",
            "region_scope_summary": "浙江省优先",
            "min_net_profit_yuan": 20_000_000,
            "max_pe": 13,
            "max_valuation_yuan": 1_000_000_000,
            "min_market_cap_yuan": 500_000_000,
            "max_market_cap_yuan": 3_000_000_000,
            "max_debt_ratio": 65,
            "requires_consolidation": "yes",
            "preferred_listed_status": "preparing_listing",
        },
    )

    assert score > 90
    assert "行业命中：医药与健康（主赛道）" in evidence
    assert "市值处于买家要求范围" in evidence
    assert "负债率未超过买家上限" in evidence
    assert "上市状态符合偏好" in evidence
    assert gaps == []
    assert meta["conflicts"] == []
    assert meta["excluded_hit"] is None
    assert meta["state"] == "compatible"
    assert meta["unknown_dimensions"] == []


def test_score_gate_mismatch_becomes_conflict() -> None:
    score, evidence, gaps, meta = _score_target_against_intent(
        {
            "industry_l1": "能源",
            "current_net_profit_yuan": 5_000_000,
        },
        {
            "industries_json": ["能源"],
            "min_net_profit_yuan": 100_000_000,
        },
    )

    assert "净利润低于买家门槛" in meta["conflicts"]
    assert meta["state"] == "conflict"


def test_asking_price_never_gates_the_enterprise_value_axis() -> None:
    """Regression: a 10亿 budget for 25% of a 40亿 target is not a conflict.

    报价（交易对价）与买家的估值区间（整体价值）口径不同，混用会把
    "大标的 + 小比例" 这类国资买家最典型的诉求整片判成硬冲突。
    """
    _, _, _, meta = _score_target_against_intent(
        {
            "industry_l1": "能源",
            "listed_status": "unlisted",
            "asking_price_yuan": 2_000_000_000,
        },
        {
            "industries_json": ["能源"],
            "max_valuation_yuan": 1_500_000_000,
        },
    )

    assert meta["state"] != "conflict"
    assert meta["conflicts"] == []
    assert "整体估值" in meta["unknown_dimensions"]


def test_enterprise_value_axis_uses_market_cap_for_listed_targets() -> None:
    _, _, _, meta = _score_target_against_intent(
        {
            "industry_l1": "能源",
            "listed_status": "listed",
            "market_cap_yuan": 9_000_000_000,
            "asking_price_yuan": 500_000_000,
        },
        {
            "industries_json": ["能源"],
            "max_valuation_yuan": 5_000_000_000,
        },
    )

    assert "整体估值超出买家上限" in meta["conflicts"]
    assert meta["state"] == "conflict"


def test_score_excluded_industry_is_a_conflict() -> None:
    _, _, gaps, meta = _score_target_against_intent(
        {
            "industry_l1": "能源",
            "industry_l2": "风电",
            "current_net_profit_yuan": 300_000_000,
        },
        {
            "industries_json": ["能源"],
            "excluded_industries_json": ["风电"],
            "excluded_terms_resolved": {"l1": [], "l2": ["风电"], "unresolved": []},
            "min_net_profit_yuan": 100_000_000,
        },
    )

    assert meta["excluded_hit"] == "风电"
    assert meta["state"] == "conflict"
    assert gaps[0] == "命中排除项：风电"


def test_unknown_dimensions_score_optimistically_but_are_tracked() -> None:
    """信息缺失不再打折沉底：乐观分给满分，缺口只记录，用于二级排序与调研。"""
    known_score, _, _, known_meta = _score_target_against_intent(
        {
            "industry_l1": "制造与工业",
            "current_net_profit_yuan": 300_000_000,
            "current_debt_ratio": 40,
        },
        {
            "industries_json": ["制造与工业"],
            "min_net_profit_yuan": 100_000_000,
            "max_debt_ratio": 60,
        },
    )
    blank_score, _, _, blank_meta = _score_target_against_intent(
        {"industry_l1": "制造与工业"},
        {
            "industries_json": ["制造与工业"],
            "min_net_profit_yuan": 100_000_000,
            "max_debt_ratio": 60,
        },
    )

    # 缺数据的标的不出局、不掉分，只是"已知条件数"更少，同分时排在后面。
    assert blank_meta["state"] == "possible"
    assert blank_score == known_score
    assert blank_meta["known_count"] < known_meta["known_count"]
    assert set(blank_meta["unknown_dimensions"]) == {"净利润", "负债率"}


def test_score_multi_industry_secondary_track_and_region_group() -> None:
    score, evidence, gaps, meta = _score_target_against_intent(
        {
            "industry_l1": "信息技术与通信",
            "location_province": "江苏省",
            "location_city": "苏州市",
        },
        {
            "industries_json": ["制造与工业", "信息技术与通信"],
            "region_scope_summary": "长三角优先",
        },
    )

    assert "行业命中：信息技术与通信" in evidence
    assert "区域匹配：江苏省苏州市" in evidence
    assert meta["conflicts"] == []
    # 次赛道命中 25.5/30 + 区域 12/12 => (25.5+12)/42
    assert 85 <= score <= 95


def test_financial_thresholds_are_and_without_explicit_scenarios() -> None:
    score, evidence, gaps, meta = _score_target_against_intent(
        {
            "industry_l1": "制造与工业",
            "current_revenue_yuan": 30_000_000_000,
            "current_net_profit_yuan": 150_000_000,
        },
        {
            "industries_json": ["制造与工业"],
            "min_revenue_yuan": 1_000_000_000,
            "min_net_profit_yuan": 300_000_000,
        },
    )

    # 规则层不得自行推断 OR；真正的 OR 由两条显式方案表达。
    assert "净利润低于买家门槛" in gaps
    assert meta["conflicts"] == ["净利润低于买家门槛"]
    assert meta["state"] == "conflict"


def test_pending_confirmation_fields_do_not_screen_or_rank() -> None:
    score, evidence, gaps, meta = _score_against_scenarios(
        {
            "industry_l1": "医药与健康",
            "current_revenue_yuan": 8_000_000,
            "can_control": "yes",
        },
        {
            "industries_json": ["医药与健康"],
            "min_revenue_yuan": 10_000_000,
            "requires_control": "yes",
            "needs_confirmation_json": [
                {"field": "min_revenue_yuan", "reason": "单位待确认"}
            ],
        },
        [{"id": None, "label": None, "fields": {}, "needs_confirmation": []}],
    )

    assert meta["state"] == "compatible"
    assert "营收低于买家门槛" not in gaps
    assert "营收达到门槛" not in evidence
    assert "满足控股要求" in evidence
    assert score == 100


def test_rerank_status_without_job_is_not_requested() -> None:
    status = _build_recommendation_rerank_status(
        rerank_job=None,
        reranked_candidates=[],
        candidate_sets={},
    )

    assert status["requested"] is False
    assert status["status"] == "not_requested"
    assert status["job_id"] is None


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
            if "status in (__[POSTCOMPILE_deep_statuses])" in statement:
                # 别的买家正对 busy_target 尽调；深度查询不得受 intent_ids 限制。
                return _Rel([{"buyer_intent_id": other_intent, "seller_target_id": busy_target}])
            # 精确关系查询只能返回当前候选意向的 relation。
            return _Rel([{"id": relation_id, "buyer_intent_id": intent, "seller_target_id": paired_target, "status": "interested"}])

    db = _Db()
    annotated = _annotate_candidate_relations(db, result, mode="buyer_to_target")
    by_target = {c["seller_target_id"]: c for c in annotated["candidates"]}

    # 精确查询和深度推进查询的语义分离：后者只按标的筛，不得按候选意向筛。
    assert len(db.statements) == 2
    assert "buyer_intent_id in (__[POSTCOMPILE_intent_ids])" in db.statements[0]
    assert "seller_target_id in (__[POSTCOMPILE_target_ids])" in db.statements[0]
    assert "buyer_intent_id in (__[POSTCOMPILE_intent_ids])" not in db.statements[1]
    assert "seller_target_id in (__[POSTCOMPILE_target_ids])" in db.statements[1]

    assert by_target[paired_target]["relation_status"] == "interested"
    assert by_target[paired_target]["relation_id"] == relation_id
    assert by_target[paired_target]["deep_progress_elsewhere"] is False
    # busy_target 没和本意向建关系，但别人在尽调 → 标注、不给关系状态
    assert by_target[busy_target]["relation_status"] is None
    assert by_target[busy_target]["deep_progress_elsewhere"] is True


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


def test_reverse_recommendation_uses_inverse_thresholds_and_ignores_pending_fields() -> None:
    db = _reverse_pool_db(
        [
            _intent_row("00000000-0000-0000-0000-000000000501", "营收500万", 5_000_000),
            _intent_row("00000000-0000-0000-0000-000000000502", "营收1000万", 10_000_000),
            _intent_row(
                "00000000-0000-0000-0000-000000000503",
                "营收待确认",
                10_000_000,
                pending=True,
            ),
        ]
    )

    result = _candidate_intents_for_target(
        db,
        {
            "id": SELLER_TARGET_ID,
            "target_name": "医药标的",
            "industry_l1": "医药与健康",
            "current_revenue_yuan": 8_000_000,
            "can_control": "yes",
        },
        20,
    )

    names = {candidate["buyer_intent_name"] for candidate in result["candidates"]}
    assert names == {"营收500万", "营收待确认"}
    candidate_sql = next(sql for sql in db.statements if "from buyer_intent bi" in sql)
    assert "bi.min_revenue_yuan <= :target_revenue_yuan" in candidate_sql
    assert db.candidate_params["target_revenue_yuan"] == 8_000_000


def test_candidate_pool_scans_everything_and_reports_the_funnel() -> None:
    rows = [
        _target_row(seller_target_name="达标", current_net_profit_yuan=300_000_000),
        _target_row(seller_target_name="利润不足", current_net_profit_yuan=1_000_000),
        _target_row(seller_target_name="利润未知", current_net_profit_yuan=None),
        _target_row(seller_target_name="手工排除", is_excluded=True),
    ]
    result = _candidate_targets_for_intent(
        _pool_db(rows),
        {
            "id": BUYER_INTENT_ID,
            "intent_name": "测试需求",
            "industries_json": ["制造与工业"],
            "min_net_profit_yuan": 100_000_000,
        },
        20,
    )

    funnel = result["funnel"]
    assert funnel["scan_count"] == 4
    assert funnel["excluded_count"] == 1
    assert funnel["conflict_count"] == 1  # 利润不足 = 明确冲突，出局
    assert funnel["eligible_count"] == 2  # 达标 + 利润未知（缺失不出局）
    names = [candidate["seller_target_name"] for candidate in result["candidates"]]
    assert names == ["达标", "利润未知"]  # 同为满分，已知条件多的排前面
    assert result["candidates"][1]["match_state"] == "possible"
    assert result["candidates"][1]["missing_dimensions"] == ["净利润"]


def test_industry_l2_focus_narrows_score_without_dropping_the_candidate() -> None:
    """L2 是买家列的关注方向，通常不是穷举白名单，因此不沉底；硬规则走排除项。"""
    hit_score, _, _, hit_meta = _score_target_against_intent(
        {"industry_l1": "信息技术与通信", "industry_l2": "集成电路"},
        {"industries_json": ["信息技术与通信"], "industry_l2_json": ["集成电路", "北斗"]},
    )
    miss_score, _, _, miss_meta = _score_target_against_intent(
        {"industry_l1": "信息技术与通信", "industry_l2": "电商"},
        {"industries_json": ["信息技术与通信"], "industry_l2_json": ["集成电路", "北斗"]},
    )

    assert hit_meta["state"] == "compatible"
    assert miss_meta["state"] != "conflict"
    assert miss_score < hit_score


def test_exclusions_match_l2_exactly_instead_of_scanning_free_text() -> None:
    resolved = {"l1": [], "l2": ["风电"], "unresolved": []}
    excluded_target = {"industry_l1": "能源", "industry_l2": "风电"}
    kept_target = {"industry_l1": "能源", "industry_l2": "光伏"}
    intent = {
        "industries_json": ["能源"],
        "excluded_industries_json": ["风电"],
        "excluded_terms_resolved": resolved,
    }

    _, _, _, excluded_meta = _score_target_against_intent(excluded_target, intent)
    _, _, _, kept_meta = _score_target_against_intent(kept_target, intent)

    assert excluded_meta["excluded_hit"] == "风电"
    assert excluded_meta["state"] == "conflict"
    # 同属能源 L1 的其他赛道不受影响——排除风电不等于排除整个能源行业。
    assert kept_meta["excluded_hit"] is None
    assert kept_meta["state"] != "conflict"


def test_buyer_accepting_minority_softens_the_control_conflict() -> None:
    """先参股后控股是常见路径，买家自己接受少数股权时不该把标的沉底。"""
    target = {"industry_l1": "制造与工业", "can_control": "no"}
    strict = {"industries_json": ["制造与工业"], "requires_control": "yes"}
    flexible = {**strict, "accepts_minority_investment": "yes"}

    _, _, _, strict_meta = _score_target_against_intent(target, strict)
    _, _, _, flexible_meta = _score_target_against_intent(target, flexible)

    assert strict_meta["state"] == "conflict"
    assert flexible_meta["state"] != "conflict"


def test_equity_cap_conflicts_when_target_must_sell_more() -> None:
    _, _, _, meta = _score_target_against_intent(
        {"industry_l1": "医药与健康", "transfer_ratio_min": 51},
        {"industries_json": ["医药与健康"], "desired_equity_ratio_max": 29.9},
    )

    assert "标的最低转让股比高于买家股比上限" in meta["conflicts"]
    assert meta["state"] == "conflict"


def test_requirement_capability_matrix_drives_relocation_and_retention() -> None:
    intent = {
        "industries_json": ["制造与工业"],
        "requires_relocation": "required",
        "requires_team_retention": "preferred",
    }
    refuses = {
        "industry_l1": "制造与工业",
        "accepts_relocation": "no",
        "management_retention_possible": "no",
    }
    accepts = {
        "industry_l1": "制造与工业",
        "accepts_relocation": "yes",
        "management_retention_possible": "yes",
    }

    _, _, refuse_gaps, refuse_meta = _score_target_against_intent(refuses, intent)
    _, _, _, accept_meta = _score_target_against_intent(accepts, intent)

    # required × no => 冲突出局；preferred × no => 只扣分
    assert "标的明确不接受迁址" in refuse_meta["conflicts"]
    assert "标的不接受团队留任（买家为偏好项）" in refuse_gaps
    assert "标的不接受团队留任（买家为偏好项）" not in refuse_meta["conflicts"]
    assert accept_meta["state"] == "compatible"


def test_domestic_listing_requirement_excludes_overseas_targets() -> None:
    _, _, _, meta = _score_target_against_intent(
        {"industry_l1": "信息技术与通信", "listing_market_region": "overseas"},
        {"industries_json": ["信息技术与通信"], "listing_market_region": "domestic"},
    )

    assert "上市地不符合买家要求" in meta["conflicts"]


def test_net_margin_and_ps_are_derived_from_revenue_and_valuation() -> None:
    _, evidence, _, meta = _score_target_against_intent(
        {
            "industry_l1": "制造与工业",
            "current_revenue_yuan": 1_000_000_000,
            "current_net_profit_yuan": 150_000_000,
            "market_cap_yuan": 3_000_000_000,
        },
        {"industries_json": ["制造与工业"], "min_net_margin": 10, "max_ps": 5},
    )

    assert "净利率达到门槛" in evidence
    assert "PS 未超过上限" in evidence
    assert meta["state"] == "compatible"


def _scenario_row(scenario_id: str, label: str, **fields) -> dict:
    return {"id": scenario_id, "label": label, "sort_order": 0, "fields_json": fields}


SCENARIO_LISTED = "aaaaaaaa-0000-0000-0000-000000000001"
SCENARIO_UNLISTED = "aaaaaaaa-0000-0000-0000-000000000002"


def test_scenarios_are_or_ed_so_one_branch_is_enough() -> None:
    """荆州式或条件：低 PE 走一套，高 PE 但可控股走另一套，命中任一即可。"""
    rows = [
        _target_row(seller_target_name="低PE", pe_ratio=8),
        _target_row(seller_target_name="高PE但可控股", pe_ratio=25, can_control="yes"),
        _target_row(seller_target_name="两套都不满足", pe_ratio=50, can_control="yes"),
    ]
    scenarios = [
        _scenario_row(SCENARIO_LISTED, "低估值方案", max_pe=10),
        _scenario_row(SCENARIO_UNLISTED, "控股方案", max_pe=30, requires_control="yes"),
    ]

    result = _candidate_targets_for_intent(
        _pool_db(rows, scenarios),
        {"id": BUYER_INTENT_ID, "intent_name": "医药并购", "industries_json": ["制造与工业"]},
        20,
    )

    names = [candidate["seller_target_name"] for candidate in result["candidates"]]
    assert "低PE" in names
    assert "高PE但可控股" in names
    # PE 是 gate 维度，两套方案都明确不满足 => 出局
    assert "两套都不满足" not in names
    assert result["funnel"]["scenario_count"] == 2
    assert result["funnel"]["conflict_count"] == 1


def test_candidate_records_its_best_and_additional_scenarios() -> None:
    rows = [
        _target_row(
            seller_target_name="两套都满足",
            pe_ratio=8,
            can_control="yes",
            current_net_profit_yuan=50_000_000,
        )
    ]
    scenarios = [
        _scenario_row(SCENARIO_LISTED, "宽方案", max_pe=30),
        _scenario_row(SCENARIO_UNLISTED, "窄方案", max_pe=10, requires_control="yes"),
    ]

    result = _candidate_targets_for_intent(
        _pool_db(rows, scenarios),
        {"id": BUYER_INTENT_ID, "intent_name": "需求", "industries_json": ["制造与工业"]},
        20,
    )

    candidate = result["candidates"][0]
    assert sorted(candidate["matched_scenarios"]) == sorted([SCENARIO_LISTED, SCENARIO_UNLISTED])
    assert set(candidate["matched_scenario_labels"]) == {"宽方案", "窄方案"}
    assert candidate["best_scenario_label"] in {"宽方案", "窄方案"}


def test_intent_without_scenarios_keeps_the_single_pass_behaviour() -> None:
    """存量意向零方案行：与多方案上线前逐字节一致。"""
    rows = [_target_row(seller_target_name="达标")]

    result = _candidate_targets_for_intent(
        _pool_db(rows, scenarios=[]),
        {
            "id": BUYER_INTENT_ID,
            "intent_name": "需求",
            "industries_json": ["制造与工业"],
            "min_net_profit_yuan": 100_000_000,
        },
        20,
    )

    assert result["scenarios"] == []
    assert "scenario_count" not in result["funnel"]
    assert result["candidates"][0]["matched_scenarios"] == []


def test_disabled_scenario_is_skipped_for_this_session_only() -> None:
    rows = [_target_row(seller_target_name="仅命中控股方案", pe_ratio=25, can_control="yes")]
    scenarios = [
        _scenario_row(SCENARIO_LISTED, "低估值方案", max_pe=10),
        _scenario_row(SCENARIO_UNLISTED, "控股方案", max_pe=30, requires_control="yes"),
    ]
    intent = {"id": BUYER_INTENT_ID, "intent_name": "需求", "industries_json": ["制造与工业"]}

    kept = _candidate_targets_for_intent(_pool_db(rows, scenarios), intent, 20)
    dropped = _candidate_targets_for_intent(
        _pool_db(rows, scenarios), intent, 20, {SCENARIO_UNLISTED}
    )

    assert [c["seller_target_name"] for c in kept["candidates"]] == ["仅命中控股方案"]
    # 停用控股方案后只剩低估值方案，该标的 PE 超限 => 本轮出局；买家需求本身不受影响
    assert dropped["candidates"] == []
    assert dropped["funnel"]["scenario_count"] == 1
