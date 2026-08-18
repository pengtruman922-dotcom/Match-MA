"""需求解析快照的归一化 —— 纯单测，不打 LLM。

每个用例都用 fixture 模拟解析节点的返回，验证**代码这一侧**的收敛：白名单、
类型强制、行业闭集、双出口、失配识别。模型输出得好不好是提示词的事，这里钉住
的是「无论模型给什么，代码都不会把用户的话弄丢、也不会替用户编条件」。

用例编号对应《推荐升级阶段二施工单_需求解析节点0817.md》第六节。
"""

from __future__ import annotations

import json
import importlib.util
import pathlib
import sys

import pytest

from backend.app.services.recommendation_conditions import (
    MAX_CONDITION_GROUPS,
    fallback_intent_parse_result,
    normalize_intent_parse_result,
    screening_fields_prompt_json,
)

# 生产字典的子集，够覆盖用例即可。闭集之外的词（新能源车企、醋酸下游）是用来
# 验证「落不进闭集就不进 conditions」的，不要往这里加。
L1_TERMS = [
    "制造与工业",
    "信息技术与通信",
    "房地产与建筑",
    "能源",
    "商贸与消费",
    "医药与健康",
]
L2_TERMS = [
    "机器人",
    "人工智能",
    "半导体",
    "汽车零部件",
    "整车制造",
    "新能源",
    "房地产",
]


def parse(raw, user_message: str) -> dict:
    return normalize_intent_parse_result(
        raw,
        industry_l1_terms=L1_TERMS,
        industry_l2_terms=L2_TERMS,
        user_message=user_message,
    )


def only_group(result: dict) -> dict:
    assert len(result["condition_groups"]) == 1, result["condition_groups"]
    return result["condition_groups"][0]


def all_text(result: dict) -> str:
    """定性诉求 + 残留笔记拼起来，用来断言「这句话没丢」。"""
    return " || ".join([*result["qualitative_requirements"], *result["unstructured_notes"]])


def _query_prompt_module():
    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "publish_query_parser_v030_prompt.py"
    spec = importlib.util.spec_from_file_location("publish_query_parser_v030_prompt", path)
    loaded = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(loaded)
    return loaded


# -- 用例 1-4：正常解析 ----------------------------------------------------


def test_case1_region_only_adds_nothing_else() -> None:
    """杭州的标的 —— 只说了地区就只筛地区，不许长出别的条件。"""
    result = parse(
        {
            "condition_groups": [
                {"label": "", "conditions": {"region_constraints_json": [{"province": "浙江省", "city": "杭州市"}]}}
            ],
            "qualitative_requirements": [],
            "exclusions": {},
            "unstructured_notes": [],
        },
        "杭州的标的",
    )
    group = only_group(result)
    assert group["conditions"] == {
        "region_constraints_json": [{"province": "浙江省", "city": "杭州市"}]
    }
    assert result["parser_status"] == "ok"


def test_case2_debt_ratio_is_a_percentage_not_a_fraction() -> None:
    """负债率 60% 落库是 60，不是 0.6。写成小数条件会一家也筛不到且不报错。"""
    result = parse(
        {
            "condition_groups": [
                {
                    "label": "",
                    "conditions": {
                        "industries_json": ["制造与工业"],
                        "region_constraints_json": [{"province": "江苏省"}],
                        "min_net_profit_yuan": 10000000,
                        "max_debt_ratio": 60,
                    },
                }
            ],
            "qualitative_requirements": [],
            "exclusions": {},
            "unstructured_notes": [],
        },
        "江苏的制造业，净利1000万以上，负债率不超过60%",
    )
    conditions = only_group(result)["conditions"]
    assert conditions["max_debt_ratio"] == 60
    assert conditions["min_net_profit_yuan"] == 10000000
    assert conditions["industries_json"] == ["制造与工业"]
    assert conditions["region_constraints_json"] == [{"province": "江苏省"}]


