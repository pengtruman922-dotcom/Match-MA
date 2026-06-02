from uuid import UUID

from backend.app.api.routes.recommendations import (
    _build_recommendation_rerank_status,
    _enrich_candidates_with_selection,
    _extract_recommendation_candidate_sets,
    _optional_uuid,
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
            "seller_target_id": SELLER_TARGET_ID,
            "buyer_intent_id": BUYER_INTENT_ID,
            "score": 75,
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
