from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser
from backend.app.api.routes.utils import owner_scope_required, relation_visible_sql, visible_scope_sql
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
    created_by_name: str | None = None
    evidence_span: dict[str, Any] | None = None
    research_evidence: dict[str, Any] | None = None
    debug_ref: dict[str, Any] | None = None


@router.get("", response_model=list[FieldValueSourceOut])
def list_field_sources(
    current_user: CurrentUser,
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
    if owner_scope_required(current_user):
        params["scope_user_id"] = current_user.user_id
        if entity_type == "seller_target":
            where.append(
                f"""
                exists (
                  select 1 from seller_target scope_st
                  where scope_st.id = fvs.entity_id
                    and scope_st.deleted_at is null
                    and {visible_scope_sql("seller_target", "scope_st")}
                )
                """
            )
        elif entity_type == "buyer_intent":
            where.append(
                f"""
                exists (
                  select 1 from buyer_intent scope_bi
                  where scope_bi.id = fvs.entity_id
                    and scope_bi.deleted_at is null
                    and {visible_scope_sql("buyer_intent", "scope_bi")}
                )
                """
            )
        elif entity_type == "buyer_party":
            where.append(
                f"""
                exists (
                  select 1 from buyer_party scope_bp
                  where scope_bp.id = fvs.entity_id
                    and scope_bp.deleted_at is null
                    and {visible_scope_sql("buyer_party", "scope_bp")}
                )
                """
            )
        elif entity_type == "buyer_seller_relation":
            where.append(
                f"""
                exists (
                  select 1 from buyer_seller_relation scope_r
                  where scope_r.id = fvs.entity_id
                    and scope_r.deleted_at is null
                    and {relation_visible_sql("scope_r")}
                )
                """
            )
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
              author.name as created_by_name,
              ev.id as ev_id, ev.source_type as ev_source_type, ev.source_id as ev_source_id,
              ev.attachment_id as ev_attachment_id, ev.parsed_document_id as ev_parsed_document_id,
              ev.page_no as ev_page_no, ev.slide_no as ev_slide_no, ev.sheet_name as ev_sheet_name,
              ev.cell_range as ev_cell_range,
              -- 证据存的是附件全文，字段溯源只需要展示用的开头。
              left(ev.text_excerpt, 500) as ev_text_excerpt,
              ev.char_start as ev_char_start, ev.char_end as ev_char_end,
              ev.created_at::text as ev_created_at,
              rp.id as rp_id, rp.job_id as rp_job_id, rp.source_type as rp_source_type,
              rp.source_url as rp_source_url, rp.source_title as rp_source_title,
              rp.source_excerpt as rp_source_excerpt, rp.period_label as rp_period_label,
              rp.as_of_date::text as rp_as_of_date
            from field_value_source fvs
            left join app_user author on author.id = fvs.created_by
            left join evidence_span ev on ev.id = fvs.evidence_id
            left join research_proposal rp
              on fvs.source_type = 'research_proposal'
             and rp.id = fvs.source_id
             and rp.team_id = fvs.team_id
             and rp.workspace_id = fvs.workspace_id
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
    value_snapshot = dict(row.get("value_snapshot_json") or {})
    source_context = dict(value_snapshot.get("source_context") or {})
    research_evidence = None
    if row.get("source_type") == "research_proposal":
        research_evidence = {
            "proposal_id": row.get("rp_id") or row.get("source_id"),
            "job_id": row.get("rp_job_id") or source_context.get("research_job_id"),
            "source_type": row.get("rp_source_type"),
            "source_url": row.get("rp_source_url") or source_context.get("source_url"),
            "source_title": row.get("rp_source_title") or source_context.get("source_title"),
            "source_excerpt": row.get("rp_source_excerpt") or source_context.get("source_excerpt"),
            "period_label": row.get("rp_period_label") or source_context.get("period_label"),
            "as_of_date": row.get("rp_as_of_date") or source_context.get("as_of_date"),
        }
    return {
        "id": row["id"],
        "entity_type": row["entity_type"],
        "entity_id": row["entity_id"],
        "field_path": row["field_path"],
        "value_snapshot_json": value_snapshot,
        "source_type": row.get("source_type"),
        "source_id": row.get("source_id"),
        "evidence_id": row.get("evidence_id"),
        "source_label": row.get("source_label"),
        "confidence": row.get("confidence"),
        "review_status": row["review_status"],
        "created_at": row["created_at"],
        "created_by": row.get("created_by"),
        "created_by_name": row.get("created_by_name"),
        "evidence_span": evidence_span,
        "research_evidence": research_evidence,
        "debug_ref": _debug_ref(row.get("source_type"), row.get("source_id")),
    }


def _debug_ref(entity_type: str | None, entity_id: Any) -> dict[str, str] | None:
    if not entity_type or entity_id is None:
        return None
    if entity_type in {"seller_target_parse", "buyer_intent_parse", "attachment_ocr_parse"}:
        entity_type = "background_job"
    entity_id_text = str(entity_id)
    if entity_type == "extracted_action":
        return {
            "entity_type": "extracted_action",
            "entity_id": entity_id_text,
            "route": f"/api/v1/extracted-actions/{entity_id_text}",
        }
    return {
        "entity_type": entity_type,
        "entity_id": entity_id_text,
        "route": f"/debug/entities/{entity_type}/{entity_id_text}",
    }
