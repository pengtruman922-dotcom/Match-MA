"""Matching profile sections: the qualitative layer behind deep eval.

Six sections per entity, each carrying its own source and as-of date. Writes
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
    PROFILE_SECTION_CODES,
    PROFILE_SECTION_LABELS,
    profile_coverage,
    upsert_profile_section,
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
    confidence: float | None
    review_status: str
    updated_at: str


class ProfileSectionWrite(BaseModel):
    section_code: str
    info_status: str = Field(default="filled", pattern="^(filled|not_found|not_applicable)$")
    content_text: str | None = None
    source_type: str | None = None
    source_url: str | None = None
    source_title: str | None = None
    source_excerpt: str | None = None
    as_of_date: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


def _validate_target(entity_type: str, section_code: str | None = None) -> None:
    if entity_type not in ENTITY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"entity_type must be one of {sorted(ENTITY_TYPES)}.",
        )
    if section_code is not None and section_code not in PROFILE_SECTION_CODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"section_code must be one of {list(PROFILE_SECTION_CODES)}.",
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
              id, entity_type, entity_id, section_code, info_status, content_text,
              source_type, source_url, source_title, source_excerpt,
              as_of_date::text as as_of_date, confidence, review_status,
              updated_at::text as updated_at
            from entity_profile_section
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = :entity_type
              and entity_id = :entity_id
              and deleted_at is null
            order by section_code, as_of_date desc nulls last, updated_at desc
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
    current = {row["section_code"]: dict(row) for row in reversed(rows)}
    return {
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "sections": sections,
        "coverage": profile_coverage(current),
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
    row = upsert_profile_section(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        section_code=payload.section_code,
        info_status=payload.info_status,
        content_text=payload.content_text,
        source_type=payload.source_type or "manual",
        source_url=payload.source_url,
        source_title=payload.source_title,
        source_excerpt=payload.source_excerpt,
        as_of_date=payload.as_of_date,
        confidence=payload.confidence,
        user_id=current_user.user_id,
    )
    db.commit()
    return {
        **row,
        "section_label": PROFILE_SECTION_LABELS.get(row["section_code"], row["section_code"]),
    }
