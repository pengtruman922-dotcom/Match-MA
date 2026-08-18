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

MANUFACTURING = "制造与工业"
HEALTHCARE = "医药与健康"
JIANGSU = [{"province": "江苏省"}]


def _clause(column: str, value, index: int = 0):
    return build_clause(SCREENING_FIELDS_BY_COLUMN[column], value, index)


# -- 算子级：SQL 片段 -----------------------------------------------------


def test_gte_and_lte_compare_the_declared_target_column() -> None:
    assert _clause("min_net_profit_yuan", 10000000).sql == "st.current_net_profit_yuan >= :c0"
    assert _clause("max_debt_ratio", 0.6).sql == "st.current_debt_ratio <= :c0"


def test_in_and_eq_bind_their_values() -> None:
    listed = _clause("acceptable_listed_status_json", ["listed", "pre_ipo"])
    assert listed.sql == "st.listed_status = any(:c0)"
    assert listed.params == {"c0": ["listed", "pre_ipo"]}

    exchange = _clause("listing_market_region", "sse")
    assert exchange.sql == "st.listing_market_region = :c0"


def test_requirement_capability_passes_yes_and_likely() -> None:
    """强度不进 SQL：required 与 preferred 生成的条件完全一样。"""
    clause = _clause("requires_control", True)

    assert clause.sql == "st.can_control = any(:c0)"
    assert clause.params == {"c0": ["yes", "likely"]}


def test_industry_overlap_reads_the_pairs_json_not_the_display_columns() -> None:
    """industry_pairs_json 是唯一事实源，industry_l1/l2 只是派生投影。"""
    clause = _clause("industries_json", [MANUFACTURING])

    assert "jsonb_array_elements(" in clause.sql
    assert "st.industry_pairs_json" in clause.sql
    assert "->> 'l1' = any(:c0)" in clause.sql
    assert "st.industry_l1" not in clause.sql


def test_industry_l2_overlap_reads_the_l2_key() -> None:
    assert "->> 'l2' = any(:c0)" in _clause("industry_l2_json", ["专用设备"]).sql


def test_exclusion_matches_either_level() -> None:
    clause = _clause("excluded_industries_json", ["房地产与建筑"])

    assert clause.sql.startswith("not (")
    assert "->> 'l1'" in clause.sql and "->> 'l2'" in clause.sql


