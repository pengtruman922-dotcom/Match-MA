"""「不接受的重大风险」三态语义的唯一派生点。

买家对重大风险的表态有三种，业务方 0817 明确：**未提及 / 不接受全部 / 不接受特定**。
它们全部由 ``buyer_intent.unacceptable_risk_flags_json`` 一个列表列表达 ——
「不接受全部」落库时展开成全集，「未提及」落成空数组。

这样做的目的是**让 SQL 只有一条路径**：初筛永远是同一个 not_overlap，不需要
分支去判三态。代价是「全部」这个语义必须在写入侧就消解掉，而写入侧不止一处
（解析、业务更新采纳、人工编辑），所以展开逻辑必须单点 —— 否则重演
recommendation_status 那次事故：一列只有一条窄路径正确置位，其余路径静默漂移。

注意方向：本列存的是「**不**接受什么」。标的侧 major_risk_flags_json 存的是
「有什么风险」，两者用 not_overlap 相碰。写反了不会报错，只会把结论倒过来。
"""

from __future__ import annotations

from typing import Any

from backend.app.registry.indicators import indicator_by_column

# 与注册表同源：加一个风险类型只改注册表，这里自动跟随。
ALL_UNACCEPTABLE_RISK_FLAGS: tuple[str, ...] = tuple(
    code for code, _ in (indicator_by_column("buyer_intent", "unacceptable_risk_flags_json").enum_options or ())
)

# 中文与英文的「全部」说法。运行时提示词可编辑，模型给数组、给 "all"、给
# "全部"、给 true 都得接住 —— 归一化的作用就是让这四种落到同一个数组上。
_ALL_ALIASES: frozenset[str] = frozenset(
    {"all", "any", "全部", "所有", "全都不接受", "均不接受", "都不接受", "不接受任何重大风险"}
)

# 模型可能给中文风险名而不是枚举码。标的侧的解析归一化走的是
# handlers/common.py 的 ENUM_VALUE_ALIASES，但那份表按标的列组织，
# 这一列的中文说法（「被执行」「失信被执行人」）在那边没有条目。
_FLAG_ALIASES: dict[str, str] = {
    "litigation": "litigation",
    "涉诉": "litigation",
    "诉讼": "litigation",
    "重大诉讼": "litigation",
    "法律纠纷": "litigation",
    "equity_frozen": "equity_frozen",
    "股权冻结": "equity_frozen",
    "冻结": "equity_frozen",
    "股权质押冻结": "equity_frozen",
    "enforcement": "enforcement",
    "被执行": "enforcement",
    "强制执行": "enforcement",
    "失信被执行人": "enforcement",
    "执行": "enforcement",
    "violation": "violation",
    "违规违法": "violation",
    "违法违规": "violation",
    "行政处罚": "violation",
    "立案": "violation",
    "违规": "violation",
}


def normalize_unacceptable_risk_flags(raw: Any) -> list[str] | None:
    """把模型或人工给的任意形状收敛成一个合法数组。

    返回 ``None`` 表示「这次没有对本列的有效表态」，调用方应当**不写**这一列 ——
    与写入空数组不同：空数组是「明确未提及」这个结论，而 None 是「本次输入里
    没有这件事」。解析链路一律把 None 当作不改。
    """
    if raw is None:
        return None

    # 「不接受全部」的三种给法：布尔真、别名字符串、别名字符串组成的数组。
    if raw is True:
        return list(ALL_UNACCEPTABLE_RISK_FLAGS)
    if raw is False:
        return []

    items: list[Any]
    if isinstance(raw, str):
        items = [raw]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        return None

    normalized: list[str] = []
    for item in items:
        if item is None:
            continue
        text = str(item).strip()
        if not text:
            continue
        if text.lower() in _ALL_ALIASES or text in _ALL_ALIASES:
            return list(ALL_UNACCEPTABLE_RISK_FLAGS)
        code = _FLAG_ALIASES.get(text.lower()) or _FLAG_ALIASES.get(text)
        if code and code not in normalized:
            normalized.append(code)

    # 给了内容但一个都没落进闭集：这是「说了但我们没听懂」，不是「未提及」。
    # 写空数组会把它变成一个我们没有依据的结论，所以不写。
    if items and not normalized:
        return None
    return normalized
