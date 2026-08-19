"""The registry is the single source; these guard it against reality.

The parse and research whitelists now derive from the registry (common.py and
research_apply.py read writable_columns/writable_enum_values), so there is no
separate hand-list to reconcile — the registry IS the definition. What still
needs guarding is the registry against the sources it does NOT yet own: the
frontend screening badges (until R3a-2 switches the panel), the columns the
scorer reads, the real DB columns, and the DB enum check constraints.
"""

import re
from pathlib import Path

from backend.app.jobs.handlers.common import (
    BUYER_INTENT_CHANGE_FIELDS,
    BUYER_INTENT_ENUM_FIELDS,
    SELLER_TARGET_CHANGE_FIELDS,
    SELLER_TARGET_ENUM_FIELDS,
)
from backend.app.registry.indicators import (
    BUYER_INTENT_INDICATORS,
    SELLER_TARGET_INDICATORS,
    GROUPS,
    indicators_for,
    multi_value_enum_values,
    screening_columns,
    seller_target_fact_columns,
    writable_columns,
    writable_enum_values,
)
from backend.app.api.routes.meta import _section_label
from backend.app.services.profile_sections import PROFILE_SECTION_HINTS
from backend.app.services.research_apply import RESEARCH_STRUCTURED_FIELDS

REPO = Path(__file__).resolve().parents[1]
MIGRATIONS = REPO / "database/migrations"
BASELINE = REPO / "database/migrations/001_baseline.sql"
R4A_MIGRATION = REPO / "database/migrations/002_target_information_model.sql"
R5_MIGRATION = REPO / "database/migrations/004_information_refinement.sql"
RESEARCH_PERIOD_MIGRATION = REPO / "database/migrations/009_research_financial_period_guard.sql"
BUYER_CONTRACT_MIGRATION = REPO / "database/migrations/011_buyer_intent_condition_contract.sql"
TARGET_FACTS_MIGRATION = REPO / "database/migrations/015_target_risk_and_structure_facts.sql"
GRADE_MIGRATION = REPO / "database/migrations/017_entity_grade.sql"
BUYER_CLOSED_SETS_MIGRATION = REPO / "database/migrations/018_buyer_condition_closed_sets.sql"


def test_consumers_derive_from_the_registry() -> None:
    # 白名单已改为派生，这里确认「派生」这条线没被谁悄悄改回硬列表。
    assert SELLER_TARGET_CHANGE_FIELDS == writable_columns("parse")
    assert set(RESEARCH_STRUCTURED_FIELDS) == writable_columns("research")
    assert SELLER_TARGET_ENUM_FIELDS == writable_enum_values()
    assert BUYER_INTENT_CHANGE_FIELDS == writable_columns("parse", "buyer_intent")
    assert BUYER_INTENT_ENUM_FIELDS == writable_enum_values("buyer_intent")


def test_buyer_intent_indicators_are_real_columns() -> None:
    sql = BASELINE.read_text(encoding="utf-8")
    body = re.search(r"create table buyer_intent \((.*?)\n\);", sql, re.S)
    assert body, "baseline 未找到 buyer_intent 建表块"
    columns = set(re.findall(r"^\s+([a-z_0-9]+)\s", body.group(1), re.M))
    missing = {ind.column for ind in BUYER_INTENT_INDICATORS} - columns
    post_baseline = {
        "acceptable_listed_status_json": BUYER_CONTRACT_MIGRATION,
        "condition_effects_json": BUYER_CONTRACT_MIGRATION,
        "unacceptable_risk_flags_json": BUYER_CLOSED_SETS_MIGRATION,
        "intent_grade": GRADE_MIGRATION,
    }
    assert missing <= set(post_baseline), (
        f"注册表引用了 buyer_intent 不存在的列：{sorted(missing - set(post_baseline))}"
    )
    for column in missing - {"intent_grade"}:
        migration_sql = post_baseline[column].read_text(encoding="utf-8")
        assert f"add column if not exists {column} jsonb" in migration_sql
    assert "add column if not exists intent_grade text not null default 'C'" in (
        GRADE_MIGRATION.read_text(encoding="utf-8")
    )
    assert indicators_for("buyer_intent") is BUYER_INTENT_INDICATORS


