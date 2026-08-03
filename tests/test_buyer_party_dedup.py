from uuid import UUID

from backend.app.api.authn import AuthContext
from backend.app.api.routes.buyer_parties import buyer_party_dedup_check


class _MappingResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def mappings(self) -> "_MappingResult":
        return self

    def all(self) -> list[dict[str, object]]:
        return self.rows


class _RecordingSession:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.sql = ""
        self.params: dict[str, object] = {}

    def execute(self, statement: object, params: dict[str, object]) -> _MappingResult:
        self.sql = str(statement)
        self.params = params
        return _MappingResult(self.rows)


def _user() -> AuthContext:
    return AuthContext(
        user_id=UUID("00000000-0000-0000-0000-000000000123"),
        role="consultant",
        name="测试用户",
    )


def test_dedup_check_searches_all_buyers_with_ilike_and_returns_ids() -> None:
    buyer_id = UUID("10000000-0000-0000-0000-000000000001")
    row = {
        "id": buyer_id,
        "buyer_name": "北控集团有限公司",
        "owner_name": "其他顾问",
        "match_type": "buyer_name",
        "status": "active",
    }
    db = _RecordingSession([row])

    result = buyer_party_dedup_check(current_user=_user(), q=" 北控集团 ", limit=None, db=db)

    assert result == {"exists": True, "query": "北控集团", "matches": [row]}
    assert "bp.buyer_name ilike :name_pattern" in db.sql
    assert "bp.legal_name" not in db.sql
    assert "alias_name ilike :name_pattern" in db.sql
    assert "owner_user_id = :scope_user_id" not in db.sql
    assert " limit " not in f" {db.sql.lower()} "
    assert db.params["name_pattern"] == "%北控集团%"


def test_dedup_check_escapes_ilike_wildcards() -> None:
    db = _RecordingSession([])

    buyer_party_dedup_check(current_user=_user(), q=r"100%_资本", limit=None, db=db)

    assert db.params["name_pattern"] == r"%100\%\_资本%"
