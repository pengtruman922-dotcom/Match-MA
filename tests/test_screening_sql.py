"""初筛 SQL：算子级片段 + 71 条生产快照的端到端验收（施工单 0817 · 阶段一）。

两层：

- 算子级用例不需要数据库，钉住「缺失即出局」与「unknown 不是 null」这两条
  最容易被改回去的规则；
- 快照级用例把 `tests/fixtures/screening_targets_snapshot.json`（2026-08-17 的
  71 条生产标的，其中 E 级 2 条）灌进真实 Postgres 后逐条断言命中数。SQL 的
  三值逻辑、`count(*) filter` 的拆分、jsonb 展开都只有真库能验 —— 参照
  `test_job_queue_sql.py` 的教训，没有 DATABASE_URL 时跳过，CI 的
  `Fresh database from baseline` job 里跑。
"""

import json
import os
import re
from pathlib import Path

import pytest
from dataclasses import replace
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.registry.indicators import indicator_by_column
from backend.app.services.screening_schema import (
    SCREENING_FIELDS,
    SCREENING_FIELDS_BY_COLUMN,
    UNKNOWN_CODE,
)
from backend.app.services.screening_sql import (
    ROW_COLUMNS,
    _count_sql,
    _rows_sql,
    build_clause,
    screen_targets,
)

FIXTURE = Path(__file__).parent / "fixtures" / "screening_targets_snapshot.json"

JIANGSU = [{"province": "江苏省"}]


def _clause(column: str, value, index: int = 0):
    return build_clause(SCREENING_FIELDS_BY_COLUMN[column], value, index)


# -- 算子级：SQL 片段 -----------------------------------------------------


def test_gte_and_lte_compare_the_declared_target_column() -> None:
    assert _clause("min_net_profit_yuan", 10000000).sql == "st.current_net_profit_yuan >= :c0"
    assert _clause("max_pe", 15).sql == "st.pe_ratio <= :c0"


def test_in_and_eq_bind_their_values() -> None:
    listed = _clause("acceptable_listed_status_json", ["listed", "pre_ipo"])
    assert listed.sql == "st.listed_status = any(:c0)"
    assert listed.params == {"c0": ["listed", "pre_ipo"]}

    # `eq` 算子 0828 起在买家侧没有在役字段了（上市地要求随双侧皆空的枚举退役），
    # 但 build_clause 仍然实现它 —— 下一个成对新建的单值枚举会直接用上。
    # 拿一个临时构造的字段验，而不是删掉这条：算子实现坏了不会有别的东西报警。
    exchange = build_clause(
        replace(SCREENING_FIELDS_BY_COLUMN["max_pe"], operator="eq", target_column="listing_market_region"),
        "sse",
        0,
    )
    assert exchange.sql == "st.listing_market_region = :c0"


def test_requirement_capability_passes_yes_and_likely() -> None:
    """强度不进 SQL：required 与 preferred 生成的条件完全一样。"""
    clause = _clause("requires_control", True)

    assert clause.sql == "st.can_control = any(:c0)"
    assert clause.params == {"c0": ["yes", "likely"]}


def test_excluded_regions_are_the_negation_of_acceptable_regions() -> None:
    """region_any 与 region_none 共用同一段构造，只在最后取反。

    0828 之前买家侧只有 region_constraints_json 一列，靠元素里的 effect 三态区分
    可接受/优先/排除，而 SQL 只实现了 required 那一档 —— 也就是说**排除地区
    从来没有真的排除过任何标的**，存了等于没存且看不出来。
    """
    acceptable = _clause("acceptable_regions_json", JIANGSU)
    excluded = _clause("excluded_regions_json", JIANGSU)

    assert acceptable.sql == "((st.location_province = :c0_0_province))"
    assert excluded.sql == "not coalesce(((st.location_province = :c0_0_province)), false)"


