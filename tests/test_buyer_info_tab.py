from pathlib import Path

from backend.app.api.routes.buyer_parties import (
    BUYER_PARTY_OUT_COLUMNS,
    BuyerPartyCreate,
    BuyerPartyOut,
    BuyerPartyUpdate,
)


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_SOURCE = ROOT / "frontend" / "src" / "components" / "BuyerIntentWorkspace.tsx"


def test_buyer_party_api_exposes_shared_profile_fields() -> None:
    for field in ("industries_json", "industry_l2_json", "contact_name", "contact_info_json", "notes"):
        assert field in BuyerPartyCreate.model_fields
        assert field in BuyerPartyUpdate.model_fields
        assert field in BuyerPartyOut.model_fields
        assert field in BUYER_PARTY_OUT_COLUMNS

    payload = BuyerPartyUpdate(contact_info_json={"text": "13800000000"})
    assert payload.model_dump(exclude_unset=True) == {
        "contact_info_json": {"text": "13800000000"},
    }


def test_buyer_info_tab_is_trimmed_and_uses_inline_editors() -> None:
    content = WORKSPACE_SOURCE.read_text(encoding="utf-8")

    assert "{ key: 'buyer', label: '买家信息' }" in content
    for label in ("买家名称", "所在地区", "所属行业", "联系人", "联系方式", "其他"):
        assert f'label="{label}"' in content

    for removed_label in ("法人全称", "买家类型", "所属集团", "上市状态", "主营业务", "资金实力/规模", "资料摘要"):
        assert f'label="{removed_label}"' not in content

    assert "editingField === field" in content
    assert "<IndustryPairsEditor" in content
    assert content.count("<AdministrativeAreaPicker") == 1
    assert "<RegionConstraintsEditor" not in content
    assert "以下均为买家主体资料。编辑后会同步到同一买家的所有需求" in content
    assert "本次收购需求的行业和目标地区在“需求信息”中维护。" in content
    assert "编辑资料" not in content
