from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser, require_admin
from backend.app.api.routes.utils import ensure_entity_visible, ensure_entity_writable
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db
from backend.app.services.search_docs import (
    create_embedding_job_for_search_doc,
    create_search_doc_rebuild_job,
    rebuild_buyer_intent_search_doc,
    rebuild_seller_target_search_doc,
)

router = APIRouter(tags=["search-docs"])


class SearchDocOut(BaseModel):
    id: UUID
    entity_type: str
    entity_id: UUID
    title: str | None
    full_text: str | None
    embedding_model: str | None
    embedding_dim: int | None
    has_embedding: bool
    source_version: int
    updated_at: str


class SearchDocRebuildOut(BaseModel):
    entity_type: str
    entity_id: UUID
    search_doc_id: UUID
    source_version: int
    full_text_length: int
    embedding_job_id: UUID | None = None


class SearchDocJobOut(BaseModel):
    job_id: UUID
    job_type: str
    status: str
    queue_name: str
    entity_type: str
    entity_id: UUID


class SearchDocBulkJobOut(BaseModel):
    entity_type: str
    requested_count: int
    job_count: int
    jobs: list[SearchDocJobOut]


@router.get("/search-docs/seller-targets/{seller_target_id}", response_model=SearchDocOut)
def get_seller_target_search_doc(
    seller_target_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_entity_visible(db, current_user, entity_type="seller_target", entity_id=seller_target_id)
    row = db.execute(
        text(
            """
            select
              id, 'seller_target' as entity_type, seller_target_id as entity_id,
              title, full_text, embedding_model, embedding_dim,
              embedding is not null as has_embedding,
              source_version, updated_at::text as updated_at
            from seller_target_search_doc
            where seller_target_id = :seller_target_id
              and doc_type = 'profile'
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seller target search doc not found.")
    return dict(row)


@router.get("/search-docs/buyer-intents/{buyer_intent_id}", response_model=SearchDocOut)
def get_buyer_intent_search_doc(
    buyer_intent_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_entity_visible(db, current_user, entity_type="buyer_intent", entity_id=buyer_intent_id)
    row = db.execute(
        text(
            """
            select
              id, 'buyer_intent' as entity_type, buyer_intent_id as entity_id,
              title, full_text, embedding_model, embedding_dim,
              embedding is not null as has_embedding,
              source_version, updated_at::text as updated_at
            from buyer_intent_search_doc
            where buyer_intent_id = :buyer_intent_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Buyer intent search doc not found.")
    return dict(row)


@router.post("/search-docs/seller-targets/{seller_target_id}/rebuild", response_model=SearchDocRebuildOut)
def rebuild_seller_target_search_doc_now(
    seller_target_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    enqueue_embedding: bool = Query(default=True),
) -> dict[str, Any]:
    ensure_entity_writable(db, current_user, entity_type="seller_target", entity_id=seller_target_id)
    result = rebuild_seller_target_search_doc(db, seller_target_id)
    embedding_job_id = None
    if enqueue_embedding:
        embedding_job_id = create_embedding_job_for_search_doc(
            db,
            owner_job_id=None,
            entity_type="seller_target",
            entity_id=seller_target_id,
            search_doc_id=result["search_doc_id"],
        )
    db.commit()
    return {
        "entity_type": "seller_target",
        "entity_id": seller_target_id,
        "search_doc_id": result["search_doc_id"],
        "source_version": result["source_version"],
        "full_text_length": len(result["full_text"] or ""),
        "embedding_job_id": embedding_job_id,
    }


@router.post("/search-docs/buyer-intents/{buyer_intent_id}/rebuild", response_model=SearchDocRebuildOut)
def rebuild_buyer_intent_search_doc_now(
    buyer_intent_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    enqueue_embedding: bool = Query(default=True),
) -> dict[str, Any]:
    ensure_entity_writable(db, current_user, entity_type="buyer_intent", entity_id=buyer_intent_id)
    result = rebuild_buyer_intent_search_doc(db, buyer_intent_id)
    embedding_job_id = None
    if enqueue_embedding:
        embedding_job_id = create_embedding_job_for_search_doc(
            db,
            owner_job_id=None,
            entity_type="buyer_intent",
            entity_id=buyer_intent_id,
            search_doc_id=result["search_doc_id"],
        )
    db.commit()
    return {
        "entity_type": "buyer_intent",
        "entity_id": buyer_intent_id,
        "search_doc_id": result["search_doc_id"],
        "source_version": result["source_version"],
        "full_text_length": len(result["full_text"] or ""),
        "embedding_job_id": embedding_job_id,
    }


@router.post("/search-docs/jobs/seller-targets/rebuild", response_model=SearchDocBulkJobOut)
def create_seller_target_search_doc_jobs(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=1000),
    include_embedded: bool = Query(default=False),
) -> dict[str, Any]:
    require_admin(current_user)
    rows = db.execute(
        text(
            f"""
            select st.id
            from seller_target st
            left join seller_target_search_doc sd
              on sd.seller_target_id = st.id
             and sd.doc_type = 'profile'
            where st.team_id = :team_id
              and st.workspace_id = :workspace_id
              and st.deleted_at is null
              and st.recommendation_status = 'recommendable'
              {'and (sd.id is null or sd.embedding is null)' if not include_embedded else ''}
            order by st.updated_at desc
            limit :limit
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "limit": limit,
        },
    ).mappings().all()
    jobs = [
        create_search_doc_rebuild_job(
            db,
            entity_type="seller_target",
            entity_id=row["id"],
            source="bulk_seller_target_search_doc_rebuild",
        )
        for row in rows
    ]
    db.commit()
    return {
        "entity_type": "seller_target",
        "requested_count": len(rows),
        "job_count": len(jobs),
        "jobs": jobs,
    }


@router.post("/search-docs/jobs/buyer-intents/rebuild", response_model=SearchDocBulkJobOut)
def create_buyer_intent_search_doc_jobs(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=1000),
    include_embedded: bool = Query(default=False),
) -> dict[str, Any]:
    require_admin(current_user)
    rows = db.execute(
        text(
            f"""
            select bi.id
            from buyer_intent bi
            left join buyer_intent_search_doc bd
              on bd.buyer_intent_id = bi.id
            where bi.team_id = :team_id
              and bi.workspace_id = :workspace_id
              and bi.deleted_at is null
              and bi.status = 'active'
              {'and (bd.id is null or bd.embedding is null)' if not include_embedded else ''}
            order by bi.updated_at desc
            limit :limit
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "limit": limit,
        },
    ).mappings().all()
    jobs = [
        create_search_doc_rebuild_job(
            db,
            entity_type="buyer_intent",
            entity_id=row["id"],
            source="bulk_buyer_intent_search_doc_rebuild",
        )
        for row in rows
    ]
    db.commit()
    return {
        "entity_type": "buyer_intent",
        "requested_count": len(rows),
        "job_count": len(jobs),
        "jobs": jobs,
    }


@router.post("/search-docs/seller-targets/{seller_target_id}/jobs", response_model=SearchDocJobOut)
def create_seller_target_search_doc_job(
    seller_target_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_entity_writable(db, current_user, entity_type="seller_target", entity_id=seller_target_id)
    result = create_search_doc_rebuild_job(
        db,
        entity_type="seller_target",
        entity_id=seller_target_id,
        source="search_doc_job_endpoint",
    )
    db.commit()
    return result


@router.post("/search-docs/buyer-intents/{buyer_intent_id}/jobs", response_model=SearchDocJobOut)
def create_buyer_intent_search_doc_job(
    buyer_intent_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_entity_writable(db, current_user, entity_type="buyer_intent", entity_id=buyer_intent_id)
    result = create_search_doc_rebuild_job(
        db,
        entity_type="buyer_intent",
        entity_id=buyer_intent_id,
        source="search_doc_job_endpoint",
    )
    db.commit()
    return result
