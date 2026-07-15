from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser, require_admin
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db
from backend.app.services.industry_dictionary_import import parse_industry_import


def _require_admin(current_user: CurrentUser) -> None:
    require_admin(current_user)


router = APIRouter(
    prefix="/data-dictionaries",
    tags=["data-dictionaries"],
    dependencies=[Depends(_require_admin)],
)


class IndustryAliasOut(BaseModel):
    id: UUID
    term: str
    active: bool


class IndustryTermCreate(BaseModel):
    term: str = Field(min_length=1, max_length=120)
    level: Literal["l1", "l2"]
    parent_id: UUID | None = None
    aliases: list[str] = Field(default_factory=list, max_length=100)
    sort_order: int = 0
    active: bool = True


class IndustryTermUpdate(BaseModel):
    term: str | None = Field(default=None, min_length=1, max_length=120)
    parent_id: UUID | None = None
    aliases: list[str] | None = Field(default=None, max_length=100)
    sort_order: int | None = None
    active: bool | None = None


class IndustryTermOut(BaseModel):
    id: UUID
    term: str
    level: Literal["l1", "l2"]
    l1_name: str
    parent_id: UUID | None
    parent_name: str | None
    aliases: list[IndustryAliasOut] = Field(default_factory=list)
    active: bool
    sort_order: int
    usage_count: int
    created_at: str
    updated_at: str


class IndustryImportRowOut(BaseModel):
    row_number: int
    l1: str
    l2: str | None
    aliases: list[str]
    active: bool
    status: Literal["ready", "error"]
    message: str


class IndustryImportOut(BaseModel):
    dry_run: bool
    total_rows: int
    ready_rows: int
    error_rows: int
    created_l1: int = 0
    created_l2: int = 0
    created_aliases: int = 0
    rows: list[IndustryImportRowOut]


@router.get("")
def list_dictionary_types(db: Session = Depends(get_db)) -> dict[str, object]:
    count = db.execute(
        text(
            """
            select count(*) from industry_taxonomy
            where team_id = :team_id and workspace_id = :workspace_id
              and active = true and level in ('l1', 'l2')
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).scalar_one()
    return {
        "items": [
            {
                "key": "industry",
                "name": "行业分类",
                "description": "一级、二级标准行业及其别名映射",
                "active_count": int(count or 0),
            }
        ]
    }


@router.get("/industry", response_model=list[IndustryTermOut])
def list_industry_terms(
    db: Session = Depends(get_db),
    q: str | None = Query(default=None, max_length=120),
    level: Literal["l1", "l2"] | None = None,
    include_inactive: bool = True,
) -> list[dict[str, Any]]:
    where = [
        "tax.team_id = :team_id",
        "tax.workspace_id = :workspace_id",
        "tax.level in ('l1', 'l2')",
    ]
    params: dict[str, object] = {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}
    if q:
        where.append(
            "(tax.term ilike :q or tax.l1_name ilike :q or exists ("
            "select 1 from industry_taxonomy alias where alias.canonical_term_id = tax.id "
            "and alias.active = true and alias.term ilike :q))"
        )
        params["q"] = f"%{q.strip()}%"
    if level:
        where.append("tax.level = :level")
        params["level"] = level
    if not include_inactive:
        where.append("tax.active = true")
    rows = db.execute(text(_industry_term_select_sql(" and ".join(where))), params).mappings().all()
    return [_industry_term_output(row) for row in rows]


@router.post("/industry", response_model=IndustryTermOut, status_code=status.HTTP_201_CREATED)
def create_industry_term(payload: IndustryTermCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    term = payload.term.strip()
    _ensure_unique_term(db, term)
    parent = None
    if payload.level == "l2":
        if payload.parent_id is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="二级行业必须选择所属一级行业。")
        parent = _get_industry_term(db, payload.parent_id)
        if parent["level"] != "l1":
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="二级行业的父级必须是一级行业。")
    l1_name = term if payload.level == "l1" else str(parent["term"])
    row = db.execute(
        text(
            """
            insert into industry_taxonomy (
              team_id, workspace_id, term, level, l1_name, parent_id, active, sort_order
            ) values (
              :team_id, :workspace_id, :term, :level, :l1_name, :parent_id, :active, :sort_order
            ) returning id
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "term": term,
            "level": payload.level,
            "l1_name": l1_name,
            "parent_id": payload.parent_id,
            "active": payload.active,
            "sort_order": payload.sort_order,
        },
    ).mappings().one()
    _sync_aliases(db, canonical_id=row["id"], aliases=payload.aliases, l1_name=l1_name)
    db.commit()
    return _get_industry_term(db, row["id"])


