def test_scenario_fields_go_through_the_shared_whitelist() -> None:
    from backend.app.services.recommendation_conditions import normalize_scenario_fields

    fields = normalize_scenario_fields(
        {
            "max_pe": "13",
            "business_tags_json": "医药与健康",
            "seller_target_id": "越权字段",
            "min_net_profit_yuan": "not-a-number",
            # 0901 退役：门槛搬进方案时它没跟过来，内容进 other_requirements_text。
            # 白名单必须**吃掉**它而不是原样透传 —— 透传的话它会被当成一个
            # 方案字段写进 insert 的参数表，而那一列在方案表上不存在。
            "requires_control": "YES",
        }
    )

    assert fields == {"max_pe": 13.0, "business_tags_json": ["医药与健康"]}


