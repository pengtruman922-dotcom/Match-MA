"""Profile writes in the update timeline, and undoing them.

Auto-accepting researched profiles is only safe because every write lands in
更新记录 and can be rolled back. These tests cover that chain rather than the
research agent that produces the writes.
"""

from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from backend.app.api.routes.update_logs import (
    _apply_field_rollback,
    _get_current_field_value,
    _profile_section_code,
    _rollbackability,
)
from backend.app.services.profile_sections import (
    PROFILE_SECTION_FIELD_PREFIX,
    apply_profile_section,
)

ENTITY_ID = UUID("11111111-1111-1111-1111-111111111111")
USER_ID = UUID("22222222-2222-2222-2222-222222222222")
NEW_SECTION_ID = uuid4()
OLD_SECTION_ID = uuid4()


class _Db:
    """Records statements; replays a superseded row then the inserted row."""

    def __init__(self, *, had_previous: bool = True) -> None:
        self.statements: list[tuple[str, dict]] = []
        self._had_previous = had_previous

    def execute(self, statement, params=None):
        rendered = str(statement)
        self.statements.append((rendered, dict(params or {})))
        outer = self

        class _Result:
            def mappings(self):
                return self

            def all(self):
                if "deleted_at = now()" in rendered and "returning" in rendered:
                    if not outer._had_previous:
                        return []
                    return [
                        {
                            "id": OLD_SECTION_ID,
                            "info_status": "filled",
                            "content_text": "旧版画像",
                        }
                    ]
                return []

            def one(self):
                return {
                    "id": NEW_SECTION_ID,
                    "info_status": "filled",
                    "content_text": "新版画像",
                }

            def one_or_none(self):
                return None

        return _Result()

    def find(self, fragment: str) -> list[tuple[str, dict]]:
        return [item for item in self.statements if fragment in item[0]]


def test_writing_a_section_lands_in_the_update_timeline() -> None:
    """画像不是实体的列，此前完全不进 action_application_log ——
    调研改了画像，更新记录里看不到，也回滚不了。"""
    db = _Db()

    apply_profile_section(
        db,
        entity_type="seller_target",
        entity_id=ENTITY_ID,
        section_code="ops_quality",
        info_status="filled",
        content_text="新版画像",
        review_status="auto_accepted",
        user_id=USER_ID,
        log_source_type="research_proposal",
    )

    logs = db.find("insert into action_application_log")
    assert len(logs) == 1
    params = logs[0][1]
    assert params["field_path"] == f"{PROFILE_SECTION_FIELD_PREFIX}ops_quality"
    assert params["old_value_json"] == {"info_status": "filled", "content_text": "旧版画像"}
    assert params["new_value_json"] == {"info_status": "filled", "content_text": "新版画像"}
    assert params["source_type"] == "research_proposal"
    assert params["applied_by"] == USER_ID
    metadata = params["metadata_json"]
    assert metadata["profile_section_id"] == str(NEW_SECTION_ID)
    assert metadata["superseded_profile_section_id"] == str(OLD_SECTION_ID)
    assert metadata["section_label"] == "经营质量"


def test_first_write_records_no_previous_value() -> None:
    db = _Db(had_previous=False)

    apply_profile_section(
        db,
        entity_type="seller_target",
        entity_id=ENTITY_ID,
        section_code="ops_quality",
        info_status="not_found",
        content_text=None,
        user_id=USER_ID,
    )

    params = db.find("insert into action_application_log")[0][1]
    assert params["old_value_json"] is None
    assert params["metadata_json"]["superseded_profile_section_id"] is None


def test_profile_field_paths_are_recognized_and_bounded() -> None:
    assert _profile_section_code("profile_section.ops_quality") == "ops_quality"
    assert _profile_section_code("profile_section.not_a_section") is None
    assert _profile_section_code("current_revenue_yuan") is None
    assert _profile_section_code(None) is None


def test_profile_logs_are_rollbackable_without_being_entity_columns() -> None:
    """画像不在 ROLLBACK_FIELDS_BY_ENTITY 里，需要单独放行。"""
    log = {
        "entity_type": "seller_target",
        "field_path": "profile_section.ops_quality",
        "can_rollback": True,
        "rollback_at": None,
        "source_type": "research_proposal",
    }

    assert _rollbackability(log) == {"ok": True, "reason": None}
    assert _rollbackability({**log, "rollback_at": "2026-07-21"})["ok"] is False
    assert _rollbackability({**log, "field_path": "profile_section.nope"})["ok"] is False


def test_rollback_retires_the_new_revision_and_revives_the_old_one() -> None:
    """每一版都还在表里，所以回滚是恢复版本而不是照日志重建文本。"""
    db = _Db()
    log = {
        "entity_type": "seller_target",
        "entity_id": ENTITY_ID,
        "field_path": "profile_section.ops_quality",
        "metadata_json": {
            "profile_section_id": str(NEW_SECTION_ID),
            "superseded_profile_section_id": str(OLD_SECTION_ID),
        },
    }

    _apply_field_rollback(db, log, actor_user_id=USER_ID)

    retire = db.find("set deleted_at = now()")
    revive = db.find("set deleted_at = null")
    assert retire[0][1]["section_id"] == str(NEW_SECTION_ID)
    assert revive[0][1]["section_id"] == str(OLD_SECTION_ID)


def test_rollback_of_a_first_write_leaves_nothing_to_revive() -> None:
    db = _Db()
    log = {
        "entity_type": "seller_target",
        "entity_id": ENTITY_ID,
        "field_path": "profile_section.ops_quality",
        "metadata_json": {"profile_section_id": str(NEW_SECTION_ID)},
    }

    _apply_field_rollback(db, log, actor_user_id=USER_ID)

    assert db.find("set deleted_at = now()")
    assert db.find("set deleted_at = null") == []


def test_rollback_refuses_logs_written_before_this_chain_existed() -> None:
    """老日志没有 profile_section_id，无从确定要恢复哪一版 —— 明确拒绝，
    而不是猜一个版本回去。"""
    db = _Db()
    log = {
        "entity_type": "seller_target",
        "entity_id": ENTITY_ID,
        "field_path": "profile_section.ops_quality",
        "metadata_json": {},
    }

    with pytest.raises(HTTPException) as excinfo:
        _apply_field_rollback(db, log, actor_user_id=USER_ID)

    assert excinfo.value.status_code == 409


def test_current_value_check_reads_the_section_row() -> None:
    db = _Db()

    value = _get_current_field_value(
        db,
        {
            "entity_type": "seller_target",
            "entity_id": ENTITY_ID,
            "field_path": "profile_section.ops_quality",
            "metadata_json": {"profile_section_id": str(NEW_SECTION_ID)},
        },
    )

    assert value is None
    assert db.find("from entity_profile_section")
