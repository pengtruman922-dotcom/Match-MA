from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db
from backend.app.services.search_docs import create_search_doc_rebuild_job

router = APIRouter(prefix="/update-logs", tags=["update-logs"])


class UpdateLogOut(BaseModel):
    id: UUID
    extracted_action_id: UUID | None = None
    business_update_id: UUID | None = None
    entity_type: str
    entity_id: UUID
    field_path: str
    old_value_json: Any
    new_value_json: Any
    source_type: str | None
    source_id: UUID | None = None
    applied_by: UUID | None
    applied_at: str
    edited_before_apply: bool
    can_rollback: bool
    rollback_at: str | None


class UpdateLogRollbackRequest(BaseModel):
    force: bool = False
    reason: str | None = None


class UpdateLogRollbackOut(BaseModel):
    status: str
    rollback_count: int
    rolled_back_logs: list[dict[str, Any]]
    skipped_logs: list[dict[str, Any]]
    extracted_action_id: UUID | None = None
    business_update_id: UUID | None = None


@router.get("", response_model=list[UpdateLogOut])
def list_update_logs(
    entity_type: str = Query(pattern="^(seller_target|buyer_intent|buyer_party|buyer_seller_relation)$"),
    entity_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    where = [
        "team_id = :team_id",
        "workspace_id = :workspace_id",
        "entity_type = :entity_type",
    ]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "entity_type": entity_type,
        "limit": limit,
        "offset": offset,
    }

    if entity_id is not None:
        where.append("entity_id = :entity_id")
        params["entity_id"] = entity_id

    rows = db.execute(
        text(
            f"""
            select
              id, extracted_action_id, business_update_id,
              entity_type, entity_id, field_path,
              old_value_json, new_value_json, source_type, source_id, applied_by,
              applied_at::text as applied_at,
              edited_before_apply, can_rollback,
              rollback_at::text as rollback_at
            from action_application_log
            where {' and '.join(where)}
            order by applied_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()

    return [dict(row) for row in rows]


@router.post("/{log_id}/rollback", response_model=UpdateLogRollbackOut)
def rollback_update_log(
    log_id: UUID,
    payload: UpdateLogRollbackRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    request = payload or UpdateLogRollbackRequest()
    log = _get_update_log_or_404(db, log_id)
    result = _rollback_logs(db, [log], force=request.force, reason=request.reason)
    db.commit()
    return result


@router.post("/actions/{extracted_action_id}/rollback", response_model=UpdateLogRollbackOut)
def rollback_extracted_action_logs(
    extracted_action_id: UUID,
    payload: UpdateLogRollbackRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    request = payload or UpdateLogRollbackRequest()
    logs = _get_rollbackable_logs_for_action(db, extracted_action_id)
    if not logs:
        return {
            "status": "noop",
            "rollback_count": 0,
            "rolled_back_logs": [],
            "skipped_logs": [],
            "extracted_action_id": extracted_action_id,
            "business_update_id": None,
        }
    result = _rollback_logs(db, logs, force=request.force, reason=request.reason)
    _mark_action_rejected_after_rollback(db, extracted_action_id)
    db.commit()
    return {**result, "extracted_action_id": extracted_action_id}


ROLLBACK_TABLE_BY_ENTITY = {
    "seller_target": "seller_target",
    "buyer_intent": "buyer_intent",
    "buyer_party": "buyer_party",
    "buyer_seller_relation": "buyer_seller_relation",
}

ROLLBACK_FIELDS_BY_ENTITY = {
    "seller_target": {
        "target_name",
        "target_type",
        "industry_primary",
        "industry_secondary",
        "registered_province",
        "registered_city",
        "headquarter_province",
        "headquarter_city",
        "raw_region_text",
        "region_granularity",
        "listed_status",
        "market_cap_yuan",
        "current_revenue_yuan",
        "current_net_profit_yuan",
        "current_total_profit_yuan",
        "current_assets_yuan",
        "current_debt_ratio",
        "current_operating_cash_flow_yuan",
        "financial_period_label",
        "profitability_status",
        "cash_flow_status",
        "operation_stability_status",
        "valuation_yuan",
        "asking_price_yuan",
        "pe_ratio",
        "pe_source_type",
        "premium_rate",
        "is_for_sale",
        "can_control",
        "can_consolidate",
        "accepts_minority_investment",
        "transfer_ratio_min",
        "transfer_ratio_max",
        "transfer_ratio_text",
        "transfer_flexibility_type",
        "consolidation_path_summary",
        "accepts_relocation",
        "accepts_return_investment",
        "management_team_summary",
        "management_retention_possible",
        "earnout_dependency_status",
        "recommendation_status",
        "information_status",
        "business_summary",
        "transaction_summary",
        "risk_summary",
        "gap_summary",
    },
    "buyer_intent": {
        "intent_name",
        "status",
        "pause_reason",
        "contact_name",
        "contact_info_json",
        "raw_requirement_text",
        "intent_summary",
        "parsed_requirement_json",
        "industry_primary",
        "industry_secondary",
        "region_scope_summary",
        "region_constraints_json",
        "min_revenue_yuan",
        "min_net_profit_yuan",
        "min_total_profit_yuan",
        "max_pe",
        "max_valuation_yuan",
        "market_cap_range_summary",
        "requires_control",
        "requires_consolidation",
        "accepts_minority_investment",
        "desired_equity_ratio_min",
        "desired_equity_ratio_max",
        "equity_ratio_summary",
        "equity_requirement_type",
        "acceptable_control_paths_json",
        "preferred_listed_status",
        "transaction_type",
        "negative_summary",
        "priority_summary",
        "preference_summary",
        "unknown_summary",
    },
    "buyer_party": {
        "buyer_name",
        "legal_name",
        "aliases_json",
        "buyer_type",
        "group_name",
        "listed_status",
        "region_province",
        "region_city",
        "main_business",
        "capital_strength_summary",
        "profile_summary",
        "status",
    },
    "buyer_seller_relation": {
        "status",
        "status_reason",
        "first_recommended_at",
        "last_contact_at",
        "last_event_at",
        "last_event_summary",
    },
}

JSONB_ROLLBACK_FIELDS = {
    ("buyer_intent", "contact_info_json"),
    ("buyer_intent", "parsed_requirement_json"),
    ("buyer_intent", "region_constraints_json"),
    ("buyer_intent", "acceptable_control_paths_json"),
    ("buyer_party", "aliases_json"),
}


def _get_update_log_or_404(db: Session, log_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, extracted_action_id, business_update_id,
              entity_type, entity_id, field_path,
              old_value_json, new_value_json, source_type, source_id,
              applied_by, applied_at::text as applied_at,
              edited_before_apply, can_rollback,
              rollback_at::text as rollback_at, metadata_json
            from action_application_log
            where id = :log_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {"log_id": log_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Update log not found.")
    return dict(row)


def _get_rollbackable_logs_for_action(db: Session, extracted_action_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, extracted_action_id, business_update_id,
              entity_type, entity_id, field_path,
              old_value_json, new_value_json, source_type, source_id,
              applied_by, applied_at::text as applied_at,
              edited_before_apply, can_rollback,
              rollback_at::text as rollback_at, metadata_json
            from action_application_log
            where extracted_action_id = :extracted_action_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and can_rollback = true
              and rollback_at is null
              and coalesce(source_type, '') <> 'rollback'
            order by applied_at desc
            """
        ),
        {
            "extracted_action_id": extracted_action_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _rollback_logs(
    db: Session,
    logs: list[dict[str, Any]],
    *,
    force: bool,
    reason: str | None,
) -> dict[str, Any]:
    rolled_back_logs: list[dict[str, Any]] = []
    skipped_logs: list[dict[str, Any]] = []
    business_update_id = logs[0].get("business_update_id") if logs else None
    extracted_action_id = logs[0].get("extracted_action_id") if logs else None

    for log in logs:
        rollbackability = _rollbackability(log)
        if not rollbackability["ok"]:
            if len(logs) == 1:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=rollbackability["reason"])
            skipped_logs.append({"id": log["id"], "reason": rollbackability["reason"]})
            continue

        current_value = _get_current_field_value(db, log)
        if not force and not _values_match_for_rollback(current_value, log.get("new_value_json")):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Current field value no longer matches this update log. "
                    "Refresh the page or retry with force=true after manual review."
                ),
            )

        _apply_field_rollback(db, log)
        rollback_log = _insert_rollback_log(db, log, current_value=current_value, reason=reason)
        _mark_field_sources_ignored_after_rollback(db, log)
        _mark_log_rolled_back(db, log["id"])
        _enqueue_rebuild_after_rollback(db, log)
        rolled_back_logs.append(rollback_log)

    return {
        "status": "rolled_back" if rolled_back_logs else "noop",
        "rollback_count": len(rolled_back_logs),
        "rolled_back_logs": rolled_back_logs,
        "skipped_logs": skipped_logs,
        "extracted_action_id": extracted_action_id,
        "business_update_id": business_update_id,
    }


