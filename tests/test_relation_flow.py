"""Relation status/event constants must track the DB check constraints.

Manual progress writes validate status and event_type against these tuples
before touching the database. If the baseline widens or narrows the check
constraint and the tuple is not updated, the API would reject values the DB
accepts (or vice versa), so this pins the two together.
"""

import re
from pathlib import Path

import pytest

from backend.app.services.relation_flow import (
    RELATION_EVENT_TYPES,
    RELATION_STATUSES,
    change_relation_status,
    record_relation_event,
)

BASELINE = Path(__file__).resolve().parents[1] / "database" / "migrations" / "001_baseline.sql"


def _enum_containing(column: str, sentinel: str) -> set[str]:
    """The ARRAY enum for `column` — disambiguated by a value unique to it,
    since several tables have a `status` column with different enums."""
    sql = BASELINE.read_text(encoding="utf-8")
    for match in re.finditer(column + r" = ANY \(ARRAY\[(.*?)\]\)", sql, re.S):
        values = set(re.findall(r"'([a-z_]+)'", match.group(1)))
        if sentinel in values:
            return values
    raise AssertionError(f"{column} check constraint containing {sentinel!r} not found in the baseline")


def test_relation_statuses_match_the_check_constraint() -> None:
    assert set(RELATION_STATUSES) == _enum_containing("status", "in_discussion")


def test_relation_event_types_match_the_check_constraint() -> None:
    assert set(RELATION_EVENT_TYPES) == _enum_containing("event_type", "material_sent")


class _RejectingDb:
    """Any DB access means validation let a bad value through."""

    def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("validation should have rejected the input before any query")

    def commit(self) -> None:
        raise AssertionError("validation should have rejected the input before commit")


def test_invalid_status_is_rejected_before_touching_the_db() -> None:
    with pytest.raises(Exception) as exc:
        change_relation_status(_RejectingDb(), _uuid(), actor_user_id=_uuid(), new_status="nonsense")
    assert "Invalid status" in str(exc.value.detail)


def test_invalid_event_type_is_rejected_before_touching_the_db() -> None:
    with pytest.raises(Exception) as exc:
        record_relation_event(_RejectingDb(), _uuid(), actor_user_id=_uuid(), event_type="nonsense", content="x")
    assert "Invalid event_type" in str(exc.value.detail)


def test_empty_event_is_rejected() -> None:
    with pytest.raises(Exception) as exc:
        record_relation_event(_RejectingDb(), _uuid(), actor_user_id=_uuid(), event_type="call")
    assert "title or content" in str(exc.value.detail)


def _uuid():
    from uuid import uuid4

    return uuid4()