def test_case3_two_groups_keep_the_shared_industry() -> None:
    """上市一档、非上市一档 —— 组间 OR 由主 Agent 拆成两次调用实现。"""
    result = parse(
        {
            "condition_groups": [
                {
                    "label": "上市公司",
                    "conditions": {
                        "industry_l2_json": ["机器人", "人工智能"],
                        "acceptable_listed_status_json": ["listed"],
                        "min_market_cap_yuan": 100000000,
                        "max_pe": 15,
                    },
                    "strength": {"min_market_cap_yuan": "required", "max_pe": "preferred"},
                },
                {
                    "label": "非上市公司",
                    "conditions": {
                        "industry_l2_json": ["机器人", "人工智能"],
                        "acceptable_listed_status_json": ["unlisted"],
                        "min_revenue_yuan": 30000000,
                    },
                    "strength": {"min_revenue_yuan": "required"},
                },
            ],
            "qualitative_requirements": [],
            "exclusions": {},
            "unstructured_notes": [],
        },
        "机器人/AI行业，上市的市值1亿PE15，非上市的营收3000万",
    )
    listed, unlisted = result["condition_groups"]
    assert listed["label"] == "上市公司"
    assert unlisted["label"] == "非上市公司"
    for group in (listed, unlisted):
        assert group["conditions"]["industry_l2_json"] == ["机器人", "人工智能"]
    assert listed["conditions"]["acceptable_listed_status_json"] == ["listed"]
    assert listed["conditions"]["max_pe"] == 15
    assert listed["strength"]["max_pe"] == "preferred"
    assert unlisted["conditions"]["acceptable_listed_status_json"] == ["unlisted"]
    assert unlisted["conditions"]["min_revenue_yuan"] == 30000000


def test_case4_soft_wish_lands_in_qualitative_requirements() -> None:
    """海外仓这种不可枚举的诉求筛选用不上，但深评要用，必须抓出来。"""
    result = parse(
        {
            "condition_groups": [
                {
                    "conditions": {
                        "industries_json": ["制造与工业"],
                        "region_constraints_json": [{"province": "浙江省"}],
                    }
                }
            ],
            "qualitative_requirements": ["最好有成熟的海外仓"],
            "exclusions": {},
            "unstructured_notes": [],
        },
        "浙江的制造业，最好有成熟的海外仓",
    )
    assert only_group(result)["conditions"]["industries_json"] == ["制造与工业"]
    assert result["qualitative_requirements"] == ["最好有成熟的海外仓"]


# -- 阶段四 4A：最近五轮驱动的完整当前快照 -------------------------------


def test_4a_add_condition_keeps_previous_industry_and_profit_in_the_full_snapshot() -> None:
    """「只看上市公司」不是一份只含 listed 的增量，输出仍是完整当前需求。"""
    result = parse(
        {
            "condition_groups": [{
                "label": "当前需求",
                "conditions": {
                    "industries_json": ["制造与工业"],
                    "min_net_profit_yuan": 10000000,
                    "acceptable_listed_status_json": ["listed"],
                },
                "strength": {},
            }],
            "qualitative_requirements": [],
            "exclusions": {},
            "unstructured_notes": [],
        },
        "只看上市公司",
    )

    assert only_group(result)["conditions"] == {
        "industries_json": ["制造与工业"],
        "min_net_profit_yuan": 10000000,
        "acceptable_listed_status_json": ["listed"],
    }
    assert result["raw_text"] == "只看上市公司"


def test_4a_replace_condition_changes_only_profit_when_everything_else_stays() -> None:
    result = parse(
        {
            "condition_groups": [{
                "conditions": {
                    "industries_json": ["制造与工业"],
                    "region_constraints_json": [{"province": "江苏省"}],
                    "min_net_profit_yuan": 5000000,
                    "acceptable_listed_status_json": ["listed"],
                }
            }],
            "qualitative_requirements": [],
            "exclusions": {},
            "unstructured_notes": [],
        },
        "净利放宽到500万，其他不变",
    )

    assert only_group(result)["conditions"] == {
        "industries_json": ["制造与工业"],
        "region_constraints_json": [{"province": "江苏省"}],
        "min_net_profit_yuan": 5000000,
        "acceptable_listed_status_json": ["listed"],
    }


