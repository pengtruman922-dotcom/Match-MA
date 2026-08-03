from backend.app.api.routes.buyer_parties import BuyerPartyDedupMatchOut


def test_buyer_party_dedup_match_exposes_entity_id_for_cross_owner_reuse() -> None:
    fields = set(BuyerPartyDedupMatchOut.model_fields)

    assert {"id", "buyer_name", "owner_name", "match_type", "status"}.issubset(fields)
