"""MCP 的 JSON-RPC 层：无状态 Streamable HTTP 需要的那一小段协议。

**为什么不用官方 SDK。** 我们只需要 initialize / tools/list / tools/call 三个方法，
无状态（每个请求独立，API 多副本也不用协调会话），返回纯 JSON。官方 SDK 要在
FastAPI 里挂它自己的 lifespan 和会话管理器，还要多一个依赖进两套部署的构建链。
这一层不到两百行，而且能用 TestClient 直接测。协议兼容性用官方客户端实测过。

**工具错误不是协议错误。** 参数不对、库里没有、内部异常，都作为
``{"isError": true, "content": [...]}`` 的正常结果返回，模型看得到原因、能改参数重试。
只有请求本身不成形（不是 JSON-RPC、方法不存在）才回 JSON-RPC error。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = ("2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "match-ma"

# JSON-RPC 2.0 错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[Any, dict[str, Any]], dict[str, Any]]

    def as_listing(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


@dataclass
class ToolCallRecord:
    """一次 tools/call 的观测数据，交给路由写 agent_call_log。"""

    tool_name: str
    arguments: dict[str, Any]
    duration_ms: int
    matched: int | None
    returned: int | None
    error_text: str | None


class ToolError(Exception):
    """工具层的可解释错误：会以 isError 结果回给模型，而不是 500。"""


def _result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        payload["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": payload}


def negotiate_protocol_version(requested: Any) -> str:
    version = str(requested or "").strip()
    return version if version in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION


def handle_message(
    message: Any,
    *,
    tools: list[ToolSpec],
    context: Any,
    server_version: str,
    instructions: str,
    records: list[ToolCallRecord] | None = None,
) -> dict[str, Any] | None:
    """处理一条 JSON-RPC 消息。通知（没有 id）返回 None。"""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
        return _error(
            message.get("id") if isinstance(message, dict) else None,
            INVALID_REQUEST,
            "Invalid JSON-RPC request.",
        )
    method = str(message.get("method") or "")
    request_id = message.get("id")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return _error(request_id, INVALID_PARAMS, "params must be an object.")

    if method.startswith("notifications/"):
        return None
    if request_id is None:
        # 非通知却没有 id：按通知处理，不回声。
        return None

    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": negotiate_protocol_version(params.get("protocolVersion")),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": server_version},
                "instructions": instructions,
            },
        )
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": [tool.as_listing() for tool in tools]})
    if method == "tools/call":
        return _result(
            request_id, _call_tool(params, tools=tools, context=context, records=records)
        )
    return _error(request_id, METHOD_NOT_FOUND, f"Method not found: {method}")


def _call_tool(
    params: dict[str, Any],
    *,
    tools: list[ToolSpec],
    context: Any,
    records: list[ToolCallRecord] | None,
) -> dict[str, Any]:
    name = str(params.get("name") or "")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return _tool_error(f"arguments must be an object, got {type(arguments).__name__}.")
    tool = next((item for item in tools if item.name == name), None)
    if tool is None:
        return _tool_error(f"Unknown tool: {name!r}. Available: {[item.name for item in tools]}")

    started = time.monotonic()
    error_text: str | None = None
    result: dict[str, Any] | None = None
    try:
        result = tool.handler(context, arguments)
    except ToolError as exc:
        error_text = str(exc)
    except Exception as exc:  # noqa: BLE001 —— 工具内部异常回给模型，但要留痕
        error_text = f"{type(exc).__name__}: {exc}"
    duration_ms = int((time.monotonic() - started) * 1000)

    if records is not None:
        records.append(
            ToolCallRecord(
                tool_name=name,
                arguments=arguments,
                duration_ms=duration_ms,
                matched=_int_or_none((result or {}).get("matched")),
                returned=len((result or {}).get("returned") or [])
                if isinstance((result or {}).get("returned"), list)
                else None,
                error_text=error_text,
            )
        )
    if error_text is not None:
        return _tool_error(error_text)
    return {
        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}],
        "isError": False,
    }


def _tool_error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def handle_body(
    body: Any,
    *,
    tools: list[ToolSpec],
    context: Any,
    server_version: str,
    instructions: str,
    records: list[ToolCallRecord] | None = None,
) -> Any | None:
    """HTTP 请求体 → 响应体。单条或批量都认，全是通知时返回 None（HTTP 202）。"""
    kwargs = dict(
        tools=tools,
        context=context,
        server_version=server_version,
        instructions=instructions,
        records=records,
    )
    if isinstance(body, list):
        if not body:
            return _error(None, INVALID_REQUEST, "Empty batch.")
        responses = [handle_message(item, **kwargs) for item in body]
        responses = [item for item in responses if item is not None]
        return responses or None
    return handle_message(body, **kwargs)
