"""级别与它的「E 细分原因」这一对列的派生规则（施工单 0814）。

这套规则的价值全在边界上：写错任何一条，表现都是「某个标的悄悄退出/回到推荐池」
而不是报错。所以四条核心行为逐条钉住。
"""

import pytest

from backend.app.services.entity_grade import (
    BUYER_GRADE,
    DEFAULT_GRADE,
    SELLER_GRADE,
    normalize_grade,
    normalize_lifecycle_status,
    resolve_grade_pair,
)

ACTIVE_TARGET = {"target_grade": "B", "lifecycle_status": "active"}
SOLD_TARGET = {"target_grade": "E", "lifecycle_status": "sold"}
ACTIVE_INTENT = {"intent_grade": "C", "status": "active"}
PAUSED_INTENT = {"intent_grade": "E", "status": "paused"}


def test_no_grade_claim_writes_nothing() -> None:
    """「没解析出级别就不改」—— 整条规则靠这个空字典成立，不许加任何兜底。"""
    assert resolve_grade_pair(
        SELLER_GRADE,
        {"current_revenue_yuan": 100},
        ACTIVE_TARGET,
        allow_reactivation=False,
    ) == {}


def test_grade_alone_fills_the_reason() -> None:
    assert resolve_grade_pair(
        SELLER_GRADE, {"target_grade": "A"}, ACTIVE_TARGET, allow_reactivation=False
    ) == {"target_grade": "A", "lifecycle_status": "active"}


def test_bare_e_takes_the_weaker_default_reason() -> None:
    """裸 E 默认「已停售」而不是「已售出」：后者是凭空声称一笔交易。"""
    assert resolve_grade_pair(
        SELLER_GRADE, {"target_grade": "E"}, ACTIVE_TARGET, allow_reactivation=False
    ) == {"target_grade": "E", "lifecycle_status": "off_market"}
    assert resolve_grade_pair(
        BUYER_GRADE, {"intent_grade": "E"}, ACTIVE_INTENT, allow_reactivation=False
    ) == {"intent_grade": "E", "status": "paused"}


def test_reason_alone_derives_the_grade() -> None:
    assert resolve_grade_pair(
        SELLER_GRADE, {"lifecycle_status": "sold"}, ACTIVE_TARGET, allow_reactivation=False
    ) == {"target_grade": "E", "lifecycle_status": "sold"}
    assert resolve_grade_pair(
        BUYER_GRADE, {"status": "closed"}, ACTIVE_INTENT, allow_reactivation=False
    ) == {"intent_grade": "E", "status": "closed"}


def test_grade_wins_when_the_pair_contradicts_itself() -> None:
    """级别是结论，原因是注解。让陈旧的「已停售」推翻顾问刚设的 B 是静默降级。"""
    assert resolve_grade_pair(
        SELLER_GRADE,
        {"target_grade": "B", "lifecycle_status": "off_market"},
        SOLD_TARGET,
        allow_reactivation=True,
    ) == {"target_grade": "B", "lifecycle_status": "active"}


def test_ai_can_enter_e_but_never_leave_it() -> None:
    """既有不变式：AI 只能把标的推进 E，拉回在售只能由人做。"""
    assert resolve_grade_pair(
        SELLER_GRADE, {"target_grade": "A"}, SOLD_TARGET, allow_reactivation=False
    ) == {}
    assert resolve_grade_pair(
        SELLER_GRADE, {"lifecycle_status": "active"}, SOLD_TARGET, allow_reactivation=False
    ) == {}
    assert resolve_grade_pair(
        BUYER_GRADE, {"status": "active"}, PAUSED_INTENT, allow_reactivation=False
    ) == {}
    # 人工可以，且必须落到一个具体的 A-D，不留「自动」。
    assert resolve_grade_pair(
        SELLER_GRADE, {"target_grade": "C"}, SOLD_TARGET, allow_reactivation=True
    ) == {"target_grade": "C", "lifecycle_status": "active"}


def test_reactivating_by_reason_alone_lands_on_the_default_grade() -> None:
    """E 不记得自己之前是几级，所以只说「在售」时落到与新建同一个默认。"""
    assert resolve_grade_pair(
        SELLER_GRADE, {"lifecycle_status": "active"}, SOLD_TARGET, allow_reactivation=True
    ) == {"target_grade": DEFAULT_GRADE, "lifecycle_status": "active"}


def test_staying_in_e_keeps_the_existing_reason() -> None:
    """已售出的标的被再次判为 E，不该被默认原因改写成「已停售」。"""
    assert resolve_grade_pair(
        SELLER_GRADE, {"target_grade": "E"}, SOLD_TARGET, allow_reactivation=True
    ) == {"target_grade": "E", "lifecycle_status": "sold"}


def test_illegal_values_write_nothing() -> None:
    for changes in ({"target_grade": "F"}, {"target_grade": None}, {"lifecycle_status": "谁知道"}):
        assert resolve_grade_pair(
            SELLER_GRADE, changes, ACTIVE_TARGET, allow_reactivation=True
        ) == {}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("a", "A"), (" e ", "E"), ("A", "A"), ("F", None), ("", None), (None, None), (3, None)],
)
def test_normalize_grade(raw: object, expected: str | None) -> None:
    assert normalize_grade(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("已售出", "sold"),
        ("已成交", "sold"),
        ("已停售", "off_market"),
        # 「是否还卖=否」沿用既有推断（施工单 0814 §5.1 记为待决项，本轮不改）。
        ("no", "off_market"),
        ("SOLD", "sold"),
        ("在售", "active"),
        ("随便什么", None),
    ],
)
def test_normalize_lifecycle_status(raw: str, expected: str | None) -> None:
    assert normalize_lifecycle_status(raw) == expected
