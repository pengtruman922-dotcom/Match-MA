"""Draft row and terminal answer write, executed against a real Postgres.

Neither can be checked without a database. The draft leans on an ON CONFLICT
against a unique index that only exists in migration 019, and the answer write
serialises two racing producers with `pg_advisory_xact_lock` — a fake session
proves nothing about either.

Skipped unless DATABASE_URL points at a migrated database; CI runs them in the
`Fresh database from baseline` job, which already has one.
"""

import os
from uuid import uuid4

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="needs a migrated Postgres (DATABASE_URL)",
)

TURN_ID = "turn-sql-1"


@pytest.fixture
def db():
    from backend.app.db import session_scope

    with session_scope() as session:
        yield session


@pytest.fixture
def session_id(db):
    from backend.app.constants import (
        DEFAULT_ADMIN_USER_ID,
        DEFAULT_TEAM_ID,
        DEFAULT_WORKSPACE_ID,
    )

    new_id = uuid4()
    db.execute(
        text(
            """
            insert into recommendation_session (
              id, team_id, workspace_id, mode, created_by
            )
            values (:id, :team_id, :workspace_id, 'buyer_to_target', :created_by)
            """
        ),
        {
            "id": new_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "created_by": DEFAULT_ADMIN_USER_ID,
        },
    )
    db.commit()
    yield new_id
    db.execute(text("delete from recommendation_message where session_id = :id"), {"id": new_id})
    db.execute(
        text("delete from recommendation_answer_draft where session_id = :id"), {"id": new_id}
    )
    db.execute(text("delete from recommendation_session where id = :id"), {"id": new_id})
    db.commit()


# -- the draft row -------------------------------------------------------


def test_a_turn_has_at_most_one_draft_and_the_latest_text_wins(db, session_id) -> None:
    from backend.app.services.recommendation_answer_draft import (
        read_answer_draft,
        upsert_answer_draft,
    )

    upsert_answer_draft(db, session_id=session_id, turn_id=TURN_ID, markdown="推荐杭州")
    upsert_answer_draft(db, session_id=session_id, turn_id=TURN_ID, markdown="推荐杭州XX精密制造。")
    db.commit()

    row = read_answer_draft(db, session_id=session_id, turn_id=TURN_ID)
    assert row["markdown"] == "推荐杭州XX精密制造。"
    count = db.execute(
        text("select count(*) from recommendation_answer_draft where session_id = :id"),
        {"id": session_id},
    ).scalar_one()
    assert count == 1


def test_the_draft_timestamp_moves_so_staleness_is_observable(db, session_id) -> None:
    from backend.app.services.recommendation_answer_draft import (
        read_answer_draft,
        upsert_answer_draft,
    )

    upsert_answer_draft(db, session_id=session_id, turn_id=TURN_ID, markdown="一")
    db.commit()
    first = read_answer_draft(db, session_id=session_id, turn_id=TURN_ID)["updated_at"]
    db.execute(
        text(
            """
            update recommendation_answer_draft
            set updated_at = now() - interval '1 minute'
            where session_id = :id
            """
        ),
        {"id": session_id},
    )
    db.commit()

    upsert_answer_draft(db, session_id=session_id, turn_id=TURN_ID, markdown="一二")
    db.commit()

    assert read_answer_draft(db, session_id=session_id, turn_id=TURN_ID)["updated_at"] >= first


def test_deleting_a_draft_that_is_not_there_is_not_an_error(db, session_id) -> None:
    from backend.app.services.recommendation_answer_draft import (
        delete_answer_draft,
        read_answer_draft,
    )

    delete_answer_draft(db, session_id=session_id, turn_id=TURN_ID)
    db.commit()

    assert read_answer_draft(db, session_id=session_id, turn_id=TURN_ID) is None


def test_drafts_disappear_with_the_session_they_belong_to(db) -> None:
    """草稿是进行中的中间态，没有独立的保留价值。"""
    from backend.app.constants import (
        DEFAULT_ADMIN_USER_ID,
        DEFAULT_TEAM_ID,
        DEFAULT_WORKSPACE_ID,
    )
    from backend.app.services.recommendation_answer_draft import (
        read_answer_draft,
        upsert_answer_draft,
    )

    doomed = uuid4()
    db.execute(
        text(
            """
            insert into recommendation_session (id, team_id, workspace_id, mode, created_by)
            values (:id, :team_id, :workspace_id, 'buyer_to_target', :created_by)
            """
        ),
        {
            "id": doomed,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "created_by": DEFAULT_ADMIN_USER_ID,
        },
    )
    upsert_answer_draft(db, session_id=doomed, turn_id=TURN_ID, markdown="正文")
    db.commit()

    db.execute(text("delete from recommendation_session where id = :id"), {"id": doomed})
    db.commit()

    assert read_answer_draft(db, session_id=doomed, turn_id=TURN_ID) is None


# -- the terminal answer write -------------------------------------------


def _insert(db, session_id, markdown="正文"):
    from backend.app.services.recommendation_flow import insert_agent_answer_message

    return insert_agent_answer_message(
        db,
        session_id=session_id,
        turn_id=TURN_ID,
        markdown=markdown,
        model_name="writer",
        generation_mode="llm",
        duration_ms=46700,
    )


def test_the_first_producer_writes_the_answer(db, session_id) -> None:
    write = _insert(db, session_id)
    db.commit()

    assert write.status == "inserted"
    assert write.message_id is not None


def test_a_second_producer_does_not_append_a_duplicate_answer(db, session_id) -> None:
    """双页签 / job 重排都可能让两个生产者跑同一轮，正文只能有一份。"""
    first = _insert(db, session_id, markdown="第一份")
    db.commit()
    second = _insert(db, session_id, markdown="第二份")
    db.commit()

    assert second.status == "already_exists"
    assert second.message_id == first.message_id
    count = db.execute(
        text(
            """
            select count(*)
            from recommendation_message
            where session_id = :id
              and metadata_json ->> 'message_type' = 'agent_answer'
            """
        ),
        {"id": session_id},
    ).scalar_one()
    assert count == 1


def test_a_stopped_turn_refuses_the_answer_even_after_it_was_generated(db, session_id) -> None:
    from backend.app.services.recommendation_flow import insert_agent_aborted_message

    insert_agent_aborted_message(db, session_id=session_id, turn_id=TURN_ID)
    db.commit()

    write = _insert(db, session_id)
    db.commit()

    assert write.status == "aborted"
    assert write.message_id is None


def test_find_agent_answer_id_matches_the_full_reader(db, session_id) -> None:
    """锁内用的轻量查询和页面用的完整解码必须指向同一行。"""
    from backend.app.services.recommendation_flow import (
        find_agent_answer_id,
        find_agent_turn_answer,
    )

    written = _insert(db, session_id, markdown="唯一正文")
    db.commit()

    assert find_agent_answer_id(db, session_id, TURN_ID) == written.message_id
    full = find_agent_turn_answer(db, session_id, TURN_ID)
    assert full["id"] == written.message_id
    assert full["markdown"] == "唯一正文"
    assert full["duration_ms"] == 46700
