from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db

router = APIRouter(prefix="/field-sources", tags=["field-sources"])


class FieldValueSourceOut(BaseModel):
    id: UUID
    entity_type: str
    entity_id: UUID
    field_path: str
    value_snapshot_json: dict[str, Any]
    source_type: str | None
    source_id: UUID | None
    evidence_id: UUID | None
    source_label: str | None
    confidence: float | None
    review_status: str
    created_at: str
    created_by: UUID | None
    evidence_span: dict[str, Any] | None = None
    debug_ref: dict[str, Any] | None = None


@router.get("", response_model=list[FieldValueSourceOut])
def list_field_sources(
    entity_type: str = Query(pattern="^(seller_target|buyer_intent|buyer_party|buyer_seller_relation)$"),
    entity_id: UUID | None = None,
    field_path: str | None = Query(default=None, max_length=200),
    review_status: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=100, ge=1, le=300),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    where = [
        "fvs.team_id = :team_id",
        "fvs.workspace_id = :workspace_id",
        "fvs.entity_type = :entity_type",
    ]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "entity_type": entity_type,
        "limit": limit,
        "offset": offset,
    }
    if entity_id is not None:
        where.append("fvs.entity_id = :entity_id")
        params["entity_id"] = entity_id
    if field_path:
        where.append("fvs.field_path = :field_path")
        params["field_path"] = field_path
    if review_status:
        where.append("fvs.review_status = :review_status")
        params["review_status"] = review_status

    rows = db.execute(
        text(
            f"""
            select
              fvs.id, fvs.entity_type, fvs.entity_id, fvs.field_path,
              fvs.value_snapshot_json, fvs.source_type, fvs.source_id,
              fvs.evidence_id, fvs.source_label, fvs.confidence,
              fvs.review_status, fvs.created_at::text as created_at, fvs.created_by,
              ev.id as ev_id, ev.source_type as ev_source_type, ev.source_id as ev_source_id,
              ev.attachment_id as ev_attachment_id, ev.parsed_document_id as ev_parsed_document_id,
              ev.page_no as ev_page_no, ev.slide_no as ev_slide_no, ev.sheet_name as ev_sheet_name,
              ev.cell_range as ev_cell_range, ev.text_excerpt as ev_text_excerpt,
              ev.char_start as ev_char_start, ev.char_end as ev_char_end,
              ev.created_at::text as ev_created_at
            from field_value_source fvs
            left join evidence_span ev on ev.id = fvs.evidence_id
            where {' and '.join(where)}
            order by fvs.created_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return [_field_value_source_out(dict(row)) for row in rows]


def _field_value_source_out(row: dict[str, Any]) -> dict[str, Any]:
    evidence_id = row.get("ev_id")
    evidence_span = None
    if evidence_id:
        evidence_span = {
            "id": evidence_id,
            "source_type": row.get("ev_source_type"),
            "source_id": row.get("ev_source_id"),
            "attachment_id": row.get("ev_attachment_id"),
            "parsed_document_id": row.get("ev_parsed_document_id"),
            "page_no": row.get("ev_page_no"),
            "slide_no": row.get("ev_slide_no"),
            "sheet_name": row.get("ev_sheet_name"),
            "cell_range": row.get("ev_cell_range"),
            "text_excerpt": row.get("ev_text_excerpt"),
            "char_start": row.get("ev_char_start"),
            "char_end": row.get("ev_char_end"),
            "created_at": row.get("ev_created_at"),
        }
    return {
        "id": row["id"],
        "entity_type": row["entity_type"],
        "entity_id": row["entity_id"],
        "field_path": row["field_path"],
        "value_snapshot_json": row["value_snapshot_json"],
        "source_type": row.get("source_type"),
        "source_id": row.get("source_id"),
        "evidence_id": row.get("evidence_id"),
        "source_label": row.get("source_label"),
        "confidence": row.get("confidence"),
        "review_status": row["review_status"],
        "created_at": row["created_at"],
        "created_by": row.get("created_by"),
        "evidence_span": evidence_span,
        "debug_ref": _debug_ref(row.get("source_type"), row.get("source_id")),
    }


def _debug_ref(entity_type: str | None, entity_id: Any) -> dict[str, str] | None:
    if not entity_type or entity_id is None:
        return None
    if entity_type in {"seller_target_parse", "buyer_intent_parse", "attachment_ocr_parse"}:
        entity_type = "background_job"
    entity_id_text = str(entity_id)
    return {
        "entity_type": entity_type,
        "entity_id": entity_id_text,
        "route": f"/debug/entities/{entity_type}/{entity_id_text}",
    }