def _constraint_value_sets(sql: str, column: str) -> list[set[str]]:
    """这一份 SQL 里，该列的 check 约束分别接受哪些取值。

    两种写法都认：baseline 的 `col = ANY (ARRAY['a'::text, …])`，
    以及后续迁移手写的 `col in ('a', …)`。

    必须锚在 `check (` 上、且中间不跨语句（`[^;]`）：光看 `col in (…)` 会把
    数据迁移里的 `where listed_status in (…)` 当成约束，于是「最后提到这一列的
    文件」指向一个根本没定义约束的迁移，守卫误报。

    列名前的 `(?<![a-z_])` 同样是必须的：没有它，`status` 会匹配上
    `listed_status` / `review_status` / `information_status` 的约束。

    取值要认大写：级别（target_grade / intent_grade）是 A-E，只认小写会让 017
    的约束读成空集，守卫误报「注册表枚举 DB 不接受」。
    """
    pattern = re.compile(
        r"check\s*\([^;]*?(?<![a-z_])" + re.escape(column) + r"\s*(?:=\s*ANY\s*\(ARRAY\[(.*?)\]\)|in\s*\((.*?)\))",
        re.S | re.I,
    )
    return [
        set(re.findall(r"'([A-Za-z_]+)'", any_body or in_body))
        for any_body, in_body in pattern.findall(sql)
    ]


def _db_accepts(column: str, values: set[str]) -> bool | None:
    """DB 最终是否接受这些取值。

    只看 baseline 会漏判：约束被后续迁移重建过的列（上市地在 016 换成了交易所
    闭集），拿 baseline 的旧取值去比必然对不上。所以按迁移编号顺序扫，
    **最后提到这一列的那份文件说了算** —— 那就是线上的实际约束。

    同名列可能出现在多张表（status 尤其），所以在选中的那份文件里，
    只要有一个约束是超集就算通过。

    Returns None when no migration constrains the column at all.
    """
    latest: list[set[str]] | None = None
    for path in [BASELINE, *sorted(MIGRATIONS.glob("0*.sql"))]:
        sets = _constraint_value_sets(path.read_text(encoding="utf-8"), column)
        if sets:
            latest = sets
    if latest is None:
        return None
    return any(values <= accepted for accepted in latest)


def test_registry_enum_values_valid_for_both_entities() -> None:
    # 注册表声明的枚举取值必须能被对应 DB check 约束接受，否则写入会被 DB 拒。
    for entity in ("seller_target", "buyer_intent"):
        for column, values in writable_enum_values(entity).items():
            accepted = _db_accepts(column, values)
            if accepted is None:
                continue  # 无 DB check 约束的列
            assert accepted, f"{entity}.{column} 注册表枚举含 DB 不接受的值"


def test_the_enum_guard_reads_past_the_baseline() -> None:
    """守卫本身的回归：上市地的约束在 016 被重建过，baseline 里是旧取值。

    如果 _db_accepts 退回只读 baseline，这条会挂 —— 而真正的漂移
    （注册表加了 DB 不认的取值）会变成静默通过。
    """
    assert _db_accepts("listing_market_region", {"sse", "hkex"}) is True
    assert _db_accepts("listing_market_region", {"domestic"}) is False


def test_closed_list_columns_match_their_db_check() -> None:
    """多值枚举列的 check 约束是 jsonb 包含（`<@`），_db_accepts 认不出这种形状。

    这类列的漂移方式很隐蔽：注册表加一个取值、忘了改迁移，结果是解析归一化放行、
    DB 在写入的最后一刻整条打回。所以单独比对一次。
    """
    # 两侧都查：买家侧 0817 起也有闭集多值列（不接受的重大风险、可接受交易结构），
    # 只查标的侧的话，买家侧加取值忘改迁移一样会在写入的最后一刻被 DB 打回。
    sources = {
        "seller_target": (TARGET_FACTS_MIGRATION, multi_value_enum_values()),
        "buyer_intent": (BUYER_CLOSED_SETS_MIGRATION, multi_value_enum_values("buyer_intent")),
    }
    for entity, (path, columns) in sources.items():
        entity_sql = path.read_text(encoding="utf-8")
        for column, values in columns.items():
            block = re.search(
                rf"constraint chk_{entity}_{column}\b.*?<@ '\[(.*?)\]'::jsonb", entity_sql, re.S
            )
            assert block, f"{column} 在迁移里没有元素级 check 约束"
            assert values == set(re.findall(r'"([a-z_]+)"', block.group(1))), (
                f"{column} 注册表枚举与 DB check 约束不一致"
            )
    sql = TARGET_FACTS_MIGRATION.read_text(encoding="utf-8")
    # check 约束里不能有子查询（0A000），写了会在 preDeploy 阶段炸掉整次部署。
    for statement in re.findall(r"check \((.*?)\n  \)", sql, re.S):
        assert "select" not in statement.lower(), "check 约束里出现了子查询"


