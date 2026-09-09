"""Target list filters: cascading region, business-tag containment and tag-aware search.

施工单 0727 · T3. The old filters compared a flattened
``concat_ws(' ', 省, 市, 区)`` string for exact equality, so "只看广东省" was
impossible — you could only pick a full 省市区 leaf. Search covered
name/subject/summary but *not* the industry facet.

方案 0908: the industry dictionary is gone. The facet is now the free business
tag list (``business_tags_json``), filtered by exact containment (same operator
as the buyer-party list) and searched through a ``::text ilike``.

The filters are pure ``(where, params)`` builders precisely so they can be
asserted without a database.
"""

import inspect

import pytest

from backend.app.api.routes.seller_targets import (
    SELLER_TARGET_OUT_COLUMNS,
    SELLER_TARGET_SEARCH_COLUMNS,
    _business_tag_filter,
    _location_filter,
    _search_filter,
    list_seller_targets,
    seller_target_filter_options,
)


def _build(fn, **kwargs) -> tuple[list[str], dict[str, object]]:
    where: list[str] = []
    params: dict[str, object] = {}
    fn(where, params, **kwargs)
    return where, params


# --- 地区 -------------------------------------------------------------------


def test_province_only_filter_does_not_constrain_city_or_district() -> None:
    where, params = _build(_location_filter, province="广东省", city=None, district=None)
    joined = " ".join(where)
    assert "location_province = :location_province" in joined
    assert "location_city" not in joined
    assert "location_district" not in joined
    assert params == {"location_province": "广东省"}


def test_city_filter_adds_to_province() -> None:
    where, params = _build(_location_filter, province="广东省", city="深圳市", district=None)
    joined = " ".join(where)
    assert "location_province = :location_province" in joined
    assert "location_city = :location_city" in joined
    assert "location_district" not in joined
    assert params == {"location_province": "广东省", "location_city": "深圳市"}


def test_district_filter_is_the_narrowest_level() -> None:
    where, params = _build(
        _location_filter, province="浙江省", city="杭州市", district="余杭区"
    )
    assert len(where) == 3
    assert params["location_district"] == "余杭区"


def test_city_without_province_still_filters() -> None:
    # URL 可以被手工编辑；缺上级不该让筛选静默失效。
    where, params = _build(_location_filter, province=None, city="深圳市", district=None)
    assert where == ["location_city = :location_city"]
    assert params == {"location_city": "深圳市"}


def test_empty_region_adds_nothing() -> None:
    where, params = _build(_location_filter, province=None, city="", district=None)
    assert where == []
    assert params == {}


def test_region_values_are_normalized_before_matching() -> None:
    """URL 里传「广东」也要能命中库里的「广东省」。"""
    _, params = _build(_location_filter, province="广东", city=None, district=None)
    assert params["location_province"] == "广东省"


# --- 业务标签 ---------------------------------------------------------------


def test_business_tag_filter_is_exact_containment() -> None:
    """与买家主体列表同一个算子：`business_tags_json ? :tag`，不做模糊匹配。

    下拉的取值来自 filter-options，本来就是库里真实存在的标签；模糊匹配会让
    「食品」同时命中「休闲食品」「食品机械」，而顾问点的是那一个词。
    """
    where, params = _build(_business_tag_filter, business_tag="汽车零部件")
    assert where == ["business_tags_json ? :business_tag"]
    assert params == {"business_tag": "汽车零部件"}


def test_business_tag_filter_trims_and_ignores_blank() -> None:
    where, params = _build(_business_tag_filter, business_tag="  PCB ")
    assert params == {"business_tag": "PCB"}
    where, params = _build(_business_tag_filter, business_tag="   ")
    assert where == []
    assert params == {}


def test_business_tag_filter_does_not_touch_the_retired_industry_columns() -> None:
    """行业字典 0908 下线：筛选不得再读 industry_pairs_json / industry_l1 / industry_l2。"""
    source = inspect.getsource(_business_tag_filter) + inspect.getsource(seller_target_filter_options)
    for retired in ("industry_pairs_json", "industry_l1", "industry_l2", "industry_taxonomy"):
        assert retired not in source


def test_filter_options_aggregate_real_tags_not_a_dictionary_skeleton() -> None:
    """自由标签没有字典骨架可渲染：下拉只列库里真实存在的标签及其计数。"""
    source = inspect.getsource(seller_target_filter_options)
    assert "jsonb_array_elements_text" in source
    assert "business_tags" in source
    assert "industries" not in source


# --- 搜索 -------------------------------------------------------------------


def test_business_tags_is_a_searchable_field() -> None:
    assert "business_tags" in SELLER_TARGET_SEARCH_COLUMNS
    assert "industry" not in SELLER_TARGET_SEARCH_COLUMNS


def test_all_field_search_includes_business_tags() -> None:
    """搜「食品」要能命中标签为「休闲食品」的标的，即使摘要里没这个词。"""
    where, params = _build(_search_filter, q="食品", search_field=None)
    joined = " ".join(where)
    assert "target_name ilike :q" in joined
    assert "business_summary ilike :q" in joined
    assert "business_tags_json::text ilike :q" in joined
    assert params["q"] == "%食品%"


def test_business_tags_search_field_only_searches_tags() -> None:
    where, params = _build(_search_filter, q="食品", search_field="business_tags")
    joined = " ".join(where)
    assert "business_tags_json::text ilike :q" in joined
    assert "target_name" not in joined
    assert "business_summary" not in joined
    assert params["q"] == "%食品%"


@pytest.mark.parametrize(
    "field", ["target_name", "target_subject_name", "business_summary"]
)
def test_scalar_search_fields_stay_single_column(field: str) -> None:
    where, _ = _build(_search_filter, q="食品", search_field=field)
    assert where == [f"{field} ilike :q"]


def test_blank_query_adds_nothing() -> None:
    where, params = _build(_search_filter, q=None, search_field="target_name")
    assert where == []
    assert params == {}


def test_target_list_does_not_aggregate_relation_events() -> None:
    source = inspect.getsource(list_seller_targets)

    assert "buyer_seller_relation" not in source
    assert "relation_event" not in source
    assert "latest_progress" not in source


def test_target_list_exposes_pending_research_conflicts_without_frontend_n_plus_one() -> None:
    source = inspect.getsource(list_seller_targets)

    assert "pending_research_conflict_count" in source or "SELLER_TARGET_OUT_COLUMNS" in source
    assert "research_proposal" in SELLER_TARGET_OUT_COLUMNS
    assert "review_status = 'pending_review'" in SELLER_TARGET_OUT_COLUMNS
    assert "conflict_kind = 'same_period_conflict'" in SELLER_TARGET_OUT_COLUMNS
