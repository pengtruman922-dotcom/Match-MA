from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID, SYSTEM_USER_ID
from backend.app.api.routes.utils import (
    diff_payload,
    ensure_business_update_visible,
    ensure_entity_writable,
    extracted_action_visible_sql,
    owner_scope_required,
    write_action_logs_for_diff,
    write_field_value_sources_for_diff,
)
from backend.app.db import get_db
from backend.app.services.search_docs import create_search_doc_rebuild_job
from backend.app.services.extracted_action_apply import (  # noqa: F401 - re-exported for compatibility
    _POST_PARSE_INFORMATION_STATUSES,
    _action_source_context,
    _allowed_buyer_intent_changes,
    _allowed_relation_changes,
    _allowed_seller_target_changes,
    _event_type_from_relation_status,
    _get_buyer_intent_snapshot_or_404,
    _get_buyer_party_id_for_intent,
    _get_or_create_relation,
    _get_seller_target_snapshot_or_404,
    _insert_relation_event,
    _mark_action_applied,
    _optional_uuid,
    _refresh_business_update_status,
    _relation_event_content,
    _required_uuid,
    _seller_target_changes_with_parse_completion,
    apply_buyer_intent_target_exclusion_action,
    apply_buyer_intent_update_action,
    apply_buyer_seller_relation_update_action,
    apply_seller_fact_update_action,
)

router = APIRouter(tags=["extracted-actions"])


class ExtractedActionCreate(BaseModel):
    action_type: str
    target_entity_type: str | None = None
    target_entity_id: UUID | None = None
    proposed_changes_json: dict[str, Any] = Field(default_factory=dict)
    raw_evidence_text: str | None = None
    evidence_id: UUID | None = None
    confidence: Decimal | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ExtractedActionReviewUpdate(BaseModel):
    review_status: str


class ExtractedActionOut(BaseModel):
    id: UUID
    business_update_id: UUID
    action_type: str
    target_entity_type: str | None
    target_entity_id: UUID | None
    proposed_changes_json: dict[str, Any]
    raw_evidence_text: str | None
    evidence_id: UUID | None = None
    confidence: Decimal | None
    review_status: str
    reviewed_by: UUID | None
    reviewed_at: str | None
    applied_at: str | None
    metadata_json: dict[str, Any]
    created_at: str


class ApplyActionOut(BaseModel):
    status: str
    extracted_action_id: UUID
    business_update_id: UUID
    entity_type: str
    entity_id: UUID
    applied_fields: list[str]


