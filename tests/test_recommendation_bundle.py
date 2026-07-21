from uuid import UUID

from backend.app.api.routes.recommendations import (
    _build_recommendation_rerank_status,
    _candidate_targets_for_intent,
    _enqueue_recommendation_rerank_job,
    _enrich_candidates_with_selection,
    _extract_recommendation_candidate_sets,
    _optional_uuid,
    _score_target_against_intent,
    _with_frontend_candidate_fields,
)


SELLER_TARGET_ID = "5e415f59-79ba-44b3-9d48-519092ffa07b"
BUYER_INTENT_ID = "8ff4bc53-047c-47be-b9b8-a3c465a519a1"


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


def test_deep_eval_job_uses_llm_queue_and_caps_candidates_at_twenty() -> None:
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
        candidates=[{"rank": index + 1} for index in range(25)],
    )

    assert str(job_id).endswith("0099")
    assert "'recommendation_deep_eval'" in db.statement
    assert "'llm'" in db.statement
    assert len(db.params["payload_json"]["candidates"]) == 20


def test_score_target_against_intent_uses_expanded_buyer_filters() -> None:
    score, evidence, gaps, meta = _score_target_against_intent(
        {
            "industry_l1": "医药与健康",
            "industry_primary": "医药健康",
            "headquarter_province": "浙江省",
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
            "industry_primary": "风电",
            "current_net_profit_yuan": 300_000_000,
        },
        {
            "industries_json": ["能源"],
            "excluded_industries_json": ["风电"],
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
            "headquarter_province": "江苏省",
            "headquarter_city": "苏州市",
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


def test_score_financial_or_semantics_softens_single_miss() -> None:
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

    # 营收达标、净利润未达标：记 gap 但不算冲突（买家常用或条件）
    assert "净利润低于买家门槛" in gaps
    assert meta["conflicts"] == []
    assert meta["state"] != "conflict"


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


def _pool_db(rows: list[dict]) -> object:
    class _Result:
        def mappings(self):
            return self

        def all(self):
            return rows

    class _Db:
        statement = ""

        def execute(self, statement, params):
            self.statement = str(statement)
            return _Result()

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
        "max_risk_level": 0,
    }
    row.update(overrides)
    return row


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


def test_candidate_pool_downweights_critical_risk_without_dropping_it() -> None:
    rows = [
        _target_row(seller_target_name="干净"),
        _target_row(seller_target_name="重大风险", max_risk_level=4),
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

    by_name = {candidate["seller_target_name"]: candidate for candidate in result["candidates"]}
    assert len(by_name) == 2
    assert by_name["重大风险"]["score"] < by_name["干净"]["score"]
    assert "存在重大风险记录（critical），需人工核对" in by_name["重大风险"]["evidence_json"]["gaps"]
