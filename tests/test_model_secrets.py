from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from backend.app.ai.llm_client import _get_api_key
from backend.app.api.routes.model_config import (
    ProviderOut,
    ProviderUpdate,
    _ensure_model_can_deactivate,
    _model_secret_update_data,
)
from backend.app.config import get_settings
from backend.app.services.model_secrets import decrypt_model_secret, encrypt_model_secret

MODEL_ID = UUID("00000000-0000-0000-0000-000000000001")


def test_direct_model_key_is_encrypted_and_can_be_used(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    get_settings.cache_clear()
    try:
        ciphertext = encrypt_model_secret("secret-value")

        assert ciphertext != "secret-value"
        assert decrypt_model_secret(ciphertext) == "secret-value"
        assert _get_api_key(None, ciphertext) == "secret-value"
    finally:
        get_settings.cache_clear()


def test_direct_key_update_keeps_existing_ciphertext_when_key_is_blank() -> None:
    result = _model_secret_update_data(
        ProviderUpdate(secret_mode="direct"),
        current={"secret_mode": "direct", "api_key_encrypted": "ciphertext"},
    )

    assert result == {
        "secret_mode": "direct",
        "api_key_secret_ref": None,
        "api_key_encrypted": "ciphertext",
    }


def test_switching_to_environment_reference_removes_ciphertext() -> None:
    result = _model_secret_update_data(
        ProviderUpdate(secret_mode="env", api_key_secret_ref="MODEL_API_KEY"),
        current={"secret_mode": "direct", "api_key_encrypted": "ciphertext"},
    )

    assert result["api_key_secret_ref"] == "MODEL_API_KEY"
    assert result["api_key_encrypted"] is None


def test_provider_response_never_serializes_ciphertext() -> None:
    output = ProviderOut.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "provider_name": "主模型",
            "model_name": "example-model",
            "provider_type": "openai_compatible",
            "base_url": "https://example.com/v1",
            "secret_mode": "direct",
            "api_key_secret_ref": None,
            "api_key_encrypted": "must-not-leak",
            "secret_configured": True,
            "key_display": "已加密保存",
            "auth_type": "bearer",
            "extra_headers_json": {},
            "extra_config_json": {},
            "is_active": True,
            "is_default": True,
            "created_at": "2026-07-15T00:00:00Z",
            "updated_at": "2026-07-15T00:00:00Z",
            "metadata_json": {},
        }
    ).model_dump()

    assert "api_key_encrypted" not in output
    assert output["key_display"] == "已加密保存"


class _ScalarResult:
    def __init__(self, value: int):
        self.value = value

    def scalar_one(self):
        return self.value


class _ModelConstraintDb:
    def __init__(self, values: list[int]):
        self.values = iter(values)

    def execute(self, _statement, _params):
        return _ScalarResult(next(self.values))


def test_bound_model_cannot_be_deleted() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _ensure_model_can_deactivate(
            _ModelConstraintDb([1]),
            MODEL_ID,
        )

    assert exc_info.value.status_code == 409
    assert "business node" in exc_info.value.detail


def test_final_active_model_cannot_be_deleted() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _ensure_model_can_deactivate(
            _ModelConstraintDb([0, 0]),
            MODEL_ID,
        )

    assert exc_info.value.status_code == 409
    assert "At least one active model" in exc_info.value.detail


def test_unbound_model_can_be_deleted_when_another_model_remains() -> None:
    _ensure_model_can_deactivate(
        _ModelConstraintDb([0, 1]),
        MODEL_ID,
    )
