"""The unified seller_target write channel: validation, diff, no-op.

The audit/field-source/search-doc helpers it calls are covered by their own
paths' tests; here we pin the writer's own logic — that it rejects non-registry
columns, writes only what changed, and returns the applied fields — by
recording the downstream calls.
"""

from uuid import uuid4

import pytest

import backend.app.services.field_writer as fw
from backend.app.services.field_writer import (
    FieldWriteError,
    WriteProvenance,
    write_seller_target_fields,
)


class _Result:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self._row


class _Db:
    """Answers the writer's current-value SELECT, records everything else."""

    def __init__(self, current: dict):
        self._current = current
        self.updates: list[str] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        if sql.strip().lower().startswith("\n            select") or "from seller_target" in sql and "update" not in sql.lower():
            return _Result(dict(self._current))
        self.updates.append(sql)
        return _Result(None)


@pytest.fixture
def recorded(monkeypatch):
    calls = {"logs": None, "sources": None, "search": None}

    def _logs(db, **kwargs):
        calls["logs"] = kwargs

    def _sources(db, **kwargs):
        calls["sources"] = kwargs

    def _search(db, **kwargs):
        calls["search"] = kwargs

    monkeypatch.setattr(fw, "write_action_logs_for_diff", _logs)
    monkeypatch.setattr(fw, "write_field_value_sources_for_diff", _sources)
    monkeypatch.setattr(fw, "create_search_doc_rebuild_job", _search)
    return calls


def _prov():
    return WriteProvenance(source_type="research_proposal", actor_user_id=uuid4())


def test_unknown_column_is_rejected_before_any_write() -> None:
    class _Boom:
        def execute(self, *a, **k):
            raise AssertionError("must reject before touching the db")

    with pytest.raises(FieldWriteError) as exc:
        write_seller_target_fields(_Boom(), uuid4(), {"not_a_column": "x"}, provenance=_prov(), search_doc_source="t")
    assert "not_a_column" in str(exc.value)


def test_empty_changes_is_a_noop() -> None:
    class _Boom:
        def execute(self, *a, **k):
            raise AssertionError("no db for empty changes")

    assert write_seller_target_fields(_Boom(), uuid4(), {}, provenance=_prov(), search_doc_source="t") == []


def test_no_actual_change_writes_nothing(recorded) -> None:
    db = _Db({"business_summary": "同一段话"})
    applied = write_seller_target_fields(
        db, uuid4(), {"business_summary": "同一段话"}, provenance=_prov(), search_doc_source="t"
    )
    assert applied == []
    assert not db.updates
    assert recorded["logs"] is None and recorded["sources"] is None and recorded["search"] is None


def test_real_change_updates_audits_and_returns_fields(recorded) -> None:
    db = _Db({"business_summary": "旧", "listed_status": "unknown"})
    applied = write_seller_target_fields(
        db,
        uuid4(),
        {"business_summary": "新", "listed_status": "listed"},
        provenance=_prov(),
        search_doc_source="research_proposal_accept",
    )
    assert set(applied) == {"business_summary", "listed_status"}
    assert db.updates, "expected an UPDATE"
    assert set(recorded["logs"]["diff"]) == {"business_summary", "listed_status"}
    assert recorded["sources"]["diff"], "field-value source recorded"
    assert recorded["search"]["source"] == "research_proposal_accept"


def test_field_source_can_be_suppressed(recorded) -> None:
    db = _Db({"business_summary": "旧"})
    prov = WriteProvenance(source_type="research_proposal", actor_user_id=uuid4(), write_field_source=False)
    write_seller_target_fields(db, uuid4(), {"business_summary": "新"}, provenance=prov, search_doc_source="t")
    assert recorded["logs"] is not None
    assert recorded["sources"] is None


def test_writer_rejects_a_registry_field_when_the_source_is_not_authorized() -> None:
    class _Boom:
        def execute(self, *a, **k):
            raise AssertionError("authorization must reject before reading the db")

    # 报价是卖方私下向顾问表达的诉求，公开渠道不存在，调研永远不该写它 ——
    # 财务数字自 0728 起对调研开放，这里换一个仍然关闭的字段守同一个边界。
    with pytest.raises(FieldWriteError, match="research may not write"):
        write_seller_target_fields(
            _Boom(),
            uuid4(),
            {"asking_price_yuan": 100},
            provenance=_prov(),
            search_doc_source="t",
        )


def test_manual_write_is_recorded_with_the_real_actor(recorded) -> None:
    actor = uuid4()
    db = _Db({"current_revenue_yuan": 1})
    write_seller_target_fields(
        db,
        uuid4(),
        {"current_revenue_yuan": 100},
        provenance=WriteProvenance(source_type="manual_edit", writer="manual", actor_user_id=actor),
        search_doc_source="t",
    )
    assert recorded["sources"]["created_by"] == actor
