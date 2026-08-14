"""Manual writes to a buyer_intent × seller_target relation.

A relation is the unit of matchmaking progress: one buyer intent paired with
one seller target, with a status pipeline and an event timeline. This module
owns both consultant-written events and the editable placeholder that an AI
follow-up job fills asynchronously.

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
from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.services.entity_grade import BLOCKED_GRADE

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

# “正在深入推进”只表示仍在进行中的深度阶段。推荐结果与关系详情必须
# 共同引用这一份口径，避免早期接触或已经成交的关系被误标为正在深入推进。
DEEP_PROGRESS_STATUSES: tuple[str, ...] = (
    "due_diligence",
    "agreement",
)

# Mirrors the relation_event.event_type check constraint.
RELATION_EVENT_TYPES: tuple[str, ...] = (
    "recommended",
    "buyer_interested",
    "buyer_not_interested",
    "meeting",
    "call",
    "message",
    "email",
    "material_sent",
    "quote_update",
    "nda_signed",
    "management_meeting",
    "due_diligence_started",
    "due_diligence_progress",
    "agreement_discussion",
    "exclusivity",
    "deal_closed",
    "paused",
    "internal_note",
    "other",
)

RELATION_EVENT_LABELS: dict[str, str] = {
    "recommended": "推荐", "buyer_interested": "买家有意向", "buyer_not_interested": "买家暂不考虑",
    "meeting": "会议沟通", "call": "电话沟通", "message": "即时消息", "email": "邮件沟通",
    "material_sent": "发送材料", "quote_update": "报价更新", "nda_signed": "签署保密协议",
    "management_meeting": "管理层会谈", "due_diligence_started": "启动尽调",
    "due_diligence_progress": "尽调进展", "agreement_discussion": "协议讨论",
    "exclusivity": "排他安排", "deal_closed": "交易完成", "paused": "暂停推进",
    "internal_note": "内部备注", "other": "其他",
}

FOLLOWUP_AI_PENDING = "pending"
FOLLOWUP_AI_SUCCEEDED = "succeeded"
FOLLOWUP_AI_FAILED = "failed"
FOLLOWUP_AI_MANUAL = "manual"
FOLLOWUP_AI_PENDING_SUMMARY = "AI解析中"
FOLLOWUP_AI_FAILED_SUMMARY = "AI解析失败，请删除该记录重新录入或手动编辑。"

_SYSTEM_EVENT_TYPES = {
    "recommended",
    "buyer_interested",
    "buyer_not_interested",
    "due_diligence_started",
    "agreement_discussion",
    "deal_closed",
    "paused",
}
MANUAL_RELATION_EVENT_TYPES = frozenset(set(RELATION_EVENT_TYPES) - _SYSTEM_EVENT_TYPES)

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
    source_type: str,
    source_id: UUID | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> UUID:
    return db.execute(
        text(
            """
            insert into relation_event (
              team_id, workspace_id, relation_id, buyer_intent_id, buyer_party_id,
              seller_target_id, event_type, event_time, title, content, next_step,
              source_type, source_id, metadata_json, created_by, updated_by
            )
            values (
              :team_id, :workspace_id, :relation_id, :buyer_intent_id, :buyer_party_id,
              :seller_target_id, :event_type, now(), :title, :content, :next_step,
              :source_type, :source_id, :metadata_json, :created_by, :updated_by
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
            "source_type": source_type,
            "source_id": source_id,
            "metadata_json": metadata_json or {},
            "created_by": actor_user_id,
            "updated_by": actor_user_id,
        },
    ).scalar_one()