def test_every_indicator_is_a_real_seller_target_column() -> None:
    sql = BASELINE.read_text(encoding="utf-8")
    body = re.search(r"create table seller_target \((.*?)\n\);", sql, re.S)
    assert body, "baseline 未找到 seller_target 建表块"
    columns = set(re.findall(r"^\s+([a-z_0-9]+)\s", body.group(1), re.M))
    missing = {ind.column for ind in SELLER_TARGET_INDICATORS} - columns
    migration_sql = R4A_MIGRATION.read_text(encoding="utf-8")
    refinement_sql = R5_MIGRATION.read_text(encoding="utf-8")
    target_facts_sql = TARGET_FACTS_MIGRATION.read_text(encoding="utf-8")
    post_baseline_columns = {
        "location_province": (migration_sql, "add column location_province text"),
        "location_city": (migration_sql, "add column location_city text"),
        "location_district": (migration_sql, "add column location_district text"),
        "industry_pairs_json": (refinement_sql, "add column industry_pairs_json jsonb"),
        "financial_period_end_date": (
            RESEARCH_PERIOD_MIGRATION.read_text(encoding="utf-8"),
            "add column if not exists financial_period_end_date date",
        ),
        "major_risk_flags_json": (target_facts_sql, "add column if not exists major_risk_flags_json jsonb"),
        "acceptable_transaction_structures_json": (
            target_facts_sql,
            "add column if not exists acceptable_transaction_structures_json jsonb",
        ),
        "main_products_text": (target_facts_sql, "add column if not exists main_products_text text"),
        "stock_code": (target_facts_sql, "add column if not exists stock_code text"),
        "target_grade": (
            GRADE_MIGRATION.read_text(encoding="utf-8"),
            "add column if not exists target_grade text not null default 'C'",
        ),
    }
    assert missing <= set(post_baseline_columns), (
        f"注册表引用了 seller_target 不存在的列：{sorted(missing - set(post_baseline_columns))}"
    )
    for column in missing:
        sql, expected = post_baseline_columns[column]
        assert expected in sql, f"{column} 没有对应的建列迁移"
    for retired in ("industry_primary", "industry_secondary", "registered_province", "registered_city", "headquarter_province", "headquarter_city", "raw_region_text", "region_granularity"):
        assert f"drop column {retired}" in migration_sql
    # 判死的列不能还留在注册表里——注册表是写入白名单的事实源，留着等于允许写。
    assert "drop column if exists operation_stability_status" in target_facts_sql
    assert "operation_stability_status" not in {ind.column for ind in SELLER_TARGET_INDICATORS}


def test_fact_projection_is_derived_everywhere_it_is_read() -> None:
    """标的事实列的 SELECT 投影只能有一份。

    以前信息页 / 解析 / 采纳 / 业务更新各手写一份，加一列漏改一处的表现是
    「字段存进去了但某个页面看不见」，最难查。推荐域的 recommendation_agent_tools
    仍是手写，是有意的：它只取候选摘要需要的子集。（另一处 recommendation_flow
    的手写投影随阶段五 5B 的打分链路一起删掉了。）
    """
    projection = seller_target_fact_columns()
    assert set(projection) >= {ind.column for ind in SELLER_TARGET_INDICATORS}
    assert len(projection) == len(set(projection)), "投影里有重复列名"
    for relative in (
        "backend/app/api/routes/seller_targets.py",
        "backend/app/api/routes/update_logs.py",
        "backend/app/jobs/handlers/seller_target_parse.py",
        "backend/app/services/extracted_action_apply.py",
        "backend/app/services/business_update_flow.py",
    ):
        source = (REPO / relative).read_text(encoding="utf-8")
        assert "seller_target_fact_columns" in source, f"{relative} 没有走派生投影"


