from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.api.authn import AuthContext, require_admin
from backend.app.api.routes.utils import owner_filter_condition, owner_scope_required
from backend.app.config import get_settings
from backend.app.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    stored = hash_password("s3cret-pass")

    assert stored.startswith("scrypt$")
    assert len(stored.split("$")) == 6
    assert verify_password("s3cret-pass", stored)
    assert not verify_password("wrong-pass", stored)


def test_verify_password_rejects_malformed_hash() -> None:
    assert not verify_password("whatever", "not-a-hash")
    assert not verify_password("whatever", "md5$1$2$3$abc$def")


def test_access_token_roundtrip_and_tamper_rejection() -> None:
    user_id = str(uuid4())
    token = create_access_token(
        secret="unit-test-secret",
        user_id=user_id,
        role="consultant",
        name="测试顾问",
        expires_in_seconds=60,
    )

    payload = decode_access_token(token, secret="unit-test-secret")
    assert payload is not None
    assert payload["sub"] == user_id
    assert payload["role"] == "consultant"

    assert decode_access_token(token, secret="other-secret") is None
    header, body, signature = token.split(".")
    assert decode_access_token(f"{header}.{body}x.{signature}", secret="unit-test-secret") is None


def test_access_token_expiry() -> None:
    token = create_access_token(
        secret="unit-test-secret",
        user_id=str(uuid4()),
        role="admin",
        name="x",
        expires_in_seconds=-1,
    )
    assert decode_access_token(token, secret="unit-test-secret") is None


def test_require_admin_blocks_consultant() -> None:
    consultant = AuthContext(user_id=uuid4(), role="consultant", name="顾问")
    admin = AuthContext(user_id=uuid4(), role="admin", name="管理员")

    require_admin(admin)
    with pytest.raises(HTTPException) as exc_info:
        require_admin(consultant)
    assert exc_info.value.status_code == 403


def test_owner_filter_condition_parsing() -> None:
    assert owner_filter_condition(None) is None
    assert owner_filter_condition("") is None
    assert owner_filter_condition("unassigned") == ("owner_user_id is null", None)

    user_id = uuid4()
    condition = owner_filter_condition(str(user_id), column="bi.owner_user_id")
    assert condition == ("bi.owner_user_id = :owner_user_id", user_id)

    with pytest.raises(HTTPException):
        owner_filter_condition("not-a-uuid")


def test_owner_scope_required_respects_setting_and_admin_role(monkeypatch) -> None:
    admin = AuthContext(user_id=uuid4(), role="admin", name="admin")
    consultant = AuthContext(user_id=uuid4(), role="consultant", name="consultant")

    monkeypatch.setenv("OWNER_SCOPE_ENFORCED", "false")
    get_settings.cache_clear()
    assert owner_scope_required(admin) is False
    assert owner_scope_required(consultant) is False

    monkeypatch.setenv("OWNER_SCOPE_ENFORCED", "true")
    get_settings.cache_clear()
    assert owner_scope_required(admin) is False
    assert owner_scope_required(consultant) is True
    get_settings.cache_clear()
