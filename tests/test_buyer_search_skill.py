"""反向检索 skill 的纯逻辑守卫（不打网络）。

`skills/buyer-search/search_buyers.py` 是给 wegent 等外部 Agent 用的独立脚本，
不在包里，所以按路径加载 —— 与 `test_intent_parse_result.py` 加载提示词脚本
同一手法。

守的三件事，每一件都是「错了不报错、只是结果悄悄变坏」的那一类：

1. **空值方向。** 反向检索里把「买家没提这条门槛」当成「不满足」，
   一半以上的买家会当场消失，而且是最灵活、最该推的那批。
2. **联系人与运营备注永不返回。** 这是业务规则不是配置项。
3. **闸门。** E 级 / 已结束 / 非在库主体不进推荐（总纲 §2.4，本 skill 是第六处实现）。
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

SKILL = pathlib.Path(__file__).resolve().parents[1] / "skills" / "buyer-search" / "search_buyers.py"


@pytest.fixture(scope="module")
def skill():
    spec = importlib.util.spec_from_file_location("buyer_search_skill", SKILL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["buyer_search_skill"] = module
    spec.loader.exec_module(module)
    return module


TARGET = {
    "revenue_yuan": 200_000_000,
    "net_profit_yuan": 20_000_000,
    "pe": 12,
    "listed_status": "unlisted",
    "province": "江苏省",
    "city": "苏州市",
}


# -- 1. 空值方向 ----------------------------------------------------------


def test_a_buyer_with_no_thresholds_passes_everything(skill) -> None:
    """**本文件最重要的一条。**

    一条门槛都没提的需求是「库里最灵活的买家」，不是「信息不足」。
    正向筛选里「没提」= 不带这个条件、天然无害；反向里如果把 NULL 当成
    「不满足」，这一批会整体消失 —— 方向恰好是最贵的那一边。
    """
    checks = skill._intent_checks({}, TARGET)

    assert checks, "至少要判几条，返回空说明判定表没接上"
    assert all(passed for _, _, passed in checks)
    assert not any(stated for _, stated, _ in checks), "买家什么都没提，stated 不该为真"


def test_an_unstated_threshold_is_reported_as_not_an_obstacle(skill) -> None:
    """返回里必须**如实区分**「明确符合」与「买家没提过」—— 这是两个结论。

    合并成一个「通过」会让调用方无法判断这条命中有多硬。
    """
    checks = skill._intent_checks({"min_revenue_yuan": 100_000_000}, TARGET)
    verdicts = {
        label: ("明确符合" if stated else "买家没提过这个门槛，不构成障碍")
        for label, stated, _ in checks
    }

    assert verdicts["最低营收"] == "明确符合"
    assert verdicts["PE 上限"] == "买家没提过这个门槛，不构成障碍"


def test_a_stated_threshold_that_fails_really_fails(skill) -> None:
    """没提就通过，但**提了就要真判** —— 否则这个工具等于没筛。"""
    checks = dict((label, (stated, passed)) for label, stated, passed in skill._intent_checks(
        {
            "min_revenue_yuan": 500_000_000,
            "acceptable_regions_json": [{"province": "广东省"}],
            "acceptable_listed_status_json": ["listed"],
        },
        TARGET,
    ))

    assert checks["最低营收"] == (True, False)
    assert checks["可接受地区"] == (True, False)
    assert checks["可接受上市状态"] == (True, False)


def test_an_empty_region_array_means_unrestricted_not_no_region(skill) -> None:
    """空数组 = 不限，**不是**「没有可接受地区」。

    读反了的话，凡是没填地区的买家全部出局 —— 而那是绝大多数。
    """
    checks = dict((label, (stated, passed)) for label, stated, passed in skill._intent_checks(
        {"acceptable_regions_json": [], "excluded_regions_json": []}, TARGET
    ))

    assert checks["可接受地区"] == (False, True)
    assert checks["排除地区"] == (False, True)


def test_a_target_with_no_region_is_not_thrown_out_by_an_exclusion(skill) -> None:
    """买家说「不要新疆」，一个连省份都没录的标的不该因此出局。

    那是数据缺口，不是「它在新疆」。方向反了会把没录地区的标的整批筛掉。
    """
    blind = {**TARGET, "province": "", "city": "", "district": ""}
    checks = dict((label, passed) for label, _, passed in skill._intent_checks(
        {"excluded_regions_json": [{"province": "新疆维吾尔自治区"}]}, blind
    ))

    assert checks["排除地区"] is True


def test_an_excluded_region_that_matches_does_throw_the_target_out(skill) -> None:
    checks = dict((label, passed) for label, _, passed in skill._intent_checks(
        {"excluded_regions_json": [{"province": "江苏省"}]}, TARGET
    ))

    assert checks["排除地区"] is False


def test_region_levels_match_independently(skill) -> None:
    """只填省 = 全省命中；填到市 = 只匹配那个市。"""
    province_only = dict((label, passed) for label, _, passed in skill._intent_checks(
        {"acceptable_regions_json": [{"province": "江苏省"}]}, TARGET
    ))
    wrong_city = dict((label, passed) for label, _, passed in skill._intent_checks(
        {"acceptable_regions_json": [{"province": "江苏省", "city": "南京市"}]}, TARGET
    ))

    assert province_only["可接受地区"] is True
    assert wrong_city["可接受地区"] is False


def test_a_missing_target_number_is_not_counted_as_a_shortfall(skill) -> None:
    """标的这一侧没给数时，不能判它不达标。

    「我们不知道这个标的的 PE」和「这个标的 PE 太高」是两个结论。
    """
    checks = dict((label, passed) for label, _, passed in skill._intent_checks(
        {"max_pe": 10}, {**TARGET, "pe": None}
    ))

    assert checks["PE 上限"] is True


# -- 2. 联系人与运营备注永不返回 ------------------------------------------


def test_contacts_and_operational_notes_never_leave_the_skill(skill) -> None:
    """联系人三件套只能来自非公开渠道；notes 是运营备注，不进任何推荐上下文。

    这是业务规则不是配置项 —— 合并进去等于把内部备注送进外部 LLM。
    """
    party = {
        "id": "p-1",
        "buyer_name": "示例买家",
        "business_summary": "做工业自动化的。",
        "contact_name": "王经理",
        "contact_info_json": {"phone": "13800000000"},
        "our_contact_name": "李顾问",
        "notes": "这家老板难沟通，别直接打电话",
        "status": "active",
    }

    for payload in (skill._party_full(party), skill._party_business(party, brief=False)):
        rendered = str(payload)
        assert "王经理" not in rendered
        assert "13800000000" not in rendered
        assert "李顾问" not in rendered
        assert "难沟通" not in rendered
        assert "contact_name" not in payload
        assert "notes" not in payload


# -- 3. 闸门 --------------------------------------------------------------


def test_the_gate_drops_e_grade_closed_and_archived(skill) -> None:
    """总纲 §2.4 记着闸门有五处独立实现，**本 skill 是第六处**。

    漏改一处不报错，表现是「E 级的还在被推荐」。
    """
    parties = skill._live_parties([
        {"id": "live", "status": "active"},
        {"id": "archived", "status": "archived"},
    ])
    assert set(parties) == {"live"}

    intents = skill._live_intents(
        [
            {"id": "ok", "buyer_party_id": "live", "intent_grade": "C", "status": "active"},
            {"id": "paused", "buyer_party_id": "live", "intent_grade": "B", "status": "paused"},
            {"id": "e-grade", "buyer_party_id": "live", "intent_grade": "E", "status": "active"},
            {"id": "closed", "buyer_party_id": "live", "intent_grade": "C", "status": "closed"},
            {"id": "orphan", "buyer_party_id": "archived", "intent_grade": "C", "status": "active"},
        ],
        parties,
    )

    # paused 保留：那条需求还在，只是暂时停了，顾问要知道它的存在。
    assert {intent["id"] for intent in intents} == {"ok", "paused"}


def test_a_paused_intent_is_returned_but_labelled(skill) -> None:
    payload = skill._intent_business(
        {"intent_name": "示例需求", "status": "paused", "intent_business_summary": "找上游"},
        brief=False,
    )

    assert "暂停" in payload["状态"]


# -- 4. 已知的坑 ----------------------------------------------------------


def test_zero_width_characters_are_stripped_before_matching(skill) -> None:
    """生产里有一条记录名字带零宽不连字，精确匹配会**静默失败**。

    表现是「库里没有这家」，而它就在库里。
    """
    assert skill._clean("‌广州电缆有限公司​") == "广州电缆有限公司"


def test_unknown_counts_as_empty(skill) -> None:
    """`unknown` 不是 `null`，但判「这个字段有没有值」时两者必须等价 ——
    多个枚举列在 DDL 里是 `not null default 'unknown'`。"""
    assert skill._blank("unknown")
    assert skill._blank(None)
    assert skill._blank([])
    assert not skill._blank("listed")


def test_unknown_buyer_facts_do_not_satisfy_explicit_filters(skill) -> None:
    """用户明确筛买家自身条件时，未知事实就是不符合。"""
    assert not skill._party_conditions_hit(
        {"ownership_type": "unknown", "market_cap_yuan": None},
        {"ownership_type": "private"},
    )
    assert not skill._party_conditions_hit(
        {"ownership_type": "private", "market_cap_yuan": None},
        {"min_market_cap_yuan": 10_000_000_000},
    )
    assert not skill._party_conditions_hit(
        {"ownership_type": "private", "location_province": None},
        {"province": "江苏省"},
    )


def test_direct_municipality_region_is_not_doubled(skill) -> None:
    """直辖市的省与市同名，直接拼会变成「北京市北京市」。"""
    assert skill._region_text([{"province": "北京市", "city": "北京市"}]) == "北京市"
    assert skill._region_text([{"province": "江苏省", "city": "苏州市"}]) == "江苏省苏州市"


def test_only_the_levels_that_were_filled_are_rendered(skill) -> None:
    """补全成三级会让「只说了江苏省」看起来像「江苏省某个具体的市」。"""
    assert skill._region_text([{"province": "江苏省"}]) == "江苏省"


def test_repeated_attachment_blocks_are_collapsed(skill) -> None:
    """实测最长一条 raw_requirement_text 有 3746 字，其中约 2000 字是同一附件
    出现了两遍。不清洗的话 50 条全量档会撑到 22 万字符。"""
    block = "公司主营锂电池正极材料，2024 年营收 3 亿元，净利润 3000 万元。"
    text = f"解析要求：只提取买家意向字段\n\n{block}\n\n{block}\n\n短"
    cleaned = skill._clean_requirement_text(text)

    assert cleaned is not None
    assert cleaned.count("锂电池正极材料") == 1
    assert "解析要求" not in cleaned


def test_a_threshold_free_intent_says_so_explicitly(skill) -> None:
    """门槛整块为空时不能只是「少了一个键」—— 那会被读成信息不足。

    必须有一句话明说「不构成障碍」，因为这批买家恰恰最该推。
    """
    payload = skill._intent_full({
        "id": "i-1",
        "intent_name": "示例需求",
        "intent_grade": "B",
        "status": "active",
        "intent_business_summary": "找华东的工业自动化标的",
    })

    assert "门槛" not in payload
    assert "不构成障碍" in payload["门槛说明"]


def test_facts_and_thresholds_stay_in_two_separate_blocks(skill) -> None:
    """两类缺失含义相反，所以数据形状上必须分开 —— 拍平成一层就没法区分了。"""
    payload = skill._intent_full({
        "id": "i-2",
        "intent_name": "示例需求",
        "intent_business_summary": "找上游材料",
        "min_revenue_yuan": "100000000",
    })

    assert payload["业务方向"]["要买什么业务"] == "找上游材料"
    assert payload["门槛"]["最低营收"] == "1亿"
    assert "最低营收" not in payload["业务方向"]


def test_full_intent_includes_pause_and_confirmation_details(skill) -> None:
    payload = skill._intent_full({
        "id": "i-3",
        "intent_name": "示例需求",
        "status": "paused",
        "pause_reason": "等待顾问确认",
        "needs_confirmation_json": [{"field": "max_pe", "reason": "材料口径不清"}],
    })

    assert payload["暂停原因"] == "等待顾问确认"
    assert payload["待确认项"][0]["field"] == "max_pe"


def test_wegent_tool_definition_is_a_single_tool_object() -> None:
    tool_path = SKILL.parent / "tool.json"
    tool = json.loads(tool_path.read_text(encoding="utf-8"))

    assert isinstance(tool, dict)
    assert tool["name"] == "search_buyers"
    assert tool["parameters"]["properties"]["operation"]["enum"] == [
        "business",
        "get",
        "filter",
    ]
    assert tool["parameters"]["required"] == ["operation"]


def test_wegent_entrypoint_dispatches_each_operation(skill, monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_business(**kwargs):
        calls.append(("business", kwargs))
        return {"operation": "business"}

    def fake_get(**kwargs):
        calls.append(("get", kwargs))
        return {"operation": "get"}

    def fake_filter(**kwargs):
        calls.append(("filter", kwargs))
        return {"operation": "filter"}

    monkeypatch.setattr(skill, "search_buyers_business", fake_business)
    monkeypatch.setattr(skill, "get_buyer", fake_get)
    monkeypatch.setattr(skill, "filter_buyers", fake_filter)

    assert skill.search_buyers("business", detail="brief") == {"operation": "business"}
    assert skill.search_buyers("get", name="北大健康") == {"operation": "get"}
    assert skill.search_buyers("filter", city="杭州市", target_district="西湖区") == {"operation": "filter"}
    assert calls == [
        ("business", {"detail": "brief"}),
        ("get", {"name": "北大健康", "buyer_party_id": None}),
        (
            "filter",
            {
                "ownership_type": None,
                "listed_status": None,
                "province": None,
                "city": "杭州市",
                "district": None,
                "min_market_cap_yuan": None,
                "min_revenue_yuan": None,
                "target_revenue_yuan": None,
                "target_net_profit_yuan": None,
                "target_pe": None,
                "target_market_cap_yuan": None,
                "target_valuation_yuan": None,
                "target_listed_status": None,
                "target_province": None,
                "target_city": None,
                "target_district": "西湖区",
            },
        ),
    ]


def test_wegent_entrypoint_rejects_unknown_operation_without_network(skill) -> None:
    result = skill.search_buyers("unsupported")

    assert result["matched"] == 0
    assert result["returned"] == []
    assert "operation" in result["error"]