def test_every_indicator_group_key_is_declared() -> None:
    group_keys = {group.key for group in GROUPS}
    used = {ind.group for ind in SELLER_TARGET_INDICATORS if ind.group is not None}
    assert used <= group_keys, f"指标引用了未声明的分组：{sorted(used - group_keys)}"


def test_supplement_block_is_titled_by_what_belongs_in_it() -> None:
    """补充栏的标题与提示语跟着栏目走，不是五栏共用一句「其他」。

    共用一句的后果实测过：产业优势这类内容没有明确落点，会随机掉进别的栏
    （水晶光电的产业地位描述落进了当时的「技术与团队·其他」）。
    """
    labels = {group.key: _section_label(group.section_code, group.label) for group in GROUPS}
    assert labels["business_product"] == "产业优势"
    # 栏名只是组名的复述时退回「其他」，否则页面上是组名套组名。
    assert labels["identity"] == "其他"
    assert labels["deal_terms"] == "其他"

    hint = PROFILE_SECTION_HINTS["business_product"]
    assert "产业链位置" in hint and "业务摘要" in hint, "产业优势栏没说清该写什么、不该写什么"
    assert set(PROFILE_SECTION_HINTS) >= {group.section_code for group in GROUPS}


# -- 0817：四项声明的自洽性。schema 生成器读这四项，任何一处不自洽落到推荐上
#    都是「条件静默消失」或「筛出来恒为空」，而且都不报错。


def test_buyer_conditions_have_all_four_declarations() -> None:
    """进初筛的买家条件，四项声明必须齐备。

    少一个 operator，那个条件在推荐里完全不存在；少一个 target_column，
    SQL 生成器不知道拿它比标的哪一列。两种都不会报错。
    """
    broken = [
        indicator.column
        for indicator in indicators_for("buyer_intent")
        if indicator.screening and not (indicator.operator and indicator.target_column)
    ]
    assert not broken, f"screening=True 却缺 operator/target_column：{broken}"

    seller_columns = {indicator.column for indicator in SELLER_TARGET_INDICATORS}
    dangling = [
        (indicator.column, base)
        for indicator in indicators_for("buyer_intent")
        if indicator.target_column
        for base in _target_bases(indicator.target_column)
        if base not in seller_columns
    ]
    assert not dangling, f"target_column 指向不存在的标的列：{dangling}"


def _target_bases(spec: str) -> list[str]:
    """target_column 有四种写法：col、col.key、a/b（现算）、a,b,c（多列）。"""
    return [
        part.strip().split(".")[0]
        for chunk in spec.split(",")
        for part in chunk.split("/")
    ]


def test_seller_screening_matches_who_points_at_it() -> None:
    """标的侧的 screening 只喂信息页那个「筛」角标，所以它撒谎的代价是人的时间：
    顾问按角标决定先补哪个字段，角标错了就补错方向。

    两个方向都要守：标成会筛却没人比对，和有人比对却没标。

    原来「有人比对」还包含旧规则打分器读到的列（`_scorer_reads`，扒
    recommendation_flow 的源码）。阶段五 5B 删掉打分链路后那条来源没有了，
    唯一的比对方就是买家条件的 `target_column` 映射，判据因此变严一档。
    """
    pointed: set[str] = set()
    for indicator in indicators_for("buyer_intent"):
        if indicator.target_column:
            pointed.update(_target_bases(indicator.target_column))

    screening = screening_columns()
    folded = {
        ind.column: ind.fold_into for ind in SELLER_TARGET_INDICATORS if ind.fold_into
    }

    unbacked = {column for column in screening if column not in pointed}
    assert not unbacked, f"标为 screening 却没有任何买家条件或打分维度读它：{sorted(unbacked)}"

    unmarked = {
        column
        for column in pointed
        if column not in screening and folded.get(column) not in screening
    }
    assert not unmarked, f"有买家条件指向却没标 screening：{sorted(unmarked)}"


