"""节点测试的输出预算要跟着输入走。

回归背景：test-jobs 在节点有提示词时会渲染完整的业务提示词（买家需求原文、
字段契约、行业字典……），但输出预算固定回落到 64 token。JSON 从中间被切断，
测试报"失败"，看上去像模型或提示词有问题 —— 其实是测试自己把答案掐了。
12 个已配置节点里有 8 个没设 max_tokens，这个坑对它们全都成立。
"""

from __future__ import annotations

from backend.app.jobs.handlers.model_node_test import _test_max_tokens


def test_connectivity_probe_stays_cheap() -> None:
    # 没有提示词的节点，测试只发 'Return {"status":"ok"}'，不该为它买大预算。
    assert _test_max_tokens({"user_prompt_template": None}) == 64
    assert _test_max_tokens({"user_prompt_template": "   "}) == 64


def test_business_prompt_gets_room_to_answer() -> None:
    assert _test_max_tokens({"user_prompt_template": "买家需求原文：{{ raw_requirement_text }}"}) == 4096


def test_node_setting_still_wins() -> None:
    # 节点自己设了 max_tokens 就用节点的 —— 这个兜底只在没设时生效。
    config = {"user_prompt_template": "x", "max_tokens": 8000}
    assert (config.get("max_tokens") or _test_max_tokens(config)) == 8000