@router.post(
    "/business-updates/{business_update_id}/extracted-actions",
    response_model=ExtractedActionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_extracted_action(
    business_update_id: UUID,
    payload: ExtractedActionCreate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _ensure_business_update_exists(db, business_update_id)
    ensure_business_update_visible(db, current_user, business_update_id)
    _ensure_action_target_writable(
        db,
        current_user,
        action_type=payload.action_type,
        target_entity_type=payload.target_entity_type,
        target_entity_id=payload.target_entity_id,
        proposed_changes=payload.proposed_changes_json,
    )

    statement = text(
        """
        insert into extracted_action (
          team_id, workspace_id, business_update_id,
          action_type, target_entity_type, target_entity_id,
          proposed_changes_json, raw_evidence_text, evidence_id, confidence, metadata_json
        )
        values (
          :team_id, :workspace_id, :business_update_id,
          :action_type, :target_entity_type, :target_entity_id,
          :proposed_changes_json, :raw_evidence_text, :evidence_id, :confidence, :metadata_json
        )
        returning
          id, business_update_id, action_type, target_entity_type, target_entity_id,
          proposed_changes_json, raw_evidence_text, evidence_id, confidence, review_status,
          reviewed_by, reviewed_at::text as reviewed_at, applied_at::text as applied_at,
          metadata_json, created_at::text as created_at
        """
    ).bindparams(
        bindparam("proposed_changes_json", type_=JSONB),
        bindparam("metadata_json", type_=JSONB),
    )

    row = db.execute(
        statement,
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "business_update_id": business_update_id,
            "action_type": payload.action_type,
            "target_entity_type": payload.target_entity_type,
            "target_entity_id": payload.target_entity_id,
            "proposed_changes_json": payload.proposed_changes_json,
            "raw_evidence_text": payload.raw_evidence_text,
            "evidence_id": payload.evidence_id,
            "confidence": payload.confidence,
            "metadata_json": payload.metadata_json,
        },
    ).mappings().one()

    db.execute(
        text(
            """
            update business_update
            set processing_status = 'parsed'
            where id = :business_update_id
              and processing_status in ('pending', 'processing')
            """
        ),
        {"business_update_id": business_update_id},
    )

    db.commit()
    return dict(row)


@router.get("/extracted-actions", response_model=list[ExtractedActionOut])
def list_extracted_actions(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    business_update_id: UUID | None = None,
    review_status: str | None = None,
    target_entity_type: str | None = None,
    target_entity_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    where = ["team_id = :team_id", "workspace_id = :workspace_id"]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
        "offset": offset,
    }

    if business_update_id:
        where.append("business_update_id = :business_update_id")
        params["business_update_id"] = business_update_id
    if review_status:
        where.append("review_status = :review_status")
        params["review_status"] = review_status
    if target_entity_type:
        where.append("target_entity_type = :target_entity_type")
        params["target_entity_type"] = target_entity_type
    if target_entity_id:
        where.append("target_entity_id = :target_entity_id")
        params["target_entity_id"] = target_entity_id
    if owner_scope_required(current_user):
        where.append(extracted_action_visible_sql("extracted_action"))
        params["scope_user_id"] = current_user.user_id

    rows = db.execute(
        text(
            f"""
            select
              id, business_update_id, action_type, target_entity_type, target_entity_id,
              proposed_changes_json, raw_evidence_text, evidence_id, confidence, review_status,
              reviewed_by, reviewed_at::text as reviewed_at, applied_at::text as applied_at,
              metadata_json, created_at::text as created_at
            from extracted_action
            where {' and '.join(where)}
            order by created_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


@router.get("/extracted-actions/{extracted_action_id}", response_model=ExtractedActionOut)
def get_extracted_action(
    extracted_action_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    action = _get_extracted_action_or_404(db, extracted_action_id)
    _ensure_extracted_action_visible(db, current_user, extracted_action_id)
    return action


@router.patch("/extracted-actions/{extracted_action_id}", response_model=ExtractedActionOut)
def update_extracted_action_review(
    extracted_action_id: UUID,
    payload: ExtractedActionReviewUpdate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    action = _get_extracted_action_or_404(db, extracted_action_id)
    _ensure_extracted_action_writable(db, current_user, action)

    row = db.execute(
        text(
            """
            update extracted_action
            set review_status = :review_status,
                reviewed_by = :reviewed_by,
                reviewed_at = now()
            where id = :extracted_action_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            returning
              id, business_update_id, action_type, target_entity_type, target_entity_id,
              proposed_changes_json, raw_evidence_text, evidence_id, confidence, review_status,
              reviewed_by, reviewed_at::text as reviewed_at, applied_at::text as applied_at,
              metadata_json, created_at::text as created_at
            """
        ),
        {
            "extracted_action_id": extracted_action_id,
            "review_status": payload.review_status,
            "reviewed_by": current_user.user_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one()
    db.commit()
    return dict(row)


@router.post("/extracted-actions/{extracted_action_id}/apply", response_model=ApplyActionOut)
def apply_extracted_action(
    extracted_action_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    action = _get_extracted_action_or_404(db, extracted_action_id)
    _ensure_extracted_action_writable(db, current_user, action)
    if action["action_type"] == "seller_fact_update":
        result = apply_seller_fact_update_action(
            db, action, require_accepted=True, actor_user_id=current_user.user_id
        )
    elif action["action_type"] == "buyer_intent_update":
        result = apply_buyer_intent_update_action(
            db, action, require_accepted=True, actor_user_id=current_user.user_id
        )
    elif action["action_type"] == "buyer_seller_relation_update":
        result = apply_buyer_seller_relation_update_action(
            db, action, require_accepted=True, actor_user_id=current_user.user_id
        )
    elif action["action_type"] == "buyer_intent_target_exclusion":
        result = apply_buyer_intent_target_exclusion_action(
            db, action, require_accepted=True, actor_user_id=current_user.user_id
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This action type is not supported by apply yet.",
        )
    db.commit()
    return result


# Transient statuses a follow-up-only parse should release the target from.
# Only the parse-lifecycle statuses set by this flow.


def _ensure_extracted_action_visible(db: Session, current_user: CurrentUser, extracted_action_id: UUID) -> None:
    if not owner_scope_required(current_user):
        return
    row = db.execute(
        text(
            f"""
            select 1
            from extracted_action action_scope
            where action_scope.id = :extracted_action_id
              and action_scope.team_id = :team_id
              and action_scope.workspace_id = :workspace_id
              and {extracted_action_visible_sql("action_scope")}
            """
        ),
        {
            "extracted_action_id": extracted_action_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "scope_user_id": current_user.user_id,
        },
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extracted action not found.")


def _ensure_extracted_action_writable(
    db: Session,
    current_user: CurrentUser,
    action: dict[str, Any],
) -> None:
    _ensure_action_target_writable(
        db,
        current_user,
        action_type=action.get("action_type"),
        target_entity_type=action.get("target_entity_type"),
        target_entity_id=action.get("target_entity_id"),
        proposed_changes=action.get("proposed_changes_json") or {},
    )
    if owner_scope_required(current_user) and not action.get("target_entity_id"):
        ensure_business_update_visible(db, current_user, action["business_update_id"])


def _ensure_action_target_writable(
    db: Session,
    current_user: CurrentUser,
    *,
    action_type: str | None,
    target_entity_type: str | None,
    target_entity_id: UUID | None,
    proposed_changes: dict[str, Any],
) -> None:
    if not owner_scope_required(current_user):
        return
    if target_entity_type in {"seller_target", "buyer_intent", "buyer_party"} and target_entity_id:
        ensure_entity_writable(
            db,
            current_user,
            entity_type=target_entity_type,
            entity_id=target_entity_id,
        )
        return
    if target_entity_type == "buyer_seller_relation" and target_entity_id:
        if _relation_has_owned_side(db, current_user, relation_id=target_entity_id):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot modify this relation.")
    if action_type in {"buyer_seller_relation_update", "buyer_intent_target_exclusion"}:
        seller_target_id = _optional_uuid(proposed_changes.get("seller_target_id"))
        buyer_intent_id = _optional_uuid(proposed_changes.get("buyer_intent_id"))
        buyer_party_id = _optional_uuid(proposed_changes.get("buyer_party_id"))
        if _relation_payload_has_owned_side(
            db,
            current_user,
            seller_target_id=seller_target_id,
            buyer_intent_id=buyer_intent_id,
            buyer_party_id=buyer_party_id,
        ):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot modify this relation.")


def _relation_has_owned_side(db: Session, current_user: CurrentUser, *, relation_id: UUID) -> bool:
    return bool(
        db.execute(
            text(
                """
                select 1
                from buyer_seller_relation r
                left join buyer_intent bi on bi.id = r.buyer_intent_id and bi.deleted_at is null
                left join buyer_party bp on bp.id = coalesce(r.buyer_party_id, bi.buyer_party_id) and bp.deleted_at is null
                left join seller_target st on st.id = r.seller_target_id and st.deleted_at is null
                where r.id = :relation_id
                  and r.team_id = :team_id
                  and r.workspace_id = :workspace_id
                  and r.deleted_at is null
                  and (
                    st.owner_user_id = :scope_user_id
                    or bi.owner_user_id = :scope_user_id
                    or bp.owner_user_id = :scope_user_id
                  )
                """
            ),
            {
                "relation_id": relation_id,
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "scope_user_id": current_user.user_id,
            },
        ).first()
    )


def _relation_payload_has_owned_side(
    db: Session,
    current_user: CurrentUser,
    *,
    seller_target_id: UUID | None,
    buyer_intent_id: UUID | None,
    buyer_party_id: UUID | None,
) -> bool:
    row = db.execute(
        text(
            """
            select 1
            where
              (
                cast(:seller_target_id as uuid) is not null
                and exists (
                  select 1 from seller_target st
                  where st.id = cast(:seller_target_id as uuid)
                    and st.owner_user_id = :scope_user_id
                    and st.deleted_at is null
                )
              )
              or (
                cast(:buyer_intent_id as uuid) is not null
                and exists (
                  select 1 from buyer_intent bi
                  where bi.id = cast(:buyer_intent_id as uuid)
                    and bi.owner_user_id = :scope_user_id
                    and bi.deleted_at is null
                )
              )
              or (
                cast(:buyer_party_id as uuid) is not null
                and exists (
                  select 1 from buyer_party bp
                  where bp.id = cast(:buyer_party_id as uuid)
                    and bp.owner_user_id = :scope_user_id
                    and bp.deleted_at is null
                )
              )
            """
        ),
        {
            "seller_target_id": seller_target_id,
            "buyer_intent_id": buyer_intent_id,
            "buyer_party_id": buyer_party_id,
            "scope_user_id": current_user.user_id,
        },
    ).first()
    return bool(row)


def _ensure_business_update_exists(db: Session, business_update_id: UUID) -> None:
    exists = db.execute(
        text(
            """
            select exists(
              select 1
              from business_update
              where id = :business_update_id
                and team_id = :team_id
                and workspace_id = :workspace_id
            )
            """
        ),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).scalar_one()
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business update not found.")


def _get_extracted_action_or_404(db: Session, extracted_action_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, business_update_id, action_type, target_entity_type, target_entity_id,
              proposed_changes_json, raw_evidence_text, evidence_id, confidence, review_status,
              reviewed_by, reviewed_at::text as reviewed_at, applied_at::text as applied_at,
              metadata_json, created_at::text as created_at
            from extracted_action
            where id = :extracted_action_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "extracted_action_id": extracted_action_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extracted action not found.")

    return dict(row)
