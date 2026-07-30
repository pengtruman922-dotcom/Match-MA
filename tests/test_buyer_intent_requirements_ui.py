from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "frontend" / "src" / "components" / "BuyerIntentRequirements.tsx"


def test_buyer_intent_conditions_use_inline_single_field_editing() -> None:
    content = SOURCE.read_text(encoding="utf-8")

    assert "InlineConditionEditor" in content
    assert "normalizeCommonFieldChanges(changes, indicators)" in content
    assert "编辑公共条件" not in content
    assert "标记已复核" not in content
    assert "function cleanFields" not in content
    assert "function intentDraft" not in content


def test_pending_confirmation_is_rendered_inside_condition_rows() -> None:
    content = SOURCE.read_text(encoding="utf-8")

    assert "pendingForRow(row)" in content
    assert "<PendingItems" in content
    assert "确认前不参加初筛和软排序" in content
