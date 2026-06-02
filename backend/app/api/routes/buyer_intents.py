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

router = APIRouter(prefix="/buyer-intents", tags=["buyer-intents"])


class BuyerIntentCreate(BaseModel):
    intent_name: str = Field(min_length=1, max_length=300)
    buyer_party_id: UUID | None = None
    owner_user_id: UUID | None = None
    contact_name: str | None = None
    raw_requirement_text: str | None = None
    intent_summary: str | None = None
    industry_primary: str | None = None
    industry_secondary: str | None = None
    region_scope_summary: str | None = None
    parsed_requirement_json: dict[str, Any] | None = None
    region_constraints_json: list[Any] | dict[str, Any] | None = None
    min_revenue_yuan: Decimal | None = None
    min_net_profit_yuan: Decimal | None = None
    min_total_profit_yuan: Decimal | None = None
    max_pe: Decimal | None = None
    max_valuation_yuan: Decimal | None = None
    market_cap_range_summary: str | None = None
    requires_control: str = "unknown"
    requires_consolidation: str = "unknown"
    accepts_minority_investment: str = "unknown"
    desired_equity_ratio_min: Decimal | None = None
    desired_equity_ratio_max: Decimal | None = None
    equity_ratio_summary: str | None = None
    equity_requirement_type: str | None = None
    acceptable_control_paths_json: list[Any] | dict[str, Any] | None = None
    preferred_listed_status: str | None = "unknown"
    transaction_type: str | None = None
    negative_summary: str | None = None
    priority_summary: str | None = None
    preference_summary: str | None = None
    unknown_summary: str | None = None


class BuyerIntentOut(BaseModel):
    id: UUID
    buyer_party_id: UUID | None
    intent_name: str
    status: str
    contact_name: str | None
    raw_requirement_text: str | None
    intent_summary: str | None
    industry_primary: str | None
    industry_secondary: str | None
    region_scope_summary: str | None
    parsed_requirement_json: dict[str, Any]
    region_constraints_json: list[Any] | dict[str, Any]
    min_revenue_yuan: Decimal | None
    min_net_profit_yuan: Decimal | None
    min_total_profit_yuan: Decimal | None
    max_pe: Decimal | None
    max_valuation_yuan: Decimal | None
    market_cap_range_summary: str | None
    requires_control: str
    requires_consolidation: str
    accepts_minority_investment: str
    desired_equity_ratio_min: Decimal | None
    desired_equity_ratio_max: Decimal | None
    equity_ratio_summary: str | None
    equity_requirement_type: str | None
    acceptable_control_paths_json: list[Any] | dict[str, Any]
    preferred_listed_status: str | None
    transaction_type: str | None
    negative_summary: str | None
    priority_summary: str | None
    preference_summary: str | None
    unknown_summary: str | None
    created_at: str
    updated_at: str


class BuyerIntentUpdate(BaseModel):
    intent_name: str | None = Field(default=None, min_length=1, max_length=300)
    status: str | None = None
    pause_reason: str | None = None
    contact_name: str | None = None
    raw_requirement_text: str | None = None
    intent_summary: str | None = None
    industry_primary: str | None = None
    industry_secondary: str | None = None
    region_scope_summary: str | None = None
    parsed_requirement_json: dict[str, Any] | None = None
    region_constraints_json: list[Any] | dict[str, Any] | None = None
    min_revenue_yuan: Decimal | None = None
    min_net_profit_yuan: Decimal | None = None
    min_total_profit_yuan: Decimal | None = None
    max_pe: Decimal | None = None
    max_valuation_yuan: Decimal | None = None
    market_cap_range_summary: str | None = None
    requires_control: str | None = None
    requires_consolidation: str | None = None
    accepts_minority_investment: str | None = None
    desired_equity_ratio_min: Decimal | None = None
    desired_equity_ratio_max: Decimal | None = None
    equity_ratio_summary: str | None = None
    equity_requirement_type: str | None = None
    acceptable_control_paths_json: list[Any] | dict[str, Any] | None = None
    preferred_listed_status: str | None = None
    transaction_type: str | None = None
    negative_summary: str | None = None
    priority_summary: str | None = None
    preference_summary: str | None = None
    unknown_summary: str | None = None