def _rollbackability(log: dict[str, Any]) -> dict[str, Any]:
    entity_type = log.get("entity_type")
    field_path = log.get("field_path")
    if not log.get("can_rollback"):
        return {"ok": False, "reason": "This update log is marked as not rollbackable."}
    if log.get("rollback_at") is not None:
        return {"ok": False, "reason": "This update log has already been rolled back."}
    if log.get("source_type") == "rollback":
        return {"ok": False, "reason": "Rollback logs cannot be rolled back again."}
    if entity_type not in ROLLBACK_TABLE_BY_ENTITY:
        return {"ok": False, "reason": f"Rollback is not supported for entity_type={entity_type}."}
    if field_path not in ROLLBACK_FIELDS_BY_ENTITY.get(entity_type, set()):
        return {"ok": False, "reason": f"Rollback is not supported for field_path={field_path}."}
    return {"ok": True, "reason": None}


def _get_current_field_value(db: Session, log: dict[str, Any]) -> Any:
    entity_type = log["entity_type"]
    field_path = log["field_path"]
    table_name = ROLLBACK_TABLE_BY_ENTITY[entity_type]
    row = db.execute(
        text(
            f"""
            select {field_path} as value
            from {table_name}
            where id = :entity_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "entity_id": log["entity_id"],
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rollback target entity not found.")
    return row["value"]


def _apply_field_rollback(db: Session, log: dict[str, Any]) -> None:
    entity_type = log["entity_type"]
    field_path = log["field_path"]
    table_name = ROLLBACK_TABLE_BY_ENTITY[entity_type]
    statement = text(
        f"""
        update {table_name}
        set {field_path} = :rollback_value,
            updated_at = now(),
            updated_by = :updated_by
        where id = :entity_id
          and team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
        """
    )
    if (entity_type, field_path) in JSONB_ROLLBACK_FIELDS:
        statement = statement.bindparams(bindparam("rollback_value", type_=JSONB))
    result = db.execute(
        statement,
        {
            "rollback_value": log.get("old_value_json"),
            "updated_by": DEFAULT_ADMIN_USER_ID,
            "entity_id": log["entity_id"],
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    if result.rowcount != 1:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rollback target entity not found.")


def _insert_rollback_log(
    db: Session,
    original_log: dict[str, Any],
    *,
    current_value: Any,
    reason: str | None,
) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            insert into action_application_log (
              team_id, workspace_id, extracted_action_id, business_update_id,
              entity_type, entity_id, field_path,
              old_value_json, new_value_json, source_type, source_id,
              applied_by, edited_before_apply, can_rollback, metadata_json
            )
            values (
              :team_id, :workspace_id, :extracted_action_id, :business_update_id,
              :entity_type, :entity_id, :field_path,
              :old_value_json, :new_value_json, 'rollback', :source_id,
              :applied_by, false, false, :metadata_json
            )
            returning
              id, extracted_action_id, business_update_id,
              entity_type, entity_id, field_path,
              old_value_json, new_value_json, source_type, source_id,
              applied_by, applied_at::text as applied_at,
              edited_before_apply, can_rollback,
              rollback_at::text as rollback_at, metadata_json
            """
        ).bindparams(
            bindparam("old_value_json", type_=JSONB),
            bindparam("new_value_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "extracted_action_id": original_log.get("extracted_action_id"),
            "business_update_id": original_log.get("business_update_id"),
            "entity_type": original_log["entity_type"],
            "entity_id": original_log["entity_id"],
            "field_path": original_log["field_path"],
            "old_value_json": _json_safe(current_value),
            "new_value_json": original_log.get("old_value_json"),
            "source_id": original_log["id"],
            "applied_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {
                "source": "update_log_rollback",
                "rolled_back_log_id": str(original_log["id"]),
                "rollback_reason": reason,
            },
        },
    ).mappings().one()
    return dict(row)