@router.patch("/industry/{term_id}", response_model=IndustryTermOut)
def update_industry_term(
    term_id: UUID,
    payload: IndustryTermUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    current = _get_industry_term(db, term_id)
    data = payload.model_dump(exclude_unset=True)
    aliases = data.pop("aliases", None)
    if current["level"] == "l1" and data.get("term") and data["term"].strip() != current["term"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="一级行业名称不能直接修改。")
    if "term" in data:
        data["term"] = data["term"].strip()
        _ensure_unique_term(db, data["term"], exclude_id=term_id)
    l1_name = str(current["l1_name"])
    if current["level"] == "l1":
        data["parent_id"] = None
        data["l1_name"] = current["term"]
    elif "parent_id" in data:
        if data["parent_id"] is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="二级行业必须选择所属一级行业。")
        parent = _get_industry_term(db, data["parent_id"])
        if parent["level"] != "l1":
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="二级行业的父级必须是一级行业。")
        l1_name = str(parent["term"])
        data["l1_name"] = l1_name
    if data:
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
    if aliases is not None:
        _sync_aliases(db, canonical_id=term_id, aliases=aliases, l1_name=l1_name)
    elif current["level"] == "l2" and "parent_id" in data:
        db.execute(
            text(
                """
                update industry_taxonomy
                set l1_name = :l1_name, updated_at = now()
                where canonical_term_id = :canonical_id
                """
            ),
            {"l1_name": l1_name, "canonical_id": term_id},
        )
    db.commit()
    return _get_industry_term(db, term_id)


@router.get("/industry/import-template")
def download_industry_import_template() -> Response:
    content = "一级行业,二级行业,别名,状态\n制造与工业,模具制造,精密模具加工、模具加工,启用\n"
    return Response(
        content=content.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="industry_dictionary_template.csv"'},
    )


@router.post("/industry/import", response_model=IndustryImportOut)
async def import_industry_dictionary(
    file: UploadFile = File(...),
    dry_run: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="导入文件不能超过 5MB。")
    try:
        rows = parse_industry_import(file.filename or "industry.csv", content)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    preview_rows = _validate_import_rows(db, rows)
    errors = [row for row in preview_rows if row["status"] == "error"]
    result: dict[str, Any] = {
        "dry_run": dry_run,
        "total_rows": len(preview_rows),
        "ready_rows": len(preview_rows) - len(errors),
        "error_rows": len(errors),
        "rows": preview_rows,
    }
    if dry_run or errors:
        return result
    try:
        counts = _apply_import_rows(db, rows)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {**result, **counts}


def _industry_term_select_sql(where_sql: str) -> str:
    return f"""
        select tax.id, tax.term, tax.level, tax.l1_name, tax.parent_id,
          parent.term as parent_name, tax.active, tax.sort_order,
          tax.created_at::text as created_at, tax.updated_at::text as updated_at,
          coalesce((
            select jsonb_agg(jsonb_build_object('id', alias.id, 'term', alias.term, 'active', alias.active)
              order by alias.term)
            from industry_taxonomy alias
            where alias.canonical_term_id = tax.id
          ), '[]'::jsonb) as aliases,
          case when tax.level = 'l1' then
            (select count(*) from seller_target st
             where st.team_id = tax.team_id and st.workspace_id = tax.workspace_id
               and st.deleted_at is null and st.industry_l1 = tax.term)
            +
            (select count(*) from buyer_intent bi
             where bi.team_id = tax.team_id and bi.workspace_id = tax.workspace_id
               and bi.deleted_at is null and bi.industries_json ? tax.term)
          else
            (select count(*) from seller_target st
             where st.team_id = tax.team_id and st.workspace_id = tax.workspace_id
               and st.deleted_at is null and st.industry_secondary = tax.term)
          end as usage_count
        from industry_taxonomy tax
        left join industry_taxonomy parent on parent.id = tax.parent_id
        where {where_sql}
        order by case tax.level when 'l1' then 0 else 1 end,
          coalesce(parent.sort_order, tax.sort_order), tax.sort_order, tax.term
    """


