"""外部 Agent 看到的买家库（服务端版，2026-09-07）。

从 tests/test_buyer_search_skill.py 搬过来的那几条铁律，加上服务端才有的两件事：
投影里根本不选联系人，以及多方案「其他要求」的输出层去重。
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.registry.indicators import buyer_party_fact_columns
from backend.app.services import agent_buyer_views as views


def _party(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "p1",
        "buyer_name": "北大健康",
        "aliases_json": ["北大医疗"],
        "status": "active",
        "ownership_type": "state_owned",
        "listed_status": "unlisted",
        "location_province": "浙江省",
        "location_city": "杭州市",
        "location_district": None,
        "business_tags_json": ["医药商业"],
        "business_summary": "医药流通与制药。",
        "market_cap_yuan": None,
        "valuation_yuan": None,
        "current_revenue_yuan": 5e9,
        "created_at": "2026-09-07 06:32:40+00",
        "updated_at": "2026-09-07 07:10:00+00",
    }
    base.update(overrides)
    return base


def _scenario(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "s1",
        "scenario_summary": "收购医药标的",
        "business_tags_json": ["医药"],
        "excluded_business_text": None,
        "required_regions_json": [],
        "acceptable_listed_status_json": [],
        "min_revenue_yuan": None,
        "min_net_profit_yuan": None,
        "max_pe": None,
        "min_market_cap_yuan": None,
        "max_market_cap_yuan": None,
        "min_valuation_yuan": None,
        "max_valuation_yuan": None,
        "other_requirements_text": None,
        "updated_at": "2026-09-07 07:00:00+00",
    }
    base.update(overrides)
    return base


def _intent(scenarios: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    base = {
        "id": "i1",
        "buyer_party_id": "p1",
        "intent_name": "北大健康-并购需求",
        "intent_grade": "B",
        "status": "active",
        "pause_reason": None,
        "raw_requirement_text": None,
        "needs_confirmation_json": [],
        "scenarios_json": scenarios,
        "created_at": "2026-09-07 06:32:40+00",
        "updated_at": "2026-09-07 07:05:00+00",
    }
    base.update(overrides)
    return base


# -- 1. 联系人永不出库 ----------------------------------------------------


def test_the_projection_never_selects_contacts_or_notes() -> None:
    columns = views.party_projection_columns()
    assert set(columns) <= set(buyer_party_fact_columns())
    assert not views.CONTACT_COLUMNS & set(columns)
    assert "notes" not in columns


def test_a_row_that_somehow_carries_contacts_still_does_not_leak_them() -> None:
    party = _party(
        contact_name="张三",
        contact_info_json={"phone": "13800000000"},
        our_contact_name="李四",
        notes="内部备注",
    )
    for shaped in (views.party_card(party), views.party_dossier(party)):
        text = str(shaped)
        assert (
            "张三" not in text
            and "1380000" not in text
            and "李四" not in text
            and "内部备注" not in text
        )


# -- 2. 空值方向 ----------------------------------------------------------


def test_a_scenario_without_thresholds_passes_everything_and_says_so() -> None:
    checks = views.scenario_fact_checks(
        _scenario(), {"revenue_yuan": 1, "listed_status": "listed", "province": "海南省"}
    )
    assert all(passed for _, _, passed in checks)
    assert all(not stated for _, stated, _ in checks)

    card = views.intent_card(_intent([_scenario()]))
    assert card["门槛说明"] == "这个方案没有提出任何硬门槛，不构成障碍。"
    assert "门槛" not in card


def test_a_stated_threshold_really_filters_but_a_missing_target_number_does_not() -> None:
    scenario = _scenario(min_revenue_yuan=2e8, required_regions_json=[{"province": "江苏省"}])
    fails = views.scenario_fact_checks(scenario, {"revenue_yuan": 1e8, "province": "江苏省"})
    assert ("最低营收", True, False) in fails
    unknown = views.scenario_fact_checks(scenario, {"revenue_yuan": None, "province": None})
    assert ("最低营收", True, True) in unknown and ("要求地区", True, True) in unknown
    outside = views.scenario_fact_checks(scenario, {"revenue_yuan": 3e8, "province": "浙江省"})
    assert ("要求地区", True, False) in outside


# -- 3. 多方案是 OR，共同要求只写一遍 --------------------------------------


def test_matching_any_one_scenario_matches_the_requirement() -> None:
    intent = _intent(
        [
            _scenario(id="a", acceptable_listed_status_json=["listed"], max_market_cap_yuan=5e9),
            _scenario(id="b", acceptable_listed_status_json=["unlisted"], max_pe=13),
        ]
    )
    verdicts, _ = views._intent_verdicts(
        intent, {"listed_status": "unlisted", "pe": 10}, {}, True, False
    )
    assert verdicts is not None and verdicts["上市状态"] == "明确符合"
    none, single = views._intent_verdicts(
        intent, {"listed_status": "unlisted", "pe": 40}, {}, True, False
    )
    # 两个方案各差一条，marginal 报第一个方案差的那条。
    assert none is None and single == "上市状态"


def test_shared_other_requirements_are_hoisted_out_of_the_scenarios() -> None:
    shared = "要求实控权并表；交易方式：老股转让、定增"
    intent = _intent(
        [
            _scenario(id="a", other_requirements_text=shared + "；PE 不超 30"),
            _scenario(id="b", other_requirements_text=shared + "；经营稳定"),
        ]
    )
    card = views.intent_card(intent)
    assert card["各方案共同要求"] == "要求实控权并表；交易方式：老股转让、定增"
    assert [block["其他要求"] for block in card["方案"]] == ["PE 不超 30", "经营稳定"]
    assert "满足任意一个方案" in card["方案说明"]


# -- 4. 按买家提出的门槛反查 ----------------------------------------------


def test_stated_requirement_checks() -> None:
    scenario = _scenario(
        acceptable_listed_status_json=["listed"],
        required_regions_json=[{"province": "上海市"}],
        max_pe=13,
    )
    assert views.scenario_stated_checks(scenario, {"requires_listed_status": "listed"})
    assert not views.scenario_stated_checks(scenario, {"requires_listed_status": "unlisted"})
    assert views.scenario_stated_checks(scenario, {"requires_region": {"province": "上海市"}})
    assert not views.scenario_stated_checks(scenario, {"requires_region": {"province": "江苏省"}})
    assert views.scenario_stated_checks(scenario, {"has_threshold": ["max_pe"]})
    assert not views.scenario_stated_checks(scenario, {"has_threshold": ["min_revenue_yuan"]})
    # 没提门槛的方案对「谁要求上市」不算命中 —— 这里的语义是「要求」，不是「接受」。
    assert not views.scenario_stated_checks(_scenario(), {"requires_listed_status": "listed"})


# -- 5. 三个查询 ------------------------------------------------------------


@pytest.fixture
def library(monkeypatch: pytest.MonkeyPatch) -> None:
    parties = {
        "p1": _party(),
        "p2": _party(
            id="p2",
            buyer_name="广州工控",
            aliases_json=[],
            location_city="广州市",
            ownership_type="unknown",
        ),
        "p3": _party(id="p3", buyer_name="没有需求的买家", aliases_json=[], location_city="杭州市"),
    }
    intents = [
        _intent([_scenario(min_revenue_yuan=2e8)], id="i1", buyer_party_id="p1"),
        _intent(
            [_scenario(id="x", acceptable_listed_status_json=["listed"])],
            id="i2",
            buyer_party_id="p2",
            intent_grade="C",
            status="paused",
        ),
    ]
    monkeypatch.setattr(views, "load_active_parties", lambda db: parties)
    monkeypatch.setattr(views, "load_live_intents", lambda db: intents)


def test_scan_skips_parties_without_requirements_and_orders_by_grade(library: None) -> None:
    result = views.buyers_scan(db=None)
    assert [card["买家名称"] for card in result["returned"]] == ["北大健康", "广州工控"]
    assert result["returned"][1]["需求"][0]["状态"].startswith("暂停推荐")
    assert result["returned"][0]["更新时间"] == "2026-09-07 07:10:00"


def test_get_by_alias_and_by_id(library: None) -> None:
    by_alias = views.buyer_get(None, names=["北大医疗"])
    assert (
        by_alias["matched"] == 1 and by_alias["returned"][0]["买家信息"]["买家名称"] == "北大健康"
    )
    by_id = views.buyer_get(None, ids=["p3"])
    assert by_id["returned"][0]["收购需求"] == []
    missing = views.buyer_get(None, names=["不存在"])
    assert missing["matched"] == 0 and "不在库里" in missing["notes"][0]


def test_filter_by_party_facts_alone_includes_parties_without_requirements(library: None) -> None:
    result = views.buyers_filter(None, {"city": "杭州市"})
    assert [item["买家信息"]["买家名称"] for item in result["returned"]] == [
        "北大健康",
        "没有需求的买家",
    ]
    # 企业性质 unknown 的显式筛选不算满足
    assert views.buyers_filter(None, {"ownership_type": "state_owned"})["matched"] == 2


def test_filter_by_target_facts_returns_verdicts_and_marginal_notes(library: None) -> None:
    result = views.buyers_filter(
        None, {"target_revenue_yuan": 1e8, "target_listed_status": "listed"}
    )
    names = [item["买家信息"]["买家名称"] for item in result["returned"]]
    assert names == ["广州工控"]
    verdict = result["returned"][0]["收购需求"][0]["条件判定"]
    assert verdict["上市状态"] == "明确符合" and verdict["最低营收"].startswith("买家没提过")
    assert any("最低营收（去掉能多召回 1 条需求）" in note for note in result["notes"])


def test_filter_by_stated_requirements_grade_and_paging(library: None) -> None:
    assert views.buyers_filter(None, {"requires_listed_status": "listed"})["matched"] == 1
    assert views.buyers_filter(None, {"has_threshold": ["min_revenue_yuan"]})["matched"] == 1
    assert views.buyers_filter(None, {"grade": ["B"]})["matched"] == 1
    assert views.buyers_filter(None, {"include_paused": False})["matched"] == 1
    paged = views.buyers_filter(None, {"limit": 1, "offset": 0})
    assert paged["matched"] == 3 and len(paged["returned"]) == 1 and "另有 2 家" in paged["note"]
    assert "returned" not in views.buyers_filter(None, {"count_only": True})


# -- 6. 原文清洗 ------------------------------------------------------------


def test_raw_text_cleaning_strips_the_intake_header_and_duplicate_blocks() -> None:
    raw = (
        "【新建买家及并购需求初始输入】\n买家名称：X\n\n"
        "解析要求：只提取买家意向字段。\n\n【需求原文/补充材料】\n"
        "收购华东地区的医药流通企业，净利润 2000 万以上。\n\n"
        "收购华东地区的医药流通企业，净利润 2000 万以上。"
    )
    cleaned = views.clean_requirement_text(raw)
    assert cleaned.count("收购华东地区") == 1
    assert "解析要求" not in cleaned and "初始输入" not in cleaned
