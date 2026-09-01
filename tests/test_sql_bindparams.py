"""每个 `text(...).bindparams(...)` 声明的名字，都必须在语句里真的出现。

**这是一类没有任何静态检查能拦住的 bug。** SQLAlchemy 的
`TextClause.bindparams()` 对不存在的名字直接抛 `ArgumentError`，而这些
`text()` 全是在**请求期**构造的 —— 于是表现是那个接口每一次调用都 500，
而代码能 import、能通过 lint、能通过所有不打数据库的单测。

已经发生过两次，方向相反：

- **018**：加 `unacceptable_risk_flags_json` 时接了 params 与插入列、
  **漏了 `type_=JSONB` 声明**，Python 的 `[]` 被适配成 Postgres 数组写进
  jsonb 列，类型不匹配 → 新建买家需求每次 500。
- **0828（12ee8b5）**：加 `intent_business_tags_json` /
  `acceptable_regions_json` / `excluded_regions_json` 三个新列时，
  参数字典与 `bindparams()` 都加了、**唯独漏了 insert 的列与值清单** →
  同一个接口从 0828 上线一直炸到 0901 才被人点到。三天里没有任何告警。

所以守卫必须是结构性的，不是针对某个字段的。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SOURCE_DIRS = (
    REPO / "backend" / "app" / "api" / "routes",
    REPO / "backend" / "app" / "services",
    REPO / "backend" / "app" / "jobs" / "handlers",
)

# `text(` 之后到与之配对的 `)` 之前是语句，紧跟的 `.bindparams(` 到它的配对
# `)` 之间是声明。正则做不了括号配对，所以用扫描器。
_BINDPARAM_NAME = re.compile(r'bindparam\(\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']')
_PLACEHOLDER = re.compile(r"(?<!\\):([A-Za-z_][A-Za-z0-9_]*)")


def _matching(source: str, open_index: int) -> int:
    """返回与 source[open_index] 这个左括号配对的右括号下标。

    跳过字符串字面量（含三引号）—— SQL 正文里满是括号，不跳过就配错。
    """
    depth = 0
    i = open_index
    length = len(source)
    while i < length:
        char = source[i]
        if char in "\"'":
            triple = source[i : i + 3]
            if triple in ('"""', "'''"):
                end = source.find(triple, i + 3)
                i = length if end < 0 else end + 3
                continue
            quote = char
            i += 1
            while i < length and source[i] != quote:
                i += 2 if source[i] == "\\" else 1
            i += 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _text_bindparams_pairs(source: str) -> list[tuple[int, str, list[str]]]:
    """找出所有 `text(...)....bindparams(...)`，返回 (行号, 语句正文, 声明的名字)。"""
    pairs: list[tuple[int, str, list[str]]] = []
    for match in re.finditer(r"\btext\(", source):
        open_index = match.end() - 1
        close_index = _matching(source, open_index)
        if close_index < 0:
            continue
        statement = source[open_index + 1 : close_index]
        # text(...) 之后可能接 .bindparams(...)，中间允许换行与空白。
        tail = source[close_index + 1 :]
        bind_match = re.match(r"\s*\.\s*bindparams\(", tail)
        if not bind_match:
            continue
        bind_open = close_index + 1 + bind_match.end() - 1
        bind_close = _matching(source, bind_open)
        if bind_close < 0:
            continue
        declaration = source[bind_open + 1 : bind_close]
        names = _BINDPARAM_NAME.findall(declaration)
        if names:
            line = source.count("\n", 0, match.start()) + 1
            pairs.append((line, statement, names))
    return pairs


def _sources() -> list[Path]:
    files: list[Path] = []
    for directory in SOURCE_DIRS:
        files.extend(sorted(directory.rglob("*.py")))
    return [path for path in files if "__pycache__" not in path.parts]