def test_excluded_regions_do_not_throw_out_targets_with_no_region_recorded() -> None:
    """买家说「不要新疆」，一个连省份都没录的标的**不该**因此出局。

    那是数据缺口不是「它在新疆」。所以这一条的缺失恒 false ——
    它从不贡献缺失统计，agent 也就不会拿它去解释召回为什么少。
    """
    clause = _clause("excluded_regions_json", JIANGSU)

    assert clause.missing_sql == "false"


def test_a_flat_array_overlap_does_not_go_through_the_industry_path() -> None:
    """交易结构存的是字符串数组。

    走错形状不会报错：0828 之前这里有一条行业分支，打在 industry_pairs_json 上的
    overlap 恒不命中（候选池恒空），扁平数组的字段一旦走错就是这个结果。
    行业分支已随需求侧行业条件一起删除，这条守的是「没走回去」。
    """
    clause = _clause("transaction_types_json", ["equity_transfer"])

    assert "jsonb_array_elements_text(" in clause.sql
    assert "acceptable_transaction_structures_json" in clause.sql
    assert "industry_pairs_json" not in clause.sql


def test_risk_exclusion_also_throws_out_targets_nobody_checked() -> None:
    """`not exists(...)` 对空数组恒为真，而空数组是「未核查」。

    少了前半段，「没查过」会被当成「干净」通过风险条件 —— 方向恰好是危险的那一边。
    """
    clause = _clause("unacceptable_risk_flags_json", ["litigation"])

    assert clause.sql.startswith("not (st.major_risk_flags_json is null or jsonb_array_length(")
    assert "not exists(" in clause.sql


def test_region_ands_the_levels_that_were_given_and_ors_the_constraints() -> None:
    clause = _clause(
        "acceptable_regions_json",
        [{"province": "江苏省", "city": "苏州市"}, {"province": "浙江省"}],
    )

    assert clause.sql == (
        "((st.location_province = :c0_0_province and st.location_city = :c0_0_city)"
        " or (st.location_province = :c0_1_province))"
    )
    assert clause.params["c0_0_city"] == "苏州市"


def test_a_condition_never_lets_a_missing_value_through() -> None:
    """缺失即出局：模板不带**放行**缺失的 `is null or`。

    一旦缺失也算通过，「去掉这一条能多召回几家」就恒等于 0，agent 的放宽策略
    整个失效。

    注意反过来的写法是合法的：not_overlap 打在扁平数组上时，命中 SQL 必须
    显式排掉缺失（`not (col is null or jsonb_array_length(col) = 0) and ...`），
    因为 `not exists(...)` 对空数组恒为真 —— major_risk_flags_json 的空数组是
    「未核查」，放它过去就等于把「没查过」当成「干净」。所以这里判的是
    「有没有放行缺失的分支」，不是「字面出没出现 is null」。
    """
    samples = {
        "number": 1.0,
        "boolean": True,
        "region_list": [{"province": "江苏省"}],
    }
    for field in SCREENING_FIELDS:
        if field.value_type == "enum":
            value = field.enum_values[0]
        elif field.value_type == "enum_list":
            value = [field.enum_values[0]]
        else:
            value = samples[field.value_type]
        clause = build_clause(field, value, 0)
        if field.operator == "region_none":
            # 排除类条件天生是「命中即出局」，缺失恒 false —— 它不参与
            # 「缺失即出局」这条规则，参与了反而会把没录地区的标的一起扔掉。
            continue
        permissive = clause.sql.replace(f"not {clause.missing_sql}", "")
        assert "is null" not in permissive, field.column


# -- 算子级：unknown 不是 null --------------------------------------------


