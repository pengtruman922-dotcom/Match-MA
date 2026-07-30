import pytest
from pydantic import ValidationError

from backend.app.api.routes.buyer_intents import BuyerIntentCreate, BuyerIntentUpdate


@pytest.mark.parametrize("field", ["equity_requirement_type", "listing_market_region"])
def test_nullable_buyer_intent_enums_normalize_blank_to_none(field: str) -> None:
    update = BuyerIntentUpdate.model_validate({field: "  "})

    assert getattr(update, field) is None


def test_buyer_intent_create_normalizes_nullable_enum_blanks() -> None:
    intent = BuyerIntentCreate.model_validate(
        {
            "intent_name": "测试需求",
            "equity_requirement_type": "",
            "listing_market_region": "",
        }
    )

    assert intent.equity_requirement_type is None
    assert intent.listing_market_region is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("equity_requirement_type", ""),
        ("listing_market_region", "hong_kong"),
        ("requires_relocation", "yes"),
        ("requires_control", "required"),
    ],
)
def test_invalid_buyer_intent_enum_values_do_not_reach_database(field: str, value: str) -> None:
    if field in {"equity_requirement_type", "listing_market_region"} and value == "":
        assert getattr(BuyerIntentUpdate.model_validate({field: value}), field) is None
        return

    with pytest.raises(ValidationError):
        BuyerIntentUpdate.model_validate({field: value})
