from backend.app.api.routes.model_config import (
    ProviderUpdate,
    _default_chat_test_messages,
    _node_test_record_from_job,
    _queue_name_for_node_test,
    get_model_config_capabilities,
)

import pytest
from fastapi import HTTPException
from pydantic import ValidationError


def test_capabilities_expose_prompt_and_test_support() -> None:
    capabilities = get_model_config_capabilities()

    assert capabilities["node_types"]["llm"]["prompt_editable"] is True
    assert capabilities["node_types"]["llm"]["test_supported"] is True
    assert capabilities["node_types"]["ocr"]["prompt_editable"] is False
    assert capabilities["node_types"]["ocr"]["test_supported"] is True
    # embedding / rerank 的 worker 已下线，异步测试无人消费，因此不再声明可测。
    assert capabilities["node_types"]["embedding"]["prompt_editable"] is False
    assert capabilities["node_types"]["embedding"]["test_supported"] is False
    assert capabilities["node_types"]["rerank"]["prompt_editable"] is False
    assert capabilities["node_types"]["rerank"]["test_supported"] is False


def test_json_chat_node_default_test_message_returns_json_instruction() -> None:
    messages = _default_chat_test_messages({"response_format": "json_object"}, None)

    assert "JSON only" in messages[0]["content"]
    assert '{"status":"ok"}' in messages[1]["content"]


def test_queue_name_for_node_test_routes_by_node_type() -> None:
    assert _queue_name_for_node_test("llm") == "llm"
    assert _queue_name_for_node_test("parser") == "llm"
    assert _queue_name_for_node_test("research") == "llm"
    assert _queue_name_for_node_test("ocr") == "ocr"


@pytest.mark.parametrize("node_type", ["embedding", "rerank"])
def test_queue_name_for_node_test_rejects_retired_queues(node_type: str) -> None:
    # 这两个 worker 已从 Railway 删除；放行只会让测试任务永久排队。
    with pytest.raises(HTTPException) as excinfo:
        _queue_name_for_node_test(node_type)
    assert excinfo.value.status_code == 400


def test_node_test_record_prefers_result_latency_and_output(monkeypatch) -> None:
    def fake_traces(_db, *, job_id):
        assert str(job_id) == "00000000-0000-0000-0000-000000000001"
        return [{"latency_ms": 200, "status": "succeeded"}]

    monkeypatch.setattr("backend.app.api.routes.model_config._list_node_test_traces", fake_traces)
    record = _node_test_record_from_job(
        None,
        {
            "job_id": "00000000-0000-0000-0000-000000000001",
            "result_json": {"latency_ms": 100, "output_json": {"ok": True}},
        },
    )

    assert record["latency_ms"] == 100
    assert record["output_json"] == {"ok": True}
    assert record["latest_trace"] == {"latency_ms": 200, "status": "succeeded"}


def test_provider_key_field_accepts_only_environment_variable_references() -> None:
    assert ProviderUpdate(api_key_secret_ref="ALIYUN_API_KEY").api_key_secret_ref == "ALIYUN_API_KEY"
    with pytest.raises(ValidationError):
        ProviderUpdate(api_key_secret_ref="not-an-env-reference")