def _get_industry_term(db: Session, term_id: UUID) -> dict[str, Any]:
    rows = db.execute(
        text(
            _industry_term_select_sql(
                "tax.id = :id and tax.team_id = :team_id and tax.workspace_id = :workspace_id "
                "and tax.level in ('l1', 'l2')"
            )
        ),
        {"id": term_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().all()
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Industry term not found.")
    return _industry_term_output(rows[0])


def _industry_term_output(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["usage_count"] = int(result.get("usage_count") or 0)
    result["aliases"] = list(result.get("aliases") or [])
    return result


def _sync_aliases(db: Session, *, canonical_id: UUID, aliases: list[str], l1_name: str) -> None:
    cleaned: list[str] = []
    for raw in aliases:
        alias = str(raw or "").strip()[:120]
        if alias and alias not in cleaned:
            cleaned.append(alias)
    existing = db.execute(
        text("select id, term, active from industry_taxonomy where canonical_term_id = :canonical_id"),
        {"canonical_id": canonical_id},
    ).mappings().all()
    existing_by_term = {str(row["term"]).lower(): dict(row) for row in existing}
    desired = {alias.lower(): alias for alias in cleaned}
    for lowered, row in existing_by_term.items():
        db.execute(
            text("update industry_taxonomy set active = :active, updated_at = now() where id = :id"),
            {"active": lowered in desired, "id": row["id"]},
        )
    for lowered, alias in desired.items():
        if lowered in existing_by_term:
            continue
        _ensure_unique_term(db, alias)
        db.execute(
            text(
                """
                insert into industry_taxonomy (
                  team_id, workspace_id, term, level, l1_name, canonical_term_id, active
                ) values (
                  :team_id, :workspace_id, :term, 'alias', :l1_name, :canonical_term_id, true
                )
                """
            ),
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "term": alias,
                "l1_name": l1_name,
                "canonical_term_id": canonical_id,
            },
        )


def _validate_import_rows(db: Session, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = _industry_terms_by_lower_name(db)
    existing_by_id = {value["id"]: value for value in existing.values()}
    planned_levels: dict[str, str] = {
        key: str(value["level"])
        for key, value in existing.items()
        if value["level"] in {"l1", "l2"}
    }
    planned_l2_parents: dict[str, str] = {}
    alias_owners: dict[str, str | None] = {}
    for key, value in existing.items():
        if value["level"] == "l2":
            parent = existing_by_id.get(value.get("parent_id"))
            planned_l2_parents[key] = str(parent["term"]).lower() if parent else str(value["l1_name"]).lower()
        elif value["level"] == "alias":
            canonical = existing_by_id.get(value.get("canonical_term_id"))
            alias_owners[key] = str(canonical["term"]).lower() if canonical else None
    output: list[dict[str, Any]] = []
    for row in rows:
        errors: list[str] = []
        l1 = str(row["l1"] or "").strip()
        l2 = str(row.get("l2") or "").strip() or None
        l1_key = l1.lower()
        l2_key = l2.lower() if l2 else None
        if not l1:
            errors.append("缺少一级行业")
        elif l1_key in existing and existing[l1_key]["level"] != "l1":
            errors.append("一级行业名称已被其他层级占用")
        elif l1_key in planned_levels and planned_levels[l1_key] != "l1":
            errors.append("一级行业名称已被其他层级占用")
        else:
            planned_levels[l1_key] = "l1"
        if l2 and l2_key:
            if l2_key in existing and existing[l2_key]["level"] != "l2":
                errors.append("二级行业名称已被其他层级占用")
            elif l2_key in planned_levels and planned_levels[l2_key] != "l2":
                errors.append("二级行业名称已被其他层级占用")
            elif l2_key in planned_l2_parents and planned_l2_parents[l2_key] != l1_key:
                errors.append("二级行业已归属于其他一级行业")
            else:
                planned_levels[l2_key] = "l2"
                planned_l2_parents[l2_key] = l1_key
        canonical_key = l2_key or l1_key
        for alias in row["aliases"]:
            alias_key = alias.lower()
            if alias_key in planned_levels:
                errors.append(f"别名与标准行业重名：{alias}")
            elif alias_key in existing and existing[alias_key]["level"] != "alias":
                errors.append(f"别名已被标准行业占用：{alias}")
            elif alias_key in alias_owners and alias_owners[alias_key] != canonical_key:
                errors.append(f"别名已归属于其他行业：{alias}")
            else:
                alias_owners[alias_key] = canonical_key
        output.append(
            {
                **row,
                "l1": l1,
                "l2": l2,
                "status": "error" if errors else "ready",
                "message": "；".join(errors) if errors else "可导入",
            }
        )
    return output


def _apply_import_rows(db: Session, rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"created_l1": 0, "created_l2": 0, "created_aliases": 0}
    for row in rows:
        l1_id, created = _ensure_import_canonical(db, term=row["l1"], level="l1", parent=None, active=row["active"])
        counts["created_l1"] += int(created)
        canonical_id = l1_id
        if row.get("l2"):
            canonical_id, created = _ensure_import_canonical(
                db,
                term=row["l2"],
                level="l2",
                parent={"id": l1_id, "term": row["l1"]},
                active=row["active"],
            )
            counts["created_l2"] += int(created)
        for alias in row["aliases"]:
            counts["created_aliases"] += int(
                _ensure_import_alias(
                    db,
                    term=alias,
                    canonical_id=canonical_id,
                    l1_name=row["l1"],
                )
            )
    return counts


def _ensure_import_canonical(
    db: Session,
    *,
    term: str,
    level: Literal["l1", "l2"],
    parent: dict[str, Any] | None,
    active: bool,
) -> tuple[UUID, bool]:
    existing = db.execute(
        text(
            """
            select id from industry_taxonomy
            where team_id = :team_id and workspace_id = :workspace_id and lower(term) = lower(:term)
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "term": term},
    ).scalar_one_or_none()
    if existing:
        db.execute(
            text(
                """
                update industry_taxonomy
                set active = :active,
                    parent_id = case when :level = 'l2' then :parent_id else null end,
                    l1_name = :l1_name,
                    updated_at = now()
                where id = :id
                """
            ),
            {
                "active": active,
                "level": level,
                "parent_id": parent["id"] if parent else None,
                "l1_name": term if level == "l1" else parent["term"],
                "id": existing,
            },
        )
        return existing, False
    row = db.execute(
        text(
            """
            insert into industry_taxonomy (
              team_id, workspace_id, term, level, l1_name, parent_id, active
            ) values (
              :team_id, :workspace_id, :term, :level, :l1_name, :parent_id, :active
            ) returning id
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "term": term,
            "level": level,
            "l1_name": term if level == "l1" else parent["term"],
            "parent_id": parent["id"] if parent else None,
            "active": active,
        },
    ).scalar_one()
    return row, True


def _ensure_import_alias(
    db: Session,
    *,
    term: str,
    canonical_id: UUID,
    l1_name: str,
) -> bool:
    existing = db.execute(
        text(
            """
            select id from industry_taxonomy
            where team_id = :team_id and workspace_id = :workspace_id
              and lower(term) = lower(:term) and level = 'alias'
              and canonical_term_id = :canonical_term_id
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "term": term,
            "canonical_term_id": canonical_id,
        },
    ).scalar_one_or_none()
    if existing:
        db.execute(
            text(
                """
                update industry_taxonomy
                set active = true, l1_name = :l1_name, updated_at = now()
                where id = :id
                """
            ),
            {"l1_name": l1_name, "id": existing},
        )
        return False
    db.execute(
        text(
            """
            insert into industry_taxonomy (
              team_id, workspace_id, term, level, l1_name, canonical_term_id, active
            ) values (
              :team_id, :workspace_id, :term, 'alias', :l1_name, :canonical_term_id, true
            )
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "term": term,
            "l1_name": l1_name,
            "canonical_term_id": canonical_id,
        },
    )
    return True


def _industry_terms_by_lower_name(db: Session) -> dict[str, dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select id, term, level, l1_name, parent_id, canonical_term_id
            from industry_taxonomy
            where team_id = :team_id and workspace_id = :workspace_id
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().all()
    return {str(row["term"]).lower(): dict(row) for row in rows}


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