def test_4a_delete_condition_removes_only_region_from_the_full_snapshot() -> None:
    result = parse(
        {
            "condition_groups": [{
                "conditions": {
                    "industries_json": ["制造与工业"],
                    "min_net_profit_yuan": 5000000,
                    "acceptable_listed_status_json": ["listed"],
                }
            }],
            "qualitative_requirements": [],
            "exclusions": {},
            "unstructured_notes": [],
        },
        "去掉地区限制",
    )

    conditions = only_group(result)["conditions"]
    assert "region_constraints_json" not in conditions
    assert conditions == {
        "industries_json": ["制造与工业"],
        "min_net_profit_yuan": 5000000,
        "acceptable_listed_status_json": ["listed"],
    }


def test_4a_reset_can_discard_the_old_demand_entirely() -> None:
    result = parse(
        {
            "condition_groups": [{
                "conditions": {
                    "industries_json": ["医药与健康"],
                    "region_constraints_json": [{"province": "浙江省"}],
                }
            }],
            "qualitative_requirements": [],
            "exclusions": {},
            "unstructured_notes": [],
        },
        "重新找浙江医疗行业",
    )

    assert only_group(result)["conditions"] == {
        "industries_json": ["医药与健康"],
        "region_constraints_json": [{"province": "浙江省"}],
    }


# -- 用例 5：必须过 —— 白名单吃掉的表达不得静默蒸发 --------------------------


def test_case5_deleted_field_survives_as_a_qualitative_requirement() -> None:
    """「经营稳定」对应的字段已在指标重构中判为伪枚举删除。

    只有过滤没有兜底的话，这句话既不进条件也不进定性诉求，静默蒸发 —— 这是
    本阶段最容易做错的地方，所以钉死在这里。
    """
    result = parse(
        {
            "condition_groups": [
                {
                    "conditions": {
                        "industries_json": ["制造与工业"],
                        "operation_stability_status": "stable",
                    }
                }
            ],
            "qualitative_requirements": [],
            "exclusions": {},
            "unstructured_notes": [],
        },
        "要经营稳定的制造业",
    )
    conditions = only_group(result)["conditions"]
    assert conditions == {"industries_json": ["制造与工业"]}
    assert "operation_stability_status" not in conditions
    # 兜底出口里必须找得到它，而且 parser_notes 要说清楚为什么没进条件。
    assert "operation_stability_status" in all_text(result)
    assert any("operation_stability_status" in note for note in result["parser_notes"])


def test_case5_model_written_wording_is_preferred_when_it_gives_one() -> None:
    """模型按提示词把「经营稳定」写进定性诉求时，保留用户的说法。"""
    result = parse(
        {
            "condition_groups": [{"conditions": {"industries_json": ["制造与工业"]}}],
            "qualitative_requirements": ["经营稳定"],
            "exclusions": {},
            "unstructured_notes": [],
        },
        "要经营稳定的制造业",
    )
    assert result["qualitative_requirements"] == ["经营稳定"]


# -- 用例 6：排除项 --------------------------------------------------------


def test_case6_exclusions_normalize_to_industry_and_risk_flags() -> None:
    result = parse(
        {
            "condition_groups": [],
            "qualitative_requirements": [],
            "exclusions": {"industries": ["房地产与建筑"], "risk_flags": ["股权冻结"]},
            "unstructured_notes": [],
        },
        "不要房地产，也不接受股权被冻结的",
    )
    assert result["exclusions"]["industries"] == ["房地产与建筑"]
    assert result["exclusions"]["risk_flags"] == ["equity_frozen"]


