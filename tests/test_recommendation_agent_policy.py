"""4B hard policy: condition groups, relaxation evidence and fair pooling."""

from __future__ import annotations

from backend.app.services.recommendation_agent_policy import (
    build_deep_eval_pool,
    compile_condition_groups,
    validate_search_call,
)


SNAPSHOT = {
    "condition_groups": [
        {
            "label": "上市制造",
            "conditions": {
                "min_revenue_yuan": 50_000_000,
                "min_net_profit_yuan": 10_000_000,
                "max_pe": 15,
                "acceptable_listed_status_json": ["listed"],
            },
            "strength": {
                "min_revenue_yuan": "required",
                "min_net_profit_yuan": "required",
                "max_pe": "preferred",
                "acceptable_listed_status_json": "required",
            },
        },
        {
            "label": "医疗",
            "conditions": {
                "min_revenue_yuan": 80_000_000,
                "min_market_cap_yuan": 100_000_000,
                "acceptable_listed_status_json": ["unlisted"],
            },
            "strength": {"min_market_cap_yuan": "required"},
        },
    ],
    "exclusions": {
        "industries": ["房地产与建筑"],
        "risk_flags": ["equity_frozen"],
    },
}


def _groups(snapshot=SNAPSHOT):
    return compile_condition_groups(snapshot)


def _real_call(
    *,
    call_index: int = 1,
    group_id: str = "group-1",
    eligible_count: int = 2,
    filters: dict | None = None,
) -> dict:
    return {
        "call_index": call_index,
        "valid": True,
        "group_id": group_id,
        "count_only": False,
        "eligible_count": eligible_count,
        "filters": filters
        or {
            "min_revenue_yuan": 50_000_000,
            "min_net_profit_yuan": 10_000_000,
            "max_pe": 15,
            "acceptable_listed_status_json": ["listed"],
            "unacceptable_risk_flags_json": ["equity_frozen"],
        },
    }


def _validate(conditions, *, prior=None, group_id="group-1", count_only=False, **kwargs):
    return validate_search_call(
        group_id,
        conditions,
        prior or [],
        groups=_groups(),
        count_only=count_only,
        **kwargs,
    )


def test_group_outside_field_and_cross_group_value_are_rejected() -> None:
    outside = _validate(
        {
            "min_revenue_yuan": 50_000_000,
            "min_net_profit_yuan": 10_000_000,
            "max_pe": 15,
            "acceptable_listed_status_json": ["listed"],
            # 第二组才有的字段，不许出现在第一组的调用里
            "min_market_cap_yuan": 100_000_000,
        }
    )
    cross_value = _validate(
        {
            # 第一组的字段，但取值是第二组的。必须挑一个**非数值**字段：
            # 数值字段的取值差异会先被「放宽方向」那一关拦下，报的是另一个错。
            "min_revenue_yuan": 50_000_000,
            "min_net_profit_yuan": 10_000_000,
            "max_pe": 15,
            "acceptable_listed_status_json": ["unlisted"],
        }
    )

    assert outside.error_code == "field_outside_group"
    assert cross_value.error_code == "condition_value_changed"


def test_first_real_search_must_use_the_complete_group() -> None:
    plan = _validate(
        {"min_revenue_yuan": 50_000_000, "min_net_profit_yuan": 10_000_000}
    )

    assert plan.error_code == "first_real_search_must_be_full"


def test_preferred_condition_can_be_removed_with_a_real_basis() -> None:
    plan = _validate(
        {
            "min_revenue_yuan": 50_000_000,
            "min_net_profit_yuan": 10_000_000,
            "acceptable_listed_status_json": ["listed"],
        },
        prior=[_real_call(eligible_count=20)],
        relaxation_reason="调用1召回20家，但 PE 字段为空者很多，优先移除 preferred",
        based_on_call_index=1,
    )

    assert plan.valid is True
    assert plan.relaxed_fields == ("max_pe",)
    assert plan.full_conditions is False


def test_required_condition_can_relax_after_low_real_recall() -> None:
    plan = _validate(
        {
            "min_revenue_yuan": 50_000_000,
            "min_net_profit_yuan": 5_000_000,
            "max_pe": 15,
            "acceptable_listed_status_json": ["listed"],
        },
        prior=[_real_call(eligible_count=2)],
        relaxation_reason="调用1只有2家，净利条件去掉后可多召回",
        based_on_call_index=1,
    )

    assert plan.valid is True
    assert plan.relaxed_fields == ("min_net_profit_yuan",)
    assert plan.based_on_call_index == 1


def test_required_relaxation_without_basis_or_low_recall_is_rejected() -> None:
    no_basis = _validate(
        {
            "min_revenue_yuan": 50_000_000,
            "min_net_profit_yuan": 5_000_000,
            "max_pe": 15,
            "acceptable_listed_status_json": ["listed"],
        },
        prior=[_real_call(eligible_count=2)],
    )
    enough = _validate(
        {
            "min_revenue_yuan": 50_000_000,
            "min_net_profit_yuan": 5_000_000,
            "max_pe": 15,
            "acceptable_listed_status_json": ["listed"],
        },
        prior=[_real_call(eligible_count=6)],
        relaxation_reason="想多找一些",
        based_on_call_index=1,
    )

    assert no_basis.error_code == "relaxation_basis_required"
    assert enough.error_code == "required_relaxation_without_low_recall"


