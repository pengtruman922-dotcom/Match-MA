from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.api.routes.utils import diff_payload, write_action_log, write_action_logs_for_diff
from backend.app.db import get_db
from backend.app.services.search_docs import create_search_doc_rebuild_job

router = APIRouter(prefix="/seller-targets", tags=["seller-targets"])


class SellerTargetCreate(BaseModel):
    target_name: str = Field(min_length=1, max_length=300)
    target_type: str = "company"
    target_subject_name: str | None = Field(default=None, max_length=300)
    owner_user_id: UUID | None = None
    industry_primary: str | None = None
    industry_secondary: str | None = None
    headquarter_province: str | None = None
    headquarter_city: str | None = None
    listed_status: str = "unknown"
    current_revenue_yuan: Decimal | None = None
    current_net_profit_yuan: Decimal | None = None
    valuation_yuan: Decimal | None = None
    valuation_date: str | None = Field(default=None, max_length=80)
    asking_price_yuan: Decimal | None = None
    asking_price_date: str | None = Field(default=None, max_length=80)
    pe_ratio: Decimal | None = None
    is_for_sale: str = "unknown"
    can_control: str = "unknown"
    can_consolidate: str = "unknown"
    business_summary: str | None = None
    transaction_summary: str | None = None
    risk_summary: str | None = None


class SellerTargetOut(BaseModel):
    id: UUID
    target_name: str
    target_type: str
    target_subject_name: str | None
    recommendation_status: str
    information_status: str
    industry_primary: str | None
    industry_secondary: str | None
    registered_province: str | None
    registered_city: str | None
    headquarter_province: str | None
    headquarter_city: str | None
    raw_region_text: str | None
    region_granularity: str | None
    listed_status: str
    market_cap_yuan: Decimal | None
    current_revenue_yuan: Decimal | None
    current_net_profit_yuan: Decimal | None
    current_total_profit_yuan: Decimal | None
    current_assets_yuan: Decimal | None
    current_debt_ratio: Decimal | None
    current_operating_cash_flow_yuan: Decimal | None
    financial_period_label: str | None
    profitability_status: str | None
    cash_flow_status: str | None
    operation_stability_status: str | None
    valuation_yuan: Decimal | None
    valuation_date: str | None
    asking_price_yuan: Decimal | None
    asking_price_date: str | None
    pe_ratio: Decimal | None
    pe_source_type: str | None
    premium_rate: Decimal | None
    is_for_sale: str
    can_control: str
    can_consolidate: str
    accepts_minority_investment: str
    transfer_ratio_min: Decimal | None
    transfer_ratio_max: Decimal | None
    transfer_ratio_text: str | None
    transfer_flexibility_type: str | None
    consolidation_path_summary: str | None
    accepts_relocation: str
    accepts_return_investment: str
    management_team_summary: str | None
    management_retention_possible: str
    earnout_dependency_status: str | None
    business_summary: str | None
    transaction_summary: str | None
    risk_summary: str | None
    gap_summary: str | None
    created_at: str
    updated_at: str


