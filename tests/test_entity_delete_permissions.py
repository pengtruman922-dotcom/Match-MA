from uuid import UUID

from backend.app.api.authn import AuthContext
from backend.app.api.routes import buyer_parties, seller_targets


class _Session:
    def __init__(self) -> None:
        self.committed = False

    def commit(self) -> None:
        self.committed = True


def _consultant() -> AuthContext:
    return AuthContext(
        user_id=UUID("00000000-0000-0000-0000-000000000123"),
        role="consultant",
        name="测试顾问",
    )


def test_consultant_can_delete_owned_seller_target(monkeypatch) -> None:
    db = _Session()
    target_id = UUID("00000000-0000-0000-0000-000000000101")
    writable_calls: list[dict[str, object]] = []
    deleted: list[UUID] = []

    monkeypatch.setattr(seller_targets, "_get_seller_target_or_404", lambda *_: {})
    monkeypatch.setattr(
        seller_targets,
        "ensure_entity_writable",
        lambda _db, user, **kwargs: writable_calls.append({"user_id": user.user_id, **kwargs}),
    )
    monkeypatch.setattr(
        seller_targets,
        "_soft_delete_seller_targets",
        lambda _db, ids, **_: deleted.extend(ids),
    )

    seller_targets.delete_seller_target(target_id, current_user=_consultant(), db=db)

    assert writable_calls == [
        {"user_id": _consultant().user_id, "entity_type": "seller_target", "entity_id": target_id}
    ]
    assert deleted == [target_id]
    assert db.committed


def test_consultant_can_delete_owned_buyer_party(monkeypatch) -> None:
    db = _Session()
    party_id = UUID("00000000-0000-0000-0000-000000000201")
    writable_calls: list[dict[str, object]] = []
    deleted: list[UUID] = []

    monkeypatch.setattr(buyer_parties, "_get_buyer_party_or_404", lambda *_: {})
    monkeypatch.setattr(
        buyer_parties,
        "ensure_entity_writable",
        lambda _db, user, **kwargs: writable_calls.append({"user_id": user.user_id, **kwargs}),
    )
    monkeypatch.setattr(
        buyer_parties,
        "_soft_delete_buyer_parties",
        lambda _db, ids, **_: deleted.extend(ids),
    )

    buyer_parties.delete_buyer_party(party_id, current_user=_consultant(), db=db)

    assert writable_calls == [
        {"user_id": _consultant().user_id, "entity_type": "buyer_party", "entity_id": party_id}
    ]
    assert deleted == [party_id]
    assert db.committed
