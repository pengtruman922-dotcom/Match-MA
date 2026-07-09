from backend.app.api.routes.buyer_parties import BuyerPartyDedupMatchOut


def test_buyer_party_dedup_match_does_not_expose_entity_id() -> None:
    fields = set(BuyerPartyDedupMatchOut.model_fields)

    assert "id" not in fields
    assert {"buyer_name", "legal_name", "owner_name", "match_type", "status"}.issubset(fields)
