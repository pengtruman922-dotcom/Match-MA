from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser, require_admin
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db


def _require_admin(current_user: CurrentUser) -> None:
    require_admin(current_user)


router = APIRouter(
    prefix="/data-dictionaries",
    tags=["data-dictionaries"],
    dependencies=[Depends(_require_admin)],
)


class IndustryTermCreate(BaseModel):
    term: str = Field(min_length=1, max_length=120)
    level: Literal["l1", "l2", "alias"]
    l1_name: str = Field(min_length=1, max_length=120)
    sort_order: int = 0
    active: bool = True


class IndustryTermUpdate(BaseModel):
    term: str | None = Field(default=None, min_length=1, max_length=120)
    l1_name: str | None = Field(default=None, min_length=1, max_length=120)
    sort_order: int | None = None
    active: bool | None = None


class IndustryTermOut(BaseModel):
    id: UUID
    term: str
    level: str
    l1_name: str
    active: bool
    sort_order: int
    usage_count: int
    created_at: str
    updated_at: str


@router.get("")
def list_dictionary_types(db: Session = Depends(get_db)) -> dict[str, object]:
    count = db.execute(
        text(
            """
            select count(*) from industry_taxonomy
            where team_id = :team_id and workspace_id = :workspace_id and active = true
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).scalar_one()
    return {
        "items": [
            {
                "key": "industry",
                "name": "行业分类",
                "description": "封闭一级行业、半开放二级行业及别名映射",
                "active_count": int(count or 0),
            }
        ]
    }


@router.get("/industry", response_model=list[IndustryTermOut])
def list_industry_terms(
    db: Session = Depends(get_db),
    q: str | None = Query(default=None, max_length=120),
    level: Literal["l1", "l2", "alias"] | None = None,
    include_inactive: bool = True,
) -> list[dict[str, object]]:
    where = ["tax.team_id = :team_id", "tax.workspace_id = :workspace_id"]
    params: dict[str, object] = {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}
    if q:
        where.append("(tax.term ilike :q or tax.l1_name ilike :q)")
        params["q"] = f"%{q.strip()}%"
    if level:
        where.append("tax.level = :level")
        params["level"] = level
    if not include_inactive:
        where.append("tax.active = true")
    rows = db.execute(
        text(
            f"""
            select tax.id, tax.term, tax.level, tax.l1_name, tax.active, tax.sort_order,
              tax.created_at::text as created_at, tax.updated_at::text as updated_at,
              case when tax.level = 'l1' then
                (select count(*) from seller_target st
                 where st.team_id = tax.team_id and st.workspace_id = tax.workspace_id
                   and st.deleted_at is null and st.industry_l1 = tax.term)
                +
                (select count(*) from buyer_intent bi
                 where bi.team_id = tax.team_id and bi.workspace_id = tax.workspace_id
                   and bi.deleted_at is null and bi.industries_json ? tax.term)
              else 0 end as usage_count
            from industry_taxonomy tax
            where {' and '.join(where)}
            order by tax.level, tax.sort_order, tax.term
            """
        ),
        params,
    ).mappings().all()
    return [{**dict(row), "usage_count": int(row["usage_count"] or 0)} for row in rows]


@router.post("/industry", response_model=IndustryTermOut, status_code=status.HTTP_201_CREATED)
def create_industry_term(payload: IndustryTermCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    term = payload.term.strip()
    l1_name = term if payload.level == "l1" else payload.l1_name.strip()
    _ensure_unique_term(db, term)
    _ensure_l1_exists(db, l1_name, allow_same_term=payload.level == "l1")
    row = db.execute(
        text(
            """
            insert into industry_taxonomy (
              team_id, workspace_id, term, level, l1_name, active, sort_order
            ) values (
              :team_id, :workspace_id, :term, :level, :l1_name, :active, :sort_order
            ) returning id
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "term": term,
            "level": payload.level,
            "l1_name": l1_name,
            "active": payload.active,
            "sort_order": payload.sort_order,
        },
    ).mappings().one()
    db.commit()
    return _get_industry_term(db, row["id"])


@router.patch("/industry/{term_id}", response_model=IndustryTermOut)
def update_industry_term(
    term_id: UUID,
    payload: IndustryTermUpdate,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    current = _get_industry_term(db, term_id)
    data = payload.model_dump(exclude_unset=True)
    if current["level"] == "l1" and data.get("term") and data["term"].strip() != current["term"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Used level-1 industry names cannot be renamed directly; add a replacement and migrate data first.",
        )
    if "term" in data:
        data["term"] = data["term"].strip()
        _ensure_unique_term(db, data["term"], exclude_id=term_id)
    if current["level"] == "l1":
        data["l1_name"] = current["term"]
    elif "l1_name" in data:
        data["l1_name"] = data["l1_name"].strip()
        _ensure_l1_exists(db, data["l1_name"])
    if not data:
        return current
    set_clauses = [f"{key} = :{key}" for key in data]
    db.execute(
        text(
            f"""
            update industry_taxonomy
            set {', '.join(set_clauses)}, updated_at = now()
            where id = :id and team_id = :team_id and workspace_id = :workspace_id
            """
        ),
        {**data, "id": term_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    )
    db.commit()
    return _get_industry_term(db, term_id)


def _get_industry_term(db: Session, term_id: UUID) -> dict[str, object]:
    row = db.execute(
        text(
            """
            select id, term, level, l1_name, active, sort_order,
              created_at::text as created_at, updated_at::text as updated_at
            from industry_taxonomy
            where id = :id and team_id = :team_id and workspace_id = :workspace_id
            """
        ),
        {"id": term_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Industry term not found.")
    usage_count = 0
    if row["level"] == "l1":
        usage_count = int(
            db.execute(
                text(
                    """
                    select
                      (select count(*) from seller_target
                       where team_id = :team_id and workspace_id = :workspace_id
                         and deleted_at is null and industry_l1 = :term)
                      +
                      (select count(*) from buyer_intent
                       where team_id = :team_id and workspace_id = :workspace_id
                         and deleted_at is null and industries_json ? :term)
                    """
                ),
                {
                    "term": row["term"],
                    "team_id": DEFAULT_TEAM_ID,
                    "workspace_id": DEFAULT_WORKSPACE_ID,
                },
            ).scalar_one()
            or 0
        )
    return {**dict(row), "usage_count": usage_count}


def _ensure_unique_term(db: Session, term: str, *, exclude_id: UUID | None = None) -> None:
    exclude_clause = ""
    params: dict[str, object] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "term": term,
    }
    if exclude_id is not None:
        exclude_clause = "and id <> :exclude_id"
        params["exclude_id"] = exclude_id
    row = db.execute(
        text(
            f"""
            select id from industry_taxonomy
            where team_id = :team_id and workspace_id = :workspace_id
              and lower(term) = lower(:term)
              {exclude_clause}
            limit 1
            """
        ),
        params,
    ).first()
    if row:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Industry term already exists.")


def _ensure_l1_exists(db: Session, l1_name: str, *, allow_same_term: bool = False) -> None:
    if allow_same_term:
        return
    exists = db.execute(
        text(
            """
            select 1 from industry_taxonomy
            where team_id = :team_id and workspace_id = :workspace_id
              and level = 'l1' and active = true and term = :l1_name
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "l1_name": l1_name},
    ).first()
    if exists is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Active level-1 industry not found.")
