"""自由业务标签的归一（0828 建）。

`buyer_intent.intent_business_tags_json` 与 `buyer_party.business_tags_json` 是
同构的**自由标签**列：不过行业字典，写的是买家自己说的细分主业。

这里刻意**只做形状归一**（去空白、去空值、去重、限长），不做任何词表映射 ——
过字典正是 0828 判决一要下线的东西。行业字典只有 16 个一级行业，接不住
「薄膜电容器」「线控底盘」「固态电池」这类细分方向，而字典外的词写进筛选列
等于没写：页面上看着有筛选条件，实际把全部标的挡在门外。

这段逻辑原来散在两处：`buyer_intent_industry.py`（已随字典一起删除）与
`business_update.py` 里一段内联的 `industry_focus_tags_json` 清洗。两处并存的
后果是「带不带附件」会决定标签要不要去重（2026-08-01 实测过同一类问题），
所以这一轮收成一份。
"""

from __future__ import annotations

from typing import Any

# 上限是防御性的，不是业务规则：模型偶尔会把整段业务描述拆成几十个碎词倒进来，
# 那既撑爆卡片体积又没有信息量。买家主体那边提示词里写的是「5 个以内」。
MAX_BUSINESS_TAGS = 50
MAX_BUSINESS_TAG_CHARS = 80


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