def test_min_only_lowers_and_max_only_rises() -> None:
    min_wrong = _validate(
        {
            "min_revenue_yuan": 50_000_000,
            "min_net_profit_yuan": 20_000_000,
            "max_pe": 15,
        },
        prior=[_real_call()],
        relaxation_reason="错误方向",
        based_on_call_index=1,
    )
    max_wrong = _validate(
        {
            "min_revenue_yuan": 50_000_000,
            "min_net_profit_yuan": 10_000_000,
            "max_pe": 10,
        },
        prior=[_real_call()],
        relaxation_reason="错误方向",
        based_on_call_index=1,
    )
    max_ok = _validate(
        {
            "min_revenue_yuan": 50_000_000,
            "min_net_profit_yuan": 10_000_000,
            "max_pe": 20,
        },
        prior=[_real_call()],
        relaxation_reason="调用1显示 PE 缺失较多",
        based_on_call_index=1,
    )

    assert min_wrong.error_code == "wrong_relaxation_direction"
    assert max_wrong.error_code == "wrong_relaxation_direction"
    assert max_ok.valid is True


def test_exclusions_are_injected_and_cannot_be_changed() -> None:
    full = _validate(
        {
            "min_revenue_yuan": 50_000_000,
            "min_net_profit_yuan": 10_000_000,
            "max_pe": 15,
            "acceptable_listed_status_json": ["listed"],
        }
    )
    changed = _validate(
        {
            "min_revenue_yuan": 50_000_000,
            "min_net_profit_yuan": 10_000_000,
            "max_pe": 15,
            "acceptable_listed_status_json": ["listed"],
            "unacceptable_risk_flags_json": [],
        }
    )

    assert full.valid is True
    assert full.conditions["unacceptable_risk_flags_json"] == ["equity_frozen"]
    # 排除行业 0828 起不再编译成条件（行业条件整组退役，它已经不是可筛字段），
    # 但仍如实留在快照里，并已渲染成「不接受 X」进定性诉求由主 Agent 执行。
    assert "excluded_industries_json" not in full.conditions
    assert changed.error_code == "exclusion_modified"


def test_fallback_group_accepts_only_code_injected_exclusions() -> None:
    groups = compile_condition_groups({"condition_groups": [], "exclusions": {}})
    valid = validate_search_call(
        "fallback-0", {}, [], groups=groups, count_only=False
    )
    invalid = validate_search_call(
        "fallback-0",
        {"min_net_profit_yuan": 1},
        [],
        groups=groups,
        count_only=False,
    )

    assert valid.valid is True
    assert invalid.error_code == "field_outside_group"


def _batch(call_index: int, group_id: str, ids: list[str], *, count_only=False) -> dict:
    return {
        "call_index": call_index,
        "valid": True,
        "group_id": group_id,
        "count_only": count_only,
        "candidate_ids": ids,
        "filters": {},
        "full_conditions": call_index == 1,
        "relaxed_fields": [] if call_index == 1 else ["max_pe"],
    }


def test_three_batches_of_twenty_with_thirty_duplicate_occurrences_yield_thirty() -> None:
    # 60 raw occurrences, 30 unique: batches overlap 1-15 / 11-30 / 1-10+21-30.
    pool = build_deep_eval_pool(
        [
            _batch(1, "group-1", [f"t-{i}" for i in range(1, 21)]),
            _batch(2, "group-1", [f"t-{i}" for i in range(11, 31)]),
            _batch(3, "group-2", [f"t-{i}" for i in [*range(1, 11), *range(21, 31)]]),
        ]
    )

    assert pool.raw_occurrences == 60
    assert pool.unique_before_cap == 30
    assert pool.unique_after_cap == 30
    assert set(pool.candidate_ids) == {f"t-{i}" for i in range(1, 31)}
    assert pool.capped is False


def test_pool_over_forty_is_stable_and_gives_every_group_seats() -> None:
    batches = [
        _batch(1, "group-1", [f"a-{i}" for i in range(20)]),
        _batch(2, "group-1", [f"b-{i}" for i in range(20)]),
        _batch(3, "group-2", [f"c-{i}" for i in range(20)]),
    ]

    first = build_deep_eval_pool(batches)
    second = build_deep_eval_pool(batches)

    assert first.candidate_ids == second.candidate_ids
    assert len(first.candidate_ids) == 40
    assert first.candidate_ids[:6] == ("a-0", "c-0", "b-0", "c-1", "a-1", "c-2")
    assert any(value.startswith("a-") or value.startswith("b-") for value in first.candidate_ids)
    assert any(value.startswith("c-") for value in first.candidate_ids)
    assert first.capped is True


def test_same_group_repeat_and_cross_group_hits_have_different_counts() -> None:
    pool = build_deep_eval_pool(
        [
            _batch(1, "group-1", ["same", "cross"]),
            _batch(2, "group-1", ["same"]),
            _batch(3, "group-2", ["cross"]),
        ]
    )

    assert pool.source_for("same")["group_hit_count"] == 1
    assert pool.source_for("same")["search_hit_count"] == 2
    assert pool.source_for("cross")["group_hit_count"] == 2
    assert pool.source_for("cross")["search_hit_count"] == 2


def test_count_only_batch_does_not_enter_the_pool() -> None:
    pool = build_deep_eval_pool(
        [_batch(1, "group-1", ["t-1"], count_only=True)]
    )

    assert pool.candidate_ids == ()
    assert pool.raw_occurrences == 0