class BuyerIntentParseRequest(BaseModel):
    raw_requirement_text: str | None = Field(default=None, min_length=1)
    force: bool = False


class BuyerIntentParseJobOut(BaseModel):
    job_id: UUID
    job_type: str
    status: str
    queue_name: str
    buyer_intent_id: UUID


class BuyerIntentParseStatusOut(BaseModel):
    buyer_intent: dict[str, Any]
    latest_job: dict[str, Any] | None
    latest_trace: dict[str, Any] | None
    recent_update_logs: list[dict[str, Any]]
    debug_ref: dict[str, Any]


@router.post("", response_model=BuyerIntentOut, status_code=status.HTTP_201_CREATED)
def create_buyer_intent(payload: BuyerIntentCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            insert into buyer_intent (
              team_id, workspace_id, buyer_party_id, owner_user_id,
              intent_name, contact_name, raw_requirement_text, intent_summary,
              parsed_requirement_json, industry_primary, industry_secondary,
              region_scope_summary, region_constraints_json,
              min_revenue_yuan, min_net_profit_yuan, min_total_profit_yuan,
              max_pe, max_valuation_yuan, market_cap_range_summary,
              requires_control, requires_consolidation, accepts_minority_investment,
              desired_equity_ratio_min, desired_equity_ratio_max, equity_ratio_summary,
              equity_requirement_type, acceptable_control_paths_json,
              preferred_listed_status, transaction_type,
              negative_summary, priority_summary, preference_summary, unknown_summary,
              created_by, updated_by
            )
            values (
              :team_id, :workspace_id, :buyer_party_id, :owner_user_id,
              :intent_name, :contact_name, :raw_requirement_text, :intent_summary,
              :parsed_requirement_json, :industry_primary, :industry_secondary,
              :region_scope_summary, :region_constraints_json,
              :min_revenue_yuan, :min_net_profit_yuan, :min_total_profit_yuan,
              :max_pe, :max_valuation_yuan, :market_cap_range_summary,
              :requires_control, :requires_consolidation, :accepts_minority_investment,
              :desired_equity_ratio_min, :desired_equity_ratio_max, :equity_ratio_summary,
              :equity_requirement_type, :acceptable_control_paths_json,
              :preferred_listed_status, :transaction_type,
              :negative_summary, :priority_summary, :preference_summary, :unknown_summary,
              :created_by, :updated_by
            )
            returning
              id, buyer_party_id, intent_name, status, contact_name,
              raw_requirement_text, intent_summary, parsed_requirement_json,
              industry_primary, industry_secondary, region_scope_summary,
              region_constraints_json, min_revenue_yuan, min_net_profit_yuan,
              min_total_profit_yuan, max_pe, max_valuation_yuan,
              market_cap_range_summary, requires_control, requires_consolidation,
              accepts_minority_investment, desired_equity_ratio_min,
              desired_equity_ratio_max, equity_ratio_summary, equity_requirement_type,
              acceptable_control_paths_json, preferred_listed_status, transaction_type,
              negative_summary, priority_summary, preference_summary, unknown_summary,
              created_at::text as created_at, updated_at::text as updated_at
            """
        ).bindparams(
            bindparam("parsed_requirement_json", type_=JSONB),
            bindparam("region_constraints_json", type_=JSONB),
            bindparam("acceptable_control_paths_json", type_=JSONB),
        ),
        _buyer_intent_params(payload),
    ).mappings().one()
    create_search_doc_rebuild_job(
        db,
        entity_type="buyer_intent",
        entity_id=row["id"],
        source="buyer_intent_create",
    )
    db.commit()
    return dict(row)


@router.get("", response_model=list[BuyerIntentOut])
def list_buyer_intents(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=200),
    buyer_party_id: UUID | None = None,
) -> list[dict[str, Any]]:
    where = ["team_id = :team_id", "workspace_id = :workspace_id", "deleted_at is null"]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
        "offset": offset,
    }

    if q:
        where.append("(intent_name ilike :q or raw_requirement_text ilike :q)")
        params["q"] = f"%{q}%"
    if buyer_party_id:
        where.append("buyer_party_id = :buyer_party_id")
        params["buyer_party_id"] = buyer_party_id

    rows = db.execute(
        text(
            f"""
            select
              id, buyer_party_id, intent_name, status, contact_name,
              raw_requirement_text, intent_summary, parsed_requirement_json,
              industry_primary, industry_secondary, region_scope_summary,
              region_constraints_json, min_revenue_yuan, min_net_profit_yuan,
              min_total_profit_yuan, max_pe, max_valuation_yuan,
              market_cap_range_summary, requires_control, requires_consolidation,
              accepts_minority_investment, desired_equity_ratio_min,
              desired_equity_ratio_max, equity_ratio_summary, equity_requirement_type,
              acceptable_control_paths_json, preferred_listed_status, transaction_type,
              negative_summary, priority_summary, preference_summary, unknown_summary,
              created_at::text as created_at, updated_at::text as updated_at
            from buyer_intent
            where {' and '.join(where)}
            order by updated_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


@router.get("/{buyer_intent_id}", response_model=BuyerIntentOut)
def get_buyer_intent(buyer_intent_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _get_buyer_intent_or_404(db, buyer_intent_id)


@router.post("/{buyer_intent_id}/parse", response_model=BuyerIntentParseJobOut)
def parse_buyer_intent(
    buyer_intent_id: UUID,
    payload: BuyerIntentParseRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    intent = _get_buyer_intent_or_404(db, buyer_intent_id)
    request = payload or BuyerIntentParseRequest()
    raw_requirement_text = request.raw_requirement_text or intent.get("raw_requirement_text")
    if not raw_requirement_text or not raw_requirement_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="raw_requirement_text is required to parse buyer intent.",
        )

    if request.raw_requirement_text and request.raw_requirement_text != intent.get("raw_requirement_text"):
        db.execute(
            text(
                """
                update buyer_intent
                set raw_requirement_text = :raw_requirement_text,
                    updated_at = now(),
                    updated_by = :updated_by
                where id = :buyer_intent_id
                  and team_id = :team_id
                  and workspace_id = :workspace_id
                  and deleted_at is null
                """
            ),
            {
                "raw_requirement_text": request.raw_requirement_text,
                "updated_by": DEFAULT_ADMIN_USER_ID,
                "buyer_intent_id": buyer_intent_id,
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
            },
        )

    if not request.force:
        existing_job = _latest_active_parse_job(db, buyer_intent_id)
        if existing_job:
            db.commit()
            return {
                "job_id": existing_job["id"],
                "job_type": existing_job["job_type"],
                "status": existing_job["status"],
                "queue_name": existing_job["queue_name"],
                "buyer_intent_id": existing_job["entity_id"],
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
              :team_id, :workspace_id, 'buyer_intent_parse', 100, 'llm',
              'buyer_intent', :buyer_intent_id, :idempotency_key, :payload_json,
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
            "buyer_intent_id": buyer_intent_id,
            "idempotency_key": f"buyer_intent_parse:{buyer_intent_id}:{uuid4()}",
            "payload_json": {
                "buyer_intent_id": str(buyer_intent_id),
                "raw_requirement_text": raw_requirement_text,
            },
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {"source": "buyer_intent_parse_api"},
        },
    ).mappings().one()
    db.commit()
    return {
        "job_id": row["id"],
        "job_type": row["job_type"],
        "status": row["status"],
        "queue_name": row["queue_name"],
        "buyer_intent_id": row["entity_id"],
    }


@router.get("/{buyer_intent_id}/parse-status", response_model=BuyerIntentParseStatusOut)
def get_buyer_intent_parse_status(
    buyer_intent_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    intent = _get_buyer_intent_or_404(db, buyer_intent_id)
    latest_job = _latest_parse_job(db, buyer_intent_id)
    latest_trace = _latest_parse_trace(db, buyer_intent_id)
    return {
        "buyer_intent": intent,
        "latest_job": _compact_parse_job(latest_job) if latest_job else None,
        "latest_trace": _compact_parse_trace(latest_trace) if latest_trace else None,
        "recent_update_logs": _recent_parse_update_logs(db, buyer_intent_id),
        "debug_ref": _debug_ref("buyer_intent", buyer_intent_id),
    }


@router.patch("/{buyer_intent_id}", response_model=BuyerIntentOut)
def update_buyer_intent(
    buyer_intent_id: UUID,
    payload: BuyerIntentUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    original = _get_buyer_intent_or_404(db, buyer_intent_id)
    changes = payload.model_dump(exclude_unset=True)

    if "intent_name" in changes and changes["intent_name"] is not None:
        changes["intent_name"] = changes["intent_name"].strip()

    if not changes:
        return original

    diff = diff_payload(original, changes)
    if not diff:
        return original

    set_clauses = [f"{field} = :{field}" for field in changes]
    set_clauses.extend(["updated_at = now()", "updated_by = :updated_by"])

    statement = text(
        f"""
        update buyer_intent
        set {', '.join(set_clauses)}
        where id = :buyer_intent_id
          and team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
        returning
          id, buyer_party_id, intent_name, status, contact_name,
          raw_requirement_text, intent_summary, parsed_requirement_json,
          industry_primary, industry_secondary, region_scope_summary,
          region_constraints_json, min_revenue_yuan, min_net_profit_yuan,
          min_total_profit_yuan, max_pe, max_valuation_yuan,
          market_cap_range_summary, requires_control, requires_consolidation,
          accepts_minority_investment, desired_equity_ratio_min,
          desired_equity_ratio_max, equity_ratio_summary, equity_requirement_type,
          acceptable_control_paths_json, preferred_listed_status, transaction_type,
          negative_summary, priority_summary, preference_summary, unknown_summary,
          created_at::text as created_at, updated_at::text as updated_at
        """
    )
    json_fields = {
        "parsed_requirement_json",
        "region_constraints_json",
        "acceptable_control_paths_json",
    }
    bind_params = [bindparam(field, type_=JSONB) for field in changes if field in json_fields]
    if bind_params:
        statement = statement.bindparams(*bind_params)

    row = db.execute(
        statement,
        {
            **changes,
            "updated_by": DEFAULT_ADMIN_USER_ID,
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one()

    write_action_logs_for_diff(
        db,
        entity_type="buyer_intent",
        entity_id=buyer_intent_id,
        diff=diff,
    )
    create_search_doc_rebuild_job(
        db,
        entity_type="buyer_intent",
        entity_id=buyer_intent_id,
        source="buyer_intent_update",
    )

    db.commit()
    return dict(row)


@router.delete("/{buyer_intent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_buyer_intent(buyer_intent_id: UUID, db: Session = Depends(get_db)) -> None:
    _get_buyer_intent_or_404(db, buyer_intent_id)
    db.execute(
        text(
            """
            update buyer_intent
            set deleted_at = now(),
                deleted_by = :deleted_by,
                updated_at = now(),
                updated_by = :updated_by
            where id = :buyer_intent_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "deleted_by": DEFAULT_ADMIN_USER_ID,
            "updated_by": DEFAULT_ADMIN_USER_ID,
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    write_action_log(
        db,
        entity_type="buyer_intent",
        entity_id=buyer_intent_id,
        field_path="deleted_at",
        old_value=None,
        new_value="now()",
    )
    db.commit()
    return None


def _get_buyer_intent_or_404(db: Session, buyer_intent_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, buyer_party_id, intent_name, status, contact_name,
              raw_requirement_text, intent_summary, parsed_requirement_json,
              industry_primary, industry_secondary, region_scope_summary,
              region_constraints_json, min_revenue_yuan, min_net_profit_yuan,
              min_total_profit_yuan, max_pe, max_valuation_yuan,
              market_cap_range_summary, requires_control, requires_consolidation,
              accepts_minority_investment, desired_equity_ratio_min,
              desired_equity_ratio_max, equity_ratio_summary, equity_requirement_type,
              acceptable_control_paths_json, preferred_listed_status, transaction_type,
              negative_summary, priority_summary, preference_summary, unknown_summary,
              created_at::text as created_at, updated_at::text as updated_at
            from buyer_intent
            where id = :buyer_intent_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Buyer intent not found.")

    return dict(row)


def _buyer_intent_params(payload: BuyerIntentCreate) -> dict[str, Any]:
    return {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "buyer_party_id": payload.buyer_party_id,
        "owner_user_id": payload.owner_user_id or DEFAULT_ADMIN_USER_ID,
        "intent_name": payload.intent_name.strip(),
        "contact_name": payload.contact_name,
        "raw_requirement_text": payload.raw_requirement_text,
        "intent_summary": payload.intent_summary,
        "parsed_requirement_json": payload.parsed_requirement_json or {},
        "industry_primary": payload.industry_primary,
        "industry_secondary": payload.industry_secondary,
        "region_scope_summary": payload.region_scope_summary,
        "region_constraints_json": payload.region_constraints_json or [],
        "min_revenue_yuan": payload.min_revenue_yuan,
        "min_net_profit_yuan": payload.min_net_profit_yuan,
        "min_total_profit_yuan": payload.min_total_profit_yuan,
        "max_pe": payload.max_pe,
        "max_valuation_yuan": payload.max_valuation_yuan,
        "market_cap_range_summary": payload.market_cap_range_summary,
        "requires_control": payload.requires_control,
        "requires_consolidation": payload.requires_consolidation,
        "accepts_minority_investment": payload.accepts_minority_investment,
        "desired_equity_ratio_min": payload.desired_equity_ratio_min,
        "desired_equity_ratio_max": payload.desired_equity_ratio_max,
        "equity_ratio_summary": payload.equity_ratio_summary,
        "equity_requirement_type": payload.equity_requirement_type,
        "acceptable_control_paths_json": payload.acceptable_control_paths_json or [],
        "preferred_listed_status": payload.preferred_listed_status,
        "transaction_type": payload.transaction_type,
        "negative_summary": payload.negative_summary,
        "priority_summary": payload.priority_summary,
        "preference_summary": payload.preference_summary,
        "unknown_summary": payload.unknown_summary,
        "created_by": DEFAULT_ADMIN_USER_ID,
        "updated_by": DEFAULT_ADMIN_USER_ID,
    }


def _latest_active_parse_job(db: Session, buyer_intent_id: UUID) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select id, job_type, status, queue_name, entity_id
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and job_type = 'buyer_intent_parse'
              and entity_type = 'buyer_intent'
              and entity_id = :buyer_intent_id
              and status in ('queued', 'running', 'retry_waiting')
            order by created_at desc
            limit 1
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _latest_parse_job(db: Session, buyer_intent_id: UUID) -> dict[str, Any] | None:
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
              and job_type = 'buyer_intent_parse'
              and entity_type = 'buyer_intent'
              and entity_id = :buyer_intent_id
            order by created_at desc
            limit 1
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _latest_parse_trace(db: Session, buyer_intent_id: UUID) -> dict[str, Any] | None:
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
              and node_name = 'buyer_intent_parser'
              and entity_type = 'buyer_intent'
              and entity_id = :buyer_intent_id
            order by started_at desc
            limit 1
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _recent_parse_update_logs(db: Session, buyer_intent_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, field_path, old_value_json, new_value_json, source_type, source_id,
              applied_at::text as applied_at, can_rollback, rollback_at::text as rollback_at
            from action_application_log
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = 'buyer_intent'
              and entity_id = :buyer_intent_id
              and source_type = 'buyer_intent_parse'
            order by applied_at desc
            limit 50
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
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
    return text_value[: max_length - 1] + "…"
