"""买家列表的列定义与动态渲染的一致性。

19 列改成可显示/隐藏/拖动之后，列不再写死在表格里，而是由 `intentColumns.ts` 的
列定义驱动。于是要钉的不变量换了一组：列定义里的每一列都得有渲染分支、每一列的
宽度类都得能被换算成像素（min-w 靠它算，算错就是 sticky 偏移错位）、冻结列不能
出现在可隐藏清单里（藏掉买家名整行读不懂）。

前端没有测试栈，所以这些做成对源码的结构断言。
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUYERS_DIR = PROJECT_ROOT / "frontend/src/features/buyers"
COLUMNS_SOURCE = BUYERS_DIR / "intentColumns.ts"
LIST_SOURCE = BUYERS_DIR / "IntentsList.tsx"
MANAGER_SOURCE = BUYERS_DIR / "ColumnManager.tsx"


def _column_keys() -> list[str]:
    source = COLUMNS_SOURCE.read_text(encoding="utf-8")
    table = source[source.index("export const INTENT_COLUMNS") : source.index("export const INTENT_COLUMN_BY_KEY")]
    return re.findall(r"\{\s*key:\s*'([a-zA-Z]+)'", table)


def _column_widths() -> list[str]:
    source = COLUMNS_SOURCE.read_text(encoding="utf-8")
    table = source[source.index("export const INTENT_COLUMNS") : source.index("export const INTENT_COLUMN_BY_KEY")]
    return re.findall(r"width:\s*'([^']+)'", table)


def test_every_declared_column_has_a_render_branch() -> None:
    """列定义里加一列却忘了渲染分支，那一列会整列空白且不报错。"""
    keys = _column_keys()
    assert keys, "没解析到任何列定义"

    cell = LIST_SOURCE.read_text(encoding="utf-8")
    dispatch = cell[cell.index("function IntentCell") :]
    rendered = set(re.findall(r"case '([a-zA-Z]+)':", dispatch))

    missing = [key for key in keys if key not in rendered]
    assert not missing, f"这些列没有渲染分支，会整列空白：{missing}"

    extra = sorted(rendered - set(keys))
    assert not extra, f"渲染分支里有列定义中不存在的列：{extra}"


def test_the_union_type_matches_the_column_table() -> None:
    """联合类型与列表对不上时，多出来的那个键在别处能过类型检查却永远不渲染。"""
    source = COLUMNS_SOURCE.read_text(encoding="utf-8")
    union = source[source.index("export type IntentColumnKey") : source.index("export interface IntentColumnDef")]
    declared = set(re.findall(r"\|\s*'([a-zA-Z]+)'", union))
    # 联合的第一项没有前导竖线
    declared |= set(re.findall(r"=\s*\n\s*\|?\s*'([a-zA-Z]+)'", union))

    assert declared == set(_column_keys()), (
        f"联合类型与列定义不一致：\n  只在类型里：{sorted(declared - set(_column_keys()))}"
        f"\n  只在列表里：{sorted(set(_column_keys()) - declared)}"
    )


def test_every_width_class_can_be_converted_to_pixels() -> None:
    """表格 min-w 按可见列宽度求和算出来；换算不了的类名会退回兜底值。

    退回不会报错，只会让 min-w 偏小 —— 而容器宽于 min-w 时 sticky 不激活、
    列宽也不再等于声明值，冻结列的偏移就不准了。所以宽度类必须都在可换算的形状里。
    """
    unconvertible = [
        width for width in _column_widths()
        if not re.fullmatch(r"w-\d+", width) and not re.fullmatch(r"w-\[\d+px\]", width)
    ]
    assert not unconvertible, (
        f"这些宽度类换算不成像素，min-w 会用兜底值：{unconvertible}"
    )


def test_the_frozen_columns_are_not_manageable() -> None:
    """勾选框、买家名称、操作是冻结列 —— 藏掉或挪走整行就读不懂了。

    做法是让它们根本不出现在列定义里，而不是列出来再禁用：列出来会让人反复去点。
    """
    keys = set(_column_keys())
    for forbidden in ("buyerName", "actions", "select", "checkbox"):
        assert forbidden not in keys, f"冻结列 {forbidden} 不该进可管理列表"

    list_source = LIST_SOURCE.read_text(encoding="utf-8")
    # 三根固定骨架：左冻结两列 + 右冻结一列，都写死在表格里而不是走 columns.map
    assert list_source.count("sticky left-0") >= 2, "勾选框列的表头与单元格都要固定"
    assert list_source.count("sticky left-12") == 2, "买家名称列的表头与单元格都要固定"
    assert list_source.count("sticky right-0") == 2, "操作列的表头与单元格都要固定"


def test_hidden_is_stored_rather_than_visible() -> None:
    """存「隐藏了哪些」而不是「显示哪些」：这样以后新增一列，老用户默认能看见它。

    反过来存的话，新列对所有老用户永远不可见，而且没人会想到去列管理器里找。
    """
    source = COLUMNS_SOURCE.read_text(encoding="utf-8")
    prefs = source[source.index("export interface IntentColumnPrefs") : source.index("const EMPTY_PREFS")]
    assert "hidden: IntentColumnKey[]" in prefs
    assert "visible" not in prefs


def test_column_prefs_survive_a_storage_that_throws() -> None:
    """隐私模式下 localStorage 读写直接抛 —— 不能让列设置把整个列表带崩。"""
    source = COLUMNS_SOURCE.read_text(encoding="utf-8")
    read_fn = source[source.index("export function readColumnPrefs") : source.index("export function writeColumnPrefs")]
    assert "catch" in read_fn, "读偏好没有 try/catch"
    write_fn = source[source.index("export function writeColumnPrefs") : source.index("export function resolveColumns")]
    assert "catch" in write_fn, "写偏好没有 try/catch"


def test_unknown_keys_from_storage_are_filtered_out() -> None:
    """存量偏好里可能有已经改名或删掉的列键，原样吃进来会渲染出空列。"""
    source = COLUMNS_SOURCE.read_text(encoding="utf-8")
    assert "filter(isKey)" in source, "从 localStorage 读回的列键没有逐项校验"


def test_the_manager_offers_a_way_back_to_defaults() -> None:
    """拖乱之后没有回退路径的话，用户只能去清浏览器数据。"""
    assert "resetColumnPrefs" in MANAGER_SOURCE.read_text(encoding="utf-8")
