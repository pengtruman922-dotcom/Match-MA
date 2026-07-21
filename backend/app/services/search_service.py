"""Run a search through the configured provider.

Search providers are rows in model_provider_config with provider_type='search',
so key storage, encryption and masking are the ones the Settings page already
uses for model providers — there is no second credential mechanism to keep in
step.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.services.model_secrets import ModelSecretError, decrypt_model_secret
from backend.app.services.search_providers import SearchError, SearchHit, SearchRequest, get_adapter

DEFAULT_SEARCH_TIMEOUT_SECONDS = 30


def get_default_search_provider(db: Session) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select
              id, provider_name, model_name, base_url, secret_mode,
              api_key_secret_ref, api_key_encrypted, extra_config_json,
              extra_headers_json, metadata_json
            from model_provider_config
            where team_id = :team_id
              and workspace_id = :workspace_id
              and provider_type = 'search'
              and is_active = true
            order by is_default desc, updated_at desc
            limit 1
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().one_or_none()
    return dict(row) if row else None


def resolve_search_api_key(provider: dict[str, Any]) -> str:
    """Decrypt or read the key. The plaintext never leaves this call path."""
    if provider.get("api_key_encrypted"):
        try:
            return decrypt_model_secret(str(provider["api_key_encrypted"]))
        except ModelSecretError as exc:
            raise SearchError(str(exc)) from exc
    secret_ref = str(provider.get("api_key_secret_ref") or "").strip()
    if not secret_ref:
        raise SearchError("Search provider has no API key configured.")
    api_key = os.getenv(secret_ref)
    if not api_key:
        raise SearchError(f"Environment variable is not configured: {secret_ref}")
    return api_key


def run_search(
    provider: dict[str, Any],
    query: str,
    *,
    max_results: int = 8,
    api_key: str | None = None,
) -> list[SearchHit]:
    extra_config = provider.get("extra_config_json") or {}
    # model_name doubles as the adapter id for search providers.
    adapter = get_adapter(str(extra_config.get("adapter") or provider.get("model_name") or ""))
    base_url = str(provider.get("base_url") or "").strip()
    if not base_url:
        raise SearchError("Search provider has no base_url configured.")
    timeout_seconds = int(extra_config.get("timeout_seconds") or DEFAULT_SEARCH_TIMEOUT_SECONDS)
    return adapter.search(
        SearchRequest(query=query, max_results=max_results),
        base_url=base_url,
        api_key=api_key or resolve_search_api_key(provider),
        timeout_seconds=timeout_seconds,
        extra_config=extra_config,
    )


def test_search_provider(
    provider: dict[str, Any],
    *,
    query: str = "Match-MA search connectivity check",
    api_key: str | None = None,
) -> dict[str, Any]:
    """Connectivity probe for the Settings page; never returns the key."""
    try:
        hits = run_search(provider, query, max_results=3, api_key=api_key)
    except SearchError as exc:
        return {"status": "failed", "error_message": str(exc), "result_count": 0, "sample_titles": []}
    return {
        "status": "succeeded",
        "error_message": None,
        "result_count": len(hits),
        "sample_titles": [hit.title for hit in hits[:3]],
    }
