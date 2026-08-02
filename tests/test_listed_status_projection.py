"""可接受上市状态投影回旧单值字段时，不能把「排除」写成「不限」。

回归背景：两段式解析上线后，规范化阶段开始输出多值的
acceptable_listed_status_json（如「非上市 + IPO 辅导期」，明确排除已上市）。
旧投影是 `len == 1 ? values[0] : "any"`，于是这条需求在界面上显示成
「上市状态：不限」—— 正好是买家排除掉的那一项。
"""

from __future__ import annotations

from backend.app.api.routes.buyer_intents import _legacy_listed_status
from backend.app.services.listed_status import legacy_listed_status


def test_single_choice_projects_to_itself() -> None:
    assert legacy_listed_status(["unlisted"]) == "unlisted"
    assert legacy_listed_status(["pre_ipo"]) == "pre_ipo"


def test_excluding_listed_is_not_unlimited() -> None:
    # 买家：非上市或辅导期都行，已上市不看。这不是「不限」。
    assert legacy_listed_status(["unlisted", "pre_ipo"]) == "unknown"


def test_accepting_everything_is_unlimited() -> None:
    assert legacy_listed_status(["listed", "unlisted", "pre_ipo"]) == "any"


def test_empty_says_nothing() -> None:
    assert legacy_listed_status([]) == "unknown"


def test_api_route_uses_the_same_projection() -> None:
    # 解析侧和 API 侧投影不一致，同一条需求经人工编辑后就会换个显示值。
    for statuses in ([], ["unlisted"], ["unlisted", "pre_ipo"], ["listed", "unlisted", "pre_ipo"]):
        assert _legacy_listed_status(statuses) == legacy_listed_status(statuses)
