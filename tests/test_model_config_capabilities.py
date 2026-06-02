from backend.app.api.routes.model_config import (
    _default_chat_test_messages,
    _queue_name_for_node_test,
    get_model_config_capabilities,
)


def test_capabilities_expose_prompt_and_test_support() -> None:
    capabilities = get_model_config_capabilities()

    assert capabilities["node_types"]["llm"]["prompt_editable"] is True
    assert capabilities["node_types"]["llm"]["test_supported"] is True
    assert capabilities["node_types"]["embedding"]["prompt_editable"] is False
    assert capabilities["node_types"]["embedding"]["test_supported"] is True
    assert capabilities["node_types"]["rerank"]["prompt_editable"] is False
    assert capabilities["node_types"]["rerank"]["test_supported"] is True
    assert capabilities["node_types"]["ocr"]["prompt_editable"] is False
    assert capabilities["node_types"]["ocr"]["test_supported"] is False


def test_json_chat_node_default_test_message_returns_json_instruction() -> None:
    messages = _default_chat_test_messages({"response_format": "json_object"}, None)

    assert "JSON only" in messages[0]["content"]
    assert '{"status":"ok"}' in messages[1]["content"]


def test_queue_name_for_node_test_routes_by_node_type() -> None:
    assert _queue_name_for_node_test("llm") == "llm"
    assert _queue_name_for_node_test("parser") == "llm"
    assert _queue_name_for_node_test("research") == "llm"
    assert _queue_name_for_node_test("embedding") == "embedding"
    assert _queue_name_for_node_test("rerank") == "rerank"
    assert _queue_name_for_node_test("ocr") == "ocr"
