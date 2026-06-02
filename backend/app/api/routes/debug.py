from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db

router = APIRouter(prefix="/debug", tags=["debug"])


class BusinessUpdateDebugOut(BaseModel):
    business_update: dict[str, Any]
    jobs: list[dict[str, Any]]
    traces: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    application_logs: list[dict[str, Any]]


@router.get("/business-updates/{business_update_id}", response_model=BusinessUpdateDebugOut)
def get_business_update_debug(
    business_update_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    business_update = _get_business_update(db, business_update_id)
    jobs = _jobs(db, business_update_id)
    traces = _traces(db, business_update_id)
    actions = _actions(db, business_update_id)
    application_logs = _application_logs(db, business_update_id)
    return {
        "business_update": business_update,
        "jobs": jobs,
        "traces": traces,
        "actions": actions,
        "application_logs": application_logs,
    }


def _get_business_update(db: Session, business_update_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, raw_text, input_type, processing_status,
              bound_seller_target_ids_json, bound_buyer_party_ids_json, bound_buyer_intent_ids_json,
              bound_recommendation_session_id, created_by,
              created_at::text as created_at, metadata_json
            from business_update
            where id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Business update not found.")
    return dict(row)


def _jobs(db: Session, business_update_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, job_type, status, priority, queue_name, entity_type, entity_id,
              idempotency_key, payload_json, result_json, error_code, error_message,
              error_detail_json, attempt_count, max_attempts, run_after::text as run_after,
              locked_by, locked_at::text as locked_at, started_at::text as started_at,
              finished_at::text as finished_at, parent_job_id, correlation_id, created_by,
              created_at::text as created_at, updated_at::text as updated_at, metadata_json
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = 'business_update'
              and entity_id = :business_update_id
            order by created_at desc
            limit 20
            """
        ),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _traces(db: Session, business_update_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, trace_type, node_name, job_id, correlation_id, entity_type, entity_id,
              provider_name, model_name, prompt_version, status,
              input_json, prompt_messages_json, raw_output_text, parsed_output_json,
              schema_validation_json, retrieval_output_json, tool_calls_json,
              error_code, error_message, latency_ms, prompt_tokens, completion_tokens,
              total_tokens, cost_json, started_at::text as started_at,
              finished_at::text as finished_at, metadata_json
            from ai_trace
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = 'business_update'
              and entity_id = :business_update_id
            order by started_at desc
            limit 20
            """
        ),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _actions(db: Session, business_update_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, business_update_id, action_type, target_entity_type, target_entity_id,
              proposed_changes_json, raw_evidence_text, confidence, review_status,
              reviewed_by, reviewed_at::text as reviewed_at, applied_at::text as applied_at,
              metadata_json, created_at::text as created_at
            from extracted_action
            where business_update_id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            order by created_at desc
            limit 100
            """
        ),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _application_logs(db: Session, business_update_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, extracted_action_id, business_update_id, entity_type, entity_id,
              field_path, old_value_json, new_value_json, source_type, source_id,
              evidence_id, applied_by, applied_at::text as applied_at,
              edited_before_apply, can_rollback, rollback_at::text as rollback_at,
              metadata_json
            from action_application_log
            where business_update_id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            order by applied_at desc
            limit 100
            """
        ),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]
