"""需求信息 tab 的结构守卫（2026-09-01 方案化）。

按源码文本比对，不跑浏览器。守的都是「改错了不报错、只是界面悄悄变回去」的那一类 ——
这些约束没有一条能被 TypeScript 或 eslint 抓到。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "frontend" / "src" / "components" / "BuyerIntentRequirements.tsx"
LIST_PRESENTATION = ROOT / "frontend" / "src" / "features" / "buyers" / "presentation.tsx"
TYPES = ROOT / "frontend" / "src" / "types" / "api.ts"


def test_a_single_scenario_requirement_shows_no_scenario_frame() -> None:
    """40/48 条需求只有一个方案，它们的页面上不该出现「方案」这个词。

    给 83% 的页面套一层视觉嵌套换来的是版式统一，而那点一致性抵不上噪音 ——
    这是 0901 明确拍板过的取舍，不是遗漏。
    """
    content = SOURCE.read_text(encoding="utf-8")

    assert "framed" in content
    assert "if (!framed) return" in content, "单方案必须直接渲染 body，不套方案框"


def test_the_threshold_block_says_that_empty_means_no_filter() -> None:
    """「留空 = 不筛」是全套设计里最容易被顾问理解反的一条。

    读成「漏填了」的后果是顾问去把它补满，而补满等于把候选池筛没 ——
    实测 36 家买家原话里提到地域的 16 家中有 9 家说的是「优先/最好」。
    """
    content = SOURCE.read_text(encoding="utf-8")

    assert "留空 = 不筛" in content
    assert "不是漏填" in content
    # 偏好的去处必须写在同一处，否则顾问只知道不能填、不知道该填哪。
    assert "其他要求" in content


def test_there_is_no_required_or_preferred_badge_anywhere() -> None:
    """必须/优先在 screening_sql.py 里从来不生效（那是一组纯 AND）。

    角标写着「优先」而 SQL 照硬筛 —— 它在骗人。删掉之后不能有人凭直觉加回来，
    所以这里同时钉住组件、列表页和类型三处。
    """
    for path in (SOURCE, LIST_PRESENTATION):
        content = path.read_text(encoding="utf-8")
        assert "EffectBadge" not in content, f"{path.name} 还有强度角标"
        assert "default_effect" not in content, f"{path.name} 还在读 default_effect"
        assert "effect_editable" not in content

    types = TYPES.read_text(encoding="utf-8")
    assert "effect_editable" not in types
    assert "missing_policy" in types, "缺失策略是留下来的那个，它和强度不是一回事"


def test_the_region_editor_has_no_effect_dropdown() -> None:
    """0901 之前每条地区上挂着「必须 / 优先 / 排除」三态下拉。

    它写的 effect 键从迁移 022 起会被 normalize_buyer_regions **静默吃掉** ——
    顾问在「可接受地区」里给一条选「排除」，得到的仍然是可接受地区，
    跟他选的正好相反，而且不报错。
    """
    content = SOURCE.read_text(encoding="utf-8")

    assert "RegionConstraintsEditor" in content
    assert "<option value=\"excluded\">" not in content
    assert "effect: 'preferred'" not in content
    assert "{ province: '' }" in content, "新增地区项不该再带 effect"


def test_the_raw_requirement_text_is_not_repeated_in_this_tab() -> None:
    """原始需求材料在「更新记录」tab 里看，这里不重复一份。"""
    content = SOURCE.read_text(encoding="utf-8")

    # 判「有没有渲染」而不是「有没有提到」：组件顶部的注释里写着这条决定的
    # 理由，那句话应该留着，删掉理由才是下一个人把它加回来的原因。
    assert "intent.raw_requirement_text" not in content
    assert "{intent.raw_requirement_text" not in content


def test_deleting_the_last_scenario_is_blocked() -> None:
    """方案是门槛唯一的住处，删掉最后一个等于把这条需求的要求全删了。

    删了不报错，表现是这条需求从此对谁都通过 —— 方向恰好是最贵的那一边。
    """
    content = SOURCE.read_text(encoding="utf-8")

    assert "scenarios.length <= 1" in content


def test_only_adding_a_scenario_is_offered_not_splitting() -> None:
    """只提供「新增方案」。

    拆分要把现有字段分配到两边，那需要理解原文 —— 重跑解析做得比顾问点几下准。
    """
    content = SOURCE.read_text(encoding="utf-8")

    assert "新增方案" in content
    assert "拆分方案" not in content


def test_the_list_page_reads_scenarios_not_the_retired_intent_columns() -> None:
    """列表页的「关键需求」列必须读方案。

    读需求侧那些退役列的表现是**列表页不报错、只是那一列空了**：
    重跑解析之后新值全在方案上，而列表还在读 bi 上的存量值。
    """
    content = LIST_PRESENTATION.read_text(encoding="utf-8")

    assert "item.scenarios_json" in content
    for retired in (
        "item.intent_business_tags_json",
        "item.acceptable_regions_json",
        "item.excluded_regions_json",
        "item.min_revenue_yuan",
        "item.min_net_profit_yuan",
    ):
        assert retired not in content, f"列表页还在读需求侧的 {retired}"


def test_multiple_scenarios_are_shown_side_by_side_not_collapsed_to_one() -> None:
    """多方案是 OR，列表那一格要把它们并起来显示。

    取最严会漏掉宽档能吃下的标的，取最宽会让顾问以为这个买家什么都收 ——
    两个方向都误导，所以两个都不取。
    """
    content = LIST_PRESENTATION.read_text(encoding="utf-8")

    assert "scenarios.flatMap" in content
    assert "collapseValues" in content