class SellerTargetUpdate(BaseModel):
    target_name: str | None = Field(default=None, min_length=1, max_length=300)
    target_type: str | None = None
    target_subject_name: str | None = Field(default=None, max_length=300)
    industry_primary: str | None = None
    industry_secondary: str | None = None
    registered_province: str | None = None
    registered_city: str | None = None
    headquarter_province: str | None = None
    headquarter_city: str | None = None
    raw_region_text: str | None = None
    region_granularity: str | None = None
    listed_status: str | None = None
    market_cap_yuan: Decimal | None = None
    current_revenue_yuan: Decimal | None = None
    current_net_profit_yuan: Decimal | None = None
    current_total_profit_yuan: Decimal | None = None
    current_assets_yuan: Decimal | None = None
    current_debt_ratio: Decimal | None = None
    current_operating_cash_flow_yuan: Decimal | None = None
    financial_period_label: str | None = None
    profitability_status: str | None = None
    cash_flow_status: str | None = None
    operation_stability_status: str | None = None
    valuation_yuan: Decimal | None = None
    valuation_date: str | None = Field(default=None, max_length=80)
    asking_price_yuan: Decimal | None = None
    asking_price_date: str | None = Field(default=None, max_length=80)
    pe_ratio: Decimal | None = None
    pe_source_type: str | None = None
    premium_rate: Decimal | None = None
    is_for_sale: str | None = None
    can_control: str | None = None
    can_consolidate: str | None = None
    accepts_minority_investment: str | None = None
    transfer_ratio_min: Decimal | None = None
    transfer_ratio_max: Decimal | None = None
    transfer_ratio_text: str | None = None
    transfer_flexibility_type: str | None = None
    consolidation_path_summary: str | None = None
    accepts_relocation: str | None = None
    accepts_return_investment: str | None = None
    management_team_summary: str | None = None
    management_retention_possible: str | None = None
    earnout_dependency_status: str | None = None
    recommendation_status: str | None = None
    information_status: str | None = None
    business_summary: str | None = None
    transaction_summary: str | None = None
    risk_summary: str | None = None
    gap_summary: str | None = None


class SellerTargetParseRequest(BaseModel):
    raw_target_text: str | None = Field(default=None, min_length=1)
    force: bool = False


class SellerTargetParseJobOut(BaseModel):
    job_id: UUID
    job_type: str
    status: str
    queue_name: str
    seller_target_id: UUID


class SellerTargetParseStatusOut(BaseModel):
    seller_target: dict[str, Any]
    latest_job: dict[str, Any] | None
    latest_trace: dict[str, Any] | None
    recent_update_logs: list[dict[str, Any]]
    debug_ref: dict[str, Any]


SELLER_TARGET_OUT_COLUMNS = """
              id, target_name, target_type, target_subject_name, recommendation_status, information_status,
              industry_primary, industry_secondary, registered_province, registered_city,
              headquarter_province, headquarter_city, raw_region_text, region_granularity,
              listed_status, market_cap_yuan, current_revenue_yuan, current_net_profit_yuan,
              current_total_profit_yuan, current_assets_yuan, current_debt_ratio,
              current_operating_cash_flow_yuan, financial_period_label, profitability_status,
              cash_flow_status, operation_stability_status, valuation_yuan, valuation_date,
              asking_price_yuan, asking_price_date,
              pe_ratio, pe_source_type, premium_rate, is_for_sale, can_control, can_consolidate,
              accepts_minority_investment, transfer_ratio_min, transfer_ratio_max, transfer_ratio_text,
              transfer_flexibility_type, consolidation_path_summary, accepts_relocation,
              accepts_return_investment, management_team_summary, management_retention_possible,
              earnout_dependency_status, business_summary, transaction_summary, risk_summary, gap_summary,
              created_at::text as created_at, updated_at::text as updated_at
"""


