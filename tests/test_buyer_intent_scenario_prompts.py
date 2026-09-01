"""三个买家需求提示词发布脚本的离线守卫（不访问 API）。

脚本自己带 `--check`，但**没有任何东西在 CI 里跑它** —— 而
`buyer_intent_parser` 与 `buyer_intent_update_parser` 拿不到
`field_contract_json`，方案字段清单是**手写在正文里**的，注册表加一列
它们不会跟着变。漏一个的表现是「那个字段永远解析不出来」，不报错。

三份必须同时守：兜底节点（parser）与两阶段（normalizer）产出同一个形状，
不然「走了哪条路」会决定数据长什么样。
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

from backend.app.registry.indicators import writable_columns

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
MODULES = {
    "normalizer": SCRIPTS / "publish_buyer_intent_scenario_prompt.py",
    "parser": SCRIPTS / "publish_buyer_intent_parser_v0100_prompt.py",
    "update_parser": SCRIPTS / "publish_buyer_intent_update_parser_v040_prompt.py",
}


def _load(name: str):
    path = MODULES[name]
    spec = importlib.util.spec_from_file_location(f"prompt_script_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    # 脚本在模块级跑 validate_prompt_contract：变量集合与 NodeSpec 不一致就在
    # 这里抛，等于这条测试顺带守住了「提示词变量与节点声明一致」。
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def scripts() -> dict:
    return {name: _load(name) for name in MODULES}


def test_the_hand_written_field_lists_match_the_registry(scripts) -> None:
    """parser 与 update_parser 的方案字段清单必须与注册表逐字段一致。

    这两个节点拿不到字段契约，清单只能写在正文里 —— 注册表加一列而正文没跟上，
    模型就永远不知道有那个字段可以填。
    """
    declared = set(writable_columns("parse", "buyer_intent_scenario"))
    for name in ("parser", "update_parser"):
        listed = set(scripts[name].SCENARIO_FIELDS)
        assert listed == declared, (
            f"{name} 的方案字段清单与注册表不一致；"
            f"注册表多出={sorted(declared - listed)}，脚本多出={sorted(listed - declared)}"
        )
        body = scripts[name].USER_PROMPT_TEMPLATE
        for column in declared:
            assert column in body, f"{name} 的正文里没有 {column}"


def test_no_retired_field_survives_in_any_prompt(scripts) -> None:
    """退役字段的规则正文一条都不许留下。

    留着就是在教模型填一个它已经看不见的字段 —— 写了不报错，会被静默丢弃，
    而那次解析的注意力已经花掉了。
    """
    retired = (
        "industries_json",
        "industry_l2_json",
        "region_constraints_json",
        "requires_control",
        "requires_consolidation",
        "desired_equity_ratio_min",
        "transaction_types_json",
        "unacceptable_risk_flags_json",
        "excluded_regions_json",
        "acceptable_regions_json",
        "intent_business_summary",
        "intent_business_tags_json",
        "intent_summary",
        "max_debt_ratio",
        "preferred_listed_status",
    )
    for name, module in scripts.items():
        body = module.SYSTEM_PROMPT + module.USER_PROMPT_TEMPLATE
        for column in retired:
            assert column not in body, f"{name} 的正文里还在讲已退役的 {column}"


def test_every_prompt_teaches_the_same_split_rule(scripts) -> None:
    """拆分标准决定召回，而拆错不报错 —— 两条产出方案的链路必须教同一条规则。

    只讲规则不给示例的话，模型会把材料里每个小标题都拆成一个方案；
    只给示例不讲规则，遇到没见过的形状就没有判据。所以两样都要。
    """
    for name in ("normalizer", "parser"):
        body = scripts[name].USER_PROMPT_TEMPLATE
        assert "如果任意组合都成立" in body, f"{name} 缺拆分判据"
        assert "单个字段有多个值不算绑定" in body, f"{name} 缺「多值不等于分叉」"
        assert "拿不准就拆" in body, f"{name} 缺默认倾向"
        assert "不要预设" in body, f"{name} 没写明轴不固定"
        # 一正一反两个示例：湖北农发不拆、岭南商旅拆三个。
        assert "一个方案" in body and "拆三个方案" in body, f"{name} 缺反差示例"
        assert "scenarios 至少要有一个元素" in body, f"{name} 没写明方案不能为空"


def test_preference_wording_is_routed_out_of_the_hard_region_filter(scripts) -> None:
    """「广东优先」填进要求地区会把外地的好标的直接筛掉。

    实测 36 家买家里提到地域的 16 家中有 9 家说的是「优先/最好」——
    这是提及率最高的一类误填，三份提示词都要写明它的去处。
    """
    for name, module in scripts.items():
        body = module.USER_PROMPT_TEMPLATE
        assert "other_requirements_text" in body, f"{name} 没告诉模型偏好该写哪"
        assert "优先" in body, f"{name} 没提到偏好语气"


def test_the_update_parser_must_locate_the_scenario_it_changes(scripts) -> None:
    """多方案需求的更新不给 scenario_index 就默认打到第一个方案。

    「非上市档的 PE 放宽到 15」于是被写进上市档 —— **不报错**，库里安静地存了
    一个错的数字，而两档的数字本来就不一样，人不去对根本看不出来。
    """
    body = scripts["update_parser"].USER_PROMPT_TEMPLATE

    assert body.count("scenario_index") >= 4, "方案定位要讲清楚，一句话不够"
    assert "判不出是哪一档就不要猜" in body
    assert "不要带 scenario_index" in body, "改容器字段时不该带方案定位"


def test_the_code_side_whitelist_accepts_what_the_prompt_teaches(scripts) -> None:
    """提示词教模型输出 scenario_index，代码侧的抽取白名单必须收得住。

    收不住的表现是：模型给对了，抽取阶段把它当越权字段丢掉，然后更新静默
    打到第一个方案 —— 和根本没教是同一个结果。
    """
    from backend.app.jobs.handlers.common import BUYER_INTENT_CHANGE_FIELDS

    assert "scenario_index" in BUYER_INTENT_CHANGE_FIELDS
    assert set(writable_columns("parse", "buyer_intent_scenario")) <= BUYER_INTENT_CHANGE_FIELDS


def test_the_understudy_and_the_two_stage_chain_produce_the_same_shape(scripts) -> None:
    """兜底节点与两阶段必须产出同一个形状。

    `buyer_intent_parser` 只在两阶段任一节点未就绪时代跑（NodeSpec 的
    understudy 声明）。它停在旧形状不会报错，只会让兜底那条路解析出来的需求
    **没有任何门槛** —— 而「今天走的是哪条路」顾问是看不见的。
    """
    for name in ("normalizer", "parser"):
        schema = scripts[name].OUTPUT_SCHEMA
        assert "scenarios" in schema["properties"], f"{name} 的 schema 没有 scenarios"
    assert scripts["parser"].OUTPUT_SCHEMA["required"] == ["scenarios"], (
        "兜底节点必须把 scenarios 定为必填：门槛只住在方案里，不给方案等于什么都没解析出来"
    )
