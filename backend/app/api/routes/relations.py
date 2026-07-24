from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser
from backend.app.api.routes.utils import (
    ensure_entity_visible,
    ensure_relation_visible,
    exclusion_visible_sql,
    owner_scope_required,
    relation_event_visible_sql,
    relation_visible_sql,
)
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db
from backend.app.services.relation_flow import (
    RELATION_EVENT_TYPES,
    RELATION_EVENT_LABELS,
    RELATION_STATUSES,
    change_relation_status,
    create_relation,
    delete_relation_event,
    record_relation_event,
    update_relation_event,
)

router = APIRouter(tags=["relations"])


class BuyerSellerRelationOut(BaseModel):
    id: UUID
    buyer_intent_id: UUID
    buyer_party_id: UUID | None
    seller_target_id: UUID
    status: str
    status_reason: str | None
    first_recommended_at: str | None
    last_contact_at: str | None
    last_event_at: str | None
    last_event_summary: str | None
    last_event_type: str | None
    last_event_content: str | None
    last_event_next_step: str | None
    deep_progress_elsewhere: bool = False
    buyer_intent_name: str | None
    buyer_name: str | None
    seller_target_name: str | None
    created_at: str
    updated_at: str
    metadata_json: dict[str, Any]


class RelationEventOut(BaseModel):
    id: UUID
    relation_id: UUID
    buyer_intent_id: UUID
    buyer_party_id: UUID | None
    seller_target_id: UUID
    event_type: str
    event_time: str
    title: str | None
    content: str | None
    next_step: str | None
    source_type: str | None
    source_id: UUID | None
    buyer_intent_name: str | None
    buyer_name: str | None
    seller_target_name: str | None
    metadata_json: dict[str, Any]
    created_at: str
    updated_at: str
    updated_by: UUID | None


class RelationCreate(BaseModel):
    buyer_intent_id: UUID
    seller_target_id: UUID
    source_summary: str | None = Field(default=None, max_length=1000)


class RelationCreateOut(BaseModel):
    relation: BuyerSellerRelationOut
    created: bool


class RelationStatusUpdate(BaseModel):
    status: str
    status_reason: str | None = Field(default=None, max_length=1000)
    next_step: str | None = Field(default=None, max_length=1000)


class RelationEventCreate(BaseModel):
    event_type: str
    title: str | None = Field(default=None, max_length=200)
    content: str | None = Field(default=None, max_length=4000)
    next_step: str | None = Field(default=None, max_length=1000)


class RelationEventUpdate(BaseModel):
    event_type: str | None = None
    title: str | None = Field(default=None, max_length=200)
    content: str | None = Field(default=None, max_length=4000)
    next_step: str | None = Field(default=None, max_length=1000)


class RelationMeta(BaseModel):
    statuses: list[str]
    event_types: list[dict[str, str]]


class BuyerIntentTargetExclusionOut(BaseModel):
    id: UUID
    buyer_intent_id: UUID
    buyer_party_id: UUID | None
    seller_target_id: UUID
    reason: str | None
    source_relation_id: UUID | None
    source_update_id: UUID | None
    source_event_id: UUID | None
    active: bool
    buyer_intent_name: str | None
    buyer_name: str | None
    seller_target_name: str | None
    created_at: str
    canceled_at: str | None