@router.post("", response_model=SellerTargetOut, status_code=status.HTTP_201_CREATED)
def create_seller_target(payload: SellerTargetCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.execute(
        text(
            f"""
            insert into seller_target (
              team_id, workspace_id, target_name, target_type, target_subject_name, owner_user_id,
              industry_primary, industry_secondary, headquarter_province, headquarter_city,
              listed_status, current_revenue_yuan, current_net_profit_yuan,
              valuation_yuan, valuation_date, asking_price_yuan, asking_price_date, pe_ratio,
              is_for_sale, can_control, can_consolidate,
              business_summary, transaction_summary, risk_summary,
              created_by, updated_by
            )
            values (
              :team_id, :workspace_id, :target_name, :target_type, :target_subject_name, :owner_user_id,
              :industry_primary, :industry_secondary, :headquarter_province, :headquarter_city,
              :listed_status, :current_revenue_yuan, :current_net_profit_yuan,
              :valuation_yuan, :valuation_date, :asking_price_yuan, :asking_price_date, :pe_ratio,
              :is_for_sale, :can_control, :can_consolidate,
              :business_summary, :transaction_summary, :risk_summary,
              :created_by, :updated_by
            )
            returning
{SELLER_TARGET_OUT_COLUMNS}
            """
        ),
        _seller_target_params(payload),
    ).mappings().one()
    create_search_doc_rebuild_job(
        db,
        entity_type="seller_target",
        entity_id=row["id"],
        source="seller_target_create",
    )
    db.commit()
    return dict(row)


@router.get("", response_model=list[SellerTargetOut])
def list_seller_targets(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=200),
) -> list[dict[str, Any]]:
    where = ["team_id = :team_id", "workspace_id = :workspace_id", "deleted_at is null"]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
        "offset": offset,
    }

    if q:
        where.append("(target_name ilike :q or target_subject_name ilike :q or business_summary ilike :q)")
        params["q"] = f"%{q}%"

    rows = db.execute(
        text(
            f"""
            select
{SELLER_TARGET_OUT_COLUMNS}
            from seller_target
            where {' and '.join(where)}
            order by updated_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


@router.get("/{seller_target_id}", response_model=SellerTargetOut)
def get_seller_target(seller_target_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _get_seller_target_or_404(db, seller_target_id)


@router.post("/{seller_target_id}/parse", response_model=SellerTargetParseJobOut)
def parse_seller_target(
    seller_target_id: UUID,
    payload: SellerTargetParseRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    target = _get_seller_target_or_404(db, seller_target_id)
    request = payload or SellerTargetParseRequest()
    raw_target_text = request.raw_target_text or _seller_target_parse_fallback_text(target)
    if not raw_target_text or not raw_target_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="raw_target_text or existing seller target summary is required to parse seller target.",
        )

    if not request.force:
        existing_job = _latest_active_parse_job(db, seller_target_id)
        if existing_job:
            db.commit()
            return {
                "job_id": existing_job["id"],
                "job_type": existing_job["job_type"],
                "status": existing_job["status"],
                "queue_name": existing_job["queue_name"],
                "seller_target_id": existing_job["entity_id"],
            }

    row = db.execute(
        text(
            """
            insert into background_job (
              team_id, workspace_id, job_type, priority, queue_name,
              entity_type, entity_id, idempotency_key, payload_json,
              created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, 'seller_target_parse', 100, 'llm',
              'seller_target', :seller_target_id, :idempotency_key, :payload_json,
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
            "seller_target_id": seller_target_id,
            "idempotency_key": f"seller_target_parse:{seller_target_id}:{uuid4()}",
            "payload_json": {
                "seller_target_id": str(seller_target_id),
                "raw_target_text": raw_target_text,
            },
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {"source": "seller_target_parse_api"},
        },
    ).mappings().one()
    db.commit()
    return {
        "job_id": row["id"],
        "job_type": row["job_type"],
        "status": row["status"],
        "queue_name": row["queue_name"],
        "seller_target_id": row["entity_id"],
    }


@router.get("/{seller_target_id}/parse-status", response_model=SellerTargetParseStatusOut)
def get_seller_target_parse_status(
    seller_target_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    target = _get_seller_target_or_404(db, seller_target_id)
    latest_job = _latest_parse_job(db, seller_target_id)
    latest_trace = _latest_parse_trace(db, seller_target_id)
    return {
        "seller_target": target,
        "latest_job": _compact_parse_job(latest_job) if latest_job else None,
        "latest_trace": _compact_parse_trace(latest_trace) if latest_trace else None,
        "recent_update_logs": _recent_parse_update_logs(db, seller_target_id),
        "debug_ref": _debug_ref("seller_target", seller_target_id),
    }


@router.patch("/{seller_target_id}", response_model=SellerTargetOut)
def update_seller_target(
    seller_target_id: UUID,
    payload: SellerTargetUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    original = _get_seller_target_or_404(db, seller_target_id)
    changes = payload.model_dump(exclude_unset=True)

    if "target_name" in changes and changes["target_name"] is not None:
        changes["target_name"] = changes["target_name"].strip()
    for text_field in ("target_subject_name", "valuation_date", "asking_price_date"):
        if text_field in changes and changes[text_field] is not None:
            changes[text_field] = _normalize_optional_text(changes[text_field])

    if not changes:
        return original

    diff = diff_payload(original, changes)
    if not diff:
        return original

    set_clauses = [f"{field} = :{field}" for field in changes]
    set_clauses.extend(["updated_at = now()", "updated_by = :updated_by"])

    row = db.execute(
        text(
            f"""
            update seller_target
            set {', '.join(set_clauses)}
            where id = :seller_target_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            returning
{SELLER_TARGET_OUT_COLUMNS}
            """
        ),
        {
            **changes,
            "updated_by": DEFAULT_ADMIN_USER_ID,
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one()

    write_action_logs_for_diff(
        db,
        entity_type="seller_target",
        entity_id=seller_target_id,
        diff=diff,
    )
    create_search_doc_rebuild_job(
        db,
        entity_type="seller_target",
        entity_id=seller_target_id,
        source="seller_target_update",
    )

    db.commit()
    return dict(row)


@router.delete("/{seller_target_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_seller_target(seller_target_id: UUID, db: Session = Depends(get_db)) -> None:
    _get_seller_target_or_404(db, seller_target_id)
    db.execute(
        text(
            """
            update seller_target
            set deleted_at = now(),
                deleted_by = :deleted_by,
                updated_at = now(),
                updated_by = :updated_by
            where id = :seller_target_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "deleted_by": DEFAULT_ADMIN_USER_ID,
            "updated_by": DEFAULT_ADMIN_USER_ID,
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    write_action_log(
        db,
        entity_type="seller_target",
        entity_id=seller_target_id,
        field_path="deleted_at",
        old_value=None,
        new_value="now()",
    )
    db.commit()
    return None


def _get_seller_target_or_404(db: Session, seller_target_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            f"""
            select
{SELLER_TARGET_OUT_COLUMNS}
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


def _seller_target_params(payload: SellerTargetCreate) -> dict[str, Any]:
    target_name = payload.target_name.strip()
    target_type = payload.target_type or "company"
    target_subject_name = _normalize_optional_text(payload.target_subject_name)
    if target_type == "company" and not target_subject_name:
        target_subject_name = target_name
    return {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "target_name": target_name,
        "target_type": target_type,
        "target_subject_name": target_subject_name,
        "owner_user_id": payload.owner_user_id or DEFAULT_ADMIN_USER_ID,
        "industry_primary": _normalize_optional_text(payload.industry_primary),
        "industry_secondary": _normalize_optional_text(payload.industry_secondary),
        "headquarter_province": _normalize_optional_text(payload.headquarter_province),
        "headquarter_city": _normalize_optional_text(payload.headquarter_city),
        "listed_status": payload.listed_status,
        "current_revenue_yuan": payload.current_revenue_yuan,
        "current_net_profit_yuan": payload.current_net_profit_yuan,
        "valuation_yuan": payload.valuation_yuan,
        "valuation_date": _normalize_optional_text(payload.valuation_date),
        "asking_price_yuan": payload.asking_price_yuan,
        "asking_price_date": _normalize_optional_text(payload.asking_price_date),
        "pe_ratio": payload.pe_ratio,
        "is_for_sale": payload.is_for_sale,
        "can_control": payload.can_control,
        "can_consolidate": payload.can_consolidate,
        "business_summary": payload.business_summary,
        "transaction_summary": payload.transaction_summary,
        "risk_summary": payload.risk_summary,
        "created_by": DEFAULT_ADMIN_USER_ID,
        "updated_by": DEFAULT_ADMIN_USER_ID,
    }


def _seller_target_parse_fallback_text(target: dict[str, Any]) -> str:
    parts = [
        target.get("target_name"),
        target.get("target_subject_name"),
        target.get("business_summary"),
        target.get("transaction_summary"),
        target.get("risk_summary"),
    ]
    return "\n".join(str(part).strip() for part in parts if part is not None and str(part).strip())


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _latest_active_parse_job(db: Session, seller_target_id: UUID) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select id, job_type, status, queue_name, entity_id
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and job_type = 'seller_target_parse'
              and entity_type = 'seller_target'
              and entity_id = :seller_target_id
              and status in ('queued', 'running', 'retry_waiting')
            order by created_at desc
            limit 1
            """
        ),
        {
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _latest_parse_job(db: Session, seller_target_id: UUID) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select
              id, job_type, status, queue_name, entity_type, entity_id,
              error_code, error_message, attempt_count, max_attempts,
              started_at::text as started_at, finished_at::text as finished_at,
              created_at::text as created_at, updated_at::text as updated_at,
              result_json, metadata_json
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and job_type = 'seller_target_parse'
              and entity_type = 'seller_target'
              and entity_id = :seller_target_id
            order by created_at desc
            limit 1
            """
        ),
        {
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _latest_parse_trace(db: Session, seller_target_id: UUID) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select
              id, trace_type, node_name, job_id, provider_name, model_name,
              prompt_version, status, raw_output_text, parsed_output_json,
              schema_validation_json, error_code, error_message,
              latency_ms, prompt_tokens, completion_tokens, total_tokens,
              started_at::text as started_at, finished_at::text as finished_at
            from ai_trace
            where team_id = :team_id
              and workspace_id = :workspace_id
              and node_name = 'seller_target_parser'
              and entity_type = 'seller_target'
              and entity_id = :seller_target_id
            order by started_at desc
            limit 1
            """
        ),
        {
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _recent_parse_update_logs(db: Session, seller_target_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, field_path, old_value_json, new_value_json, source_type, source_id,
              applied_at::text as applied_at, can_rollback, rollback_at::text as rollback_at
            from action_application_log
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = 'seller_target'
              and entity_id = :seller_target_id
              and source_type = 'seller_target_parse'
            order by applied_at desc
            limit 50
            """
        ),
        {
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _compact_parse_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job["id"],
        "job_type": job["job_type"],
        "status": job["status"],
        "queue_name": job["queue_name"],
        "error_code": job.get("error_code"),
        "error_message": job.get("error_message"),
        "attempt_count": job.get("attempt_count"),
        "max_attempts": job.get("max_attempts"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "result_json": job.get("result_json"),
        "debug_ref": _debug_ref("background_job", job["id"]),
    }


def _compact_parse_trace(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": trace["id"],
        "trace_type": trace["trace_type"],
        "node_name": trace["node_name"],
        "job_id": trace.get("job_id"),
        "provider_name": trace.get("provider_name"),
        "model_name": trace.get("model_name"),
        "prompt_version": trace.get("prompt_version"),
        "status": trace["status"],
        "raw_output_preview": _truncate_text(trace.get("raw_output_text"), 800),
        "parsed_output_json": trace.get("parsed_output_json"),
        "schema_validation_json": trace.get("schema_validation_json"),
        "error_code": trace.get("error_code"),
        "error_message": trace.get("error_message"),
        "latency_ms": trace.get("latency_ms"),
        "prompt_tokens": trace.get("prompt_tokens"),
        "completion_tokens": trace.get("completion_tokens"),
        "total_tokens": trace.get("total_tokens"),
        "started_at": trace.get("started_at"),
        "finished_at": trace.get("finished_at"),
        "debug_ref": _debug_ref("background_job", trace["job_id"]) if trace.get("job_id") else None,
    }


def _debug_ref(entity_type: str, entity_id: Any) -> dict[str, str]:
    entity_id_text = str(entity_id)
    return {
        "entity_type": entity_type,
        "entity_id": entity_id_text,
        "route": f"/debug/entities/{entity_type}/{entity_id_text}",
    }


def _truncate_text(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    if len(text_value) <= max_length:
        return text_value
    return text_value[: max_length - 3] + "..."
