from pathlib import Path
from uuid import UUID

from backend.app.api.authn import AuthContext
from backend.app.api.routes import buyer_intents, buyer_parties, seller_targets


REPO = Path(__file__).resolve().parents[1]


class _Session:
    def __init__(self) -> None:
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _EmptyRows:
    def mappings(self):
        return self

    def all(self) -> list[dict[str, object]]:
        return []


class _SqlSession:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.params: list[dict[str, object]] = []

    def execute(self, statement, params):
        self.statements.append(str(statement))
        self.params.append(params)
        return _EmptyRows()


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


def test_consultant_can_delete_owned_buyer_intent(monkeypatch) -> None:
    db = _Session()
    intent_id = UUID("00000000-0000-0000-0000-000000000301")
    writable_calls: list[dict[str, object]] = []
    deleted: list[UUID] = []

    monkeypatch.setattr(buyer_intents, "_get_buyer_intent_or_404", lambda *_: {})
    monkeypatch.setattr(
        buyer_intents,
        "ensure_entity_writable",
        lambda _db, user, **kwargs: writable_calls.append({"user_id": user.user_id, **kwargs}),
    )
    monkeypatch.setattr(
        buyer_intents,
        "_soft_delete_buyer_intents",
        lambda _db, ids, **_: deleted.extend(ids),
    )

    buyer_intents.delete_buyer_intent(intent_id, current_user=_consultant(), db=db)

    assert writable_calls == [
        {"user_id": _consultant().user_id, "entity_type": "buyer_intent", "entity_id": intent_id}
    ]
    assert deleted == [intent_id]
    assert db.committed


def test_consultant_bulk_delete_is_scoped_to_owned_entities(monkeypatch) -> None:
    cases = [
        (
            seller_targets,
            "_soft_delete_seller_targets",
            seller_targets.SellerTargetBulkDeleteRequest,
            seller_targets.bulk_delete_seller_targets,
        ),
        (
            buyer_parties,
            "_soft_delete_buyer_parties",
            buyer_parties.BuyerPartyBulkDeleteRequest,
            buyer_parties.bulk_delete_buyer_parties,
        ),
        (
            buyer_intents,
            "_soft_delete_buyer_intents",
            buyer_intents.BuyerIntentBulkDeleteRequest,
            buyer_intents.bulk_delete_buyer_intents,
        ),
    ]
    entity_ids = [
        UUID("00000000-0000-0000-0000-000000000401"),
        UUID("00000000-0000-0000-0000-000000000402"),
    ]

    for module, helper_name, payload_type, route in cases:
        db = _Session()
        calls: list[dict[str, object]] = []

        def scoped_delete(_db, ids, **kwargs):
            calls.append({"ids": ids, **kwargs})
            return ids[:1]

        monkeypatch.setattr(module, helper_name, scoped_delete)
        result = route(payload_type(ids=entity_ids), current_user=_consultant(), db=db)

        assert calls == [
            {
                "ids": entity_ids,
                "actor_user_id": _consultant().user_id,
                "owner_user_id": _consultant().user_id,
            }
        ]
        assert result["deleted_ids"] == entity_ids[:1]
        assert result["skipped_ids"] == entity_ids[1:]
        assert db.committed


def test_bulk_delete_owner_scope_is_enforced_in_update_sql() -> None:
    entity_id = UUID("00000000-0000-0000-0000-000000000501")
    cases = [
        seller_targets._soft_delete_seller_targets,
        buyer_parties._soft_delete_buyer_parties,
        buyer_intents._soft_delete_buyer_intents,
    ]

    for soft_delete in cases:
        db = _SqlSession()
        soft_delete(
            db,
            [entity_id],
            actor_user_id=_consultant().user_id,
            owner_user_id=_consultant().user_id,
        )

        assert "and owner_user_id = :owner_user_id" in db.statements[0]
        assert db.params[0]["owner_user_id"] == _consultant().user_id


def test_frontend_delete_actions_use_owned_entity_permission() -> None:
    bulk_bar = (REPO / "frontend/src/components/BulkActionBar.tsx").read_text(encoding="utf-8")
    buyer_list = (REPO / "frontend/src/features/buyers/IntentsList.tsx").read_text(encoding="utf-8")

    assert '<button onClick={onDelete} disabled={deleting}' in bulk_bar
    assert "{admin && (\n          <button onClick={onDelete}" not in bulk_bar
    assert "const canDelete = canManageOwnedEntity(item.owner_user_id);" in buyer_list
    assert "{canDelete && (" in buyer_list
    assert "{isAdmin() && (" not in buyer_list