@pytest.mark.parametrize(
    ("column", "target_column"),
    # 从注册表派生，不手写：手写的那份会在指标进出初筛时静默漏掉新字段，
    # 而这条守卫恰恰是用来挡「新加的枚举列忘了把 unknown 当缺失」的。
    sorted(
        (field.column, field.target_column)
        for field in SCREENING_FIELDS
        if field.target_column
        and "," not in field.target_column
        and "/" not in field.target_column
        and UNKNOWN_CODE
        in {
            code
            for code, _ in (
                indicator_by_column("seller_target", field.target_column).enum_options or ()
            )
        }
        and not indicator_by_column("seller_target", field.target_column).multi_value
    ),
)
def test_unknown_counts_as_missing_on_every_enum_with_an_unknown_level(
    column: str, target_column: str
) -> None:
    """这些列在 DDL 里是 `not null default 'unknown'`，`is null` 永远判不到它们。

    漏掉这一条不会报错：整批未录入的标的会被算成「确实不达标」，agent 于是去
    放宽一个根本不该放宽的条件。
    """
    field = SCREENING_FIELDS_BY_COLUMN[column]
    value = [field.enum_values[0]] if field.value_type == "enum_list" else (
        field.enum_values[0] if field.value_type == "enum" else True
    )
    missing = build_clause(field, value, 0).missing_sql

    assert missing == f"(st.{target_column} is null or st.{target_column} = 'unknown')"


def test_a_nullable_column_without_an_unknown_level_only_checks_null() -> None:
    assert _clause("min_revenue_yuan", 1.0).missing_sql == "st.current_revenue_yuan is null"


def test_region_missing_means_compatible_but_incomplete() -> None:
    """买家要苏州市、标的只录到江苏省，那是数据没录；山东省的标的是真不达标。

    两者不分开，agent 会把一个真门槛当成数据缺口去放宽。
    """
    missing = _clause("acceptable_regions_json", [{"province": "江苏省", "city": "苏州市"}]).missing_sql

    assert "st.location_province = :c0_0_province or coalesce(st.location_province, '') = ''" in missing
    assert "coalesce(st.location_city, '') = ''" in missing
    assert "location_district" not in missing


# -- 算子级：查询结构 -----------------------------------------------------


def test_the_breakdown_is_one_scan_not_one_query_per_condition() -> None:
    clauses = [
        _clause("acceptable_regions_json", JIANGSU, 0),
        _clause("min_net_profit_yuan", 10000000, 1),
    ]
    sql = _count_sql(clauses, [f"coalesce({clause.sql}, false)" for clause in clauses])

    assert sql.count("from seller_target") == 1
    assert sql.count("count(*) filter") == 1 + 3 * len(clauses)


def test_conditions_are_coalesced_so_null_does_not_swallow_a_row() -> None:
    """`not (col >= 5)` 在 col 为 null 时是 NULL 而不是 TRUE，
    `count(*) filter` 会把这行漏掉，三个数当场对不上。"""
    clause = _clause("min_net_profit_yuan", 10000000)
    sql = _count_sql([clause], [f"coalesce({clause.sql}, false)"])

    assert "not coalesce(st.current_net_profit_yuan >= :c0, false)" in sql


def test_the_gate_and_the_sort_are_in_the_row_query() -> None:
    sql = _rows_sql([])

    assert "st.target_grade <> 'E'" in sql
    # 先排完整个命中集再截前 N，不是先截再排。
    assert sql.index("order by st.target_grade asc, st.updated_at desc") < sql.index("limit :limit")


# -- 快照级：真库 --------------------------------------------------------

_needs_db = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="needs a migrated Postgres (DATABASE_URL)",
)


@pytest.fixture(scope="module")
def snapshot_db():
    """71 条生产标的灌进真库，整个模块共用一个**最终回滚**的事务。

    事务从头到尾不提交，所以这些行不会留在库里；CI 的 job 用的本来也是一次性
    的空库。
    """
    from backend.app.db import get_session_factory

    session = get_session_factory()()
    try:
        _load_snapshot(session)
        yield session
    finally:
        session.rollback()
        session.close()


