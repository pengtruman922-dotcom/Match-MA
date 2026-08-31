"""条件强度词表的守卫。

原来这里还守着 `normalize_condition_effects` —— `buyer_intent.condition_effects_json`
的归一函数。**2026-08-28 那一列连同归一函数一起退役了**（方案 0828 判决三）：
它的三个活消费方（前端角标、深评上下文的「条件作用」、解析写入路径）本轮全部
拆掉，而筛选消费方在阶段五 5B 就已经没了。注册表里那句「recommendation_flow.py
用它放宽三道硬门槛」是过期注释，grep 过，那个人不存在。

词表 `CONDITION_EFFECTS` 本身没有退役，因为它还有两个真实用户，
两个都与那一列无关 —— 下面守的就是这两个。
"""

from backend.app.services.recommendation_conditions import CONDITION_EFFECTS


def test_condition_effects_vocabulary_is_two_states() -> None:
    # 历史上有第三个取值 deep_eval，名字骗人 —— 深评上下文从来不按字段分流，
    # 它实际只让字段跳过规则打分。那件事现在由 condition_effect 返回 None 表达。
    assert CONDITION_EFFECTS == {"required", "preferred"}


def test_missing_strength_defaults_to_required() -> None:
    """漏标强度的定量门槛必须按「必须」记，不能按「可选」。

    方向反了的代价是单向的：agent 放宽条件时会先丢掉标成可选的那一条，
    而它很可能正是用户唯一说死的那个数。
    """
    from backend.app.services.recommendation_conditions import _normalize_group_strength

    conditions = {"min_revenue_yuan": 100000000, "max_pe": 15}
    strength = _normalize_group_strength({"max_pe": "preferred"}, conditions)
    assert strength == {"min_revenue_yuan": "required", "max_pe": "preferred"}
    # 词表外的取值同样退回 required，不是原样透传。
    assert _normalize_group_strength({"max_pe": "deep_eval"}, conditions)["max_pe"] == "required"


def test_retired_condition_effects_normalizer_is_gone() -> None:
    """判决三的落点：那个函数不能被谁悄悄加回来。

    加回来本身不报错，表现是「解析又开始写一列没有任何消费方的 jsonb」，
    而模型每次解析都要为它多判一遍。
    """
    import backend.app.services.recommendation_conditions as module

    assert not hasattr(module, "normalize_condition_effects")
