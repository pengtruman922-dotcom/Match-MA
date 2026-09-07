"""MCP 端点：JSON-RPC 层与 HTTP 层（2026-09-07）。

协议层用假工具直接测；HTTP 层用 TestClient，把数据库依赖和凭证解析换成桩，
只验「无凭证 401、GET 405、initialize 回版本、通知回 202、tools/call 回 content」。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.api.routes import mcp as mcp_route
from backend.app.db import get_db
from backend.app.main import SELF_AUTHENTICATED_PATHS, create_app
from backend.app.mcp.protocol import (
    DEFAULT_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    ToolCallRecord,
    ToolError,
    ToolSpec,
    handle_body,
    handle_message,
    negotiate_protocol_version,
)
from backend.app.services.api_keys import ApiKeyContext


def _echo(context: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"matched": 2, "returned": [{"x": 1}, {"x": 2}], "echo": arguments}


def _boom(context: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    raise ToolError("需要 ids 或 names 至少一个。")


TOOLS = [
    ToolSpec(
        name="echo",
        description="回声",
        input_schema={"type": "object", "properties": {}},
        handler=_echo,
    ),
    ToolSpec(
        name="boom",
        description="炸",
        input_schema={"type": "object", "properties": {}},
        handler=_boom,
    ),
]
KW = dict(tools=TOOLS, context=None, server_version="test", instructions="读文本判断")


def _req(method: str, params: dict[str, Any] | None = None, request_id: Any = 1) -> dict[str, Any]:
    message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        message["id"] = request_id
    if params is not None:
        message["params"] = params
    return message


# ---------------------------------------------------------------- 协议层


def test_initialize_echoes_a_supported_version_and_falls_back_otherwise() -> None:
    assert negotiate_protocol_version("2025-06-18") == "2025-06-18"
    assert negotiate_protocol_version("2099-01-01") == DEFAULT_PROTOCOL_VERSION

    response = handle_message(_req("initialize", {"protocolVersion": "2025-03-26"}), **KW)
    assert response["result"]["protocolVersion"] == "2025-03-26"
    assert response["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert response["result"]["serverInfo"]["name"] == "match-ma"
    assert "读文本" in response["result"]["instructions"]


def test_notifications_get_no_response_and_unknown_methods_are_errors() -> None:
    assert handle_message(_req("notifications/initialized", request_id=None), **KW) is None
    error = handle_message(_req("resources/list"), **KW)
    assert error["error"]["code"] == METHOD_NOT_FOUND
    assert handle_message({"not": "jsonrpc"}, **KW)["error"]["code"] == -32600


def test_tools_list_and_call_round_trip() -> None:
    listing = handle_message(_req("tools/list"), **KW)["result"]["tools"]
    assert [tool["name"] for tool in listing] == ["echo", "boom"]
    assert listing[0]["inputSchema"]["type"] == "object"

    records: list[ToolCallRecord] = []
    result = handle_message(
        _req("tools/call", {"name": "echo", "arguments": {"q": "杭州"}}),
        **{**KW, "records": records},
    )["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["echo"] == {"q": "杭州"}
    assert records[0].tool_name == "echo" and records[0].matched == 2 and records[0].returned == 2


def test_tool_errors_are_results_not_protocol_errors() -> None:
    """参数不对、库里没有，模型要看到原因才能改参数重试，所以是 isError 结果而不是 500。"""
    records: list[ToolCallRecord] = []
    for name in ("boom", "nope"):
        response = handle_message(
            _req("tools/call", {"name": name, "arguments": {}}), **{**KW, "records": records}
        )
        assert "error" not in response
        assert response["result"]["isError"] is True
    assert "需要 ids" in records[0].error_text
    assert len(records) == 1, "找不到工具不是一次调用，不记日志"


def test_batches_drop_notifications_and_return_none_when_nothing_is_left() -> None:
    batch = [_req("notifications/initialized", request_id=None), _req("ping", request_id=7)]
    responses = handle_body(batch, **KW)
    assert responses == [{"jsonrpc": "2.0", "id": 7, "result": {}}]
    assert handle_body([_req("notifications/initialized", request_id=None)], **KW) is None


# ---------------------------------------------------------------- HTTP 层


class _FakeSession:
    def close(self) -> None:
        pass


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = create_app()

    def _fake_db():
        yield _FakeSession()

    app.dependency_overrides[get_db] = _fake_db
    reader = ApiKeyContext(api_key_id=None, name="stub", scopes=frozenset({"agent:read"}))
    monkeypatch.setattr(
        mcp_route,
        "resolve_agent_bearer",
        lambda db, token, admin_token: reader if token == "mma_ok" else None,
    )
    monkeypatch.setattr(mcp_route, "TOOLS", TOOLS)
    written: list[ToolCallRecord] = []
    monkeypatch.setattr(
        mcp_route, "_write_call_log", lambda db, caller, records: written.extend(records)
    )
    app.state.written = written
    return TestClient(app)


def test_the_mcp_path_bypasses_the_jwt_middleware_but_still_needs_a_key(client: TestClient) -> None:
    assert "/api/v1/mcp" in SELF_AUTHENTICATED_PATHS
    response = client.post("/api/v1/mcp", json=_req("ping"))
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert (
        client.post(
            "/api/v1/mcp", json=_req("ping"), headers={"Authorization": "Bearer mma_bad"}
        ).status_code
        == 401
    )


def test_get_is_405_because_there_is_no_event_stream(client: TestClient) -> None:
    response = client.get("/api/v1/mcp", headers={"Authorization": "Bearer mma_ok"})
    assert response.status_code == 405
    assert response.headers["allow"] == "POST"


def test_initialize_notification_and_call_over_http(client: TestClient) -> None:
    headers = {"Authorization": "Bearer mma_ok", "Accept": "application/json, text/event-stream"}

    init = client.post(
        "/api/v1/mcp", json=_req("initialize", {"protocolVersion": "2025-06-18"}), headers=headers
    )
    assert init.status_code == 200
    assert init.headers["content-type"].startswith("application/json")
    assert init.json()["result"]["protocolVersion"] == "2025-06-18"

    note = client.post(
        "/api/v1/mcp", json=_req("notifications/initialized", request_id=None), headers=headers
    )
    assert note.status_code == 202

    call = client.post(
        "/api/v1/mcp",
        json=_req("tools/call", {"name": "echo", "arguments": {"a": 1}}),
        headers=headers,
    )
    assert call.status_code == 200
    body = call.json()
    assert body["id"] == 1 and body["result"]["isError"] is False
    assert json.loads(body["result"]["content"][0]["text"])["echo"] == {"a": 1}
    assert [record.tool_name for record in client.app.state.written] == ["echo"]

    bad = client.post("/api/v1/mcp", content=b"{not json", headers=headers)
    assert bad.status_code == 400