def test_exclusions_written_inside_a_group_are_hoisted_to_the_top() -> None:
    """排除是全局粘性的。留在组里等于「只有这一组排除」，与用户的意思相反。"""
    result = parse(
        {
            "condition_groups": [
                {
                    "conditions": {
                        "industries_json": ["制造与工业"],
                        "excluded_industries_json": ["房地产与建筑"],
                        "unacceptable_risk_flags_json": ["equity_frozen"],
                    }
                }
            ],
            "qualitative_requirements": [],
            "exclusions": {},
            "unstructured_notes": [],
        },
        "制造业，不要房地产，不接受股权冻结",
    )
    conditions = only_group(result)["conditions"]
    assert "excluded_industries_json" not in conditions
    assert "unacceptable_risk_flags_json" not in conditions
    assert result["exclusions"]["industries"] == ["房地产与建筑"]
    assert result["exclusions"]["risk_flags"] == ["equity_frozen"]


def test_unmatched_exclusion_stays_negative() -> None:
    """方向陷阱：落不进闭集的排除词若原样进定性诉求，会读成「想要它」。"""
    result = parse(
        {
            "condition_groups": [],
            "qualitative_requirements": [],
            "exclusions": {"industries": ["殡葬"], "risk_flags": ["老板脾气不好"]},
            "unstructured_notes": [],
        },
        "不要殡葬相关的，老板脾气不好的也不要",
    )
    assert result["exclusions"]["industries"] == []
    assert result["exclusions"]["risk_flags"] == []
    assert "不接受殡葬" in result["qualitative_requirements"]
    assert "不接受老板脾气不好" in result["qualitative_requirements"]


# -- 用例 7：行业闭集 ------------------------------------------------------


def test_case7_out_of_vocabulary_industry_never_reaches_conditions() -> None:
    """行业名写错会静默清空候选池 —— 所以字典外的词一条都不许进 conditions。"""
    result = parse(
        {
            "condition_groups": [
                {
                    "conditions": {
                        "industries_json": ["制造与工业"],
                        "industry_l2_json": ["新能源车企", "整车制造"],
                    }
                }
            ],
            "qualitative_requirements": [],
            "exclusions": {},
            "unstructured_notes": [],
        },
        "新能源车企",
    )
    conditions = only_group(result)["conditions"]
    assert conditions["industry_l2_json"] == ["整车制造"]
    assert "新能源车企" not in json.dumps(conditions, ensure_ascii=False)
    # 剔掉的那个词交给深评判断，不是丢掉。
    assert "新能源车企" in all_text(result)


def test_canonicalised_region_is_not_reported_as_leftover() -> None:
    """地区会被改写成标准名（浙江 → 浙江省）。

    拿改写前后的字面量逐项对比，会把一条已经生效的条件当成漏网的诉求再报一遍，
    深评那头收到的就是一句 Python 字典的 repr。
    """
    result = parse(
        {"condition_groups": [{"conditions": {"region_constraints_json": [{"province": "浙江"}]}}]},
        "浙江的标的",
    )
    assert only_group(result)["conditions"] == {"region_constraints_json": [{"province": "浙江省"}]}
    assert result["qualitative_requirements"] == []
    assert result["unstructured_notes"] == []


def test_whole_industry_condition_dropped_when_nothing_matches() -> None:
    result = parse(
        {
            "condition_groups": [{"conditions": {"industry_l2_json": ["醋酸下游", "偏光膜"]}}],
            "qualitative_requirements": [],
            "exclusions": {},
            "unstructured_notes": [],
        },
        "醋酸下游或偏光膜的标的",
    )
    assert result["condition_groups"] == []
    assert "醋酸下游" in all_text(result)
    assert "偏光膜" in all_text(result)


# -- 用例 8：必须过 —— 没有需求时不许编 --------------------------------------


def test_case8_small_talk_produces_no_conditions_and_keeps_the_sentence() -> None:
    """空条件 + 原话进 unstructured_notes。不报错，也不发挥。

    「用户只说杭州，agent 自己编出半导体 + 华东 + 净利 3000 万」那次事故的根
    就是模型在没有需求时自己造了一个。
    """
    result = parse(
        {
            "condition_groups": [],
            "qualitative_requirements": [],
            "exclusions": {},
            "unstructured_notes": [],
        },
        "今天天气怎么样",
    )
    assert result["condition_groups"] == []
    assert result["qualitative_requirements"] == []
    assert result["exclusions"] == {"industries": [], "risk_flags": []}
    assert result["unstructured_notes"] == ["今天天气怎么样"]
    assert result["parser_status"] == "ok"


