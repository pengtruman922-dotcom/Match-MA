"""买家列表那张 19 列表格的列数一致性。

`table-fixed` + `colgroup` 的表格里，colgroup / thead / tbody 三处列数必须相等。
少一个 `<col>` 的表现不是报错，而是**后面所有列宽整体错位一格**，而冻结列的
sticky 偏移是按声明列宽算的，于是横滚时冻结列会盖住相邻列——看起来像样式 bug，
查起来要一列一列数。`colSpan`（空态与加载态那两行）对不上则是跨度不够，整行塌陷。

前端没有测试栈，所以这条做成对源码的结构断言。
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIST_SOURCE = PROJECT_ROOT / "frontend/src/features/buyers/IntentsList.tsx"


def _between(text: str, start: str, end: str) -> str:
    head = text.index(start)
    return text[head : text.index(end, head)]


def test_the_buyer_table_declares_the_same_number_of_columns_everywhere() -> None:
    source = LIST_SOURCE.read_text(encoding="utf-8")

    colgroup = _between(source, "<colgroup>", "</colgroup>")
    thead = _between(source, "<thead", "</thead>")
    row_source = source[source.index("function IntentRow") :]
    body = _between(row_source, '<tr className="group', "</tr>")

    cols = len(re.findall(r"<col\b", colgroup))
    headers = len(re.findall(r"<th\b", thead))
    cells = len(re.findall(r"<td\b", body))

    assert cols == headers == cells, (
        f"列数对不上：colgroup {cols} 个 <col>、thead {headers} 个 <th>、行 {cells} 个 <td>"
    )

    spans = set(re.findall(r"colSpan=\{(\d+)\}", source))
    assert spans == {str(cols)}, f"空态/加载态的 colSpan 应为 {cols}，实际 {sorted(spans)}"


def test_the_frozen_column_offset_matches_the_declared_widths() -> None:
    """左侧冻结列的 sticky 偏移必须等于它前面那些列的声明宽度之和。

    对不上不会报错，只会在横滚时让冻结列压住相邻列。第一列 w-12 = 3rem = 48px，
    所以第二列必须是 left-12。
    """
    source = LIST_SOURCE.read_text(encoding="utf-8")
    colgroup = _between(source, "<colgroup>", "</colgroup>")
    first_col = re.search(r'<col className="(w-[^"]+)"', colgroup)
    assert first_col is not None and first_col.group(1) == "w-12", (
        f"第一列宽度变了（现在是 {first_col.group(1) if first_col else '未知'}），"
        "第二列的 left-12 要跟着改"
    )
    assert source.count("sticky left-12") == 2, "买家名称列的表头与单元格都要用 left-12"
