from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.api.routes.utils import (
    diff_payload,
    write_action_logs_for_diff,
    write_field_value_sources_for_diff,
)
from backend.app.db import get_db
from backend.app.services.search_docs import create_search_doc_rebuild_job

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
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _ensure_business_update_exists(db, business_update_id)

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
def get_extracted_action(extracted_action_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _get_extracted_action_or_404(db, extracted_action_id)


@router.patch("/extracted-actions/{extracted_action_id}", response_model=ExtractedActionOut)
def update_extracted_action_review(
    extracted_action_id: UUID,
    payload: ExtractedActionReviewUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _get_extracted_action_or_404(db, extracted_action_id)

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
            "reviewed_by": DEFAULT_ADMIN_USER_ID,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one()
    db.commit()
    return dict(row)


@router.post("/extracted-actions/{extracted_action_id}/apply", response_model=ApplyActionOut)
def apply_extracted_action(extracted_action_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    action = _get_extracted_action_or_404(db, extracted_action_id)
    if action["action_type"] == "seller_fact_update":
        result = apply_seller_fact_update_action(db, action, require_accepted=True)
    elif action["action_type"] == "buyer_intent_update":
        result = apply_buyer_intent_update_action(db, action, require_accepted=True)
    elif action["action_type"] == "buyer_seller_relation_update":
        result = apply_buyer_seller_relation_update_action(db, action, require_accepted=True)
    elif action["action_type"] == "buyer_intent_target_exclusion":
        result = apply_buyer_intent_target_exclusion_action(db, action, require_accepted=True)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This action type is not supported by apply yet.",
        )
    db.commit()
    return result


def apply_seller_fact_update_action(
    db: Session,
    action: dict[str, Any],
    *,
    require_accepted: bool = True,
) -> dict[str, Any]:
    if action["action_type"] != "seller_fact_update" or action["target_entity_type"] != "seller_target":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only seller_fact_update actions targeting seller_target are supported now.",
        )
    if action["target_entity_id"] is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="target_entity_id is required.")
    if action["applied_at"] is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Action has already been applied.")
    if require_accepted and action["review_status"] not in {"accepted", "auto_accepted"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action must be accepted before apply.",
        )

    changes = _allowed_seller_target_changes(action["proposed_changes_json"])
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No supported changes to apply.")

    seller_target_id = action["target_entity_id"]
    original = _get_seller_target_snapshot_or_404(db, seller_target_id)
    diff = diff_payload(original, changes)
    if not diff:
        _mark_action_applied(db, action["id"], review_status="auto_accepted")
        _refresh_business_update_status(db, action["business_update_id"])
        return {
            "status": "noop",
            "extracted_action_id": action["id"],
            "business_update_id": action["business_update_id"],
            "entity_type": "seller_target",
            "entity_id": seller_target_id,
            "applied_fields": [],
        }

    set_clauses = [f"{field} = :{field}" for field in diff]
    set_clauses.extend(["updated_at = now()", "updated_by = :updated_by"])

    db.execute(
        text(
            f"""
            update seller_target
            set {', '.join(set_clauses)}
            where id = :seller_target_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            **{field: changes[field] for field in diff},
            "updated_by": DEFAULT_ADMIN_USER_ID,
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )

    source_context = _action_source_context(action, default_source_label="Business update extracted action")
    write_action_logs_for_diff(
        db,
        entity_type="seller_target",
        entity_id=seller_target_id,
        diff=diff,
        source_type="extracted_action",
        source_id=action["id"],
        evidence_id=source_context["evidence_id"],
        business_update_id=action["business_update_id"],
        extracted_action_id=action["id"],
        metadata_json={
            "source": "extracted_action_apply",
            "action_type": action["action_type"],
            "field_value_source": source_context,
        },
    )
    write_field_value_sources_for_diff(
        db,
        entity_type="seller_target",
        entity_id=seller_target_id,
        changes=changes,
        diff=diff,
        source_type="extracted_action",
        source_id=action["id"],
        evidence_id=source_context["evidence_id"],
        source_label=source_context["source_label"],
        confidence=action.get("confidence"),
        review_status="auto_accepted",
        source_context=source_context,
    )
    create_search_doc_rebuild_job(
        db,
        entity_type="seller_target",
        entity_id=seller_target_id,
        source="seller_fact_update_apply",
    )
    _mark_action_applied(db, action["id"], review_status="auto_accepted" if not require_accepted else None)
    _refresh_business_update_status(db, action["business_update_id"])

    return {
        "status": "applied",
        "extracted_action_id": action["id"],
        "business_update_id": action["business_update_id"],
        "entity_type": "seller_target",
        "entity_id": seller_target_id,
        "applied_fields": list(diff.keys()),
    }


def apply_buyer_intent_update_action(
    db: Session,
    action: dict[str, Any],
    *,
    require_accepted: bool = True,
) -> dict[str, Any]:
    if action["action_type"] != "buyer_intent_update" or action["target_entity_type"] != "buyer_intent":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only buyer_intent_update actions targeting buyer_intent are supported now.",
        )
    if action["target_entity_id"] is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="target_entity_id is required.")
    if action["applied_at"] is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Action has already been applied.")
    if require_accepted and action["review_status"] not in {"accepted", "auto_accepted"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action must be accepted before apply.",
        )

    changes = _allowed_buyer_intent_changes(action["proposed_changes_json"])
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No supported changes to apply.")

    buyer_intent_id = action["target_entity_id"]
    original = _get_buyer_intent_snapshot_or_404(db, buyer_intent_id)
    diff = diff_payload(original, changes)
    if not diff:
        _mark_action_applied(db, action["id"], review_status="auto_accepted" if not require_accepted else None)
        _refresh_business_update_status(db, action["business_update_id"])
        return {
            "status": "noop",
            "extracted_action_id": action["id"],
            "business_update_id": action["business_update_id"],
            "entity_type": "buyer_intent",
            "entity_id": buyer_intent_id,
            "applied_fields": [],
        }

    set_clauses = [f"{field} = :{field}" for field in diff]
    set_clauses.extend(["updated_at = now()", "updated_by = :updated_by"])

    update_statement = text(
        f"""
            update buyer_intent
            set {', '.join(set_clauses)}
            where id = :buyer_intent_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
    )
    json_fields = {
        "contact_info_json",
        "parsed_requirement_json",
        "region_constraints_json",
        "acceptable_control_paths_json",
    }
    bind_params = [bindparam(field, type_=JSONB) for field in diff if field in json_fields]
    if bind_params:
        update_statement = update_statement.bindparams(*bind_params)

    db.execute(
        update_statement,
        {
            **{field: changes[field] for field in diff},
            "updated_by": DEFAULT_ADMIN_USER_ID,
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )

    source_context = _action_source_context(action, default_source_label="Business update extracted action")
    write_action_logs_for_diff(
        db,
        entity_type="buyer_intent",
        entity_id=buyer_intent_id,
        diff=diff,
        source_type="extracted_action",
        source_id=action["id"],
        evidence_id=source_context["evidence_id"],
        business_update_id=action["business_update_id"],
        extracted_action_id=action["id"],
        metadata_json={
            "source": "extracted_action_apply",
            "action_type": action["action_type"],
            "field_value_source": source_context,
        },
    )
    write_field_value_sources_for_diff(
        db,
        entity_type="buyer_intent",
        entity_id=buyer_intent_id,
        changes=changes,
        diff=diff,
        source_type="extracted_action",
        source_id=action["id"],
        evidence_id=source_context["evidence_id"],
        source_label=source_context["source_label"],
        confidence=action.get("confidence"),
        review_status="auto_accepted",
        source_context=source_context,
    )
    create_search_doc_rebuild_job(
        db,
        entity_type="buyer_intent",
        entity_id=buyer_intent_id,
        source="buyer_intent_update_apply",
    )
    _mark_action_applied(db, action["id"], review_status="auto_accepted" if not require_accepted else None)
    _refresh_business_update_status(db, action["business_update_id"])

    return {
        "status": "applied",
        "extracted_action_id": action["id"],
        "business_update_id": action["business_update_id"],
        "entity_type": "buyer_intent",
        "entity_id": buyer_intent_id,
        "applied_fields": list(diff.keys()),
    }


def apply_buyer_seller_relation_update_action(
    db: Session,
    action: dict[str, Any],
    *,
    require_accepted: bool = True,
) -> dict[str, Any]:
    if action["action_type"] != "buyer_seller_relation_update":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only buyer_seller_relation_update actions are supported here.",
        )
    if action["applied_at"] is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Action has already been applied.")
    if require_accepted and action["review_status"] not in {"accepted", "auto_accepted"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action must be accepted before apply.",
        )

    changes = action["proposed_changes_json"]
    buyer_intent_id = _required_uuid(changes.get("buyer_intent_id"), "buyer_intent_id")
    seller_target_id = _required_uuid(changes.get("seller_target_id"), "seller_target_id")
    buyer_party_id = _optional_uuid(changes.get("buyer_party_id")) or _get_buyer_party_id_for_intent(
        db,
        buyer_intent_id,
    )
    relation = _get_or_create_relation(db, buyer_intent_id, seller_target_id, buyer_party_id)

    relation_updates = _allowed_relation_changes(changes)
    relation_updates.setdefault("last_event_summary", _relation_event_content(changes, action))
    relation_updates.setdefault("last_event_at", changes.get("last_event_at") or "now()")
    if changes.get("event_type") == "recommended":
        relation_updates.setdefault("first_recommended_at", changes.get("first_recommended_at") or "now()")

    diff = diff_payload(relation, relation_updates)
    if diff:
        set_clauses: list[str] = []
        params: dict[str, Any] = {
            "relation_id": relation["id"],
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "updated_by": DEFAULT_ADMIN_USER_ID,
        }
        for field in diff:
            if field in {"last_event_at", "first_recommended_at"} and relation_updates[field] == "now()":
                set_clauses.append(f"{field} = now()")
            else:
                set_clauses.append(f"{field} = :{field}")
                params[field] = relation_updates[field]
        set_clauses.extend(["updated_at = now()", "updated_by = :updated_by"])
        db.execute(
            text(
                f"""
                update buyer_seller_relation
                set {', '.join(set_clauses)}
                where id = :relation_id
                  and team_id = :team_id
                  and workspace_id = :workspace_id
                  and deleted_at is null
                """
            ),
            params,
        )
        source_context = _action_source_context(action, default_source_label="Business update relation update")
        write_action_logs_for_diff(
            db,
            entity_type="buyer_seller_relation",
            entity_id=relation["id"],
            diff=diff,
            source_type="extracted_action",
            source_id=action["id"],
            evidence_id=source_context["evidence_id"],
            business_update_id=action["business_update_id"],
            extracted_action_id=action["id"],
            metadata_json={
                "source": "extracted_action_apply",
                "action_type": action["action_type"],
                "field_value_source": source_context,
            },
        )
        write_field_value_sources_for_diff(
            db,
            entity_type="buyer_seller_relation",
            entity_id=relation["id"],
            changes=relation_updates,
            diff=diff,
            source_type="extracted_action",
            source_id=action["id"],
            evidence_id=source_context["evidence_id"],
            source_label=source_context["source_label"],
            confidence=action.get("confidence"),
            review_status="auto_accepted",
            source_context=source_context,
        )

    _insert_relation_event(db, action, relation["id"], buyer_intent_id, seller_target_id, buyer_party_id, changes)
    _mark_action_applied(db, action["id"], review_status=None if require_accepted else "auto_accepted")
    _refresh_business_update_status(db, action["business_update_id"])

    return {
        "status": "applied",
        "extracted_action_id": action["id"],
        "business_update_id": action["business_update_id"],
        "entity_type": "buyer_seller_relation",
        "entity_id": relation["id"],
        "applied_fields": list(diff.keys()) + ["relation_event"],
    }


def apply_buyer_intent_target_exclusion_action(
    db: Session,
    action: dict[str, Any],
    *,
    require_accepted: bool = True,
) -> dict[str, Any]:
    if action["action_type"] != "buyer_intent_target_exclusion":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only buyer_intent_target_exclusion actions are supported here.",
        )
    if action["applied_at"] is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Action has already been applied.")
    if require_accepted and action["review_status"] not in {"accepted", "auto_accepted"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action must be accepted before apply.",
        )

    changes = action["proposed_changes_json"]
    buyer_intent_id = _required_uuid(changes.get("buyer_intent_id") or action["target_entity_id"], "buyer_intent_id")
    seller_target_id = _required_uuid(changes.get("seller_target_id"), "seller_target_id")
    buyer_party_id = _optional_uuid(changes.get("buyer_party_id")) or _get_buyer_party_id_for_intent(
        db,
        buyer_intent_id,
    )
    reason = (
        changes.get("reason")
        or changes.get("exclusion_reason")
        or action.get("raw_evidence_text")
        or "Marked as excluded by extracted action."
    )
    relation_id = _optional_uuid(changes.get("source_relation_id"))

    row = db.execute(
        text(
            """
            insert into buyer_intent_target_exclusion (
              team_id, workspace_id, buyer_intent_id, buyer_party_id, seller_target_id,
              reason, source_relation_id, source_update_id, created_by
            )
            values (
              :team_id, :workspace_id, :buyer_intent_id, :buyer_party_id, :seller_target_id,
              :reason, :source_relation_id, :source_update_id, :created_by
            )
            on conflict (team_id, buyer_intent_id, seller_target_id)
              where active = true and canceled_at is null
            do update set
              buyer_party_id = excluded.buyer_party_id,
              reason = excluded.reason,
              source_relation_id = coalesce(excluded.source_relation_id, buyer_intent_target_exclusion.source_relation_id),
              source_update_id = excluded.source_update_id
            returning id
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "buyer_intent_id": buyer_intent_id,
            "buyer_party_id": buyer_party_id,
            "seller_target_id": seller_target_id,
            "reason": reason,
            "source_relation_id": relation_id,
            "source_update_id": action["business_update_id"],
            "created_by": DEFAULT_ADMIN_USER_ID,
        },
    ).mappings().one()

    relation_action = {
        **action,
        "action_type": "buyer_seller_relation_update",
        "proposed_changes_json": {
            "buyer_intent_id": str(buyer_intent_id),
            "buyer_party_id": str(buyer_party_id) if buyer_party_id else None,
            "seller_target_id": str(seller_target_id),
            "status": "not_interested",
            "status_reason": reason,
            "event_type": "buyer_not_interested",
            "event_content": reason,
        },
        "applied_at": None,
        "review_status": "auto_accepted",
    }
    apply_buyer_seller_relation_update_action(db, relation_action, require_accepted=True)
    _mark_action_applied(db, action["id"], review_status=None if require_accepted else "auto_accepted")
    _refresh_business_update_status(db, action["business_update_id"])

    return {
        "status": "applied",
        "extracted_action_id": action["id"],
        "business_update_id": action["business_update_id"],
        "entity_type": "buyer_intent_target_exclusion",
        "entity_id": row["id"],
        "applied_fields": ["buyer_intent_target_exclusion", "relation.status", "relation_event"],
    }


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


def _get_seller_target_snapshot_or_404(db: Session, seller_target_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              target_name, industry_primary, industry_secondary,
              headquarter_province, headquarter_city, listed_status,
              current_revenue_yuan, current_net_profit_yuan, valuation_yuan,
              current_total_profit_yuan, asking_price_yuan, pe_ratio,
              is_for_sale, can_control, can_consolidate, accepts_minority_investment,
              transfer_ratio_min, transfer_ratio_max, transfer_ratio_text,
              transfer_flexibility_type,
              recommendation_status, information_status,
              business_summary, transaction_summary, risk_summary, gap_summary
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

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seller target not found.")
    return dict(row)


def _get_buyer_intent_snapshot_or_404(db: Session, buyer_intent_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              intent_name, status, pause_reason, contact_name, contact_info_json,
              raw_requirement_text, intent_summary, parsed_requirement_json,
              industry_primary, industry_secondary, region_scope_summary,
              region_constraints_json, min_revenue_yuan, min_net_profit_yuan,
              min_total_profit_yuan, max_pe, max_valuation_yuan, market_cap_range_summary,
              requires_control, requires_consolidation, accepts_minority_investment,
              desired_equity_ratio_min, desired_equity_ratio_max, equity_ratio_summary,
              equity_requirement_type, acceptable_control_paths_json,
              preferred_listed_status, transaction_type, negative_summary,
              priority_summary, preference_summary, unknown_summary
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
    ).mappings().one_or_none()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Buyer intent not found.")
    return dict(row)


def _get_buyer_party_id_for_intent(db: Session, buyer_intent_id: UUID) -> UUID | None:
    row = db.execute(
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
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Buyer intent not found.")
    return row["buyer_party_id"]


def _get_or_create_relation(
    db: Session,
    buyer_intent_id: UUID,
    seller_target_id: UUID,
    buyer_party_id: UUID | None,
) -> dict[str, Any]:
    existing = db.execute(
        text(
            """
            select
              id, status, status_reason, first_recommended_at, last_contact_at,
              last_event_at, last_event_summary
            from buyer_seller_relation
            where team_id = :team_id
              and workspace_id = :workspace_id
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
    ).mappings().one_or_none()
    if existing:
        return dict(existing)

    row = db.execute(
        text(
            """
            insert into buyer_seller_relation (
              team_id, workspace_id, buyer_intent_id, buyer_party_id, seller_target_id,
              status, created_by
            )
            values (
              :team_id, :workspace_id, :buyer_intent_id, :buyer_party_id, :seller_target_id,
              'recommended', :created_by
            )
            returning
              id, status, status_reason, first_recommended_at, last_contact_at,
              last_event_at, last_event_summary
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "buyer_intent_id": buyer_intent_id,
            "buyer_party_id": buyer_party_id,
            "seller_target_id": seller_target_id,
            "created_by": DEFAULT_ADMIN_USER_ID,
        },
    ).mappings().one()
    return dict(row)


def _allowed_seller_target_changes(changes: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = {
        "target_name",
        "industry_primary",
        "industry_secondary",
        "headquarter_province",
        "headquarter_city",
        "listed_status",
        "current_revenue_yuan",
        "current_net_profit_yuan",
        "current_total_profit_yuan",
        "valuation_yuan",
        "asking_price_yuan",
        "pe_ratio",
        "is_for_sale",
        "can_control",
        "can_consolidate",
        "accepts_minority_investment",
        "transfer_ratio_min",
        "transfer_ratio_max",
        "transfer_ratio_text",
        "transfer_flexibility_type",
        "recommendation_status",
        "information_status",
        "business_summary",
        "transaction_summary",
        "risk_summary",
        "gap_summary",
    }
    return {key: value for key, value in changes.items() if key in allowed_fields}


def _allowed_buyer_intent_changes(changes: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = {
        "intent_name",
        "status",
        "pause_reason",
        "contact_name",
        "contact_info_json",
        "raw_requirement_text",
        "intent_summary",
        "parsed_requirement_json",
        "industry_primary",
        "industry_secondary",
        "region_scope_summary",
        "region_constraints_json",
        "min_revenue_yuan",
        "min_net_profit_yuan",
        "min_total_profit_yuan",
        "max_pe",
        "max_valuation_yuan",
        "market_cap_range_summary",
        "requires_control",
        "requires_consolidation",
        "accepts_minority_investment",
        "desired_equity_ratio_min",
        "desired_equity_ratio_max",
        "equity_ratio_summary",
        "equity_requirement_type",
        "acceptable_control_paths_json",
        "preferred_listed_status",
        "transaction_type",
        "negative_summary",
        "priority_summary",
        "preference_summary",
        "unknown_summary",
    }
    return {key: value for key, value in changes.items() if key in allowed_fields}


def _allowed_relation_changes(changes: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = {
        "status",
        "status_reason",
        "first_recommended_at",
        "last_contact_at",
        "last_event_at",
        "last_event_summary",
    }
    return {key: value for key, value in changes.items() if key in allowed_fields}


def _insert_relation_event(
    db: Session,
    action: dict[str, Any],
    relation_id: UUID,
    buyer_intent_id: UUID,
    seller_target_id: UUID,
    buyer_party_id: UUID | None,
    changes: dict[str, Any],
) -> None:
    event_type = changes.get("event_type") or _event_type_from_relation_status(changes.get("status"))
    db.execute(
        text(
            """
            insert into relation_event (
              team_id, workspace_id, relation_id, buyer_intent_id, buyer_party_id,
              seller_target_id, event_type, event_time, title, content, next_step,
              source_type, source_id, metadata_json, created_by
            )
            values (
              :team_id, :workspace_id, :relation_id, :buyer_intent_id, :buyer_party_id,
              :seller_target_id, :event_type, now(), :title, :content, :next_step,
              'extracted_action', :source_id, :metadata_json, :created_by
            )
            """
        ).bindparams(bindparam("metadata_json", type_=JSONB)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "relation_id": relation_id,
            "buyer_intent_id": buyer_intent_id,
            "buyer_party_id": buyer_party_id,
            "seller_target_id": seller_target_id,
            "event_type": event_type,
            "title": changes.get("event_title") or changes.get("status_reason"),
            "content": _relation_event_content(changes, action),
            "next_step": changes.get("next_step"),
            "source_id": action["id"],
            "metadata_json": {
                "business_update_id": str(action["business_update_id"]),
                "raw_evidence_text": action.get("raw_evidence_text"),
            },
            "created_by": DEFAULT_ADMIN_USER_ID,
        },
    )


def _event_type_from_relation_status(status_value: Any) -> str:
    if status_value == "recommended":
        return "recommended"
    if status_value == "interested":
        return "buyer_interested"
    if status_value == "not_interested":
        return "buyer_not_interested"
    if status_value == "due_diligence":
        return "due_diligence_started"
    if status_value == "deal_closed":
        return "deal_closed"
    if status_value == "paused":
        return "paused"
    return "other"


def _relation_event_content(changes: dict[str, Any], action: dict[str, Any]) -> str:
    return (
        changes.get("event_content")
        or changes.get("last_event_summary")
        or changes.get("status_reason")
        or action.get("raw_evidence_text")
        or ""
    )


def _required_uuid(value: Any, field_name: str) -> UUID:
    parsed = _optional_uuid(value)
    if parsed is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field_name} is required.")
    return parsed


def _action_source_context(action: dict[str, Any], *, default_source_label: str) -> dict[str, Any]:
    metadata = action.get("metadata_json") if isinstance(action.get("metadata_json"), dict) else {}
    evidence_id = action.get("evidence_id") or _optional_uuid(metadata.get("evidence_id"))
    return {
        "source_type": "extracted_action",
        "source_id": action["id"],
        "source_label": metadata.get("source_label") or default_source_label,
        "business_update_id": action["business_update_id"],
        "extracted_action_id": action["id"],
        "evidence_id": evidence_id,
        "confidence": action.get("confidence"),
        "raw_evidence_text": action.get("raw_evidence_text"),
        "action_type": action.get("action_type"),
    }


def _optional_uuid(value: Any) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _mark_action_applied(
    db: Session,
    extracted_action_id: UUID,
    *,
    review_status: str | None = None,
) -> None:
    review_status_clause = ""
    if review_status:
        review_status_clause = ", review_status = :review_status, reviewed_by = :reviewed_by, reviewed_at = now()"
    db.execute(
        text(
            f"""
            update extracted_action
            set applied_at = now(){review_status_clause}
            where id = :extracted_action_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "extracted_action_id": extracted_action_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "review_status": review_status,
            "reviewed_by": DEFAULT_ADMIN_USER_ID,
        },
    )


def _refresh_business_update_status(db: Session, business_update_id: UUID) -> None:
    pending_count = db.execute(
        text(
            """
            select count(*)
            from extracted_action
            where business_update_id = :business_update_id
              and applied_at is null
              and review_status in ('pending_review', 'accepted', 'auto_accepted')
            """
        ),
        {"business_update_id": business_update_id},
    ).scalar_one()
    new_status = "applied" if int(pending_count) == 0 else "partially_applied"
    db.execute(
        text(
            """
            update business_update
            set processing_status = :processing_status
            where id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "processing_status": new_status,
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
