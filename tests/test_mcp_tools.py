"""MCP 工具目录的结构守卫：六个工具、schema 从注册表派生、说明里带着铁律。"""

from backend.app.mcp.tools import INSTRUCTIONS, TOOLS
from backend.app.services.agent_buyer_views import THRESHOLD_FIELDS
from backend.app.services.screening_schema import build_conditions_properties


def test_six_tools_with_unique_names_and_object_schemas() -> None:
    names = [tool.name for tool in TOOLS]
    assert names == [
        "buyers_scan",
        "buyer_get",
        "buyers_filter",
        "targets_scan",
        "target_get",
        "targets_filter",
    ]
    for tool in TOOLS:
        assert tool.input_schema["type"] == "object"
        assert tool.input_schema.get("additionalProperties") is False
        assert tool.description.strip()


def test_targets_filter_conditions_come_from_the_screening_registry() -> None:
    schema = next(tool for tool in TOOLS if tool.name == "targets_filter").input_schema
    assert schema["properties"]["conditions"]["properties"] == build_conditions_properties()


def test_buyers_filter_has_threshold_enum_matches_the_scenario_thresholds() -> None:
    schema = next(tool for tool in TOOLS if tool.name == "buyers_filter").input_schema
    assert schema["properties"]["has_threshold"]["items"]["enum"] == list(THRESHOLD_FIELDS)


def test_the_instructions_carry_the_three_rules() -> None:
    for phrase in ("不构成障碍", "OR", "不要从公司名猜", "没有联系人"):
        assert phrase in INSTRUCTIONS
