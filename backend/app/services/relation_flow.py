"""Manual writes to a buyer_intent × seller_target relation.

A relation is the unit of matchmaking progress: one buyer intent paired with
one seller target, with a status pipeline and an event timeline. LLM follow-up
parsing already advances relations through extracted_action_apply; this module
is the consultant driving the same relation by hand from the progress tab.

Both operations here assume the caller has already checked visibility.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.api.routes.utils import write_action_log
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID

# Mirrors the buyer_seller_relation.status check constraint.
RELATION_STATUSES: tuple[str, ...] = (
    "recommended",
    "interested",
    "in_discussion",
    "due_diligence",
    "agreement",
    "deal_closed",
    "not_interested",
    "paused",
    "lost",
)

# Mirrors the relation_event.event_type check constraint.
RELATION_EVENT_TYPES: tuple[str, ...] = (
    "recommended",
    "buyer_interested",
    "buyer_not_interested",
    "meeting",
    "call",
    "material_sent",
    "due_diligence_started",
    "agreement_discussion",
    "deal_closed",
    "paused",
    "internal_note",
    "other",
)

# 状态的中文名，只用于自动生成的动态摘要文案（last_event_summary 是展示字段，
# LLM 路径也存中文摘要，这里保持一致）。
_STATUS_LABELS: dict[str, str] = {
    "recommended": "已推荐",
    "interested": "有意向",
    "in_discussion": "沟通中",
    "due_diligence": "尽调中",
    "agreement": "协议阶段",
    "deal_closed": "已成交",
    "not_interested": "不感兴趣",
    "paused": "暂停",
    "lost": "终止",
}

# A status change records an event; this is the event type it carries.
_STATUS_EVENT_TYPE: dict[str, str] = {
    "recommended": "recommended",
    "interested": "buyer_interested",
    "not_interested": "buyer_not_interested",
    "due_diligence": "due_diligence_started",
    "agreement": "agreement_discussion",
    "deal_closed": "deal_closed",
    "paused": "paused",
}


def _load_relation(db: Session, relation_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select id, buyer_intent_id, buyer_party_id, seller_target_id,
                   status, status_reason, last_event_at, last_event_summary
            from buyer_seller_relation
            where id = :relation_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "relation_id": relation_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relation not found.")
    return dict(row)


def _insert_event(
    db: Session,
    relation: dict[str, Any],
    *,
    actor_user_id: UUID,
    event_type: str,
    title: str | None,
    content: str | None,
    next_step: str | None,
) -> UUID:
    return db.execute(
        text(
            """
            insert into relation_event (
              team_id, workspace_id, relation_id, buyer_intent_id, buyer_party_id,
              seller_target_id, event_type, event_time, title, content, next_step,
              source_type, metadata_json, created_by
            )
            values (
              :team_id, :workspace_id, :relation_id, :buyer_intent_id, :buyer_party_id,
              :seller_target_id, :event_type, now(), :title, :content, :next_step,
              'manual', :metadata_json, :created_by
            )
            returning id
            """
        ).bindparams(bindparam("metadata_json", type_=JSONB)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "relation_id": relation["id"],
            "buyer_intent_id": relation["buyer_intent_id"],
            "buyer_party_id": relation["buyer_party_id"],
            "seller_target_id": relation["seller_target_id"],
            "event_type": event_type,
            "title": title,
            "content": content,
            "next_step": next_step,
            "metadata_json": {},
            "created_by": actor_user_id,
        },
    ).scalar_one()


def _touch_relation_summary(db: Session, relation_id: UUID, summary: str | None) -> None:
    db.execute(
        text(
            """
            update buyer_seller_relation
            set last_event_at = now(),
                last_event_summary = coalesce(:summary, last_event_summary),
                last_contact_at = now(),
                updated_at = now()
            where id = :relation_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "summary": summary,
            "relation_id": relation_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )


def _buyer_party_for_intent(db: Session, buyer_intent_id: UUID) -> UUID | None:
    return db.execute(
        text(
            """
            select buyer_party_id
            from buyer_intent
            where id = :buyer_intent_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).scalar_one_or_none()


def create_relation(
    db: Session,
    *,
    buyer_intent_id: UUID,
    seller_target_id: UUID,
    actor_user_id: UUID,
    source_summary: str | None = None,
) -> tuple[UUID, bool]:
    """Start a matchmaking relation, or return the existing one.

    Returns (relation_id, created). Idempotent on (buyer_intent, seller_target):
    a target already paired with a buyer is not paired twice. On first creation
    the relation opens at 'recommended' with an opening event so it appears on
    both sides' progress tabs immediately.
    """
    existing = db.execute(
        text(
            """
            select id from buyer_seller_relation
            where team_id = :team_id and workspace_id = :workspace_id
              and buyer_intent_id = :buyer_intent_id
              and seller_target_id = :seller_target_id
              and deleted_at is null
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "buyer_intent_id": buyer_intent_id,
            "seller_target_id": seller_target_id,
        },
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    buyer_party_id = _buyer_party_for_intent(db, buyer_intent_id)
    relation_id = db.execute(
        text(
            """
            insert into buyer_seller_relation (
              team_id, workspace_id, buyer_intent_id, buyer_party_id, seller_target_id,
              status, first_recommended_at, last_event_at, last_event_summary,
              last_contact_at, created_by
            )
            values (
              :team_id, :workspace_id, :buyer_intent_id, :buyer_party_id, :seller_target_id,
              'recommended', now(), now(), :summary, now(), :created_by
            )
            returning id
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "buyer_intent_id": buyer_intent_id,
            "buyer_party_id": buyer_party_id,
            "seller_target_id": seller_target_id,
            "summary": source_summary or "开始推进",
            "created_by": actor_user_id,
        },
    ).scalar_one()
    _insert_event(
        db,
        {
            "id": relation_id,
            "buyer_intent_id": buyer_intent_id,
            "buyer_party_id": buyer_party_id,
            "seller_target_id": seller_target_id,
        },
        actor_user_id=actor_user_id,
        event_type="recommended",
        title=None,
        content=source_summary or "开始推进",
        next_step=None,
    )
    db.commit()
    return relation_id, True


def record_relation_event(
    db: Session,
    relation_id: UUID,
    *,
    actor_user_id: UUID,
    event_type: str,
    title: str | None = None,
    content: str | None = None,
    next_step: str | None = None,
) -> UUID:
    """Log a manual event (meeting, call, note, …) on the relation timeline."""
    if event_type not in RELATION_EVENT_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Invalid event_type: {event_type}")
    if not (content or title):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="An event needs a title or content.")

    relation = _load_relation(db, relation_id)
    event_id = _insert_event(
        db,
        relation,
        actor_user_id=actor_user_id,
        event_type=event_type,
        title=title,
        content=content,
        next_step=next_step,
    )
    _touch_relation_summary(db, relation_id, content or title)
    db.commit()
    return event_id


def change_relation_status(
    db: Session,
    relation_id: UUID,
    *,
    actor_user_id: UUID,
    new_status: str,
    status_reason: str | None = None,
    next_step: str | None = None,
) -> dict[str, Any]:
    """Move the relation to a new status, recording an event and an audit log.

    The audit log lands under entity_type buyer_seller_relation, the same place
    the LLM path writes, so manual and parsed status changes read identically in
    the update history and stay rollbackable.
    """
    if new_status not in RELATION_STATUSES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Invalid status: {new_status}")

    relation = _load_relation(db, relation_id)
    old_status = relation["status"]
    if new_status == old_status and not next_step and not status_reason:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Status is already set to this value.")

    summary = status_reason or f"状态更新为「{_STATUS_LABELS.get(new_status, new_status)}」"
    db.execute(
        text(
            """
            update buyer_seller_relation
            set status = :new_status,
                status_reason = :status_reason,
                last_event_at = now(),
                last_event_summary = :summary,
                last_contact_at = now(),
                first_recommended_at = coalesce(first_recommended_at,
                  case when :new_status = 'recommended' then now() else null end),
                updated_at = now()
            where id = :relation_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "new_status": new_status,
            "status_reason": status_reason,
            "summary": summary,
            "relation_id": relation_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    _insert_event(
        db,
        relation,
        actor_user_id=actor_user_id,
        event_type=_STATUS_EVENT_TYPE.get(new_status, "other"),
        title=status_reason,
        content=summary,
        next_step=next_step,
    )
    if new_status != old_status:
        write_action_log(
            db,
            entity_type="buyer_seller_relation",
            entity_id=relation_id,
            field_path="status",
            old_value=old_status,
            new_value=new_status,
            source_type="direct_api",
            applied_by=actor_user_id,
        )
    db.commit()
    return _load_relation(db, relation_id)
