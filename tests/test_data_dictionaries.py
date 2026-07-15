from uuid import UUID

from backend.app.api.routes.data_dictionaries import _ensure_unique_term


class _Result:
    def first(self):
        return None


class _Db:
    statement = ""
    params = {}

    def execute(self, statement, params):
        self.statement = str(statement)
        self.params = params
        return _Result()


def test_industry_dictionary_duplicate_check_omits_null_uuid_parameter() -> None:
    db = _Db()

    _ensure_unique_term(db, "制造与工业")

    assert "exclude_id" not in db.statement
    assert "exclude_id" not in db.params


def test_industry_dictionary_duplicate_check_excludes_current_term_on_update() -> None:
    db = _Db()
    term_id = UUID("00000000-0000-0000-0000-000000000501")

    _ensure_unique_term(db, "制造与工业", exclude_id=term_id)

    assert "id <> :exclude_id" in db.statement
    assert db.params["exclude_id"] == term_id