@router.get("/relations", response_model=list[BuyerSellerRelationOut])
def list_relations(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    seller_target_id: UUID | None = None,
    buyer_intent_id: UUID | None = None,
    buyer_party_id: UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    where = ["r.team_id = :team_id", "r.workspace_id = :workspace_id", "r.deleted_at is null"]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
        "offset": offset,
    }
    if seller_target_id:
        where.append("r.seller_target_id = :seller_target_id")
        params["seller_target_id"] = seller_target_id
    if buyer_intent_id:
        where.append("r.buyer_intent_id = :buyer_intent_id")
        params["buyer_intent_id"] = buyer_intent_id
    if buyer_party_id:
        where.append("r.buyer_party_id = :buyer_party_id")
        params["buyer_party_id"] = buyer_party_id
    if status_filter:
        where.append("r.status = :status")
        params["status"] = status_filter
    if q:
        where.append(
            """
            (
              st.target_name ilike :q or bi.intent_name ilike :q or bp.buyer_name ilike :q
              or r.last_event_summary ilike :q or r.status_reason ilike :q
            )
            """
        )
        params["q"] = f"%{q}%"
    if owner_scope_required(current_user):
        where.append(relation_visible_sql("r"))
        params["scope_user_id"] = current_user.user_id

    rows = db.execute(
        text(
            f"""
            select {_relation_select_columns()}
            from buyer_seller_relation r
            join seller_target st on st.id = r.seller_target_id
            join buyer_intent bi on bi.id = r.buyer_intent_id
            left join buyer_party bp on bp.id = r.buyer_party_id
            where {' and '.join(where)}
            order by coalesce(r.last_event_at, r.updated_at, r.created_at) desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


@router.get("/relations/{relation_id}", response_model=BuyerSellerRelationOut)
def get_relation(relation_id: UUID, current_user: CurrentUser, db: Session = Depends(get_db)) -> dict[str, Any]:
    ensure_relation_visible(db, current_user, relation_id)
    row = db.execute(
        text(
            f"""
            select {_relation_select_columns()}
            from buyer_seller_relation r
            join seller_target st on st.id = r.seller_target_id
            join buyer_intent bi on bi.id = r.buyer_intent_id
            left join buyer_party bp on bp.id = r.buyer_party_id
            where r.id = :relation_id
              and r.team_id = :team_id
              and r.workspace_id = :workspace_id
              and r.deleted_at is null
            """
        ),
        {
            "relation_id": relation_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Relation not found.")
    return dict(row)


@router.get("/relations/{relation_id}/events", response_model=list[RelationEventOut])
def list_relation_events(
    relation_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    ensure_relation_visible(db, current_user, relation_id)
    return _list_relation_events(
        db,
        current_user,
        ["e.relation_id = :relation_id"],
        {"relation_id": relation_id},
        limit=limit,
        offset=offset,
    )


@router.get("/relations-meta", response_model=RelationMeta)
def get_relations_meta() -> dict[str, Any]:
    return {
        "statuses": list(RELATION_STATUSES),
        "event_types": [
            {"value": event_type, "label": RELATION_EVENT_LABELS[event_type]}
            for event_type in RELATION_EVENT_TYPES
        ],
    }


@router.post("/relations", response_model=RelationCreateOut, status_code=201)
def create_relation_endpoint(
    payload: RelationCreate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    # 能看见任一侧即可发起（推荐/关联对手方都从自己负责的一侧出发）。
    ensure_entity_visible(db, current_user, entity_type="buyer_intent", entity_id=payload.buyer_intent_id)
    relation_id, created = create_relation(
        db,
        buyer_intent_id=payload.buyer_intent_id,
        seller_target_id=payload.seller_target_id,
        actor_user_id=current_user.user_id,
        source_summary=payload.source_summary,
    )
    return {"relation": get_relation(relation_id, current_user, db), "created": created}


@router.patch("/relations/{relation_id}", response_model=BuyerSellerRelationOut)
def update_relation_status(
    relation_id: UUID,
    payload: RelationStatusUpdate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_relation_visible(db, current_user, relation_id)
    change_relation_status(
        db,
        relation_id,
        actor_user_id=current_user.user_id,
        new_status=payload.status,
        status_reason=payload.status_reason,
        next_step=payload.next_step,
    )
    return get_relation(relation_id, current_user, db)


@router.post("/relations/{relation_id}/events", response_model=RelationEventOut, status_code=201)
def create_relation_event(
    relation_id: UUID,
    payload: RelationEventCreate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_relation_visible(db, current_user, relation_id)
    event_id = record_relation_event(
        db,
        relation_id,
        actor_user_id=current_user.user_id,
        event_type=payload.event_type,
        title=payload.title,
        content=payload.content,
        next_step=payload.next_step,
    )
    row = db.execute(
        text(
            f"""
            select {_event_select_columns()}
            from relation_event e
            join buyer_intent bi on bi.id = e.buyer_intent_id
            join seller_target st on st.id = e.seller_target_id
            left join buyer_party bp on bp.id = e.buyer_party_id
            where e.id = :event_id
            """
        ),
        {"event_id": event_id},
    ).mappings().one()
    return dict(row)


@router.patch("/relations/{relation_id}/events/{event_id}", response_model=RelationEventOut)
def update_relation_event_endpoint(
    relation_id: UUID,
    event_id: UUID,
    payload: RelationEventUpdate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_relation_visible(db, current_user, relation_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="至少修改一个动态字段。")
    update_relation_event(
        db,
        relation_id,
        event_id,
        actor_user_id=current_user.user_id,
        changes=changes,
    )
    return _get_relation_event_or_404(db, event_id)


@router.delete("/relations/{relation_id}/events/{event_id}", status_code=204)
def delete_relation_event_endpoint(
    relation_id: UUID,
    event_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> None:
    ensure_relation_visible(db, current_user, relation_id)
    delete_relation_event(db, relation_id, event_id, actor_user_id=current_user.user_id)
    return None


@router.get("/relation-events", response_model=list[RelationEventOut])
def list_relation_events_by_entity(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    relation_id: UUID | None = None,
    seller_target_id: UUID | None = None,
    buyer_intent_id: UUID | None = None,
    buyer_party_id: UUID | None = None,
    event_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    filters: list[str] = []
    params: dict[str, Any] = {}
    if relation_id:
        filters.append("e.relation_id = :relation_id")
        params["relation_id"] = relation_id
    if seller_target_id:
        filters.append("e.seller_target_id = :seller_target_id")
        params["seller_target_id"] = seller_target_id
    if buyer_intent_id:
        filters.append("e.buyer_intent_id = :buyer_intent_id")
        params["buyer_intent_id"] = buyer_intent_id
    if buyer_party_id:
        filters.append("e.buyer_party_id = :buyer_party_id")
        params["buyer_party_id"] = buyer_party_id
    if event_type:
        filters.append("e.event_type = :event_type")
        params["event_type"] = event_type
    return _list_relation_events(db, current_user, filters, params, limit=limit, offset=offset)


@router.get("/buyer-intent-target-exclusions", response_model=list[BuyerIntentTargetExclusionOut])
def list_buyer_intent_target_exclusions(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    buyer_intent_id: UUID | None = None,
    seller_target_id: UUID | None = None,
    active: bool | None = Query(default=True),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    where = ["x.team_id = :team_id", "x.workspace_id = :workspace_id"]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
        "offset": offset,
    }
    if buyer_intent_id:
        where.append("x.buyer_intent_id = :buyer_intent_id")
        params["buyer_intent_id"] = buyer_intent_id
    if seller_target_id:
        where.append("x.seller_target_id = :seller_target_id")
        params["seller_target_id"] = seller_target_id
    if active is not None:
        where.append("x.active = :active")
        params["active"] = active
    if owner_scope_required(current_user):
        where.append(exclusion_visible_sql("x"))
        params["scope_user_id"] = current_user.user_id

    rows = db.execute(
        text(
            f"""
            select
              x.id, x.buyer_intent_id, x.buyer_party_id, x.seller_target_id,
              x.reason, x.source_relation_id, x.source_update_id, x.source_event_id,
              x.active, bi.intent_name as buyer_intent_name, bp.buyer_name,
              st.target_name as seller_target_name,
              x.created_at::text as created_at, x.canceled_at::text as canceled_at
            from buyer_intent_target_exclusion x
            join buyer_intent bi on bi.id = x.buyer_intent_id
            join seller_target st on st.id = x.seller_target_id
            left join buyer_party bp on bp.id = x.buyer_party_id
            where {' and '.join(where)}
            order by x.created_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


def _relation_select_columns() -> str:
    return """
      r.id, r.buyer_intent_id, r.buyer_party_id, r.seller_target_id,
      r.status, r.status_reason,
      r.first_recommended_at::text as first_recommended_at,
      r.last_contact_at::text as last_contact_at,
      r.last_event_at::text as last_event_at,
      r.last_event_summary,
      (
        select e.event_type from relation_event e
        where e.relation_id = r.id and e.team_id = r.team_id
          and e.workspace_id = r.workspace_id and e.deleted_at is null
        order by e.event_time desc, e.created_at desc limit 1
      ) as last_event_type,
      (
        select e.content from relation_event e
        where e.relation_id = r.id and e.team_id = r.team_id
          and e.workspace_id = r.workspace_id and e.deleted_at is null
        order by e.event_time desc, e.created_at desc limit 1
      ) as last_event_content,
      (
        select e.next_step from relation_event e
        where e.relation_id = r.id and e.team_id = r.team_id
          and e.workspace_id = r.workspace_id and e.deleted_at is null
        order by e.event_time desc, e.created_at desc limit 1
      ) as last_event_next_step,
      exists (
        select 1 from buyer_seller_relation other
        where other.team_id = r.team_id and other.workspace_id = r.workspace_id
          and other.seller_target_id = r.seller_target_id
          and other.buyer_intent_id <> r.buyer_intent_id
          and other.deleted_at is null
          and other.status in ('recommended', 'interested', 'in_discussion', 'due_diligence', 'agreement')
      ) as deep_progress_elsewhere,
      bi.intent_name as buyer_intent_name,
      bp.buyer_name,
      st.target_name as seller_target_name,
      r.created_at::text as created_at,
      r.updated_at::text as updated_at,
      r.metadata_json
    """


def _event_select_columns() -> str:
    return """
      e.id, e.relation_id, e.buyer_intent_id, e.buyer_party_id, e.seller_target_id,
      e.event_type, e.event_time::text as event_time, e.title, e.content, e.next_step,
      e.source_type, e.source_id,
      bi.intent_name as buyer_intent_name,
      bp.buyer_name,
      st.target_name as seller_target_name,
      e.metadata_json,
      e.created_at::text as created_at,
      e.updated_at::text as updated_at,
      e.updated_by
    """


def _list_relation_events(
    db: Session,
    current_user: CurrentUser,
    filters: list[str],
    params: dict[str, Any],
    *,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where = ["e.team_id = :team_id", "e.workspace_id = :workspace_id", "e.deleted_at is null", *filters]
    if owner_scope_required(current_user):
        where.append(relation_event_visible_sql("e"))
        params["scope_user_id"] = current_user.user_id
    rows = db.execute(
        text(
            f"""
            select {_event_select_columns()}
            from relation_event e
            join buyer_intent bi on bi.id = e.buyer_intent_id
            join seller_target st on st.id = e.seller_target_id
            left join buyer_party bp on bp.id = e.buyer_party_id
            where {' and '.join(where)}
            order by e.event_time desc, e.created_at desc
            limit :limit offset :offset
            """
        ),
        {
            **params,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "limit": limit,
            "offset": offset,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _get_relation_event_or_404(db: Session, event_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            f"""
            select {_event_select_columns()}
            from relation_event e
            join buyer_intent bi on bi.id = e.buyer_intent_id
            join seller_target st on st.id = e.seller_target_id
            left join buyer_party bp on bp.id = e.buyer_party_id
            where e.id = :event_id and e.team_id = :team_id and e.workspace_id = :workspace_id
              and e.deleted_at is null
            """
        ),
        {"event_id": event_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Relation event not found.")
    return dict(row)


def _ensure_relation_exists(db: Session, relation_id: UUID) -> None:
    exists = db.execute(
        text(
            """
            select exists(
              select 1
              from buyer_seller_relation
              where id = :relation_id
                and team_id = :team_id
                and workspace_id = :workspace_id
                and deleted_at is null
            )
            """
        ),
        {
            "relation_id": relation_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).scalar_one()
    if not exists:
        raise HTTPException(status_code=404, detail="Relation not found.")