def _mark_log_rolled_back(db: Session, log_id: UUID) -> None:
    db.execute(
        text(
            """
            update action_application_log
            set rollback_at = now()
            where id = :log_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {"log_id": log_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    )


def _mark_field_sources_ignored_after_rollback(db: Session, log: dict[str, Any]) -> None:
    db.execute(
        text(
            """
            update field_value_source
            set review_status = 'ignored'
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = :entity_type
              and entity_id = :entity_id
              and field_path = :field_path
              and source_type = :source_type
              and source_id = :source_id
              and review_status in ('pending_review', 'accepted', 'auto_accepted')
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "entity_type": log["entity_type"],
            "entity_id": log["entity_id"],
            "field_path": log["field_path"],
            "source_type": log.get("source_type"),
            "source_id": log.get("source_id"),
        },
    )


def _mark_action_rejected_after_rollback(db: Session, extracted_action_id: UUID) -> None:
    db.execute(
        text(
            """
            update extracted_action
            set review_status = 'rejected',
                reviewed_by = :reviewed_by,
                reviewed_at = now()
            where id = :extracted_action_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and review_status in ('pending_review', 'accepted', 'auto_accepted')
            """
        ),
        {
            "extracted_action_id": extracted_action_id,
            "reviewed_by": DEFAULT_ADMIN_USER_ID,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )


def _enqueue_rebuild_after_rollback(db: Session, log: dict[str, Any]) -> None:
    if log["entity_type"] not in {"seller_target", "buyer_intent"}:
        return
    create_search_doc_rebuild_job(
        db,
        entity_type=log["entity_type"],
        entity_id=log["entity_id"],
        source="update_log_rollback",
    )


def _values_match_for_rollback(current_value: Any, logged_new_value: Any) -> bool:
    return _json_safe(current_value) == _json_safe(logged_new_value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return str(value) if value.__class__.__name__ == "Decimal" else value
