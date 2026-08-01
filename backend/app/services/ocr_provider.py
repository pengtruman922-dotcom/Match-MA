"""OCR 服务商配置的统一出口。

OCR **不是 AI 节点** —— 它不绑模型、不吃提示词，只是一次第三方 HTTP 调用
（doc2x）。和搜索工具一样，它的配置存在 `model_provider_config` 里，
`provider_type='ocr'`。

历史上这些参数只能靠环境变量给，换 key 要重新部署。这里保留环境变量作为
兜底：库里没有配置行时行为与改造前完全一致，有了才以库为准。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.services.model_secrets import ModelSecretError, decrypt_model_secret

# 目前只接了 doc2x；skeleton 表示未接真实服务，只透传上传时抓到的文本。
OCR_ADAPTERS: tuple[str, ...] = ("doc2x", "skeleton")


class OcrProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class OcrProviderConfig:
    adapter: str
    base_url: str
    model: str
    api_key: str | None
    # database = 来自设置页；environment = 来自环境变量兜底。
    source: str
    provider_config_id: str | None = None
    provider_name: str | None = None

    @property
    def configured(self) -> bool:
        return self.adapter == "doc2x" and bool(self.api_key) and bool(self.base_url)


def get_ocr_provider_row(db: Session) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select
              id, provider_name, model_name, base_url, secret_mode,
              api_key_secret_ref, api_key_encrypted, extra_config_json, metadata_json
            from model_provider_config
            where team_id = :team_id
              and workspace_id = :workspace_id
              and provider_type = 'ocr'
              and is_active = true
            order by is_default desc, updated_at desc
            limit 1
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().one_or_none()
    return dict(row) if row else None


def _resolve_api_key(provider: dict[str, Any]) -> str | None:
    """解密或读环境变量。明文不离开这个调用链。"""
    if provider.get("api_key_encrypted"):
        try:
            return decrypt_model_secret(str(provider["api_key_encrypted"]))
        except ModelSecretError as exc:
            raise OcrProviderError(str(exc)) from exc
    secret_ref = str(provider.get("api_key_secret_ref") or "").strip()
    if not secret_ref:
        return None
    return os.getenv(secret_ref) or None


def resolve_ocr_provider(db: Session) -> OcrProviderConfig:
    """当前生效的 OCR 配置：优先设置页，其次环境变量。"""
    settings = get_settings()
    row = get_ocr_provider_row(db)
    if row:
        adapter = str((row.get("extra_config_json") or {}).get("adapter") or "doc2x").strip().lower()
        return OcrProviderConfig(
            adapter=adapter,
            base_url=str(row.get("base_url") or settings.doc2x_base_url),
            model=str(row.get("model_name") or settings.doc2x_model),
            api_key=_resolve_api_key(row),
            source="database",
            provider_config_id=str(row["id"]),
            provider_name=str(row.get("provider_name") or ""),
        )
    return OcrProviderConfig(
        adapter=settings.ocr_provider.strip().lower(),
        base_url=settings.doc2x_base_url,
        model=settings.doc2x_model,
        api_key=settings.effective_doc2x_api_key,
        source="environment",
    )


def ocr_provider_status(db: Session) -> dict[str, Any]:
    """设置页「模型与搜索」用的只读状态。绝不回显密钥本身。"""
    config = resolve_ocr_provider(db)
    settings = get_settings()
    return {
        "adapter": config.adapter,
        "base_url": config.base_url,
        "model": config.model,
        "key_configured": bool(config.api_key),
        "configured": config.configured,
        "source": config.source,
        "provider_config_id": config.provider_config_id,
        "provider_name": config.provider_name,
        "adapters": list(OCR_ADAPTERS),
        # 超时与轮询属于运维调参，不放进设置页，仍由环境变量给。
        "upload_timeout_seconds": settings.doc2x_upload_timeout_seconds,
        "poll_interval_seconds": settings.doc2x_poll_interval_seconds,
        "max_wait_seconds": settings.doc2x_max_wait_seconds,
    }
