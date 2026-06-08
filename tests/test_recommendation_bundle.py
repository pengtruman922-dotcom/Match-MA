from uuid import UUID

from backend.app.api.routes.recommendations import (
    _build_recommendation_rerank_status,
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


def test_frontend_candidate_fields_include_score_breakdown() -> None:
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
                    "embedding_similarity": 0.8,
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
    assert "embedding" in candidate["display_badges"]
    assert "reranked" in candidate["display_badges"]


def test_score_target_against_intent_uses_expanded_buyer_filters() -> None:
    score, evidence, gaps = _score_target_against_intent(
        {
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

    assert score > 80
    assert "市值处于买家要求范围" in evidence
    assert "负债率未超过买家上限" in evidence
    assert "上市状态符合偏好" in evidence
    assert gaps == []


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