# 「要求」与「能力」本来就不同轴：买家说 required/preferred，标的答 yes/no/likely，
# requirement_capability 这个算子负责跨轴。加一对必须在这里显式登记 ——
# 这份白名单要挡的正是「随手让两侧枚举漂开」。
CROSS_AXIS_PAIRS = {
    ("requires_relocation", "accepts_relocation"),
    ("requires_return_investment", "accepts_return_investment"),
    ("requires_team_retention", "management_retention_possible"),
}
# 子集差集里允许出现的取值：unknown 是「查过但不确定」，none 是「已核查无风险」，
# 两者都是**状态**不是业务取值 —— 买家没有理由去选它们。
SUBSET_ONLY_CODES = {"unknown", "none"}


def test_paired_enums_are_equal_subset_or_declared_cross_axis() -> None:
    """闭集配对的规则是三档，不是等号。

    写成等号会在有意为之的地方全红（上市状态少一个 unknown、重大风险少一个
    none、三对要求↔能力整个不同轴），然后被人关掉 —— 一个被关掉的守卫
    比没有守卫更糟，因为它看起来还在。
    """
    sellers = {ind.column: ind for ind in SELLER_TARGET_INDICATORS}
    problems: list[str] = []
    for buyer in indicators_for("buyer_intent"):
        if not (buyer.target_column and buyer.enum_options):
            continue
        for base in _target_bases(buyer.target_column):
            seller = sellers.get(base)
            if seller is None or not seller.enum_options:
                problems.append(f"{buyer.column} → {base}：买家有闭集，标的侧没有")
                continue
            if (buyer.column, base) in CROSS_AXIS_PAIRS:
                continue
            buyer_codes = {code for code, _ in buyer.enum_options}
            seller_codes = {code for code, _ in seller.enum_options}
            extra = buyer_codes - seller_codes
            if extra:
                problems.append(f"{buyer.column} → {base}：买家多出标的没有的取值 {sorted(extra)}")
            dropped = seller_codes - buyer_codes
            if dropped - SUBSET_ONLY_CODES:
                problems.append(
                    f"{buyer.column} → {base}：买家漏掉了业务取值 {sorted(dropped - SUBSET_ONLY_CODES)}"
                )
    assert not problems, "闭集配对不合三档规则：\n" + "\n".join(problems)


def test_buyer_field_lists_cover_every_writable_indicator() -> None:
    """买家侧的字段清单有四份，其中三份是手写的。

    加一列漏掉任何一份，表现都不是报错而是「存进去了但某条链路看不见」：
    漏解析白名单 → 模型产出被当成 unsupported_field 丢掉；
    漏采纳白名单 → 业务更新采纳时静默不写；
    漏 JSONB 绑定 → jsonb 列被当字符串写进去。
    这条守卫要的不是「三份清单等于注册表」（它们各自还装着系统列），
    而是「注册表里可写的每一列，三份都覆盖到了」。
    """
    from backend.app.jobs.handlers.buyer_intent_parse import (
        BUYER_INTENT_PARSE_FIELDS,
        BUYER_INTENT_PARSE_JSON_FIELDS,
    )
    from backend.app.services.extracted_action_apply import _allowed_buyer_intent_changes

    writable = writable_columns("parse", "buyer_intent")
    # 解析派生的列不由模型产出，所以不进解析白名单：
    #   preferred_listed_status 由 acceptable_listed_status_json 单向计算
    #   intent_grade / status 走 resolve_grade_pair，不许各写入方自己拼
    derived = {"preferred_listed_status", "intent_grade", "status", "pause_reason"}

    missing_parse = writable - derived - BUYER_INTENT_PARSE_FIELDS
    assert not missing_parse, f"解析白名单漏了：{sorted(missing_parse)}"

    json_columns = {
        ind.column
        for ind in indicators_for("buyer_intent")
        if ind.kind == "json" and "parse" in ind.writable_by
    }
    missing_json = json_columns - BUYER_INTENT_PARSE_JSON_FIELDS
    assert not missing_json, f"JSONB 绑定清单漏了：{sorted(missing_json)}"

    # 采纳白名单是业务更新那条路，它不写摘要以外的系统列，但业务事实列必须全覆盖。
    adopted = set(_allowed_buyer_intent_changes({column: None for column in writable}))
    missing_adopt = writable - derived - adopted - {"raw_requirement_text", "parsed_requirement_json"}
    assert not missing_adopt, f"业务更新采纳白名单漏了：{sorted(missing_adopt)}"
