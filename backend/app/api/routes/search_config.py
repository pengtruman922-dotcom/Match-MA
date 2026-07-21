"""Search provider surface for the Settings page.

Providers themselves are created through /model-config/providers with
provider_type='search' — this module adds only what search needs on top: the
adapter catalog and a connectivity probe that speaks the search API rather than
the chat API.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser, require_admin
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db
from backend.app.services.model_secrets import model_secret_encryption_configured
from backend.app.services.search_providers import available_adapters
from backend.app.services.search_service import get_default_search_provider, test_search_provider

router = APIRouter(prefix="/search-config", tags=["search-config"])


class SearchProviderOut(BaseModel):
    id: UUID
    provider_name: str
    adapter: str
    base_url: str | None
    secret_mode: str
    api_key_secret_ref: str | None
    secret_configured: bool
    key_display: str
    extra_config_json: dict[str, Any]
    is_active: bool
    is_default: bool
    updated_at: str


class SearchProviderTestRequest(BaseModel):
    provider_id: UUID | None = None
    query: str = Field(default="Match-MA 搜索连通性测试", min_length=1, max_length=200)
    # 允许在保存前用草稿密钥试连；该值只用于本次请求，不落库、不回显。
    api_key: str | None = Field(default=None, min_length=1, max_length=10000)


class SearchProviderTestOut(BaseModel):
    status: str
    error_message: str | None
    result_count: int
    sample_titles: list[str]


@router.get("/overview")
def search_config_overview(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_admin(current_user)
    rows = db.execute(
        text(
            """
            select
              id, provider_name, model_name, base_url, secret_mode, api_key_secret_ref,
              (secret_mode = 'direct' and api_key_encrypted is not null)
                or (secret_mode = 'env' and api_key_secret_ref is not null) as secret_configured,
              case
                when secret_mode = 'direct' and api_key_encrypted is not null then '已加密保存'
                when secret_mode = 'env' then coalesce(api_key_secret_ref, '未配置')
                else '未配置'
              end as key_display,
              extra_config_json, is_active, is_default,
              updated_at::text as updated_at
            from model_provider_config
            where team_id = :team_id
              and workspace_id = :workspace_id
              and provider_type = 'search'
            order by is_default desc, updated_at desc
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().all()

    providers = [
        SearchProviderOut(
            **{
                **{key: value for key, value in dict(row).items() if key != "model_name"},
                "adapter": str(
                    (row["extra_config_json"] or {}).get("adapter") or row["model_name"] or ""
                ),
            }
        ).model_dump(mode="json")
        for row in rows
    ]
    return {
        "providers": providers,
        "available_adapters": available_adapters(),
        "direct_key_encryption_configured": model_secret_encryption_configured(),
        "security_note": (
            "直接填写的密钥经 Fernet 加密存库，接口只返回是否已配置，不回显明文；"
            "加密需要环境变量 MODEL_SECRET_ENCRYPTION_KEY。"
        ),
    }


@router.post("/test", response_model=SearchProviderTestOut)
def test_search_connectivity(
    payload: SearchProviderTestRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_admin(current_user)
    if payload.provider_id is None:
        provider = get_default_search_provider(db)
        if provider is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active search provider is configured.",
            )
    else:
        row = db.execute(
            text(
                """
                select
                  id, provider_name, model_name, base_url, secret_mode,
                  api_key_secret_ref, api_key_encrypted, extra_config_json
                from model_provider_config
                where id = :provider_id
                  and team_id = :team_id
                  and workspace_id = :workspace_id
                  and provider_type = 'search'
                """
            ),
            {
                "provider_id": payload.provider_id,
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
            },
        ).mappings().one_or_none()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Search provider not found."
            )
        provider = dict(row)
    return test_search_provider(provider, query=payload.query, api_key=payload.api_key)
