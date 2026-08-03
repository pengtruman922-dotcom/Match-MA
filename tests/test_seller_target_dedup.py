from uuid import UUID

from backend.app.api.authn import AuthContext
from backend.app.api.routes.seller_targets import seller_target_dedup_check


class _ScalarResult:
    def __init__(self, names: list[str]) -> None:
        self.names = names

    def scalars(self) -> "_ScalarResult":
        return self

    def all(self) -> list[str]:
        return self.names


class _RecordingSession:
    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.sql = ""
        self.params: dict[str, object] = {}

    def execute(self, statement: object, params: dict[str, object]) -> _ScalarResult:
        self.sql = str(statement)
        self.params = params
        return _ScalarResult(self.names)


def _user(*, role: str = "consultant") -> AuthContext:
    return AuthContext(
        user_id=UUID("00000000-0000-0000-0000-000000000123"),
        role=role,
        name="测试用户",
    )


def test_dedup_check_only_searches_current_owners_target_names() -> None:
    db = _RecordingSession(["张三科技有限公司"])

    result = seller_target_dedup_check(current_user=_user(), q=" 张三科技 ", db=db)

    assert result == {"query": "张三科技", "matches": ["张三科技有限公司"]}
    assert "target_name ilike :name_pattern" in db.sql
    assert "owner_user_id = :owner_user_id" in db.sql
    assert "deleted_at is null" in db.sql
    assert "target_subject_name" not in db.sql
    assert "business_summary" not in db.sql
    assert db.params["owner_user_id"] == _user().user_id
    assert db.params["name_pattern"] == "%张三科技%"


def test_dedup_check_does_not_expand_admin_scope_and_escapes_wildcards() -> None:
    db = _RecordingSession([])

    seller_target_dedup_check(current_user=_user(role="admin"), q=r"100%_科技", db=db)

    assert db.params["owner_user_id"] == _user(role="admin").user_id
    assert db.params["name_pattern"] == r"%100\%\_科技%"
    assert " limit " not in f" {db.sql.lower()} "
