"""The in-progress Writer text, readable by whoever is watching.

There is no worker→browser channel (the queue is a Postgres table; there is no
Redis), so the worker writes the prose as it grows and the SSE endpoint reads
it. That indirection is the whole point: the producer no longer depends on a
browser being connected, which is what used to lose an entire paid generation
whenever a tab closed.

A draft is strictly transient. When the turn finishes, the text moves into
`recommendation_message` as `agent_answer` and the draft is deleted; when the
turn is stopped, the draft is deleted and nothing is promoted. Half a draft is
never an answer.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID


def upsert_answer_draft(
    db: Session,
    *,
    session_id: UUID,
    turn_id: str,
    markdown: str,
) -> None:
    """Replace this turn's draft with the prose so far. Does not commit.

    Whole text rather than an append: the writer holds the full string in
    memory anyway, and storing it outright means a reader never has to
    reassemble fragments or reason about gaps.
    """
    db.execute(
        text(
            """
            insert into recommendation_answer_draft (
              team_id, workspace_id, session_id, turn_id, markdown
            )
            values (:team_id, :workspace_id, :session_id, :turn_id, :markdown)
            on conflict (session_id, turn_id) do update
            set markdown = excluded.markdown,
                updated_at = now()
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "session_id": session_id,
            "turn_id": turn_id,
            "markdown": markdown,
        },
    )


def read_answer_draft(db: Session, *, session_id: UUID, turn_id: str) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select markdown, updated_at::text as updated_at
            from recommendation_answer_draft
            where team_id = :team_id
              and workspace_id = :workspace_id
              and session_id = :session_id
              and turn_id = :turn_id
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "session_id": session_id,
            "turn_id": turn_id,
        },
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


def delete_answer_draft(db: Session, *, session_id: UUID, turn_id: str) -> None:
    """Drop the draft. Does not commit — the caller decides when it is gone."""
    db.execute(
        text(
            """
            delete from recommendation_answer_draft
            where team_id = :team_id
              and workspace_id = :workspace_id
              and session_id = :session_id
              and turn_id = :turn_id
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "session_id": session_id,
            "turn_id": turn_id,
        },
    )