def test_case8_keeps_the_models_own_note_when_it_wrote_one() -> None:
    result = parse(
        {
            "condition_groups": [],
            "qualitative_requirements": [],
            "exclusions": {},
            "unstructured_notes": ["今天天气怎么样"],
        },
        "今天天气怎么样",
    )
    assert result["unstructured_notes"] == ["今天天气怎么样"]


# -- 用例 9：强度 ----------------------------------------------------------


def test_case9_strength_defaults_to_required_for_unmarked_conditions() -> None:
    """「最好」是 preferred，没修饰词的定量门槛默认 required。

    漏标的那一条若被当成可选，agent 放宽时会先丢掉它 —— 而它很可能正是用户
    唯一说死的那个数。
    """
    result = parse(
        {
            "condition_groups": [
                {
                    "conditions": {
                        "min_net_profit_yuan": 30000000,
                        "region_constraints_json": [
                            {"province": "江苏省"},
                            {"province": "浙江省"},
                            {"province": "上海市"},
                        ],
                    },
                    "strength": {"region_constraints_json": "preferred"},
                }
            ],
            "qualitative_requirements": [],
            "exclusions": {},
            "unstructured_notes": [],
        },
        "净利要3000万以上，最好在长三角",
    )
    strength = only_group(result)["strength"]
    assert strength["min_net_profit_yuan"] == "required"
    assert strength["region_constraints_json"] == "preferred"


def test_unknown_strength_token_falls_back_to_required() -> None:
    result = parse(
        {
            "condition_groups": [
                {"conditions": {"max_pe": 15}, "strength": {"max_pe": "nice_to_have"}}
            ],
            "qualitative_requirements": [],
            "exclusions": {},
            "unstructured_notes": [],
        },
        "PE不超过15",
    )
    assert only_group(result)["strength"] == {"max_pe": "required"}


# -- 用例 10：必须过 —— 提示词与代码失配要响 ---------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        {"foo": 1},
        # 旧版提示词的形状：一个新键都没有，正是这个状态要抓的东西。
        {"condition_ops": [{"op": "set", "field": "max_pe", "value": 15}], "semantic_preferences": []},
        [],
        None,
        "杭州",
    ],
)
def test_case10_unrecognised_payload_is_flagged_not_swallowed(raw) -> None:
    """返回了 JSON 但一个认得的顶层键都没有 = 版本失配，必须看得见。

    上一轮吃过一模一样的亏：提示词把变量写成单花括号，模型收到字面量，输出
    全错但全链路零报错，只能靠人读对话记录才发现。
    """
    result = parse(raw, "杭州的标的")
    assert result["parser_status"] == "schema_mismatch"
    assert result["condition_groups"] == []
    assert result["parser_notes"], "失配必须留下可读的原因"
    # 不抛异常、不伪造条件，原话仍然带得下去。
    assert result["raw_text"] == "杭州的标的"
    assert "杭州的标的" in all_text(result)


def test_an_empty_but_recognised_shell_is_not_a_mismatch() -> None:
    """模型正确返回了空快照（用户没提需求），那是 ok，不是失配。"""
    assert parse({"condition_groups": []}, "在吗")["parser_status"] == "ok"


# -- 用例 11：必须过 —— 越界字段走兜底 ---------------------------------------


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("min_net_margin", 15, "净利率要15%以上"),
        ("max_ps", 3, "PS不超过3倍"),
        ("max_premium_rate", 20, "溢价不超过20%"),
        ("requires_relocation", "required", "必须能迁址"),
        ("requires_return_investment", "required", "要能返投"),
        ("requires_team_retention", "required", "核心团队要留任"),
    ],
)
def test_case11_non_screening_fields_go_to_qualitative_not_conditions(column, value, message) -> None:
    """注册表里 screening=False 的字段是合法的业务表达，只是不进初筛。"""
    result = parse(
        {
            "condition_groups": [{"conditions": {column: value}}],
            "qualitative_requirements": [],
            "exclusions": {},
            "unstructured_notes": [],
        },
        message,
    )
    assert result["condition_groups"] == []
    assert column not in json.dumps(result["condition_groups"], ensure_ascii=False)
    assert result["qualitative_requirements"], f"{column} 静默蒸发了"