def _fixture_columns() -> set[str]:
    """快照要灌哪些列——只灌初筛真正读的那些，从代码派生而不是手写清单。

    起因是一次实际事故：快照是生产导出的，`owner_user_id` 指向真实顾问，而空库里
    只有 baseline 种的两个用户，整批 insert 撞外键，32 个用例全部错在建 fixture
    这一步（2026-08-18 CI）。那一列筛选根本不读——本轮不做 owner 过滤。
    照搬整行生产数据，等于让每一个筛选不关心的列都有机会把用例炸掉；只灌读得到
    的列，这类事故就不会再有第二次。
    """
    columns = set(ROW_COLUMNS)
    # 级别与交易状态由 CHECK 双向绑定，灌了 target_grade 就必须一起灌它。
    columns.add("lifecycle_status")
    # 行业/风险/交易结构这类数组对手方不在 ROW_COLUMNS 里（摘要不展示它们），
    # 但 SQL 要读，所以从字段声明里补出来。
    for field in SCREENING_FIELDS:
        for chunk in field.target_column.split(","):
            columns.add(chunk.split(".")[0].strip())
    return columns


def _load_snapshot(session) -> None:
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
    types = {
        row["column_name"]: row["data_type"]
        for row in session.execute(
            text(
                "select column_name, data_type from information_schema.columns"
                " where table_schema = 'public' and table_name = 'seller_target'"
            )
        ).mappings()
    }
    wanted = _fixture_columns()
    # 只灌「真列」且「初筛读得到」的那些，其余让 DDL 默认值兜住。
    columns = [column for column in rows[0] if column in types and column in wanted]
    jsonb_columns = [column for column in columns if types[column] == "jsonb"]
    statement = text(
        "insert into seller_target (team_id, workspace_id, "
        + ", ".join(columns)
        + ") values (:team_id, :workspace_id, "
        + ", ".join(f":{column}" for column in columns)
        + ")"
    )
    if jsonb_columns:
        statement = statement.bindparams(
            *[bindparam(column, type_=JSONB) for column in jsonb_columns]
        )
    session.execute(text("delete from seller_target"))
    session.execute(
        statement,
        [
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                **{column: row[column] for column in columns},
            }
            for row in rows
        ],
    )


def _matched(db, conditions, **kwargs) -> int:
    return screen_targets(db, conditions, count_only=True, **kwargs).matched


@_needs_db
@pytest.mark.parametrize(
    ("label", "conditions", "expected"),
    [
        ("无条件（E 级闸门）", {}, 69),
        # 行业那几组 2026-08-28 随判决一删除：需求侧行业字典下线之后，
        # 初筛里没有行业条件了，业务匹配交给 LLM 读业务摘要（business_scan）。
        ("地区 region_any", {"acceptable_regions_json": JIANGSU}, 20),
        ("地区 region_none", {"excluded_regions_json": JIANGSU}, 49),
        ("净利 gte 1000万", {"min_net_profit_yuan": 10000000}, 48),
        ("净利 gte 3000万", {"min_net_profit_yuan": 30000000}, 28),
        ("地区 + 净利", {"acceptable_regions_json": JIANGSU, "min_net_profit_yuan": 10000000}, 15),
        ("排除地区 + 营收", {"excluded_regions_json": JIANGSU, "min_revenue_yuan": 50000000}, 38),
        (
            "地区 + 净利 + PE",
            {
                "acceptable_regions_json": JIANGSU,
                "min_net_profit_yuan": 10000000,
                "max_pe": 15,
            },
            5,
        ),
        (
            "可控股收窄到个位数",
            {
                "acceptable_regions_json": JIANGSU,
                "requires_control": True,
            },
            6,
        ),
    ],
)
def test_snapshot_hit_counts(snapshot_db, label: str, conditions: dict, expected: int) -> None:
    assert _matched(snapshot_db, conditions) == expected, label