def test_a_flat_array_overlap_does_not_go_through_the_industry_path() -> None:
    """交易结构存的是字符串数组，不是 {l1,l2} 对象数组。

    走错形状不会报错：打在 industry_pairs_json 上的 overlap 恒不命中，候选池恒空。
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
        "region_constraints_json",
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
        "industry_l1": [MANUFACTURING],
        "industry_l2": ["专用设备"],
        "industry_any": [MANUFACTURING],
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
        and not field.target_column.startswith("industry_pairs_json")
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


def test_industry_missing_means_no_industry_recorded_at_all() -> None:
    missing = _clause("industries_json", [MANUFACTURING]).missing_sql

    assert missing.startswith("not exists(")
    assert "->> 'l1', '') <> ''" in missing


def test_region_missing_means_compatible_but_incomplete() -> None:
    """买家要苏州市、标的只录到江苏省，那是数据没录；山东省的标的是真不达标。

    两者不分开，agent 会把一个真门槛当成数据缺口去放宽。
    """
    missing = _clause("region_constraints_json", [{"province": "江苏省", "city": "苏州市"}]).missing_sql

    assert "st.location_province = :c0_0_province or coalesce(st.location_province, '') = ''" in missing
    assert "coalesce(st.location_city, '') = ''" in missing
    assert "location_district" not in missing


# -- 算子级：查询结构 -----------------------------------------------------


def test_the_breakdown_is_one_scan_not_one_query_per_condition() -> None:
    clauses = [
        _clause("industries_json", [MANUFACTURING], 0),
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
        ("行业 overlap", {"industries_json": [MANUFACTURING]}, 21),
        ("行业 overlap（医药）", {"industries_json": [HEALTHCARE]}, 13),
        ("地区 region_any", {"region_constraints_json": JIANGSU}, 20),
        ("净利 gte 1000万", {"min_net_profit_yuan": 10000000}, 48),
        ("净利 gte 3000万", {"min_net_profit_yuan": 30000000}, 28),
        ("行业 + 地区", {"industries_json": [MANUFACTURING], "region_constraints_json": JIANGSU}, 6),
        ("行业 + 净利", {"industries_json": [MANUFACTURING], "min_net_profit_yuan": 10000000}, 16),
        (
            "行业 + 地区 + 净利",
            {
                "industries_json": [MANUFACTURING],
                "region_constraints_json": JIANGSU,
                "min_net_profit_yuan": 10000000,
            },
            6,
        ),
        (
            "再加负债率 ≤ 0.6",
            {
                "industries_json": [MANUFACTURING],
                "region_constraints_json": JIANGSU,
                "min_net_profit_yuan": 10000000,
                "max_debt_ratio": 0.6,
            },
            0,
        ),
    ],
)
def test_snapshot_hit_counts(snapshot_db, label: str, conditions: dict, expected: int) -> None:
    assert _matched(snapshot_db, conditions) == expected, label


@_needs_db
def test_the_relaxation_signal_separates_missing_data_from_a_real_shortfall(snapshot_db) -> None:
    """本阶段的核心验收（施工单 §四 用例 10，条件与期望值原样照搬）。

    6 家里 5 家只是没录负债率，所以该去掉的是负债率而不是净利 —— 这就是 agent
    放宽策略的信息来源。

    **0.6 这个取值本身是错的**，但用例照留：施工单按「0-1 小数」写它，而两侧存的
    都是百分数，所以「全库没有一家 ≤ 0.6」是单位造成的、不是数据状态
    （按 60 算全库有 14 家达标）。正确单位下的同一组条件见
    `test_the_debt_ratio_condition_is_read_as_a_percentage`。
    两条都留着：这一条钉住 marginal 语义与拆分，那一条钉住单位。
    """
    result = screen_targets(
        snapshot_db,
        {
            "industries_json": [MANUFACTURING],
            "region_constraints_json": JIANGSU,
            "min_net_profit_yuan": 10000000,
            "max_debt_ratio": 0.6,
        },
        count_only=True,
    )

    assert result.matched == 0
    assert result.excluded_by_condition["max_debt_ratio"] == {
        "总计": 6,
        "字段为空": 5,
        "确实不达标": 1,
        "去掉后命中": 6,
    }
    # marginal 语义：去掉其余任何一条都还是 0 家，因为负债率那条自己就够杀。
    for column in ("industries_json", "region_constraints_json", "min_net_profit_yuan"):
        assert result.excluded_by_condition[column]["去掉后命中"] == 0, column


@_needs_db
@pytest.mark.parametrize(
    "conditions",
    [
        {"industries_json": [MANUFACTURING]},
        {"min_net_profit_yuan": 10000000, "max_debt_ratio": 0.6},
        {"requires_control": True, "region_constraints_json": JIANGSU},
        {"excluded_industries_json": [MANUFACTURING], "min_revenue_yuan": 50000000},
        {"acceptable_profitability_status_json": ["profitable"]},
        {"transaction_types_json": ["equity_transfer", "merger"]},
        {"unacceptable_risk_flags_json": ["litigation", "violation"], "max_debt_ratio": 60},
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
    result = screen_targets(snapshot_db, {"region_constraints_json": JIANGSU}, count_only=True)

    assert result.excluded_by_condition["region_constraints_json"] == {
        "总计": 49,
        "字段为空": 2,
        "确实不达标": 47,
        "去掉后命中": 69,
    }


@_needs_db
def test_a_flat_array_condition_separates_unrecorded_from_mismatched(snapshot_db) -> None:
    """快照里只有 1 家录了可接受交易结构（股权转让/增资/资产收购），68 家空着。

    走错形状（打在 industry_pairs_json 上）的话这两条会双双变成 0 命中且不报错。
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
def test_the_debt_ratio_condition_is_read_as_a_percentage(snapshot_db) -> None:
    """与上面那条核心用例同一组条件，只把负债率换成正确单位。

    施工单里写的 0.6 是按「0-1 小数」理解的，而两侧存的都是百分数
    （标的侧实测 9.55~75）：60% 要写 60。写 0.6 的结果不是「筛得更严」，
    是**一家也筛不到**且不报错 —— 施工单说的「全库没有一家 ≤ 0.6」其实是
    单位造成的，按 60 算全库有 14 家达标。
    """
    result = screen_targets(
        snapshot_db,
        {
            "industries_json": [MANUFACTURING],
            "region_constraints_json": JIANGSU,
            "min_net_profit_yuan": 10000000,
            "max_debt_ratio": 60,
        },
        count_only=True,
    )

    assert result.matched == 1
    assert result.excluded_by_condition["max_debt_ratio"] == {
        "总计": 5,
        "字段为空": 5,
        "确实不达标": 0,
        "去掉后命中": 6,
    }


