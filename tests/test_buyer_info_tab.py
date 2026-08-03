from pathlib import Path

from backend.app.api.routes.buyer_intents import (
    BUYER_INTENT_OUT_COLUMNS,
    BuyerIntentCreate,
    BuyerIntentOut,
    BuyerIntentUpdate,
)


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_SOURCE = ROOT / "frontend" / "src" / "components" / "BuyerIntentWorkspace.tsx"


def test_buyer_intent_api_exposes_editable_contact_info() -> None:
    assert "contact_info_json" in BuyerIntentCreate.model_fields
    assert "contact_info_json" in BuyerIntentUpdate.model_fields
    assert "contact_info_json" in BuyerIntentOut.model_fields
    assert "bi.contact_name, bi.contact_info_json" in BUYER_INTENT_OUT_COLUMNS

    payload = BuyerIntentUpdate(contact_info_json={"text": "13800000000"})
    assert payload.model_dump(exclude_unset=True) == {
        "contact_info_json": {"text": "13800000000"},
    }


def test_buyer_info_tab_is_trimmed_and_uses_inline_editors() -> None:
    content = WORKSPACE_SOURCE.read_text(encoding="utf-8")

    assert "{ key: 'buyer', label: '买家信息' }" in content
    for label in ("买家名称", "所在地区", "行业", "地区", "联系人", "联系方式", "其他"):
        assert f'label="{label}"' in content

    for removed_label in ("法人全称", "买家类型", "所属集团", "上市状态", "主营业务", "资金实力/规模", "资料摘要"):
        assert f'label="{removed_label}"' not in content

    assert "editingField === field" in content
    assert "<IndustryPairsEditor" in content
    assert content.count("<AdministrativeAreaPicker") == 2
    assert "<RegionConstraintsEditor" not in content
    assert "变更上级会自动清空下级；筛选仍按省、市、区三个字段命中。" in content
    assert "编辑资料" not in content