# -- 双出口不变式 ----------------------------------------------------------


@pytest.mark.parametrize(
    "conditions",
    [
        {"min_net_margin": 15},
        {"operation_stability_status": "stable"},
        {"industries_json": ["元宇宙"]},
        {"industry_l2_json": ["偏光膜"]},
        {"acceptable_listed_status_json": ["借壳上市"]},
        {"max_pe": "十五倍"},
        {"region_constraints_json": ["江苏"]},
        {"完全瞎编的字段": True},
    ],
)
def test_every_ignored_condition_lands_in_a_fallback_exit(conditions) -> None:
    """`normalize_conditions` 报了忽略，就必须有东西进兜底出口。

    这是双出口的核心不变式：白名单只约束 conditions，不约束用户的表达。
    """
    result = parse(
        {
            "condition_groups": [{"conditions": conditions}],
            "qualitative_requirements": [],
            "exclusions": {},
            "unstructured_notes": [],
        },
        "随便一句需求",
    )
    assert result["parser_notes"], "被忽略的条件必须留下诊断"
    assert all_text(result), f"{conditions} 被静默丢弃了"


# -- 其它形状与边界 --------------------------------------------------------


def test_raw_text_comes_from_the_user_not_the_model() -> None:
    """模型会把原话改写成系统术语，而这一栏存在的意义就是「用户到底说了什么」。"""
    result = parse(
        {
            "condition_groups": [],
            "qualitative_requirements": [],
            "exclusions": {},
            "unstructured_notes": [],
            "raw_text": "买家希望收购华东地区制造业标的",
        },
        "想在江浙沪找个厂子",
    )
    assert result["raw_text"] == "想在江浙沪找个厂子"


def test_group_count_is_capped_and_the_cut_is_reported() -> None:
    result = parse(
        {
            "condition_groups": [
                {"conditions": {"min_revenue_yuan": 1000000 * (index + 1)}}
                for index in range(MAX_CONDITION_GROUPS + 3)
            ],
            "qualitative_requirements": [],
            "exclusions": {},
            "unstructured_notes": [],
        },
        "分很多档",
    )
    assert len(result["condition_groups"]) == MAX_CONDITION_GROUPS
    assert any("超过上限" in note for note in result["parser_notes"])


def test_groups_get_a_label_even_when_the_model_omits_it() -> None:
    result = parse(
        {"condition_groups": [{"conditions": {"max_pe": 15}}]},
        "PE不超过15",
    )
    assert only_group(result)["label"] == "方案1"


def test_a_single_group_object_is_accepted_like_a_one_item_list() -> None:
    result = parse(
        {"condition_groups": {"conditions": {"max_pe": 15}}},
        "PE不超过15",
    )
    assert only_group(result)["conditions"] == {"max_pe": 15}


def test_fallback_keeps_the_sentence_and_says_so() -> None:
    """LLM 调用失败时退化成「没有结构化条件的一轮」，但不许假装成功。"""
    result = fallback_intent_parse_result("杭州的制造业", note="超时")
    assert result["parser_status"] == "fallback"
    assert result["qualitative_requirements"] == ["杭州的制造业"]
    assert result["condition_groups"] == []
    assert result["exclusions"] == {"industries": [], "risk_flags": []}
    assert result["parser_notes"] == ["超时"]


def test_result_always_carries_every_top_level_key() -> None:
    expected = {
        "condition_groups",
        "qualitative_requirements",
        "exclusions",
        "unstructured_notes",
        "raw_text",
        "parser_status",
        "parser_notes",
    }
    assert expected <= set(parse({"condition_groups": []}, "在吗"))
    assert expected <= set(fallback_intent_parse_result("在吗"))


