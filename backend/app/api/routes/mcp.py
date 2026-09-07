"""MCP 端点（Streamable HTTP，无状态）：外部 Agent 查询买家库与标的库的唯一入口。

鉴权在这里自己做（API key 或静态管理员令牌），``main.py`` 的鉴权中间件对本路径放行 ——
API key 不是 JWT，中间件认不出它。每次 tools/call 写一条 ``agent_call_log``。

无状态的含义：没有 Mcp-Session-Id，GET 不开事件流（回 405），每个 POST 独立处理。
API 多副本时不需要任何跨进程协调。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from backend.app.config import get_settings
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db
from backend.app.mcp.protocol import INVALID_REQUEST, PARSE_ERROR, ToolCallRecord, handle_body
from backend.app.mcp.tools import INSTRUCTIONS, TOOLS, ToolContext
from backend.app.services.api_keys import SCOPE_AGENT_READ, ApiKeyContext, resolve_agent_bearer

router = APIRouter(prefix="/mcp", tags=["mcp"])

MCP_PATH = "/api/v1/mcp"


def _bearer(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def _unauthorized(detail: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": detail}},
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _server_version() -> str:
    settings = get_settings()
    sha = (settings.railway_git_commit_sha or "").strip()
    return f"0.1.0+{sha[:7]}" if sha else "0.1.0"


@router.post("")
async def mcp_post(request: Request, db: Session = Depends(get_db)) -> Response:
    settings = get_settings()
    caller = await run_in_threadpool(
        resolve_agent_bearer, db, _bearer(request), admin_token=settings.effective_admin_token
    )
    if caller is None:
        return _unauthorized(
            "Not authenticated: expected an API key (mma_…) in the Authorization header."
        )
    if not caller.has_scope(SCOPE_AGENT_READ):
        return _unauthorized("This API key has no agent:read scope.")

    raw = await request.body()
    try:
        body = json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, ValueError):
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": PARSE_ERROR, "message": "Body is not valid JSON."},
            },
            status_code=400,
        )
    if body is None:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": INVALID_REQUEST, "message": "Empty body."},
            },
            status_code=400,
        )

    records: list[ToolCallRecord] = []
    response = await run_in_threadpool(
        handle_body,
        body,
        tools=TOOLS,
        context=ToolContext(db=db, caller=caller),
        server_version=_server_version(),
        instructions=INSTRUCTIONS,
        records=records,
    )
    if records:
        await run_in_threadpool(_write_call_log, db, caller, records)
    if response is None:
        return Response(status_code=202)
    return JSONResponse(response, media_type="application/json")


@router.get("")
async def mcp_get() -> Response:
    # 无状态实现不开服务端事件流。协议允许用 405 表示这一点，官方客户端会照常继续。
    return Response(status_code=405, headers={"Allow": "POST"})


@router.delete("")
async def mcp_delete() -> Response:
    return Response(status_code=405, headers={"Allow": "POST"})


def _write_call_log(db: Session, caller: ApiKeyContext, records: list[ToolCallRecord]) -> None:
    """观测不是产出：写日志失败不能让这次调用失败。"""
    try:
        for record in records:
            db.execute(
                text(
                    """
                    insert into agent_call_log (
                      team_id, workspace_id, api_key_id, actor_label, tool_name,
                      arguments_json, matched, returned, duration_ms, error_text
                    )
                    values (
                      :team_id, :workspace_id, :api_key_id, :actor_label, :tool_name,
                      :arguments_json, :matched, :returned, :duration_ms, :error_text
                    )
                    """
                ).bindparams(bindparam("arguments_json", type_=JSONB)),
                {
                    "team_id": DEFAULT_TEAM_ID,
                    "workspace_id": DEFAULT_WORKSPACE_ID,
                    "api_key_id": caller.api_key_id,
                    "actor_label": caller.actor_label,
                    "tool_name": record.tool_name,
                    "arguments_json": _json_safe(record.arguments),
                    "matched": record.matched,
                    "returned": record.returned,
                    "duration_ms": record.duration_ms,
                    "error_text": (record.error_text or None) and record.error_text[:2000],
                },
            )
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))
