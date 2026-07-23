from backend.app.jobs.handlers import (
    _apply_deep_eval_results_to_candidates,
    _get_candidate_search_doc_text,
    _interleave_shards,
    _validate_deep_eval_results,
)


TARGET_A = "11111111-1111-1111-1111-111111111111"
TARGET_B = "22222222-2222-2222-2222-222222222222"
TARGET_C = "33333333-3333-3333-3333-333333333333"


def test_validate_keeps_only_ids_from_this_shard_exactly_once() -> None:
    results, problems = _validate_deep_eval_results(
        {
            "results": [
                {"candidate_id": TARGET_B, "grade": "a", "reason": "契合", "risks": "", "info_gaps": None},
                {"candidate_id": TARGET_A, "grade": "S"},
                {"candidate_id": "not-in-this-shard", "grade": "A"},
                {"candidate_id": TARGET_B, "grade": "B"},
                "not-a-dict",
            ]
        },
        {TARGET_A, TARGET_B},
    )

    assert [item["candidate_id"] for item in results] == [TARGET_B, TARGET_A]
    assert results[0]["grade"] == "A"
    assert results[0]["reason"] == "契合"
    assert results[0]["risks"] is None
    # 非法档位落到 C，但仍报告问题，供定向重试时反馈给模型
    assert results[1]["grade"] == "C"
    assert any("不属于本次候选集合" in problem for problem in problems)
    assert any("重复" in problem for problem in problems)
    assert any("grade 非法" in problem for problem in problems)


def test_validate_reports_missing_candidates_instead_of_raising() -> None:
    """缺结果不再整批失败——上层只对缺的候选定向重发。"""
    results, problems = _validate_deep_eval_results(
        {"results": [{"candidate_id": TARGET_A, "grade": "A"}]},
        {TARGET_A, TARGET_B},
    )

    assert [item["candidate_id"] for item in results] == [TARGET_A]
    assert any(TARGET_B in problem for problem in problems)


def test_validate_rejects_malformed_payloads() -> None:
    assert _validate_deep_eval_results(None, {TARGET_A}) == ([], ["输出不是 JSON 对象"])
    assert _validate_deep_eval_results({"results": []}, {TARGET_A}) == ([], ["输出缺少 results 数组"])


def test_validate_carries_matched_scenarios_through() -> None:
    results, _ = _validate_deep_eval_results(
        {"results": [{"candidate_id": TARGET_A, "grade": "A", "matched_scenarios": ["s-1", "s-2"]}]},
        {TARGET_A},
    )

    assert results[0]["matched_scenarios"] == ["s-1", "s-2"]


def test_interleave_shards_spreads_ranking_across_shards() -> None:
    """按名次轮转分片：片间若出现评级漂移，漂移方向与候选质量无关。"""
    items = list(range(7))

    shards = _interleave_shards(items, shard_size=3)

    assert shards == [[0, 3, 6], [1, 4], [2, 5]]
    assert sorted(value for shard in shards for value in shard) == items


def test_interleave_shards_keeps_small_batches_in_one_call() -> None:
    assert _interleave_shards([1, 2, 3], shard_size=15) == [[1, 2, 3]]
    assert _interleave_shards([], shard_size=15) == []


def test_apply_results_writes_back_by_entity_id_not_array_position() -> None:
    candidates = [
        {"seller_target_id": TARGET_A, "seller_target_name": "标的甲", "score": 90, "evidence_json": {"score": {"rule_score": 90}}},
        {"seller_target_id": TARGET_B, "seller_target_name": "标的乙", "score": 70, "evidence_json": {}},
        {"seller_target_id": TARGET_C, "seller_target_name": "标的丙", "score": 50, "evidence_json": {}},
    ]
    # 结果顺序与候选顺序完全不同——回写必须靠 ID，不能靠位置
    results = [
        {"candidate_id": TARGET_C, "grade": "A", "reason": "协同强", "risks": None, "info_gaps": None},
        {"candidate_id": TARGET_A, "grade": "B", "reason": "门槛达标", "risks": "估值偏高", "info_gaps": None},
        {"candidate_id": TARGET_B, "grade": "C", "reason": "行业不符", "risks": None, "info_gaps": "缺财务"},
    ]

    ordered = _apply_deep_eval_results_to_candidates(
        candidates=candidates, results=results, mode="buyer_to_target", model_name="test-model"
    )

    assert [item["seller_target_name"] for item in ordered] == ["标的丙", "标的甲", "标的乙"]
    assert [item["rank"] for item in ordered] == [1, 2, 3]
    assert ordered[0]["deep_eval"]["grade"] == "A"
    assert ordered[0]["deep_eval"]["model"] == "test-model"
    assert ordered[1]["evidence_json"]["score"]["deep_eval_grade"] == "B"
    assert ordered[1]["evidence_json"]["score"]["rule_score"] == 90
    assert ordered[2]["deep_eval"]["info_gaps"] == "缺财务"


