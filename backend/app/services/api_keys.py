"""外部 Agent 的机器凭证：API key 的签发、哈希与解析。

设计要点：

1. **明文只在签发那一刻返回一次。** 库里存 sha256，泄漏数据库拿不到可用的 key。
   前缀 `mma_` 加 8 位是给人认的（列表页显示、日志里对号），不参与鉴权。
2. **不设过期，靠停用。** 它写死在 wegent 的 Ghost 配置里，7 天 JWT 意味着每周去改
   一次配置，没人会做。停用后下一次请求即失效（每次都回库查）。
3. **权限范围是闭集。** 现在只签发 `agent:read`，`agent:write` 预留给将来的回写工具。
   scope 不在闭集里的请求在签发时就拒绝，而不是等到调用时才发现没人认。
4. **静态管理员令牌也能进 MCP 端点**，只为本机验证脚本方便。它本来就是全权限，
   这里不扩大任何东西。
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID

KEY_PREFIX = "mma_"
_PREFIX_VISIBLE_CHARS = 8
_RANDOM_BYTES = 30  # token_urlsafe(30) → 40 个字符

SCOPE_AGENT_READ = "agent:read"
SCOPE_AGENT_WRITE = "agent:write"
KNOWN_SCOPES: frozenset[str] = frozenset({SCOPE_AGENT_READ, SCOPE_AGENT_WRITE})

# last_used_at 不是审计线索（那是 agent_call_log 的事），只是列表页上的「最近用过」，
# 所以每分钟最多写一次，免得每个工具调用都多一条 UPDATE。
_LAST_USED_WRITE_INTERVAL = timedelta(seconds=60)


@dataclass(frozen=True)
class ApiKeyContext:
    """一次请求背后的调用方。``api_key_id`` 为空表示走的是静态管理员令牌。"""

    api_key_id: UUID | None
    name: str
    scopes: frozenset[str]

    @property
    def actor_label(self) -> str:
        return self.name if self.api_key_id is None else f"api_key:{self.name}"

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


ADMIN_TOKEN_CONTEXT = ApiKeyContext(api_key_id=None, name="admin-token", scopes=KNOWN_SCOPES)


def generate_api_key() -> tuple[str, str, str]:
    """返回 ``(明文, 显示前缀, sha256)``。明文只在这里出现一次。"""
    plaintext = KEY_PREFIX + secrets.token_urlsafe(_RANDOM_BYTES)
    return plaintext, plaintext[: len(KEY_PREFIX) + _PREFIX_VISIBLE_CHARS], hash_api_key(plaintext)


def hash_api_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.strip().encode("utf-8")).hexdigest()


def looks_like_api_key(token: str | None) -> bool:
    return bool(token) and str(token).startswith(KEY_PREFIX)


def normalize_scopes(raw: Any) -> list[str]:
    """签发时校验：只认闭集，去重，保持传入顺序。未知 scope 直接报错。"""
    values = raw if isinstance(raw, list) else [raw]
    scopes: list[str] = []
    for value in values:
        scope = str(value or "").strip()
        if not scope:
            continue
        if scope not in KNOWN_SCOPES:
            raise ValueError(f"未知的权限范围 {scope!r}，可用：{sorted(KNOWN_SCOPES)}")
        if scope not in scopes:
            scopes.append(scope)
    if not scopes:
        raise ValueError("至少需要一个权限范围。")
    return scopes


def resolve_api_key(db: Session, token: str) -> ApiKeyContext | None:
    """按哈希查 key。已停用返回 None，与不存在同样处理，不区分原因。"""
    if not looks_like_api_key(token):
        return None
    row = (
        db.execute(
            text(
                """
            select id, name, scopes, revoked_at, last_used_at
            from api_key
            where key_hash = :key_hash
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
            ),
            {
                "key_hash": hash_api_key(token),
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
            },
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["revoked_at"] is not None:
        return None
    scopes = frozenset(str(item) for item in (row["scopes"] or []) if item)
    _touch_last_used(db, row["id"], row["last_used_at"])
    return ApiKeyContext(api_key_id=row["id"], name=str(row["name"]), scopes=scopes)


def _touch_last_used(db: Session, api_key_id: UUID, last_used_at: datetime | None) -> None:
    now = datetime.now(UTC)
    if last_used_at is not None:
        previous = last_used_at if last_used_at.tzinfo else last_used_at.replace(tzinfo=UTC)
        if now - previous < _LAST_USED_WRITE_INTERVAL:
            return
    try:
        db.execute(
            text("update api_key set last_used_at = now() where id = :id"),
            {"id": api_key_id},
        )
        db.commit()
    except Exception:  # noqa: BLE001 —— 「最近用过」写失败不该影响这次调用
        db.rollback()


def resolve_agent_bearer(
    db: Session, token: str | None, *, admin_token: str | None
) -> ApiKeyContext | None:
    """MCP 端点的鉴权入口：API key，或静态管理员令牌（本机验证用）。"""
    token = (token or "").strip()
    if not token:
        return None
    if admin_token and token == admin_token:
        return ADMIN_TOKEN_CONTEXT
    return resolve_api_key(db, token)