@_needs_db
def test_the_relaxation_signal_separates_missing_data_from_a_real_shortfall(snapshot_db) -> None:
    """本阶段的核心验收：**「没录」和「不达标」必须分开数**。

    这就是 agent 放宽策略的全部信息来源 —— 10 家没通过 PE 条件，其中 7 家只是
    没录 PE、3 家是真的贵。该去掉的是 PE 那一条，而不是净利。分不开的话
    agent 会去放宽一个根本不该放宽的条件。

    条件组合 0828 换过一次：原来是「行业 + 地区 + 净利 + 负债率」，行业条件与
    负债率条件都在本轮退役了。换成「地区 + 净利 + PE」，教学点一字不变，
    而且 PE 的空值率（快照里 7/10）把这一条讲得更清楚。
    """
    result = screen_targets(
        snapshot_db,
        {
            "acceptable_regions_json": JIANGSU,
            "min_net_profit_yuan": 10000000,
            "max_pe": 15,
        },
        count_only=True,
    )

    assert result.matched == 5
    assert result.excluded_by_condition["max_pe"] == {
        "总计": 10,
        "字段为空": 7,
        "确实不达标": 3,
        "去掉后命中": 15,
    }
    # 地区那一条是真门槛：12 家全都是「确实不在江苏」，没有一家是数据缺口。
    assert result.excluded_by_condition["acceptable_regions_json"] == {
        "总计": 12,
        "字段为空": 0,
        "确实不达标": 12,
        "去掉后命中": 17,
    }


@_needs_db
@pytest.mark.parametrize(
    "conditions",
    [
        {"acceptable_regions_json": JIANGSU},
        {"min_net_profit_yuan": 10000000, "max_pe": 15},
        {"requires_control": True, "acceptable_regions_json": JIANGSU},
        {"excluded_regions_json": JIANGSU, "min_revenue_yuan": 50000000},
        {"acceptable_profitability_status_json": ["profitable"]},
        {"transaction_types_json": ["equity_transfer", "merger"]},
        {"unacceptable_risk_flags_json": ["litigation", "violation"], "max_pe": 15},
    ],
)
def test_missing_plus_shortfall_always_equals_the_total(snapshot_db, conditions: dict) -> None:
    result = screen_targets(snapshot_db, conditions, count_only=True)

    for column, report in result.excluded_by_condition.items():
        assert report["字段为空"] + report["确实不达标"] == report["总计"], column
        assert report["去掉后命中"] - result.matched == report["总计"], column


@_needs_db
def test_unknown_is_counted_as_missing_data_not_as_a_real_shortfall(snapshot_db) -> None:
    """快照里 can_control 是 unknown 的有 38 家、no 的有 6 家。

    只判 `is null` 的实现会把 44 家全算成「确实不达标」，agent 会得出
    「这批标的大多不能控股」——而事实是大多没录。
    """
    result = screen_targets(snapshot_db, {"requires_control": True}, count_only=True)

    assert result.matched == 25  # yes 21 + likely 4
    assert result.excluded_by_condition["requires_control"] == {
        "总计": 44,
        "字段为空": 38,
        "确实不达标": 6,
        "去掉后命中": 69,
    }


@_needs_db
def test_a_nullable_enum_counts_both_null_and_unknown_as_missing(snapshot_db) -> None:
    """profitability_status 是可空列，枚举里**也**有 unknown，两种都要判。"""
    result = screen_targets(
        snapshot_db, {"acceptable_profitability_status_json": ["profitable"]}, count_only=True
    )

    assert result.matched == 16
    assert result.excluded_by_condition["acceptable_profitability_status_json"] == {
        "总计": 53,
        "字段为空": 50,  # 49 个 NULL + 1 个 'unknown'
        "确实不达标": 3,
        "去掉后命中": 69,
    }


@_needs_db
def test_a_target_with_no_province_is_missing_data_not_the_wrong_province(snapshot_db) -> None:
    """快照里 2 家没录省份，其余 47 家是真的不在江苏。"""
    result = screen_targets(snapshot_db, {"acceptable_regions_json": JIANGSU}, count_only=True)

    assert result.excluded_by_condition["acceptable_regions_json"] == {
        "总计": 49,
        "字段为空": 2,
        "确实不达标": 47,
        "去掉后命中": 69,
    }


