"""买家主体改名的两条保护。API 与后台任务调同一个函数。

改名和改别的字段不是一回事。其他字段写错了看得见、改回来也便宜；
名称写错了影响该主体的**所有**关联需求、撮合关系和搜索，**而且不会报错**，
只会让人找不到东西。

所以这里管两件事：

1. **旧名自动进 aliases_json。** 顾问输入「北控」，AI 改成
   「北京控股集团有限公司」，若旧名不留，顾问下次搜「北控」就搜不到自己建的
   买家。dedup-check 与 suggestions 本来就查别名（精确名 → 别名 → ilike 三级），
   append 进去即保住搜索路径。
2. **非人工来源的改名要显式确认。** 解析与调研节点（下一单）拿到新名字时
   不能直接落库，必须走复核。这条路在这里留出来：调用方传 source="parse"
   而不带 confirmed 时抛 BuyerPartyNameChangeRequiresReview，由它去建
   extracted_action 等人确认，而不是静默覆盖。
"""

from __future__ import annotations

# 人工改名就是人在详情页上按下保存，那本身就是确认。其余来源都要复核。
NAME_CHANGE_REVIEW_SOURCES = frozenset({"parse", "research"})


class BuyerPartyNameChangeRequiresReview(ValueError):
    """非人工来源想改买家名称，但没有带确认。"""


def plan_buyer_party_rename(
    *,
    current_name: str,
    current_aliases: list[str],
    new_name: str,
    source: str = "manual",
    confirmed: bool = False,
) -> tuple[str, list[str]]:
    """返回 (要落库的名称, 要落库的别名列表)。

    名称未变时原样返回，别名不动 —— 大小写与空白的差异不算改名，
    否则每次保存都会往别名里塞一条只差空格的重复项。
    """
    stripped = new_name.strip()
    if not stripped:
        raise ValueError("buyer_name must not be empty")

    aliases = list(dict.fromkeys(alias.strip() for alias in current_aliases if alias and alias.strip()))
    if stripped.casefold() == current_name.strip().casefold():
        return stripped, aliases

    if source in NAME_CHANGE_REVIEW_SOURCES and not confirmed:
        raise BuyerPartyNameChangeRequiresReview(
            f"Renaming a buyer party from {source} requires explicit confirmation: "
            f"{current_name!r} -> {stripped!r}"
        )

    old_name = current_name.strip()
    known = {alias.casefold() for alias in aliases}
    if old_name and old_name.casefold() not in known and old_name.casefold() != stripped.casefold():
        aliases.append(old_name)
    return stripped, aliases
