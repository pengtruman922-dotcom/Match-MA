"""上市状态的兼容投影。

权威字段是 ``buyer_intent.acceptable_listed_status_json``（可接受的多个状态），
``preferred_listed_status`` 是它的单值旧投影，还在页面和部分查询里用着。
投影规则解析侧和 API 侧必须一致，所以只写在这里一份。
"""

from __future__ import annotations

# 「不限」在业务上就是这三种全收，没有第四种可选状态。
ALL_ACCEPTABLE_LISTED_STATUSES = frozenset({"listed", "unlisted", "pre_ipo"})


def legacy_listed_status(statuses: list[str]) -> str:
    """把可接受清单投影回单值的 ``preferred_listed_status``。

    多选一律回 ``unknown`` 而不是 ``any``：买家说「非上市和辅导期都行、已上市不看」
    时投成 ``any``，界面上就写着「上市状态不限」—— 恰好是买家排除掉的那一项。
    只有三种都收下，才是真的不限。
    """
    if len(statuses) == 1:
        return statuses[0]
    if ALL_ACCEPTABLE_LISTED_STATUSES.issubset(statuses):
        return "any"
    return "unknown"