@_needs_db
def test_an_excluded_industry_removes_only_the_targets_that_carry_it(snapshot_db) -> None:
    """行业为空的 3 家**通过**排除条件，但它们仍然是「没录行业」。

    所以「缺失」必须限定在没通过的那批里统计，否则恒等式当场破掉。
    """
    result = screen_targets(
        snapshot_db, {"excluded_industries_json": [MANUFACTURING]}, count_only=True
    )

    assert result.matched == 48
    assert result.excluded_by_condition["excluded_industries_json"] == {
        "总计": 21,
        "字段为空": 0,
        "确实不达标": 21,
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
    result = screen_targets(snapshot_db, {"industries_json": [MANUFACTURING]}, limit=20)

    for grade in {row["target_grade"] for row in result.rows}:
        updated = [row["updated_at"] for row in result.rows if row["target_grade"] == grade]
        assert updated == sorted(updated, reverse=True), grade


@_needs_db
def test_e_grade_never_comes_back_whatever_the_conditions(snapshot_db) -> None:
    for conditions in ({}, {"industries_json": [MANUFACTURING]}, {"min_net_profit_yuan": 0}):
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
        {"industries_json": [MANUFACTURING], "min_net_profit_yuan": 10000000},
        limit=3,
    ).as_tool_result()

    digest = payload["returned"][0]
    assert set(digest) <= {"id", "name", "grade", "industry", "region", "current_net_profit_yuan"}
    assert MANUFACTURING in digest["industry"]
    # 数字原样取出，不做格式化推断 —— 格式化在写作环节统一做。
    assert isinstance(digest["current_net_profit_yuan"], float)
    assert digest["current_net_profit_yuan"] >= 10000000
    assert "business_summary" not in digest


@_needs_db
def test_an_industry_outside_the_dictionary_reports_instead_of_emptying_the_pool(snapshot_db) -> None:
    result = screen_targets(snapshot_db, {"industries_json": ["星际贸易"]}, count_only=True)

    assert result.matched == 69
    assert result.ignored


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
        "industry_l1": [MANUFACTURING],
        "industry_l2": ["专用设备"],
        "industry_any": [MANUFACTURING],
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
        for sql in (clause.sql, clause.missing_sql):
            touched = set(re.findall(r"st[.]([a-z_0-9]+)", sql))
            assert touched, f"{field.column} 生成的 SQL 没有读任何标的列：{sql}"
            assert touched <= declared, (
                f"{field.column} 声明比对 {sorted(declared)}，"
                f"生成的 SQL 却读了 {sorted(touched - declared)}：{sql}"
            )