@pytest.mark.parametrize("path", _sources(), ids=lambda p: p.name)
def test_every_declared_bindparam_exists_in_its_statement(path: Path) -> None:
    """声明了但语句里没有 → `ArgumentError`，接口每次都 500。

    这条守的正是 0828 那次事故：三个新列加进了 bindparams 与参数字典，
    却没加进 insert 的列与值清单，新建买家需求因此炸了三天。
    """
    source = path.read_text(encoding="utf-8")
    problems: list[str] = []
    for line, statement, names in _text_bindparams_pairs(source):
        # 只查**字符串字面量**的语句。两类跳过：
        #   1. `text(statement.format(...))` —— 正文在运行时才拼出来，
        #      字面量里当然找不到 :name（update_logs 的 extra_ids 就是这种）；
        #   2. f-string 拼进来的列清单（如 {_SCENARIO_VALUE_SQL}）—— 展开后
        #      才有 :name，它们由各自模块的派生常量保证一致。
        if '"' not in statement and "'" not in statement:
            continue
        if "{" in statement and "}" in statement:
            continue
        placeholders = set(_PLACEHOLDER.findall(statement))
        missing = [name for name in names if name not in placeholders]
        if missing:
            problems.append(f"{path.name}:{line} 声明了但语句里没有：{missing}")
    assert not problems, "\n".join(problems)


def test_the_scanner_actually_catches_the_0828_shape() -> None:
    """守卫本身要能抓到那个形状 —— 抓不到的守卫比没有更糟。

    这里重放 0828 的真实形状：insert 的列与值清单里没有那三列，
    而 bindparams 里有。
    """
    broken = '''
    row = db.execute(
        text(
            """
            insert into buyer_intent (team_id, intent_name)
            values (:team_id, :intent_name)
            returning id
            """
        ).bindparams(
            bindparam("intent_business_tags_json", type_=JSONB),
        ),
        params,
    )
    '''
    pairs = _text_bindparams_pairs(broken)

    assert len(pairs) == 1, "扫描器没认出 text(...).bindparams(...) 这个形状"
    _, statement, names = pairs[0]
    placeholders = set(_PLACEHOLDER.findall(statement))
    assert names == ["intent_business_tags_json"]
    assert "intent_business_tags_json" not in placeholders


def test_the_scanner_does_not_cry_wolf_on_a_correct_statement() -> None:
    """正确的形状不能报错，否则这条守卫会被下一个人关掉。"""
    fine = '''
    db.execute(
        text("""insert into t (a, b) values (:a, :b)""").bindparams(
            bindparam("b", type_=JSONB),
        ),
        params,
    )
    '''
    line, statement, names = _text_bindparams_pairs(fine)[0]
    assert names == ["b"]
    assert "b" in set(_PLACEHOLDER.findall(statement))


def test_the_buyer_intent_create_insert_is_internally_consistent() -> None:
    """新建买家需求这一条单独再钉一遍：列数、值数、绑定三者对齐。

    它是全库最长的 insert（60 列），也是**唯一一条炸过两次的** ——
    通用扫描器管「声明的名字存不存在」，这条管「列和值有没有错位」。
    错位不报错：SQL 照跑，只是把 A 列的值写进了 B 列。
    """
    import inspect

    from backend.app.api.routes.buyer_intents import create_buyer_intent

    source = inspect.getsource(create_buyer_intent)
    columns_block = re.search(r"insert into buyer_intent \((.*?)\)\s*\n\s*values", source, re.S)
    values_block = re.search(r"values\s*\((.*?)\n\s*\)\n", source, re.S)
    assert columns_block and values_block

    columns = [item.strip() for item in columns_block.group(1).split(",") if item.strip()]
    values = [
        item.strip().lstrip(":")
        for item in values_block.group(1).replace("\n", " ").split(",")
        if item.strip()
    ]

    assert len(columns) == len(values), f"列 {len(columns)} 个、值 {len(values)} 个，数量不等"
    mismatched = [(a, b) for a, b in zip(columns, values) if a != b]
    assert not mismatched, f"列与占位符错位：{mismatched}"

    declared = _BINDPARAM_NAME.findall(source)
    assert declared, "这条 insert 应该有 JSONB 绑定声明"
    assert not [name for name in declared if name not in set(values)], (
        f"声明了但 insert 里没有：{[n for n in declared if n not in set(values)]}"
    )
