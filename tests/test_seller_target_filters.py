"""Target list filters: cascading region/industry and industry-aware search.

施工单 0727 · T3. The old filters compared a flattened
``concat_ws(' ', 省, 市, 区)`` string for exact equality, so "只看广东省" was
impossible — you could only pick a full 省市区 leaf. Industry had the same
shape. Search covered name/subject/summary but *not* industry, so searching
「食品」 missed a target whose industry pair is 商贸与消费/食品 unless the
summary happened to repeat the word.

The filters are pure ``(where, params)`` builders precisely so they can be
asserted without a database.
"""

import inspect

import pytest

from backend.app.api.routes.seller_targets import (
    SELLER_TARGET_OUT_COLUMNS,
    SELLER_TARGET_SEARCH_COLUMNS,
    _industry_filter,
    _industry_option_tree,
    _location_filter,
    _search_filter,
    list_seller_targets,
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


# --- 行业 -------------------------------------------------------------------


def test_industry_l1_count_is_distinct_target_count_not_sum_of_children() -> None:
    rows = [
        {"l1": "信息技术与通信", "l2": "软件", "count": 8, "l1_count": 8},
        {"l1": "信息技术与通信", "l2": "人工智能", "count": 1, "l1_count": 8},
    ]
    tree = _industry_option_tree(rows)
    assert tree[0]["count"] == 8
    assert sum(child["count"] for child in tree[0]["children"]) == 9


def test_industry_l1_only_matches_any_pair() -> None:
    where, params = _build(_industry_filter, industry_l1="商贸与消费", industry_l2=None)
    joined = " ".join(where)
    assert "jsonb_array_elements(industry_pairs_json)" in joined
    assert "'l1' = :industry_l1" in joined
    assert ":industry_l2" not in joined
    assert params == {"industry_l1": "商贸与消费"}


def test_industry_l1_and_l2_must_match_the_same_pair() -> None:
    where, params = _build(_industry_filter, industry_l1="商贸与消费", industry_l2="食品")
    joined = " ".join(where)
    # 同一个 pair 内同时命中，否则「商贸与消费/其他」+「制造与工业/食品」会被误判。
    assert joined.count("jsonb_array_elements(industry_pairs_json)") == 1
    assert "'l1' = :industry_l1" in joined and "'l2' = :industry_l2" in joined
    assert params == {"industry_l1": "商贸与消费", "industry_l2": "食品"}


def test_industry_l2_only_matches_without_parent() -> None:
    where, params = _build(_industry_filter, industry_l1=None, industry_l2="食品")
    joined = " ".join(where)
    assert "'l2' = :industry_l2" in joined
    assert ":industry_l1" not in joined
    assert params == {"industry_l2": "食品"}


def test_empty_industry_adds_nothing() -> None:
    where, params = _build(_industry_filter, industry_l1=None, industry_l2=None)
    assert where == []
    assert params == {}


# --- 搜索 -------------------------------------------------------------------


def test_industry_is_a_searchable_field() -> None:
    assert "industry" in SELLER_TARGET_SEARCH_COLUMNS


def test_all_field_search_includes_industry_pairs() -> None:
    """搜「食品」要能命中行业为 商贸与消费/食品 的标的。"""
    where, params = _build(_search_filter, q="食品", search_field=None)
    joined = " ".join(where)
    assert "target_name ilike :q" in joined
    assert "business_summary ilike :q" in joined
    assert "jsonb_array_elements(industry_pairs_json)" in joined
    assert params["q"] == "%食品%"


def test_industry_search_field_only_searches_industry() -> None:
    where, params = _build(_search_filter, q="食品", search_field="industry")
    joined = " ".join(where)
    assert "jsonb_array_elements(industry_pairs_json)" in joined
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
