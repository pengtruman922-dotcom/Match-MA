from backend.app.services.region_dictionary import normalize_buyer_region_constraints


def test_nationwide_region_means_no_constraint() -> None:
    constraints, pending = normalize_buyer_region_constraints(
        [{"province": "全国", "effect": "required"}]
    )

    assert constraints == []
    assert pending == []


def test_standard_regions_keep_individual_effects() -> None:
    constraints, pending = normalize_buyer_region_constraints(
        [
            {"province": "江苏", "effect": "required"},
            {"province": "上海市", "effect": "preferred"},
            {"province": "安徽", "effect": "excluded"},
        ]
    )

    assert constraints == [
        {"province": "江苏省", "effect": "required"},
        {"province": "上海市", "effect": "preferred"},
        {"province": "安徽省", "effect": "excluded"},
    ]
    assert pending == []


def test_unrecognized_region_is_isolated_for_confirmation() -> None:
    constraints, pending = normalize_buyer_region_constraints(
        [
            {"province": "浙江省", "effect": "preferred"},
            {"province": "某战略区域", "effect": "required", "evidence": "重点考虑某战略区域"},
        ]
    )

    assert constraints == [{"province": "浙江省", "effect": "preferred"}]
    assert pending[0]["field"] == "region_constraints_json"
    assert pending[0]["proposed_value"]["province"] == "某战略区域"