@_needs_db
def test_a_flat_array_condition_separates_unrecorded_from_mismatched(snapshot_db) -> None:
    """快照里只有 1 家录了可接受交易结构（股权转让/增资/资产收购），68 家空着。

    走错形状（打在对象数组上）的话这两条会双双变成 0 命中且不报错。
    """
    hit = screen_targets(
        snapshot_db, {"transaction_types_json": ["equity_transfer"]}, count_only=True
    )
    assert hit.matched == 1
    assert hit.excluded_by_condition["transaction_types_json"] == {
        "总计": 68,
        "字段为空": 68,
        "确实不达标": 0,
        "去掉后命中": 69,
    }

    miss = screen_targets(snapshot_db, {"transaction_types_json": ["merger"]}, count_only=True)
    assert miss.matched == 0
    assert miss.excluded_by_condition["transaction_types_json"] == {
        "总计": 69,
        "字段为空": 68,
        "确实不达标": 1,  # 那唯一一家录了，但不接受吸收合并
        "去掉后命中": 69,
    }


@_needs_db
def test_an_unchecked_target_never_passes_the_risk_condition(snapshot_db) -> None:
    """快照：67 家未核查、1 家涉诉+违规、1 家仅违规。

    买家不接受涉诉时只剩最后那一家 —— 67 家「没查过」必须记成缺失，
    既不能通过条件，也不能被算成「确实有涉诉」。
    """
    result = screen_targets(
        snapshot_db, {"unacceptable_risk_flags_json": ["litigation"]}, count_only=True
    )

    assert result.matched == 1
    assert result.excluded_by_condition["unacceptable_risk_flags_json"] == {
        "总计": 68,
        "字段为空": 67,
        "确实不达标": 1,
        "去掉后命中": 69,
    }


@_needs_db
def test_an_excluded_region_removes_only_the_targets_that_are_in_it(snapshot_db) -> None:
    """排除地区第一次真的排除得掉东西。

    0828 之前买家侧只有 region_constraints_json 一列，排除靠元素里的
    `effect="excluded"`，而 SQL 只实现了 required 那一档 —— 排除地区从来没有
    真的排除过任何标的，存了等于没存且界面上看不出来。

    **没录省份的标的不出局**：买家说「不要江苏」，一个连省份都没录的标的
    不该因此被扔掉，那是数据缺口不是「它在江苏」。所以这一条的「字段为空」
    恒为 0 —— 它从不贡献缺失统计。
    """
    result = screen_targets(snapshot_db, {"excluded_regions_json": JIANGSU}, count_only=True)

    assert result.matched == 49
    assert result.excluded_by_condition["excluded_regions_json"] == {
        "总计": 20,
        "字段为空": 0,
        "确实不达标": 20,
        "去掉后命中": 69,
    }


# -- 快照级：排序与返回 ---------------------------------------------------


@_needs_db
def test_the_whole_hit_set_is_sorted_before_the_first_twenty_are_taken(snapshot_db) -> None:
    """先截 20 再排序的话，级别构成会完全不同（混入 D、漏掉 B）。"""
    result = screen_targets(snapshot_db, {"min_net_profit_yuan": 10000000}, limit=20)

    grades = [row["target_grade"] for row in result.rows]
    assert result.matched == 48
    assert len(grades) == 20
    assert grades.count("A") == 3
    assert grades.count("B") == 13
    assert grades.count("C") == 4
    assert grades == sorted(grades)


@_needs_db
def test_within_a_grade_the_freshest_information_comes_first(snapshot_db) -> None:
    result = screen_targets(snapshot_db, {"acceptable_regions_json": JIANGSU}, limit=20)

    for grade in {row["target_grade"] for row in result.rows}:
        updated = [row["updated_at"] for row in result.rows if row["target_grade"] == grade]
        assert updated == sorted(updated, reverse=True), grade


