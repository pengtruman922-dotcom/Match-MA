"""MCP 端点（Streamable HTTP，无状态）：外部 Agent 查询买家库与标的库的唯一入口。

鉴权在这里自己做（API key 或静态管理员令牌），``main.py`` 的鉴权中间件对本路径放行 ——
API key 不是 JWT，中间件认不出它。每次 tools/call 写一条 ``agent_call_log``；
initialize / tools/list 也写（它们是「连接成功」的证据）；401 也写一条，只记 key 前缀与
User-Agent —— 「wegent 连不上」的第一个问题永远是「请求到底到没到、带没带 key」。

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
from backend.app.services.api_keys import (
    SCOPE_AGENT_READ,
    ApiKeyContext,
    looks_like_api_key,
    resolve_agent_bearer,
)

router = APIRouter(prefix="/mcp", tags=["mcp"])

MCP_PATH = "/api/v1/mcp"


def _bearer(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def _credential(request: Request) -> str | None:
    """Authorization 头优先；没有就认 URL 参数 ``api_key``。

    兜底是给发不出自定义头的客户端的：wegent 走 Claude Code 那条路时，后端把
    ``headers`` 改名成 ``auth`` 交给执行器，执行器再交给 Claude Code 时只认 ``headers``，
    Authorization 头在这一步丢掉。key 进 URL 会出现在边缘日志里，所以它只读、可停用，
    而且文档里写明能用头就用头。
    """
    return _bearer(request) or (request.query_params.get("api_key") or "").strip() or None


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


def _parse_body(raw: bytes) -> tuple[Any, JSONResponse | None]:
    try:
        body = json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, ValueError):
        return None, JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": PARSE_ERROR, "message": "Body is not valid JSON."},
            },
            status_code=400,
        )
    if body is None:
        return None, JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": INVALID_REQUEST, "message": "Empty body."},
            },
            status_code=400,
        )
    return body, None


def _methods(body: Any) -> list[str]:
    messages = body if isinstance(body, list) else [body]
    return [str(item.get("method") or "") for item in messages if isinstance(item, dict)]


@router.post("")
async def mcp_post(request: Request, db: Session = Depends(get_db)) -> Response:
    settings = get_settings()
    raw = await request.body()
    body, parse_error = _parse_body(raw)
    token = _credential(request)
    caller = await run_in_threadpool(
        resolve_agent_bearer, db, token, admin_token=settings.effective_admin_token
    )
    if caller is None or not caller.has_scope(SCOPE_AGENT_READ):
        await run_in_threadpool(
            _write_auth_failure, db, token, _methods(body), request.headers.get("user-agent")
        )
        if caller is None:
            return _unauthorized(
                "Not authenticated: expected an API key (mma_…) in the Authorization header."
            )
        return _unauthorized("This API key has no agent:read scope.")
    if parse_error is not None:
        return parse_error

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
    if not records:
        records = [
            ToolCallRecord(
                tool_name=method,
                arguments={},
                duration_ms=0,
                matched=None,
                returned=None,
                error_text=None,
            )
            for method in _methods(body)
            if method and not method.startswith("notifications/")
        ]
    if records:
        await run_in_threadpool(_write_call_log, db, caller, records)
    if response is None:
        return Response(status_code=202)
    return JSONResponse(response, media_type="application/json")


@router.get("")
@router.get("/")
async def mcp_get(request: Request) -> Response:
    """两种 GET：MCP 客户端要开事件流的，回 405（无状态实现不开流，协议允许，客户端照常继续）；
    浏览器或可达性探测的普通 GET，回 200 和一份自描述 —— 有的宿主在挂载前会先探一下 URL，
    405 会被当成「不可达」直接丢弃这个服务器。"""
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept and "application/json" not in accept:
        return Response(status_code=405, headers={"Allow": "POST"})
    return JSONResponse(
        {
            "name": "match-ma",
            "version": _server_version(),
            "transport": "streamable-http",
            "endpoint": MCP_PATH,
            "auth": "Authorization: Bearer <api key>，或 URL 参数 api_key",
            "tools": [tool.name for tool in TOOLS],
            "how": "POST JSON-RPC 2.0：initialize / tools/list / tools/call",
        },
        media_type="application/json",
    )


@router.head("")
@router.head("/")
async def mcp_head() -> Response:
    return Response(status_code=200)


@router.post("/")
async def mcp_post_slash(request: Request, db: Session = Depends(get_db)) -> Response:
    return await mcp_post(request, db)


@router.delete("")
async def mcp_delete() -> Response:
    return Response(status_code=405, headers={"Allow": "POST"})


_INSERT_CALL_LOG = text(
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
).bindparams(bindparam("arguments_json", type_=JSONB))


def _write_call_log(db: Session, caller: ApiKeyContext, records: list[ToolCallRecord]) -> None:
    """观测不是产出：写日志失败不能让这次调用失败。"""
    try:
        for record in records:
            db.execute(
                _INSERT_CALL_LOG,
                {
                    "team_id": DEFAULT_TEAM_ID,
                    "workspace_id": DEFAULT_WORKSPACE_ID,
                    "api_key_id": caller.api_key_id,
                    "actor_label": caller.actor_label,
                    "tool_name": record.tool_name[:120],
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


def _write_auth_failure(
    db: Session, token: str | None, methods: list[str], user_agent: str | None
) -> None:
    """401 也留一条：只记 key 的前缀和 User-Agent，不记完整令牌。"""
    if looks_like_api_key(token):
        presented = str(token)[:12] + "…"
    elif token:
        presented = "非 API key 的令牌"
    else:
        presented = "没有 Authorization 头"
    try:
        db.execute(
            _INSERT_CALL_LOG,
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "api_key_id": None,
                "actor_label": "unauthenticated",
                "tool_name": (methods[0] if methods else "?")[:120],
                "arguments_json": {"presented": presented, "user_agent": (user_agent or "")[:200]},
                "matched": None,
                "returned": None,
                "duration_ms": None,
                "error_text": "401",
            },
        )
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))
