"""Recommendation-session debug must expose its directly linked Agent trace."""

from uuid import uuid4

from backend.app.api.routes.debug import _recommendation_traces


class _Rows:
    def mappings(self):
        return self

    def all(self):
        return []


class _Db:
    statement = ""
    params = {}

    def execute(self, statement, params):
        self.statement = str(statement)
        self.params = params
        return _Rows()


def test_session_debug_queries_direct_recommendation_session_trace_link() -> None:
    db = _Db()
    session_id = uuid4()

    assert _recommendation_traces(db, session_id) == []
    assert "entity_type = 'recommendation_session'" in db.statement
    assert "entity_id = :session_id" in db.statement
    assert db.params["session_id"] == session_id
