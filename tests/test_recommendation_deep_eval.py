import pytest

from backend.app.jobs.handlers import (
    _apply_deep_eval_results_to_candidates,
    _get_candidate_search_doc_text,
    _validate_deep_eval_results,
)


def test_validate_deep_eval_results_normalizes_and_filters_invalid_rows() -> None:
    results = _validate_deep_eval_results(
        {
            "results": [
                {"index": 1, "grade": "a", "reason": "契合", "risks": "", "info_gaps": None},
                {"index": 0, "grade": "S"},
                {"index": 9, "grade": "A"},
                {"index": 1, "grade": "B"},
                "not-a-dict",
            ]
        },
        candidate_count=2,
    )

    assert [item["index"] for item in results] == [1, 0]
    assert results[0]["grade"] == "A"
    assert results[0]["reason"] == "契合"
    assert results[0]["risks"] is None
    assert results[1]["grade"] == "C"


def test_validate_deep_eval_results_raises_on_empty() -> None:
    with pytest.raises(ValueError):
        _validate_deep_eval_results({"results": []}, candidate_count=2)
    with pytest.raises(ValueError):
        _validate_deep_eval_results(None, candidate_count=2)
    with pytest.raises(ValueError):
        _validate_deep_eval_results({"results": [{"index": 99, "grade": "A"}]}, candidate_count=2)
    with pytest.raises(ValueError, match="cover every candidate"):
        _validate_deep_eval_results({"results": [{"index": 0, "grade": "A"}]}, candidate_count=2)


def test_apply_deep_eval_results_orders_by_grade_then_result_order() -> None:
    candidates = [
        {"seller_target_name": "标的甲", "score": 90, "evidence_json": {"score": {"rule_score": 90}}},
        {"seller_target_name": "标的乙", "score": 70, "evidence_json": {}},
        {"seller_target_name": "标的丙", "score": 50, "evidence_json": {}},
    ]
    results = [
        {"index": 2, "grade": "A", "reason": "协同强", "risks": None, "info_gaps": None},
        {"index": 0, "grade": "B", "reason": "门槛达标", "risks": "估值偏高", "info_gaps": None},
        {"index": 1, "grade": "C", "reason": "行业不符", "risks": None, "info_gaps": "缺财务"},
    ]

    ordered = _apply_deep_eval_results_to_candidates(
        candidates=candidates, results=results, model_name="test-model"
    )

    assert [item["seller_target_name"] for item in ordered] == ["标的丙", "标的甲", "标的乙"]
    assert [item["rank"] for item in ordered] == [1, 2, 3]
    assert ordered[0]["deep_eval"]["grade"] == "A"
    assert ordered[0]["deep_eval"]["model"] == "test-model"
    assert ordered[1]["evidence_json"]["score"]["deep_eval_grade"] == "B"
    assert ordered[1]["evidence_json"]["score"]["rule_score"] == 90
    assert ordered[2]["deep_eval"]["info_gaps"] == "缺财务"


def test_apply_deep_eval_missing_result_falls_to_bottom() -> None:
    candidates = [
        {"seller_target_name": "标的甲", "score": 90, "evidence_json": {}},
        {"seller_target_name": "标的乙", "score": 70, "evidence_json": {}},
    ]
    results = [{"index": 1, "grade": "B", "reason": None, "risks": None, "info_gaps": None}]

    ordered = _apply_deep_eval_results_to_candidates(
        candidates=candidates, results=results, model_name="test-model"
    )

    assert [item["seller_target_name"] for item in ordered] == ["标的乙", "标的甲"]
    assert "deep_eval" not in ordered[1]


def test_deep_eval_reads_buyer_intent_fields_without_buyer_party_profile() -> None:
    class _Result:
        def mappings(self):
            return self

        def one_or_none(self):
            return {"intent_name": "医药并购需求", "industries_json": ["医药与健康"], "max_pe": 15}

    class _Db:
        statement = ""

        def execute(self, statement, params):
            self.statement = str(statement)
            assert params["buyer_intent_id"]
            return _Result()

    db = _Db()
    text_value = _get_candidate_search_doc_text(
        db,
        mode="target_to_buyer",
        candidate={"buyer_intent_id": "8ff4bc53-047c-47be-b9b8-a3c465a519a1"},
    )

    assert '"intent_name": "医药并购需求"' in text_value
    assert "from buyer_intent" in db.statement
    assert "buyer_party" not in db.statement
    assert "capital_strength" not in db.statement
