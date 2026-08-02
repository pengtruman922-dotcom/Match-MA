"""Per-group “其他” supplementary information.

Seven groups per entity, each carrying its own source and as-of date. Writes
supersede rather than overwrite so an earlier claim stays auditable, which is
also what lets the research flow keep competing values side by side.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser
from backend.app.api.routes.utils import ensure_entity_visible, ensure_entity_writable
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db
from backend.app.services.profile_sections import (
    PROFILE_SECTION_LABELS,
    apply_profile_section,
    profile_section_codes,
)

router = APIRouter(prefix="/profile-sections", tags=["profile-sections"])

ENTITY_TYPES = {"seller_target", "buyer_intent"}


class ProfileSectionOut(BaseModel):
    id: UUID
    entity_type: str
    entity_id: UUID
    section_code: str
    section_label: str
    info_status: str
    content_text: str | None
    source_type: str | None
    source_url: str | None
    source_title: str | None
    source_excerpt: str | None
    as_of_date: str | None
    review_status: str
    updated_at: str
    updated_by_name: str | None = None


class ProfileSectionWrite(BaseModel):
    section_code: str
    info_status: str = Field(default="filled", pattern="^(filled|not_found|not_applicable)$")
    content_text: str | None = None
    source_type: str | None = None
    source_url: str | None = None
    source_title: str | None = None
    source_excerpt: str | None = None
    as_of_date: str | None = None


def _validate_target(entity_type: str, section_code: str | None = None) -> None:
    if entity_type not in ENTITY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"entity_type must be one of {sorted(ENTITY_TYPES)}.",
        )
    # 栏目按实体分：买家的三块「其他」和标的的五栏画像互不通用，
    # 写串了会在 entity_profile_section 的 check 约束上炸，不如在入口就说清楚。
    allowed = profile_section_codes(entity_type)
    if section_code is not None and section_code not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"section_code for {entity_type} must be one of {list(allowed)}.",
        )


@router.get("/{entity_type}/{entity_id}")
def list_profile_sections(
    entity_type: str,
    entity_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _validate_target(entity_type)
    ensure_entity_visible(db, current_user, entity_type=entity_type, entity_id=entity_id)
    rows = db.execute(
        text(
            """
            select
              ps.id, ps.entity_type, ps.entity_id, ps.section_code, ps.info_status, ps.content_text,
              ps.source_type, ps.source_url, ps.source_title, ps.source_excerpt,
              ps.as_of_date::text as as_of_date, ps.review_status,
              ps.updated_at::text as updated_at, author.name as updated_by_name
            from entity_profile_section ps
            left join app_user author on author.id = ps.updated_by
            where ps.team_id = :team_id
              and ps.workspace_id = :workspace_id
              and ps.entity_type = :entity_type
              and ps.entity_id = :entity_id
              and ps.deleted_at is null
            order by ps.section_code, ps.updated_at desc
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "entity_type": entity_type,
            "entity_id": entity_id,
        },
    ).mappings().all()

    sections = [
        {**dict(row), "section_label": PROFILE_SECTION_LABELS.get(row["section_code"], row["section_code"])}
        for row in rows
    ]
    return {
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "sections": sections,
        "section_catalog": [
            {"code": code, "label": label} for code, label in PROFILE_SECTION_LABELS.items()
        ],
    }


@router.put("/{entity_type}/{entity_id}", response_model=ProfileSectionOut)
def write_profile_section(
    entity_type: str,
    entity_id: UUID,
    payload: ProfileSectionWrite,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _validate_target(entity_type, payload.section_code)
    ensure_entity_writable(db, current_user, entity_type=entity_type, entity_id=entity_id)
    row = apply_profile_section(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        section_code=payload.section_code,
        info_status=payload.info_status,
        content_text=payload.content_text,
        source_type=payload.source_type or "manual_edit",
        source_url=payload.source_url,
        source_title=payload.source_title or "手动编辑",
        source_excerpt=payload.source_excerpt,
        as_of_date=payload.as_of_date,
        user_id=current_user.user_id,
        log_source_type="manual_edit",
    )
    db.commit()
    return {
        **row,
        "section_label": PROFILE_SECTION_LABELS.get(row["section_code"], row["section_code"]),
    }