def _touch_relation_summary(
    db: Session,
    relation_id: UUID,
    summary: str | None,
    *,
    actor_user_id: UUID,
) -> None:
    db.execute(
        text(
            """
            update buyer_seller_relation
            set last_event_at = now(),
                last_event_summary = coalesce(:summary, last_event_summary),
                last_contact_at = now(),
                updated_at = now(),
                updated_by = :updated_by
            where id = :relation_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "summary": summary,
            "updated_by": actor_user_id,
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
              last_contact_at, created_by, updated_by
            )
            values (
              :team_id, :workspace_id, :buyer_intent_id, :buyer_party_id, :seller_target_id,
              'recommended', now(), now(), :summary, now(), :created_by, :updated_by
            )
            on conflict (team_id, buyer_intent_id, seller_target_id)
              where deleted_at is null do nothing
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
            "updated_by": actor_user_id,
        },
    ).scalar_one_or_none()
    if relation_id is None:
        existing = db.execute(
            text(
                """
                select id from buyer_seller_relation
                where team_id = :team_id and workspace_id = :workspace_id
                  and buyer_intent_id = :buyer_intent_id
                  and seller_target_id = :seller_target_id and deleted_at is null
                """
            ),
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "buyer_intent_id": buyer_intent_id,
                "seller_target_id": seller_target_id,
            },
        ).scalar_one()
        return existing, False
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
        source_type="system",
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
    relation = _load_relation(db, relation_id)
    default_content = f"已记录：{RELATION_EVENT_LABELS[event_type]}"
    event_id = _insert_event(
        db,
        relation,
        actor_user_id=actor_user_id,
        event_type=event_type,
        title=title.strip() if title else None,
        content=content.strip() if content else default_content,
        next_step=next_step,
        source_type="manual",
    )
    _touch_relation_summary(db, relation_id, content or title or default_content, actor_user_id=actor_user_id)
    db.commit()
    return event_id


def record_direct_business_update_followup(
    db: Session,
    *,
    business_update_id: UUID,
    relation_id: UUID,
    actor_user_id: UUID,
    event_type: str,
    content: str,
) -> UUID:
    """Write a consultant's raw follow-up directly to the relation timeline.

    The caller owns the surrounding transaction.  Keeping the business update
    and relation event in that one transaction prevents an audit source from
    existing without its timeline record (or vice versa).
    """
    _validate_manual_event_type(event_type)
    clean_content = content.strip()
    if not clean_content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="直接写入跟进内容时，原始材料不能为空。",
        )
    if len(clean_content) > 4000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="直接写入的跟进内容不能超过 4000 字；较长材料请使用 AI 整理。",
        )
    relation = _load_relation(db, relation_id)
    event_id = _insert_event(
        db,
        relation,
        actor_user_id=actor_user_id,
        event_type=event_type,
        title=None,
        content=clean_content,
        next_step=None,
        source_type="manual",
        source_id=business_update_id,
        metadata_json={
            "followup_ai_status": FOLLOWUP_AI_MANUAL,
            "business_update_id": str(business_update_id),
            "entry_mode": "direct",
        },
    )
    _touch_relation_summary(db, relation_id, clean_content, actor_user_id=actor_user_id)
    _store_followup_event_id_on_business_update(db, business_update_id, event_id)
    return event_id


def ensure_ai_followup_event(
    db: Session,
    *,
    business_update_id: UUID,
    relation_id: UUID,
    actor_user_id: UUID,
    event_type: str,
    original_content: str,
    job_id: UUID | None,
) -> UUID:
    """Create (or reset) the editable timeline placeholder for an AI follow-up."""
    _validate_manual_event_type(event_type)
    existing = db.execute(
        text(
            """
            select id
            from relation_event
            where relation_id = :relation_id
              and source_type = 'manual'
              and source_id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            order by created_at desc
            limit 1
            """
        ),
        {
            "relation_id": relation_id,
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).scalar_one_or_none()
    metadata_patch = {
        "followup_ai_status": FOLLOWUP_AI_PENDING,
        "followup_ai_error": None,
        "business_update_id": str(business_update_id),
        "followup_job_id": str(job_id) if job_id else None,
        "entry_mode": "ai",
    }
    created = existing is None
    if existing is not None:
        db.execute(
            text(
                """
                update relation_event
                set event_type = :event_type,
                    metadata_json = metadata_json || :metadata_patch,
                    updated_at = now(),
                    updated_by = :updated_by
                where id = :event_id
                  and team_id = :team_id
                  and workspace_id = :workspace_id
                  and deleted_at is null
                """
            ).bindparams(bindparam("metadata_patch", type_=JSONB)),
            {
                "event_type": event_type,
                "metadata_patch": metadata_patch,
                "updated_by": actor_user_id,
                "event_id": existing,
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
            },
        )
        event_id = existing
    else:
        relation = _load_relation(db, relation_id)
        event_id = _insert_event(
            db,
            relation,
            actor_user_id=actor_user_id,
            event_type=event_type,
            title=None,
            content=original_content.strip()[:4000] or "AI 整理附件中的跟进内容",
            next_step=None,
            source_type="manual",
            source_id=business_update_id,
            metadata_json=metadata_patch,
        )
    if created:
        _touch_relation_summary(
            db,
            relation_id,
            FOLLOWUP_AI_PENDING_SUMMARY,
            actor_user_id=actor_user_id,
        )
    else:
        _recompute_relation_summary(db, relation_id, actor_user_id=actor_user_id)
    _store_followup_event_id_on_business_update(db, business_update_id, event_id)
    return event_id


def complete_ai_followup_event(
    db: Session,
    *,
    business_update_id: UUID,
    job_id: UUID,
    content: str,
    next_step: str | None,
) -> bool:
    """Replace a pending placeholder with the parsed communication result."""
    event = _followup_event_for_update(db, business_update_id)
    if event is None:
        return False
    result = db.execute(
        text(
            """
            update relation_event
            set content = :content,
                next_step = :next_step,
                metadata_json = metadata_json || :metadata_patch,
                updated_at = now()
            where id = :event_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              and metadata_json ->> 'followup_ai_status' = 'pending'
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "content": content.strip()[:4000],
            "next_step": next_step.strip()[:1000] if isinstance(next_step, str) and next_step.strip() else None,
            "metadata_patch": {
                "followup_ai_status": FOLLOWUP_AI_SUCCEEDED,
                "followup_ai_error": None,
                "followup_job_id": str(job_id),
            },
            "event_id": event["id"],
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    if not result.rowcount:
        return False
    _recompute_relation_summary(db, event["relation_id"], actor_user_id=event["created_by"])
    return True


def fail_ai_followup_event(
    db: Session,
    *,
    business_update_id: UUID,
    job_id: UUID,
    error_message: str,
) -> bool:
    """Turn a pending placeholder into an editable/deletable failure record."""
    event = _followup_event_for_update(db, business_update_id)
    if event is None:
        return False
    result = db.execute(
        text(
            """
            update relation_event
            set metadata_json = metadata_json || :metadata_patch,
                updated_at = now()
            where id = :event_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              and metadata_json ->> 'followup_ai_status' = 'pending'
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "metadata_patch": {
                "followup_ai_status": FOLLOWUP_AI_FAILED,
                "followup_ai_error": error_message[:1000],
                "followup_job_id": str(job_id),
            },
            "event_id": event["id"],
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    if not result.rowcount:
        return False
    _recompute_relation_summary(db, event["relation_id"], actor_user_id=event["created_by"])
    return True


def _validate_manual_event_type(event_type: str) -> None:
    if event_type not in MANUAL_RELATION_EVENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid manual event_type: {event_type}",
        )


def _store_followup_event_id_on_business_update(
    db: Session,
    business_update_id: UUID,
    event_id: UUID,
) -> None:
    db.execute(
        text(
            """
            update business_update
            set metadata_json = metadata_json || :metadata_patch
            where id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "metadata_patch": {"followup_event_id": str(event_id)},
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )


def _followup_event_for_update(db: Session, business_update_id: UUID) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select id, relation_id, coalesce(created_by, updated_by, :system_user_id) as created_by
            from relation_event
            where source_type = 'manual'
              and source_id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            order by created_at desc
            limit 1
            """
        ),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "system_user_id": DEFAULT_ADMIN_USER_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


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
                updated_at = now(),
                updated_by = :updated_by
            where id = :relation_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "new_status": new_status,
            "status_reason": status_reason,
            "summary": summary,
            "updated_by": actor_user_id,
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
        source_type="system",
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
    if new_status == "deal_closed":
        mark_seller_target_sold_for_deal_closed(
            db,
            seller_target_id=UUID(str(relation["seller_target_id"])),
            relation_id=relation_id,
            actor_user_id=actor_user_id,
        )
    db.commit()
    return _load_relation(db, relation_id)


def _seller_target_deal_closed_changes(target: dict[str, Any]) -> dict[str, Any]:
    """The only target-state outcome of a manually closed deal.

    A relation reaching ``deal_closed`` is an explicit transaction fact, not a
    tentative follow-up.  Keep the target list, recommendation pool, and
    information page coherent by making the target sold.  Since 0814 the
    screening gate is ``target_grade``; ``lifecycle_status`` is the E-reason and
    the two are bound by a DB check, so both have to move together here.
    Returning only actual differences keeps the linkage idempotent and makes
    its audit concise.
    """
    desired = {
        "target_grade": BLOCKED_GRADE,
        "lifecycle_status": "sold",
        "is_for_sale": "no",
    }
    return {field: value for field, value in desired.items() if target.get(field) != value}


def mark_seller_target_sold_for_deal_closed(
    db: Session,
    *,
    seller_target_id: UUID,
    relation_id: UUID,
    actor_user_id: UUID,
) -> None:
    target_row = db.execute(
        text(
            """
            select target_grade, lifecycle_status, is_for_sale
            from seller_target
            where id = :seller_target_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if target_row is None:
        # The relation is historical if its target has since been deleted; do
        # not make the valid relation status transition fail because of that.
        return
    original = dict(target_row)
    changes = _seller_target_deal_closed_changes(original)
    if not changes:
        return

    db.execute(
        text(
            """
            update seller_target
            set target_grade = :target_grade,
                lifecycle_status = :lifecycle_status,
                is_for_sale = :is_for_sale,
                updated_at = now(),
                updated_by = :updated_by
            where id = :seller_target_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "target_grade": changes.get("target_grade", original["target_grade"]),
            "lifecycle_status": changes.get("lifecycle_status", original["lifecycle_status"]),
            "is_for_sale": changes.get("is_for_sale", original["is_for_sale"]),
            "updated_by": actor_user_id,
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    for field_path, new_value in changes.items():
        write_action_log(
            db,
            entity_type="seller_target",
            entity_id=seller_target_id,
            field_path=field_path,
            old_value=original[field_path],
            new_value=new_value,
            source_type="direct_api",
            metadata_json={
                "source": "relation_deal_closed_seller_target_sync",
                "relation_id": str(relation_id),
            },
            applied_by=actor_user_id,
        )


def _recompute_relation_summary(db: Session, relation_id: UUID, *, actor_user_id: UUID) -> None:
    latest = db.execute(
        text(
            """
            select event_time,
                   case metadata_json ->> 'followup_ai_status'
                     when 'pending' then :pending_summary
                     when 'failed' then :failed_summary
                     else coalesce(nullif(content, ''), nullif(title, ''))
                   end as summary
            from relation_event
            where relation_id = :relation_id and team_id = :team_id
              and workspace_id = :workspace_id and deleted_at is null
            order by event_time desc, created_at desc
            limit 1
            """
        ),
        {
            "relation_id": relation_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "pending_summary": FOLLOWUP_AI_PENDING_SUMMARY,
            "failed_summary": FOLLOWUP_AI_FAILED_SUMMARY,
        },
    ).mappings().one_or_none()
    db.execute(
        text(
            """
            update buyer_seller_relation
            set last_event_at = :last_event_at,
                last_event_summary = :summary,
                updated_at = now(), updated_by = :updated_by
            where id = :relation_id and team_id = :team_id and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "last_event_at": latest["event_time"] if latest else None,
            "summary": latest["summary"] if latest else None,
            "updated_by": actor_user_id,
            "relation_id": relation_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )


def update_relation_event(
    db: Session,
    relation_id: UUID,
    event_id: UUID,
    *,
    actor_user_id: UUID,
    changes: dict[str, Any],
) -> None:
    event = _load_editable_manual_event(db, relation_id, event_id)
    allowed = {"event_type", "title", "content", "next_step"}
    if set(changes) - allowed:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unsupported event fields.")
    event_type = changes.get("event_type", event["event_type"])
    if event_type not in RELATION_EVENT_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Invalid event_type: {event_type}")
    title = changes.get("title", event["title"])
    content = changes.get("content", event["content"])
    if not (str(title or "").strip() or str(content or "").strip()):
        content = f"已记录：{RELATION_EVENT_LABELS[event_type]}"
    db.execute(
        text(
            """
            update relation_event
            set event_type = :event_type, title = :title, content = :content,
                next_step = :next_step,
                metadata_json = case
                  when metadata_json ? 'followup_ai_status'
                  then metadata_json || :metadata_patch
                  else metadata_json
                end,
                updated_at = now(), updated_by = :updated_by
            where id = :event_id and relation_id = :relation_id and team_id = :team_id
              and workspace_id = :workspace_id and deleted_at is null
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "event_type": event_type,
            "title": title.strip() if isinstance(title, str) and title.strip() else None,
            "content": content.strip() if isinstance(content, str) and content.strip() else None,
            "next_step": changes.get("next_step", event["next_step"]),
            "metadata_patch": {
                "followup_ai_status": FOLLOWUP_AI_MANUAL,
                "followup_ai_error": None,
            },
            "updated_by": actor_user_id,
            "event_id": event_id,
            "relation_id": relation_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    _recompute_relation_summary(db, relation_id, actor_user_id=actor_user_id)
    db.commit()


def delete_relation_event(
    db: Session,
    relation_id: UUID,
    event_id: UUID,
    *,
    actor_user_id: UUID,
) -> None:
    _load_editable_manual_event(db, relation_id, event_id)
    db.execute(
        text(
            """
            update relation_event
            set deleted_at = now(), deleted_by = :deleted_by,
                updated_at = now(), updated_by = :updated_by
            where id = :event_id and relation_id = :relation_id and team_id = :team_id
              and workspace_id = :workspace_id and deleted_at is null
            """
        ),
        {"deleted_by": actor_user_id, "updated_by": actor_user_id, "event_id": event_id,
         "relation_id": relation_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    )
    _recompute_relation_summary(db, relation_id, actor_user_id=actor_user_id)
    db.commit()


def _load_editable_manual_event(db: Session, relation_id: UUID, event_id: UUID) -> dict[str, Any]:
    event = db.execute(
        text(
            """
            select id, event_type, title, content, next_step, source_type, deleted_at
            from relation_event
            where id = :event_id and relation_id = :relation_id and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {"event_id": event_id, "relation_id": relation_id,
         "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().one_or_none()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relation event not found.")
    if event["deleted_at"] is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Relation event has been deleted.")
    if event["source_type"] != "manual":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="System relation events are immutable.")
    return dict(event)
