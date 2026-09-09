"""自由业务标签的归一与契约文案（0828 建，0908 扩到三侧）。

`buyer_party.business_tags_json`、`buyer_intent_scenario.business_tags_json` 与
`seller_target.business_tags_json` 是同构的**自由标签**列：不过行业字典，写的是
这一侧自己说的细分赛道 / 产品品类。

这里刻意**只做形状归一**（去空白、去空值、去重、限长），不做任何词表映射 ——
过字典正是 0828 判决一要下线的东西，0908 标的侧收尾时连字典表一起删了。
行业字典只有 15 个一级行业，接不住「薄膜电容器」「线控底盘」「固态电池」这类
细分方向，而字典外的词写进筛选列等于没写：页面上看着有筛选条件，实际把全部
标的挡在门外。

这段逻辑原来散在两处：`buyer_intent_industry.py`（已随字典一起删除）与
`business_update.py` 里一段内联的 `industry_focus_tags_json` 清洗。两处并存的
后果是「带不带附件」会决定标签要不要去重（2026-08-01 实测过同一类问题），
所以这一轮收成一份。

**契约文案也只有一份**（`business_tags_contract_note`）：三条解析链、两条调研链
的字段契约都引用它。粒度约定改这里，五个节点一起变；各写一份必然漂。
"""

from __future__ import annotations

from typing import Any

# 上限是防御性的，不是业务规则：模型偶尔会把整段业务描述拆成几十个碎词倒进来，
# 那既撑爆卡片体积又没有信息量。数量约定（3~5 个、最多 8 个）由契约文案控制。
MAX_BUSINESS_TAGS = 50
MAX_BUSINESS_TAG_CHARS = 80

# 三侧标签是同一粒度：细分赛道 / 产品品类，与买家方案里「薄膜电容器」「线控底盘」
# 同级。写一级大类没有信息量（阿里云 94 个标的里 52 个的行业就是「制造与工业」），
# 写公司名 / 地名 / 形容词是另一个轴的事，写对方的需求会把两侧的语义搅在一起。
_TAG_SCOPE = {
    "seller_target": ("这家公司自己经营的", "不写买家要什么"),
    "buyer_party": ("买家自己经营的", "不写它想买什么"),
    "buyer_intent_scenario": ("这个方案要买的", "不写买家自己做什么"),
}


def business_tags_contract_note(entity: str) -> str:
    """三侧共用的标签契约句。改这里，解析、更新、调研五个节点的契约一起变。"""
    try:
        scope, forbid = _TAG_SCOPE[entity]
    except KeyError:
        raise ValueError(f"business tags contract does not cover entity {entity!r}") from None
    return (
        f"自由标签数组，不过任何行业字典。写{scope}细分赛道或产品品类"
        "（如「汽车零部件」「PCB」「污水处理运营」「维生素原料药」），名词短语，"
        f"3~5 个、最多 8 个。不写一级大类（制造业、能源、医药）、公司名、地名、形容词，{forbid}。"
    )


def normalize_business_tags(raw: Any) -> list[str]:
    """任意输入 → 去重去空的标签数组。不是数组就返回空。

    单个字符串也认：模型偶尔把一个标签直接当标量给回来，直接丢掉的话
    「这条需求关注什么」会整条消失，而它本来是能救的。
    """
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    tags: list[str] = []
    for value in raw:
        if isinstance(value, (dict, list)):
            continue
        tag = str(value or "").strip()[:MAX_BUSINESS_TAG_CHARS]
        if tag and tag not in tags:
            tags.append(tag)
    return tags[:MAX_BUSINESS_TAGS]


def business_tags_text(raw: Any, limit: int = 5) -> str | None:
    """标签数组 → 给人和模型看的顿号串；空则 None（调用方据此省略键）。

    MCP 三个工具、初筛摘要、搜索文档、全局搜索副标题共用这一种写法。
    """
    tags = normalize_business_tags(raw)
    return "、".join(tags[:limit]) or None
