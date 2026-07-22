"""Saving a search provider from the Settings page.

Search providers are rows in model_provider_config with provider_type='search'.
Batch 6a extended the database CHECK constraint (migration 045) but not the API
whitelist, so every save came back 422 and search could not be configured at
all. These tests cover the save path itself rather than the search adapters.
"""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.api.routes.model_config import (
    PROVIDER_TYPES,
    ProviderCreate,
    _clear_default_provider,
    create_provider,
    get_model_config_capabilities,
)


class _Result:
    def __init__(self, row: dict) -> None:
        self._row = row

    def mappings(self):
        return self

    def one(self):
        return self._row


class _Db:
    """Records statements instead of running them."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, dict]] = []
        self.committed = False

    def execute(self, statement, params=None):
        self.statements.append((str(statement), dict(params or {})))
        return _Result({"id": uuid4(), "provider_name": "Tavily", "provider_type": "search"})

    def commit(self) -> None:
        self.committed = True

    def statements_containing(self, fragment: str) -> list[tuple[str, dict]]:
        return [item for item in self.statements if fragment in item[0]]


def _search_payload(**overrides) -> ProviderCreate:
    data = {
        "provider_name": "Tavily",
        "model_name": "tavily",
        "base_url": "https://api.tavily.com",
        "secret_mode": "env",
        "api_key_secret_ref": "TAVILY_API_KEY",
        "provider_type": "search",
        "extra_config_json": {"adapter": "tavily"},
    }
    data.update(overrides)
    return ProviderCreate(**data)


def test_search_is_an_accepted_provider_type() -> None:
    """迁移 045 放开了 DB 约束，API 白名单是另一份清单，必须同步。"""
    assert "search" in PROVIDER_TYPES
    assert "search" in get_model_config_capabilities()["provider_types"]


def test_saving_a_search_provider_is_not_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.api.routes.model_config._ensure_unique_model_config_name",
        lambda *args, **kwargs: None,
    )
    db = _Db()

    create_provider(_search_payload(), db=db)

    inserts = db.statements_containing("insert into model_provider_config")
    assert len(inserts) == 1
    assert inserts[0][1]["provider_type"] == "search"
    assert db.committed is True


def test_unknown_provider_type_is_still_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.api.routes.model_config._ensure_unique_model_config_name",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(HTTPException) as excinfo:
        create_provider(_search_payload(provider_type="telepathy"), db=_Db())

    assert excinfo.value.status_code == 422


def test_making_a_search_provider_default_leaves_the_chat_model_alone(monkeypatch) -> None:
    """默认值是每类一个。跨类型清 is_default 会把默认对话模型静默清掉，
    而这种失败要等到下一次深评才暴露出来。"""
    monkeypatch.setattr(
        "backend.app.api.routes.model_config._ensure_unique_model_config_name",
        lambda *args, **kwargs: None,
    )
    db = _Db()

    create_provider(_search_payload(is_default=True), db=db)

    clears = db.statements_containing("set is_default = false")
    assert len(clears) == 1
    statement, params = clears[0]
    assert "provider_type = :provider_type" in statement
    assert params["provider_type"] == "search"


def test_clear_default_is_scoped_to_one_provider_type() -> None:
    db = _Db()

    _clear_default_provider(db, "openai_compatible")

    statement, params = db.statements[0]
    assert "provider_type = :provider_type" in statement
    assert params["provider_type"] == "openai_compatible"
