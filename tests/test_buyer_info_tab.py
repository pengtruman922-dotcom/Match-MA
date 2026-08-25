from pathlib import Path

from backend.app.api.routes.buyer_parties import (
    BUYER_PARTY_OUT_COLUMNS,
    BuyerPartyCreate,
    BuyerPartyOut,
    BuyerPartyUpdate,
)
from backend.app.registry.indicators import buyer_party_fact_columns


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_SOURCE = ROOT / "frontend" / "src" / "components" / "BuyerIntentWorkspace.tsx"


def test_buyer_party_api_exposes_every_registry_fact() -> None:
    """三个 DTO 与出参投影必须覆盖注册表里的每一个买家主体事实列。

    0824 之前详情接口返回 15 个键、业务字段零个 —— 系统里没有任何地方能回答
    「这家买家自己是做什么的」。漏一列的表现不是报错，而是「存进去了但页面
    看不见」，所以按注册表逐列比对而不是抽查几个。
    """
    for field in buyer_party_fact_columns():
        assert field in BuyerPartyCreate.model_fields, f"创建 DTO 漏了 {field}"
        assert field in BuyerPartyUpdate.model_fields, f"更新 DTO 漏了 {field}"
        assert field in BuyerPartyOut.model_fields, f"出参 DTO 漏了 {field}"
        assert field in BUYER_PARTY_OUT_COLUMNS, f"SELECT 投影漏了 {field}"

    # 运营备注不在注册表里（不进任何推荐上下文），但仍要能读能写。
    for field in ("notes", "aliases_json", "status"):
        assert field in BuyerPartyOut.model_fields
        assert field in BUYER_PARTY_OUT_COLUMNS

    payload = BuyerPartyUpdate(contact_info_json={"text": "13800000000"})
    assert payload.model_dump(exclude_unset=True) == {
        "contact_info_json": {"text": "13800000000"},
    }


def test_retired_columns_are_gone_from_the_api() -> None:
    """013 之后又一轮清理：行业两列生产 0%，region_* 已并入 location_*。"""
    for retired in ("industries_json", "industry_l2_json", "region_province", "region_city"):
        assert retired not in BuyerPartyCreate.model_fields
        assert retired not in BuyerPartyUpdate.model_fields
        assert retired not in BuyerPartyOut.model_fields
        assert retired not in BUYER_PARTY_OUT_COLUMNS


def test_buyer_info_tab_renders_the_four_registry_groups() -> None:
    content = WORKSPACE_SOURCE.read_text(encoding="utf-8")

    assert "{ key: 'buyer', label: '买家信息' }" in content
    for group in ("基本信息", "业务信息", "财务信息", "其他"):
        assert f'title="{group}"' in content

    # 中文名与枚举下拉走 /meta/indicators?entity=buyer_party，不在前端硬编码。
    assert "indicatorRegistry.list('buyer_party')" in content
    assert "label('ownership_type'" in content
    assert "options('listed_status')" in content

    # 市值/估值是一个展示位，判断口径与列表页共用一个函数。
    assert "partyMarketValue(party)" in content
    assert "partyMarketValueField(party)" in content

    # 行业对渲染已随删列退役；三级地区选择器复用标的侧的那一个。
    assert "IndustryPairsEditor" not in content
    assert "industries_json" not in content
    assert content.count("<AdministrativeAreaPicker") == 1
    assert "showDistrict={false}" not in content

    assert "editingField === field" in content
    assert "以下均为买家主体资料" in content
    assert "本次收购需求的行业和目标地区在“需求信息”中维护。" in content


def test_supplementary_and_notes_stay_separate() -> None:
    """补充信息进推荐上下文，运营备注不进。合并会把内部备注送进 LLM。"""
    content = WORKSPACE_SOURCE.read_text(encoding="utf-8")
    assert 'field="supplementary_summary"' in content
    assert 'field="notes"' in content
    assert "会进入推荐上下文" in content
    assert "不进入推荐上下文" in content
