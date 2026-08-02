"""买家需求的行业字段只能带着字典写，两条写入路径都不例外。

回归背景（2026-08-01 生产实测）：带附件新建买家时，`business_update_extractor`
的输出经 `extracted_action_apply` 直接落库，全程不碰行业字典，于是
`industries_json = ["汽车电子零部件","储能与热管理","半导体封装与测试配套","精密模具与自动化装备"]`
四个词一个都不在字典里。这个列用 `industries_json ? :industry` 查，
页面上看着有行业筛选，实际把全部标的都挡在门外。

不带附件的那条路（buyer_intent_parse）一直是过字典的 —— 同一个封闭词表列
有两个写入者、两套政策，松的那个在带附件时先写且赢。
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services import buyer_intent_industry, extracted_action_apply
from backend.app.services.buyer_intent_industry import normalize_buyer_intent_industry_changes

L1_TERMS = {"制造与工业", "能源", "信息技术与通信", "医药与健康"}
L2_TERMS = ["汽车零部件", "储能", "半导体与集成电路", "高端装备"]
# 字典里 L2 的归属，resolve_l1 对 L1 和 L2 都能答。
L2_PARENT = {
    "汽车零部件": "制造与工业",
    "储能": "能源",
    "半导体与集成电路": "信息技术与通信",
    "高端装备": "制造与工业",
}


@pytest.fixture
def dictionary(monkeypatch) -> None:
    def _resolve_l1(_db: Any, term: Any) -> str | None:
        text_value = str(term or "").strip()
        if text_value in L1_TERMS:
            return text_value
        return L2_PARENT.get(text_value)

    monkeypatch.setattr(buyer_intent_industry, "resolve_l1", _resolve_l1)
    monkeypatch.setattr(
        buyer_intent_industry,
        "normalize_l1_values",
        lambda _db, values, *, fallback_unmapped=True: (
            [name for name in dict.fromkeys(_resolve_l1(None, v) for v in values) if name],
            [],
        ),
    )
    monkeypatch.setattr(
        buyer_intent_industry,
        "normalize_l2_values",
        lambda _db, values: (
            [v for v in dict.fromkeys(str(x).strip() for x in values) if v in L2_TERMS],
            [f"industry_l2_unmapped:{v}" for v in values if str(v).strip() not in L2_TERMS],
        ),
    )


def test_dictionary_terms_survive(dictionary) -> None:
    changes = {"industries_json": ["制造与工业", "能源"], "industry_l2_json": ["汽车零部件", "储能"]}

    normalize_buyer_intent_industry_changes(None, changes)

    assert changes["industries_json"] == ["制造与工业", "能源"]
    assert changes["industry_l2_json"] == ["汽车零部件", "储能"]


def test_terms_outside_the_dictionary_never_reach_the_screening_column(dictionary) -> None:
    # 生产实测的那四个词。
    changes = {
        "industries_json": [
            "汽车电子零部件",
            "储能与热管理",
            "半导体封装与测试配套",
            "精密模具与自动化装备",
        ]
    }

    normalize_buyer_intent_industry_changes(None, changes)

    assert "industries_json" not in changes, "字典外的词进了 SQL 筛选列，这条需求会筛掉全部标的"


def test_unmatched_terms_go_to_deep_eval_instead_of_being_dropped(dictionary) -> None:
    changes = {
        "industries_json": ["制造与工业", "汽车电子零部件"],
        "industry_l2_json": ["汽车零部件", "液冷板"],
    }

    normalize_buyer_intent_industry_changes(None, changes)

    # 能对上的留在筛选列。
    assert changes["industries_json"] == ["制造与工业"]
    assert changes["industry_l2_json"] == ["汽车零部件"]
    # 对不上的不丢，进 industry_focus_tags_json（default_effect="deep_eval"）。
    assert set(changes["industry_focus_tags_json"]) == {"汽车电子零部件", "液冷板"}


def test_attachment_path_normalizes_before_writing(monkeypatch) -> None:
    """带附件那条路必须调用同一个规范化函数，而且要在 diff 之前。

    这是本次回归的要害：函数写对了但没接上，行业照样原样落库。
    """
    called: dict[str, Any] = {}

    def _spy(_db: Any, changes: dict[str, Any]) -> list[str]:
        called["changes_at_call"] = dict(changes)
        changes["industries_json"] = ["制造与工业"]
        return ["industry_l1_unmapped:汽车电子零部件"]

    monkeypatch.setattr(extracted_action_apply, "normalize_buyer_intent_industry_changes", _spy)

    seen: dict[str, Any] = {}

    def _fake_diff(original: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
        seen["changes_at_diff"] = dict(changes)
        raise _StopHere

    monkeypatch.setattr(extracted_action_apply, "diff_payload", _fake_diff)
    monkeypatch.setattr(
        extracted_action_apply,
        "_get_buyer_intent_snapshot_or_404",
        lambda _db, _id: {},
    )

    action = {
        "action_type": "buyer_intent_update",
        "target_entity_type": "buyer_intent",
        "target_entity_id": "00000000-0000-0000-0000-0000000000b1",
        "applied_at": None,
        "review_status": "accepted",
        "business_update_id": None,
        "proposed_changes_json": {"industries_json": ["汽车电子零部件"]},
        "id": "00000000-0000-0000-0000-0000000000b2",
    }

    with pytest.raises(_StopHere):
        extracted_action_apply.apply_buyer_intent_update_action(None, action)

    assert called["changes_at_call"]["industries_json"] == ["汽车电子零部件"]
    assert seen["changes_at_diff"]["industries_json"] == ["制造与工业"], (
        "diff 用的还是没过字典的值 —— 规范化接在了错误的位置"
    )


class _StopHere(Exception):
    """在真正写库之前打断，用例只关心规范化有没有发生在 diff 之前。"""
