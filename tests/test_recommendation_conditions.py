def test_scenario_fields_go_through_the_shared_whitelist() -> None:
    from backend.app.services.recommendation_conditions import normalize_scenario_fields

    fields = normalize_scenario_fields(
        {
            "max_pe": "13",
            "requires_control": "YES",
            "intent_business_tags_json": "医药与健康",
            "seller_target_id": "越权字段",
            "min_net_profit_yuan": "not-a-number",
        }
    )

    assert fields == {"max_pe": 13.0, "requires_control": "yes", "intent_business_tags_json": ["医药与健康"]}


