"""方案里设过的字段必须硬判，否则分档等于没写。

回归背景：打分取的是各档中最好的一档（`_score_against_scenarios`）。买家写
「市值≥10亿 → 盈利≥1000万 / 市值<10亿 → 盈利≥1亿」时，`min_market_cap_yuan`
在注册表里默认是 preferred —— 一个 5亿市值、1500万盈利的标的在第一档只扣分、
不冲突，盈利又够 1000万，于是从要求更松的那一档进来了，而买家的本意是它走
第二档、盈利不达标。

注册表默认值不能直接改硬：单方案时买家说「市值最好10亿以上」，那儿它确实该软。
所以作用域必须是「在这一档内」。
"""

from __future__ import annotations

from backend.app.registry.indicators import indicator_by_column
from backend.app.services.recommendation_conditions import CONDITION_EFFECTS, condition_effect


def test_effect_vocabulary_is_two_states() -> None:
    # deep_eval 这个取值名字骗人：深评上下文是整个 anchor 打包送模型，从不按字段
    # 分流，它实际只让字段跳过规则打分。那件事现在由 None 表达。
    assert CONDITION_EFFECTS == {"required", "preferred"}


def test_market_cap_is_soft_when_there_is_only_one_requirement() -> None:
    assert indicator_by_column("buyer_intent", "min_market_cap_yuan").default_effect == "preferred"
    assert condition_effect({"condition_effects_json": {}}, "min_market_cap_yuan") == "preferred"


def test_a_field_a_scenario_sets_becomes_a_hard_gate() -> None:
    anchor = {
        "condition_effects_json": {},
        "_scenario_fields": {"min_market_cap_yuan", "min_net_profit_yuan"},
    }

    assert condition_effect(anchor, "min_market_cap_yuan") == "required"


def test_fields_outside_the_scenario_keep_their_own_rule() -> None:
    anchor = {
        "condition_effects_json": {},
        "_scenario_fields": {"min_market_cap_yuan"},
    }

    # 这一档没提负债率，它就还是全局的那条软条件。
    assert condition_effect(anchor, "max_debt_ratio") == "preferred"


def test_an_explicit_scenario_rule_still_wins() -> None:
    # 顾问在某个方案里明说这条只是偏好，就按偏好判 —— 强制只兜没写的情况。
    anchor = {
        "condition_effects_json": {"min_market_cap_yuan": "preferred"},
        "_scenario_fields": {"min_market_cap_yuan"},
    }

    assert condition_effect(anchor, "min_market_cap_yuan") == "preferred"


def test_description_fields_do_not_score() -> None:
    # 描述字段没有 default_effect，内容随「其他」进深评，不进规则打分。
    assert indicator_by_column("buyer_intent", "major_risk_tolerance_summary").default_effect is None
    assert condition_effect({}, "major_risk_tolerance_summary") is None
    assert condition_effect({}, "a_column_that_does_not_exist") is None


def test_capability_fields_still_read_their_strength_from_the_value() -> None:
    assert condition_effect({"requires_team_retention": "required"}, "requires_team_retention") == "required"
    assert condition_effect({"requires_team_retention": "preferred"}, "requires_team_retention") == "preferred"
    assert condition_effect({"requires_team_retention": "unknown"}, "requires_team_retention") is None


def test_legacy_deep_eval_values_are_dropped() -> None:
    from backend.app.services.recommendation_conditions import normalize_condition_effects

    # 存量 condition_effects_json 里可能还留着 deep_eval。迁移会清一遍，
    # 这里再兜一道：它不再是合法规则，不能继续静默让字段跳过打分。
    assert normalize_condition_effects({"max_debt_ratio": "deep_eval"}) == {}
    assert normalize_condition_effects({"max_debt_ratio": "required"}) == {"max_debt_ratio": "required"}