# -- 注入提示词的字段清单 ---------------------------------------------------


def test_screening_fields_prompt_is_generated_from_the_registry() -> None:
    """手写一份字段清单必然与注册表漂移 —— 所以它必须是生成的。"""
    from backend.app.services.screening_schema import SCREENING_FIELDS

    entries = json.loads(screening_fields_prompt_json())
    assert [entry["field"] for entry in entries] == [field.column for field in SCREENING_FIELDS]
    assert len(entries) == 24


def test_ratio_fields_declare_the_percentage_unit_in_the_prompt() -> None:
    """写成「0-1 小数」的后果是模型把 60% 写成 0.6，而库里存的是 60。"""
    by_field = {entry["field"]: entry for entry in json.loads(screening_fields_prompt_json())}
    assert "百分数" in by_field["max_debt_ratio"]["unit"]
    assert "百分数" in by_field["desired_equity_ratio_min"]["unit"]
    assert "倍数" in by_field["max_pe"]["unit"]


def test_exclusion_field_description_says_it_removes_candidates() -> None:
    """同一个形状在 not_overlap 下是「命中即出局」，方向写反会把语义倒过来。"""
    by_field = {entry["field"]: entry for entry in json.loads(screening_fields_prompt_json())}
    assert "出局" in by_field["excluded_industries_json"]["note"]
    assert "出局" in by_field["unacceptable_risk_flags_json"]["note"]
    assert "通过" in by_field["industries_json"]["note"]


# -- Prompt v0.3.0 ------------------------------------------------------


def test_query_parser_v030_uses_exactly_the_node_variables() -> None:
    from backend.app.ai.prompting import extract_template_variables
    from backend.app.registry.nodes import node_by_name

    prompt = _query_prompt_module()
    spec = node_by_name(prompt.NODE_NAME)
    assert spec is not None
    assert prompt.VERSION == "v0.3.0"
    assert set(extract_template_variables(prompt.SYSTEM_PROMPT, prompt.USER_PROMPT_TEMPLATE)) == set(
        spec.prompt_variables
    )


def test_query_parser_v030_spells_out_add_replace_delete_and_reset_semantics() -> None:
    prompt = _query_prompt_module()
    body = prompt.SYSTEM_PROMPT + prompt.USER_PROMPT_TEMPLATE

    assert "完整快照" in body and "不是本轮增量" in body
    for phrase in ("只看上市公司", "净利放宽到 500 万", "其他不变", "去掉地区限制", "重新找浙江医疗行业"):
        assert phrase in body
    assert "raw_text" in body and "本轮原话" in body


def test_query_parser_v030_rejects_a_same_version_with_different_content() -> None:
    prompt = _query_prompt_module()
    conflicting = {
        "version": prompt.VERSION,
        "system_prompt": "不同正文",
        "user_prompt_template": prompt.USER_PROMPT_TEMPLATE,
        "output_schema_json": prompt.OUTPUT_SCHEMA,
        "variables_json": list(prompt.EXPECTED_VARIABLES),
    }

    with pytest.raises(prompt.PromptVersionConflict, match="正文.*不同"):
        prompt.ensure_existing_version_compatible([conflicting])


def test_query_parser_v030_conflict_exits_nonzero(monkeypatch) -> None:
    prompt = _query_prompt_module()

    class FakeApi:
        @staticmethod
        def _resolve_token(_base):
            return "token"

        @staticmethod
        def _request_json(*_args, **_kwargs):
            return [{
                "version": prompt.VERSION,
                "system_prompt": "冲突正文",
                "user_prompt_template": prompt.USER_PROMPT_TEMPLATE,
                "output_schema_json": prompt.OUTPUT_SCHEMA,
                "variables_json": list(prompt.EXPECTED_VARIABLES),
            }]

    monkeypatch.setattr(prompt, "_api_client", lambda: FakeApi)
    monkeypatch.setattr(sys, "argv", ["publish_query_parser_v030_prompt.py", "--dry-run"])

    assert prompt.main() != 0
