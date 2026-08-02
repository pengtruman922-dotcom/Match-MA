"""画像栏目按实体分，两侧不能互相通用。

回归背景（2026-08-02 生产实测）：买家的三块「其他」在 normalize 那关按实体校验、
放行了，写库那关 `upsert_profile_section` 却还在拿卖方五栏的常量比对，于是解析
一路跑完两次 LLM 调用、写到最后一步才炸，字段一个都没落库。
"""

from __future__ import annotations

import pytest

from backend.app.registry.indicators import groups_for
from backend.app.services.profile_sections import (
    BUYER_PROFILE_SECTIONS,
    PROFILE_SECTIONS,
    normalize_profile_section_items,
    profile_section_codes,
    render_profile_text,
    upsert_profile_section,
)


def test_codes_are_disjoint_between_entities() -> None:
    seller = set(profile_section_codes("seller_target"))
    buyer = set(profile_section_codes("buyer_intent"))
    assert seller and buyer
    assert not (seller & buyer), "两侧栏目码重叠，合并的标签表就会串"


def test_buyer_codes_match_the_buyer_modules() -> None:
    # 「其他」是模块的一部分，栏目码和模块 key 必须一一对应，
    # 否则前端按 group.section_code 取不到那一块。
    assert set(profile_section_codes("buyer_intent")) == {
        group.section_code for group in groups_for("buyer_intent")
    }


def test_unknown_entity_has_no_sections() -> None:
    assert profile_section_codes("buyer_party") == ()


def test_normalize_rejects_the_other_entitys_code() -> None:
    seller_code = PROFILE_SECTIONS[0][0]
    items, notes = normalize_profile_section_items(
        [{"section_code": seller_code, "content_text": "x"}],
        entity_type="buyer_intent",
    )

    assert items == []
    assert any("unknown_section" in note for note in notes)


def test_write_accepts_a_buyer_code() -> None:
    """写库这关必须和 normalize 那关认同一套码 —— 就是当初漏掉的那一处。"""
    buyer_code = BUYER_PROFILE_SECTIONS[0][0]
    calls: list[str] = []

    class _Db:
        def execute(self, *_args, **_kwargs):
            calls.append("execute")
            raise _StopBeforeSql

    with pytest.raises(_StopBeforeSql):
        upsert_profile_section(
            _Db(),
            entity_type="buyer_intent",
            entity_id="00000000-0000-0000-0000-0000000000c1",
            section_code=buyer_code,
            info_status="filled",
            content_text="标准化不了的说法",
        )
    assert calls, "校验就把买家栏目挡下了，根本没走到写库"


def test_write_still_rejects_a_code_from_the_other_entity() -> None:
    seller_code = PROFILE_SECTIONS[0][0]
    with pytest.raises(ValueError, match="buyer_intent"):
        upsert_profile_section(
            object(),
            entity_type="buyer_intent",
            entity_id="00000000-0000-0000-0000-0000000000c1",
            section_code=seller_code,
            info_status="filled",
            content_text="x",
        )


def test_render_uses_the_entitys_own_sections() -> None:
    buyer_code = BUYER_PROFILE_SECTIONS[0][0]
    sections = {buyer_code: {"info_status": "filled", "content_text": "偏好排他合作协议"}}

    assert "偏好排他合作协议" in render_profile_text(sections, entity_type="buyer_intent")
    # 同一份数据按卖方栏目渲染应当什么都取不到，两边不该互相看见。
    assert render_profile_text(sections, entity_type="seller_target") == ""


class _StopBeforeSql(Exception):
    """校验通过后立刻打断，用例只关心校验放不放行。"""
