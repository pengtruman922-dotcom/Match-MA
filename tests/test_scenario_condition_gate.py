"""`condition_effects_json` 的取值词表守卫。

原本还守着「方案里设过的字段必须硬判」那条打分规则（`condition_effect` +
`_score_against_scenarios`）。阶段五 5B 拆掉旧 `/candidates` 打分链路后规则
打分本身不复存在，只剩下词表本身还有真实用户 —— `buyer_intents.py` 与
`buyer_intent_parse.py` 用它建单、改单、解析回填。

下面两条守的就是这个词表：合法取值只有两个，历史存量里的 `deep_eval` 必须
被清掉，不能继续静默让字段跳过判断。
"""

from __future__ import annotations

from backend.app.services.recommendation_conditions import CONDITION_EFFECTS


def test_effect_vocabulary_is_two_states() -> None:
    # deep_eval 这个取值名字骗人：深评上下文是整个 anchor 打包送模型，从不按字段
    # 分流，它实际只让字段跳过规则打分。那件事现在由 None 表达。
    assert CONDITION_EFFECTS == {"required", "preferred"}


def test_legacy_deep_eval_values_are_dropped() -> None:
    from backend.app.services.recommendation_conditions import normalize_condition_effects

    # 存量 condition_effects_json 里可能还留着 deep_eval。迁移会清一遍，
    # 这里再兜一道：它不再是合法规则，不能继续静默让字段跳过打分。
    assert normalize_condition_effects({"max_debt_ratio": "deep_eval"}) == {}
    assert normalize_condition_effects({"max_debt_ratio": "required"}) == {"max_debt_ratio": "required"}
