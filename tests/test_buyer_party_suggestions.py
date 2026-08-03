from backend.app.api.authn import ADMIN_CONTEXT
from backend.app.api.routes.buyer_parties import buyer_party_suggestions


class _MappingResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _FakeDb:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None
        self.params = None

    def execute(self, statement, params):
        self.statement = str(statement)
        self.params = params
        return _MappingResult(self.rows)


def test_buyer_party_suggestions_returns_compact_snippet_for_match() -> None:
    db = _FakeDb(
        [
            {
                "id": "00000000-0000-0000-0000-000000000301",
                "buyer_name": "测试买家",
                "contact_name": "  李经理  ",
                "search_field": "buyer_name",
                "match_type": "buyer",
                "match_text": "测试买家",
            }
        ]
    )

    result = buyer_party_suggestions(
        current_user=ADMIN_CONTEXT,
        q="测试买家",
        limit=5,
        db=db,
    )

    assert result[0]["snippet"] == "李经理"
    assert result[0]["buyer_name"] == "测试买家"
    assert db.params["q"] == "%测试买家%"
