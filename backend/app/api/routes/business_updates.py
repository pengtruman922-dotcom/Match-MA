from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db

router = APIRouter(prefix="/business-updates", tags=["business-updates"])


class BusinessUpdateCreate(BaseModel):
    raw_text: str = Field(min_length=1)
    input_type: str = "text"
    bound_seller_target_ids: list[UUID] = Field(default_factory=list)
    bound_buyer_party_ids: list[UUID] = Field(default_factory=list)
    bound_buyer_intent_ids: list[UUID] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class BusinessUpdateOut(BaseModel):
    id: UUID
    raw_text: str | None
    input_type: str
    processing_status: str
    bound_seller_target_ids_json: list[Any]
    bound_buyer_party_ids_json: list[Any]
    bound_buyer_intent_ids_json: list[Any]
    bound_recommendation_session_id: UUID | None
    created_by: UUID | None
    created_at: str
    metadata_json: dict[str, Any]


class BusinessUpdateProcessOut(BaseModel):
    job_id: UUID
    job_type: str
    status: str
    queue_name: str
    business_update_id: UUID


@router.post("", response_model=BusinessUpdateOut, status_code=status.HTTP_201_CREATED)
def create_business_update(
    payload: BusinessUpdateCreate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    statement = text(
        """
        insert into business_update (
          team_id, workspace_id, raw_text, input_type, processing_status,
          bound_seller_target_ids_json, bound_buyer_party_ids_json, bound_buyer_intent_ids_json,
          created_by, metadata_json
        )
        values (
          :team_id, :workspace_id, :raw_text, :input_type, 'pending',
          :bound_seller_target_ids_json, :bound_buyer_party_ids_json, :bound_buyer_intent_ids_json,
          :created_by, :metadata_json
        )
        returning
          id, raw_text, input_type, processing_status,
          bound_seller_target_ids_json, bound_buyer_party_ids_json, bound_buyer_intent_ids_json,
          bound_recommendation_session_id, created_by,
          created_at::text as created_at, metadata_json
        """
    ).bindparams(
        bindparam("bound_seller_target_ids_json", type_=JSONB),
        bindparam("bound_buyer_party_ids_json", type_=JSONB),
        bindparam("bound_buyer_intent_ids_json", type_=JSONB),
        bindparam("metadata_json", type_=JSONB),
    )

    row = db.execute(
        statement,
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "raw_text": payload.raw_text,
            "input_type": payload.input_type,
            "bound_seller_target_ids_json": [str(item) for item in payload.bound_seller_target_ids],
            "bound_buyer_party_ids_json": [str(item) for item in payload.bound_buyer_party_ids],
            "bound_buyer_intent_ids_json": [str(item) for item in payload.bound_buyer_intent_ids],
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": payload.metadata_json,
        },
    ).mappings().one()
    db.commit()
    return dict(row)


@router.post("/{business_update_id}/process", response_model=BusinessUpdateProcessOut)
def process_business_update(
    business_update_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _ensure_business_update_exists(db, business_update_id)

    existing_job = db.execute(
        text(
            """
            select id, job_type, status, queue_name, entity_id
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and job_type = 'business_update_extract_actions'
              and entity_type = 'business_update'
              and entity_id = :business_update_id
              and status in ('queued', 'running', 'retry_waiting')
            order by created_at desc
            limit 1
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "business_update_id": business_update_id,
        },
    ).mappings().one_or_none()
    if existing_job is not None:
        return {
            "job_id": existing_job["id"],
            "job_type": existing_job["job_type"],
            "status": existing_job["status"],
            "queue_name": existing_job["queue_name"],
            "business_update_id": existing_job["entity_id"],
        }

    job = db.execute(
        text(
            """
            insert into background_job (
              team_id, workspace_id, job_type, priority, queue_name,
              entity_type, entity_id, idempotency_key, payload_json,
              created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, 'business_update_extract_actions', 100, 'llm',
              'business_update', :business_update_id, :idempotency_key, :payload_json,
              :created_by, :metadata_json
            )
            returning id, job_type, status, queue_name, entity_id
            """
        ).bindparams(
            bindparam("payload_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "business_update_id": business_update_id,
            "idempotency_key": f"business_update_extract_actions:{business_update_id}",
            "payload_json": {"business_update_id": str(business_update_id)},
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {"source": "api_process_endpoint"},
        },
    ).mappings().one()

    db.execute(
        text(
            """
            update business_update
            set processing_status = 'processing'
            where id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and processing_status in ('pending', 'failed')
            """
        ),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    db.commit()
    return {
        "job_id": job["id"],
        "job_type": job["job_type"],
        "status": job["status"],
        "queue_name": job["queue_name"],
        "business_update_id": job["entity_id"],
    }


@router.get("", response_model=list[BusinessUpdateOut])
def list_business_updates(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    processing_status: str | None = None,
    seller_target_id: UUID | None = None,
    buyer_intent_id: UUID | None = None,
) -> list[dict[str, Any]]:
    where = ["team_id = :team_id", "workspace_id = :workspace_id"]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
        "offset": offset,
    }

    if processing_status:
        where.append("processing_status = :processing_status")
        params["processing_status"] = processing_status
    if seller_target_id:
        where.append("bound_seller_target_ids_json ? :seller_target_id")
        params["seller_target_id"] = str(seller_target_id)
    if buyer_intent_id:
        where.append("bound_buyer_intent_ids_json ? :buyer_intent_id")
        params["buyer_intent_id"] = str(buyer_intent_id)

    rows = db.execute(
        text(
            f"""
            select
              id, raw_text, input_type, processing_status,
              bound_seller_target_ids_json, bound_buyer_party_ids_json, bound_buyer_intent_ids_json,
              bound_recommendation_session_id, created_by,
              created_at::text as created_at, metadata_json
            from business_update
            where {' and '.join(where)}
            order by created_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


@router.get("/{business_update_id}", response_model=BusinessUpdateOut)
def get_business_update(
    business_update_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, raw_text, input_type, processing_status,
              bound_seller_target_ids_json, bound_buyer_party_ids_json, bound_buyer_intent_ids_json,
              bound_recommendation_session_id, created_by,
              created_at::text as created_at, metadata_json
            from business_update
            where id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business update not found.")

    return dict(row)


def _ensure_business_update_exists(db: Session, business_update_id: UUID) -> None:
    row = db.execute(
        text(
            """
            select 1
            from business_update
            where id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business update not found.")