@_needs_db
def test_e_grade_never_comes_back_whatever_the_conditions(snapshot_db) -> None:
    for conditions in ({}, {"acceptable_regions_json": JIANGSU}, {"min_net_profit_yuan": 0}):
        result = screen_targets(snapshot_db, conditions, limit=20)
        assert all(row["target_grade"] != "E" for row in result.rows)


@_needs_db
def test_offset_pages_through_the_same_sorted_hit_set(snapshot_db) -> None:
    first = screen_targets(snapshot_db, {"min_net_profit_yuan": 10000000}, limit=20)
    second = screen_targets(snapshot_db, {"min_net_profit_yuan": 10000000}, limit=20, offset=20)

    ids = {str(row["id"]) for row in first.rows}
    assert ids.isdisjoint({str(row["id"]) for row in second.rows})
    assert second.rows[0]["target_grade"] >= first.rows[-1]["target_grade"]


@_needs_db
def test_the_tool_payload_says_how_many_were_left_out(snapshot_db) -> None:
    """不做字符截断：截断一个 JSON 只会得到半个 JSON。"""
    payload = screen_targets(snapshot_db, {"min_net_profit_yuan": 10000000}, limit=20).as_tool_result()

    assert payload["matched"] == 48
    assert payload["returned_count"] == 20
    assert "另有 28 家未返回" in payload["note"]
    assert len(payload["returned"]) == 20


@_needs_db
def test_a_returned_row_is_a_short_summary_carrying_the_conditions_values(snapshot_db) -> None:
    payload = screen_targets(
        snapshot_db,
        {"acceptable_regions_json": JIANGSU, "min_net_profit_yuan": 10000000},
        limit=3,
    ).as_tool_result()

    digest = payload["returned"][0]
    assert set(digest) <= {"id", "name", "grade", "industry", "region", "current_net_profit_yuan"}
    # 行业不再是一个筛选条件，但**仍然出现在候选摘要里** —— 主 Agent 要靠它
    # 和业务摘要判业务匹配。退役的是「能不能筛」，不是「看不看得见」。
    assert "江苏省" in digest["region"]
    # 数字原样取出，不做格式化推断 —— 格式化在写作环节统一做。
    assert isinstance(digest["current_net_profit_yuan"], float)
    assert digest["current_net_profit_yuan"] >= 10000000
    assert "business_summary" not in digest


@_needs_db
def test_a_retired_condition_reports_instead_of_emptying_the_pool(snapshot_db) -> None:
    """旧版提示词还会吐 industries_json，它必须被如实忽略而不是收窄候选。

    静默丢弃比报错危险：模型以为筛过了，实际那一条从来没生效。
    """
    result = screen_targets(snapshot_db, {"industries_json": ["制造与工业"]}, count_only=True)

    assert result.matched == 69
    assert result.ignored


# -- 业务扫描：行业条件退役之后的补偿 -------------------------------------


