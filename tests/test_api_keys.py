"""外部 Agent 的 API key：签发格式、哈希、闭集 scope、解析与停用（2026-09-07）。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.app.services.api_keys import (
    ADMIN_TOKEN_CONTEXT,
    KEY_PREFIX,
    SCOPE_AGENT_READ,
    SCOPE_AGENT_WRITE,
    generate_api_key,
    hash_api_key,
    looks_like_api_key,
    normalize_scopes,
    resolve_agent_bearer,
    resolve_api_key,
)


class _Result:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self._row


class _FakeDb:
    def __init__(self, row):
        self.row = row
        self.updates: list[str] = []
        self.committed = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        if sql.lstrip().lower().startswith("update"):
            self.updates.append(sql)
            return _Result(None)
        return _Result(self.row)

    def commit(self):
        self.committed += 1

    def rollback(self):
        pass


def test_generated_key_has_prefix_and_only_its_hash_is_stored() -> None:
    plaintext, prefix, digest = generate_api_key()

    assert plaintext.startswith(KEY_PREFIX)
    assert len(plaintext) > len(KEY_PREFIX) + 30
    assert prefix == plaintext[:12] and plaintext.startswith(prefix)
    assert digest == hash_api_key(plaintext)
    assert plaintext not in digest
    assert looks_like_api_key(plaintext)
    assert not looks_like_api_key("eyJhbGciOi")


def test_scopes_are_a_closed_set() -> None:
    assert normalize_scopes([SCOPE_AGENT_READ, SCOPE_AGENT_READ]) == [SCOPE_AGENT_READ]
    assert normalize_scopes(SCOPE_AGENT_WRITE) == [SCOPE_AGENT_WRITE]
    with pytest.raises(ValueError):
        normalize_scopes(["agent:admin"])
    with pytest.raises(ValueError):
        normalize_scopes([])


def test_a_revoked_key_resolves_to_nothing_and_a_live_one_carries_its_scopes() -> None:
    key_id = uuid4()
    live = {
        "id": key_id,
        "name": "wegent",
        "scopes": ["agent:read"],
        "revoked_at": None,
        "last_used_at": None,
    }
    revoked = {**live, "revoked_at": datetime.now(UTC)}

    context = resolve_api_key(_FakeDb(live), "mma_whatever")
    assert context is not None
    assert context.api_key_id == key_id
    assert context.has_scope(SCOPE_AGENT_READ) and not context.has_scope(SCOPE_AGENT_WRITE)
    assert context.actor_label == "api_key:wegent"

    assert resolve_api_key(_FakeDb(revoked), "mma_whatever") is None
    assert resolve_api_key(_FakeDb(live), "not-a-key") is None


def test_last_used_is_written_at_most_once_a_minute() -> None:
    fresh = {
        "id": uuid4(),
        "name": "k",
        "scopes": ["agent:read"],
        "revoked_at": None,
        "last_used_at": datetime.now(UTC) - timedelta(seconds=5),
    }
    stale = {**fresh, "last_used_at": datetime.now(UTC) - timedelta(minutes=5)}

    db = _FakeDb(fresh)
    resolve_api_key(db, "mma_x")
    assert db.updates == []

    db = _FakeDb(stale)
    resolve_api_key(db, "mma_x")
    assert len(db.updates) == 1 and db.committed == 1


def test_the_static_admin_token_is_accepted_without_touching_the_database() -> None:
    class _Explodes:
        def execute(self, *args, **kwargs):
            raise AssertionError("admin token must not hit the api_key table")

    assert (
        resolve_agent_bearer(_Explodes(), "secret-admin", admin_token="secret-admin")
        is ADMIN_TOKEN_CONTEXT
    )
    assert resolve_agent_bearer(_Explodes(), "", admin_token="secret-admin") is None
    assert resolve_agent_bearer(_FakeDb(None), "mma_unknown", admin_token="secret-admin") is None
