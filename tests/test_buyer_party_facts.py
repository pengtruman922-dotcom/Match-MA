"""买家主体字段改造（0824）的写入侧规则。

改名的两条保护、闭集校验、unknown 与 null 的等价处理，都是「错了不报错」
的那一类：漏掉只会让顾问下次搜不到自己录的买家，或者让更新记录里塞满
假变更。所以单独钉住。
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from backend.app.api.routes.buyer_parties import (
    BUYER_PARTY_JSON_COLUMNS,
    BuyerPartyCreate,
    BuyerPartyUpdate,
    _normalize_buyer_party_facts,
)
from backend.app.services.buyer_party_name import (
    BuyerPartyNameChangeRequiresReview,
    plan_buyer_party_rename,
)


# -- 改名的两条保护（施工单 §七）


def test_rename_keeps_the_old_name_searchable() -> None:
    """顾问录的是「北控」，AI 改成全称；旧名不留下来，他下次就搜不到了。

    dedup-check 与 suggestions 都查别名，append 进去即保住搜索路径。
    """
    name, aliases = plan_buyer_party_rename(
        current_name="北控",
        current_aliases=[],
        new_name="北京控股集团有限公司",
    )
    assert name == "北京控股集团有限公司"
    assert aliases == ["北控"]


def test_rename_does_not_duplicate_an_existing_alias() -> None:
    _, aliases = plan_buyer_party_rename(
        current_name="北控",
        current_aliases=["北控", "BEHL"],
        new_name="北京控股集团有限公司",
    )
    assert aliases == ["北控", "BEHL"]


def test_whitespace_and_case_only_edits_are_not_renames() -> None:
    """否则每次保存都会往别名里塞一条只差空格的重复项。"""
    name, aliases = plan_buyer_party_rename(
        current_name="北控",
        current_aliases=["BEHL"],
        new_name="  北控 ",
    )
    assert name == "北控"
    assert aliases == ["BEHL"]


def test_ai_rename_requires_explicit_confirmation() -> None:
    """名称改错了影响所有关联需求、撮合关系和搜索，而且不会报错。

    所以非人工来源不能静默覆盖 —— 下一单的解析/调研节点拿到这个异常时
    应当去建 extracted_action 等人确认。
    """
    for source in ("parse", "research"):
        with pytest.raises(BuyerPartyNameChangeRequiresReview):
            plan_buyer_party_rename(
                current_name="北控",
                current_aliases=[],
                new_name="北京控股集团有限公司",
                source=source,
            )

    name, aliases = plan_buyer_party_rename(
        current_name="北控",
        current_aliases=[],
        new_name="北京控股集团有限公司",
        source="research",
        confirmed=True,
    )
    assert name == "北京控股集团有限公司"
    assert aliases == ["北控"]


def test_manual_rename_needs_no_confirmation() -> None:
    """人在详情页上按下保存，那本身就是确认。"""
    name, _ = plan_buyer_party_rename(
        current_name="北控",
        current_aliases=[],
        new_name="北京控股集团有限公司",
        source="manual",
    )
    assert name == "北京控股集团有限公司"


def test_update_payload_carries_the_review_channel() -> None:
    """默认 manual + 未确认：PATCH 的调用方是详情页上的人，行为不变。"""
    payload = BuyerPartyUpdate(buyer_name="北京控股集团有限公司")
    assert payload.name_change_source == "manual"
    assert payload.name_change_confirmed is False
    # 这两个字段不是业务事实，不该出现在落库的 changes 里。
    assert set(payload.model_dump(exclude_unset=True)) == {"buyer_name"}


# -- 写入侧归一化


def test_enum_values_are_checked_against_the_registry() -> None:
    with pytest.raises(HTTPException) as error:
        _normalize_buyer_party_facts({"ownership_type": "central_soe"})
    assert error.value.status_code == 422

    # 央企不是独立取值：合并进国企，区别落到 business_summary 表达。
    fields = {"ownership_type": "state_owned", "listed_status": "listed", "listing_exchange": "sse"}
    _normalize_buyer_party_facts(fields)
    assert fields == {"ownership_type": "state_owned", "listed_status": "listed", "listing_exchange": "sse"}


def test_null_collapses_to_unknown_for_the_not_null_enums() -> None:
    """unknown 不是 null，但前端清空下拉时发的是 null —— 收敛而不是让 DB 报错。"""
    fields = {"ownership_type": None, "listed_status": None, "listing_exchange": None}
    _normalize_buyer_party_facts(fields)
    assert fields["ownership_type"] == "unknown"
    assert fields["listed_status"] == "unknown"
    # 上市地是 nullable，null 就是 null（「没查过」），不该被改写成 unknown
    # （后者是「查过但不确定在哪上市」）。
    assert fields["listing_exchange"] is None


def test_business_tags_are_free_text_deduped_and_trimmed() -> None:
    """行业字典只有 16 个一级行业，接不住买家的细分主业，所以不过字典。"""
    fields = {"business_tags_json": [" 储能系统 ", "储能系统", "", "钙钛矿组件材料"]}
    _normalize_buyer_party_facts(fields)
    assert fields["business_tags_json"] == ["储能系统", "钙钛矿组件材料"]


def test_money_is_quantized_to_the_column_scale() -> None:
    """不对齐 numeric(20,2) 时，「没改」会被 diff 记成改过，更新记录里全是假变更。"""
    fields = {"market_cap_yuan": Decimal("3.26E+9"), "valuation_yuan": None}
    _normalize_buyer_party_facts(fields)
    assert str(fields["market_cap_yuan"]) == "3260000000.00"
    assert fields["valuation_yuan"] is None


def test_market_cap_as_of_is_a_date_and_valuation_date_is_a_label() -> None:
    """行情日期是机器给的确定日子（要能算「过没过 7 天」），估值时点是人写的中文。"""
    payload = BuyerPartyCreate(
        buyer_name="某某集团",
        market_cap_as_of="2026-08-20",
        valuation_date="2025年一季度",
    )
    assert payload.market_cap_as_of == date(2026, 8, 20)
    assert payload.valuation_date == "2025年一季度"


def test_jsonb_binding_list_is_derived_from_the_registry() -> None:
    """漏一个 jsonb 绑定的表现是「列被当字符串写进去」，不是报错。"""
    assert BUYER_PARTY_JSON_COLUMNS == {"aliases_json", "business_tags_json", "contact_info_json"}