def test_apply_results_uses_buyer_intent_id_in_the_reverse_direction() -> None:
    candidates = [
        {"buyer_intent_id": TARGET_A, "buyer_intent_name": "意向甲", "score": 60, "evidence_json": {}},
        {"buyer_intent_id": TARGET_B, "buyer_intent_name": "意向乙", "score": 80, "evidence_json": {}},
    ]
    results = [{"candidate_id": TARGET_A, "grade": "A", "reason": None, "risks": None, "info_gaps": None}]

    ordered = _apply_deep_eval_results_to_candidates(
        candidates=candidates, results=results, mode="target_to_buyer", model_name="test-model"
    )

    assert [item["buyer_intent_name"] for item in ordered] == ["意向甲", "意向乙"]
    assert "deep_eval" not in ordered[1]


def test_apply_results_leaves_uncovered_candidates_at_the_bottom() -> None:
    candidates = [
        {"seller_target_id": TARGET_A, "seller_target_name": "标的甲", "score": 90, "evidence_json": {}},
        {"seller_target_id": TARGET_B, "seller_target_name": "标的乙", "score": 70, "evidence_json": {}},
    ]
    results = [{"candidate_id": TARGET_B, "grade": "B", "reason": None, "risks": None, "info_gaps": None}]

    ordered = _apply_deep_eval_results_to_candidates(
        candidates=candidates, results=results, mode="buyer_to_target", model_name="test-model"
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


def test_legacy_index_only_output_still_maps_onto_candidate_ids() -> None:
    """生产提示词改用 candidate_id 之前，旧格式不能让整轮深评作废。"""
    results, problems = _validate_deep_eval_results(
        {"results": [{"index": 0, "grade": "A"}, {"index": 1, "grade": "B"}]},
        {TARGET_A, TARGET_B},
        index_fallback={0: TARGET_A, 1: TARGET_B},
    )

    assert [item["candidate_id"] for item in results] == [TARGET_A, TARGET_B]
    assert problems == []


def test_candidate_id_wins_over_index_when_both_are_present() -> None:
    results, _ = _validate_deep_eval_results(
        {"results": [{"candidate_id": TARGET_B, "index": 0, "grade": "A"}]},
        {TARGET_A, TARGET_B},
        index_fallback={0: TARGET_A, 1: TARGET_B},
    )

    assert results[0]["candidate_id"] == TARGET_B


def test_shard_retries_only_the_candidates_that_came_back_missing(monkeypatch) -> None:
    """定向重发：第一次漏掉的候选单独补，不整批重来。"""
    from backend.app.jobs.handlers import recommendation as module

    calls: list[list[str]] = []

    def fake_call(node_config, mode, anchor_context, items, *, correction_notes=None):
        sent = [item["candidate_id"] for item in items]
        calls.append(sent)
        if len(calls) == 1:
            # 首次只回了一个候选，另一个漏了
            return ([{"candidate_id": TARGET_A, "grade": "A"}], [f"缺少 candidate_id 的评估结果：{TARGET_B}"], 100)
        assert correction_notes, "重发必须把校验问题反馈给模型"
        return ([{"candidate_id": TARGET_B, "grade": "B"}], [], 40)

    monkeypatch.setattr(module, "_call_deep_eval", fake_call)

    outcome = module._run_single_deep_eval_shard(
        {"model_name": "test"},
        "buyer_to_target",
        "anchor",
        [{"candidate_id": TARGET_A, "index": 0}, {"candidate_id": TARGET_B, "index": 1}],
    )

    assert calls == [[TARGET_A, TARGET_B], [TARGET_B]]
    assert outcome["retried"] is True
    assert sorted(item["candidate_id"] for item in outcome["results"]) == sorted([TARGET_A, TARGET_B])
    assert outcome["total_tokens"] == 140
    assert outcome["grade_counts"] == {"A": 1, "B": 1}


def test_shard_does_not_retry_when_every_candidate_is_covered(monkeypatch) -> None:
    from backend.app.jobs.handlers import recommendation as module

    calls: list[list[str]] = []

    def fake_call(node_config, mode, anchor_context, items, *, correction_notes=None):
        calls.append([item["candidate_id"] for item in items])
        return ([{"candidate_id": item["candidate_id"], "grade": "B"} for item in items], [], 10)

    monkeypatch.setattr(module, "_call_deep_eval", fake_call)

    outcome = module._run_single_deep_eval_shard(
        {"model_name": "test"},
        "buyer_to_target",
        "anchor",
        [{"candidate_id": TARGET_A, "index": 0}],
    )

    assert len(calls) == 1
    assert outcome["retried"] is False


def test_candidate_profile_prefers_sections_over_the_search_doc() -> None:
    from backend.app.jobs.handlers.recommendation import _candidate_profile_fields

    sections = {
        "chain_position": {"section_code": "chain_position", "info_status": "filled", "content_text": "细分领域前三，链主地位"},
    }

    fields = _candidate_profile_fields(sections, "结构化摘要 / 财务 / 交易 / 风险……")

    assert fields["profile_source"] == "profile_sections"
    assert "链主地位" in fields["profile"]
    assert "结构化摘要" not in fields["profile"]
    assert "profile_missing_sections" not in fields


def test_candidate_profile_falls_back_to_the_search_doc_when_no_profile_exists() -> None:
    from backend.app.jobs.handlers.recommendation import _candidate_profile_fields

    fields = _candidate_profile_fields(None, "标的：某某\n行业大类：能源")

    assert fields["profile_source"] == "search_doc"
    assert "行业大类：能源" in fields["profile"]
    assert "profile_missing_sections" not in fields