def test_business_scan_returns_summaries_instead_of_numbers() -> None:
    """0828 判决一之后正向初筛没有行业条件了，一条只写了数字门槛的需求会召回
    接近全库。20 条的上限会把它截成任意 20 家 —— **该推的连被看见的机会都没有**。

    business_scan 是那个缺口的补偿：换一种返回形状，每条只回业务摘要，
    上限抬到 300，供主 Agent 做首轮语义筛。
    """
    from backend.app.services.screening_sql import MAX_BUSINESS_SCAN_LIMIT, ScreeningResult

    row = {
        "id": "t-1",
        "target_name": "苏州某精密制造",
        "target_grade": "B",
        "location_province": "江苏省",
        "location_city": "苏州市",
        "industry_pairs_json": [{"l1": "制造与工业", "l2": "专用设备"}],
        "business_summary": "做半导体设备精密结构件。",
        "main_products_text": "腔体、载台",
        "current_net_profit_yuan": 12_000_000,
    }
    scan = ScreeningResult(
        conditions={"min_net_profit_yuan": 10_000_000},
        matched=1,
        excluded_by_condition={},
        rows=[row],
        ignored=[],
        limit=MAX_BUSINESS_SCAN_LIMIT,
        offset=0,
        count_only=False,
        business_scan=True,
    ).as_tool_result()

    digest = scan["returned"][0]
    assert digest["business_summary"] == "做半导体设备精密结构件。"
    assert digest["main_products"] == "腔体、载台"
    # 行业不再是筛选维，但**仍然看得见** —— 主 Agent 要靠它和业务摘要判方向。
    assert "制造与工业" in digest["industry"]
    # 财务数字不进业务扫描：那一步判的是业务匹配，数字已经由 SQL 做过了，
    # 带上它们只会把 300 条撑成读不完的体积。
    assert "current_net_profit_yuan" not in digest
    assert "首轮" in scan["scan_note"] or "业务摘要" in scan["scan_note"]

    plain = ScreeningResult(
        conditions={"min_net_profit_yuan": 10_000_000},
        matched=1,
        excluded_by_condition={},
        rows=[row],
        ignored=[],
        limit=20,
        offset=0,
        count_only=False,
    ).as_tool_result()

    # 普通初筛的摘要刻意不带业务摘要（主 Agent 在那一步只判「够不够、要不要再筛」）。
    assert "business_summary" not in plain["returned"][0]
    assert "scan_note" not in plain


def test_the_business_scan_columns_are_actually_projected() -> None:
    """两种返回形状共用同一条 SQL，所以业务两列必须在投影里 ——
    漏了不会报错，只会让每条摘要都是空的。"""
    from backend.app.services.screening_sql import ROW_COLUMNS

    assert "business_summary" in ROW_COLUMNS
    assert "main_products_text" in ROW_COLUMNS


def test_every_clause_reads_the_column_it_declared() -> None:
    """生成的 SQL 必须真的打在 target_column 上。

    这条守卫是被一个实际发生的缺陷逼出来的：overlap / not_overlap 原来写死了
    行业路径（industry_pairs_json 的 {l1,l2} 对象数组），于是 0817 接线的两个
    扁平数组字段——可接受交易结构、不接受的重大风险——**静默生成了打在
    industry_pairs_json 上的 SQL**。两个方向的后果都不报错：
    overlap 恒不命中（候选池恒空）、not_overlap 恒命中（条件恒真）。

    「筛出来必然为空且不报错」正是这套契约最该防的一类事故，而当时全部
    21 个用例在改坏之后依然全绿。
    """
    samples = {
        "number": 1.0,
        "boolean": True,
        "region_list": [{"province": "江苏省"}],
    }
    for field in SCREENING_FIELDS:
        if field.value_type == "enum":
            value = field.enum_values[0]
        elif field.value_type == "enum_list":
            value = [field.enum_values[0]]
        else:
            value = samples[field.value_type]
        clause = build_clause(field, value, 0)
        declared = {
            part.strip().split(".")[0]
            for chunk in field.target_column.split(",")
            for part in chunk.split("/")
        }
        # 判的是「只读声明过的列」而不是「每一列都读到」：region_any 按 constraint
        # 实际填到的层级展开，只给了省就只出省，那是设计使然。
        # region_none 的缺失恒 "false"（排除类条件不参与缺失统计），
        # 那一条不读任何列也是对的，所以只验它的命中 SQL。
        sqls = [clause.sql] + ([] if clause.missing_sql == "false" else [clause.missing_sql])
        for sql in sqls:
            touched = set(re.findall(r"st[.]([a-z_0-9]+)", sql))
            assert touched, f"{field.column} 生成的 SQL 没有读任何标的列：{sql}"
            assert touched <= declared, (
                f"{field.column} 声明比对 {sorted(declared)}，"
                f"生成的 SQL 却读了 {sorted(touched - declared)}：{sql}"
            )
