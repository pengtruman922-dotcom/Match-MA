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


class RecommendationSessionDebugOut(BaseModel):
    session: dict[str, Any]
    jobs: list[dict[str, Any]]
    traces: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    selected_items: list[dict[str, Any]]
    reports: list[dict[str, Any]]
    relations: list[dict[str, Any]]
    relation_events: list[dict[str, Any]]
    debug: dict[str, Any]


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


@router.get("/recommendation-sessions/{session_id}", response_model=RecommendationSessionDebugOut)
def get_recommendation_session_debug(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    session = _get_recommendation_session(db, session_id)
    jobs = _recommendation_jobs(db, session_id)
    traces = _recommendation_traces(db, session_id)
    messages = _recommendation_messages(db, session_id)
    selected_items = _recommendation_selected_items(db, session_id)
    reports = _recommendation_reports(db, session_id)
    relations = _recommendation_relations(db, session_id)
    relation_events = _recommendation_relation_events(db, session_id)
    return {
        "session": session,
        "jobs": jobs,
        "traces": traces,
        "messages": messages,
        "selected_items": selected_items,
        "reports": reports,
        "relations": relations,
        "relation_events": relation_events,
        "debug": {
            "message_count": len(messages),
            "job_count": len(jobs),
            "trace_count": len(traces),
            "selected_item_count": len(selected_items),
            "active_selected_item_count": len(
                [item for item in selected_items if item.get("canceled_at") is None]
            ),
            "report_count": len(reports),
            "relation_count": len(relations),
            "relation_event_count": len(relation_events),
        },
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


def _get_recommendation_session(db: Session, session_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, mode, buyer_intent_id, buyer_party_id, seller_target_id,
              status, selected_count, report_count, anonymous_input_snapshot,
              initial_condition_snapshot_json, latest_condition_snapshot_json,
              created_by, created_at::text as created_at, updated_at::text as updated_at,
              archived_at::text as archived_at, metadata_json
            from recommendation_session
            where id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Recommendation session not found.")
    return dict(row)


def _recommendation_jobs(db: Session, session_id: UUID) -> list[dict[str, Any]]:
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
              and (
                payload_json ->> 'session_id' = :session_id_text
                or entity_id in (
                  select id
                  from recommendation_report
                  where session_id = :session_id
                    and team_id = :team_id
                    and workspace_id = :workspace_id
                )
              )
            order by created_at desc
            limit 100
            """
        ),
        {
            "session_id": session_id,
            "session_id_text": str(session_id),
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _recommendation_traces(db: Session, session_id: UUID) -> list[dict[str, Any]]:
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
              and (
                input_json ->> 'session_id' = :session_id_text
                or entity_id in (
                  select id
                  from recommendation_report
                  where session_id = :session_id
                    and team_id = :team_id
                    and workspace_id = :workspace_id
                )
              )
            order by started_at desc
            limit 100
            """
        ),
        {
            "session_id": session_id,
            "session_id_text": str(session_id),
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _recommendation_messages(db: Session, session_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, session_id, role, content, content_type,
              metadata_json, created_by, created_at::text as created_at
            from recommendation_message
            where session_id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            order by created_at asc
            limit 500
            """
        ),
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _recommendation_selected_items(db: Session, session_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              ri.id, ri.session_id, ri.mode,
              ri.seller_target_id, st.target_name as seller_target_name,
              ri.buyer_intent_id, bi.intent_name as buyer_intent_name,
              ri.buyer_party_id, bp.buyer_name,
              ri.rank_at_selection, ri.recommendation_level, ri.match_summary,
              ri.risk_summary, ri.gap_summary, ri.reason_snapshot,
              ri.evidence_snapshot_json, ri.selected_by,
              ri.selected_at::text as selected_at, ri.canceled_by,
              ri.canceled_at::text as canceled_at, ri.metadata_json
            from recommendation_selected_item ri
            left join seller_target st on st.id = ri.seller_target_id
            left join buyer_intent bi on bi.id = ri.buyer_intent_id
            left join buyer_party bp on bp.id = ri.buyer_party_id
            where ri.session_id = :session_id
              and ri.team_id = :team_id
              and ri.workspace_id = :workspace_id
            order by ri.selected_at desc
            limit 500
            """
        ),
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _recommendation_reports(db: Session, session_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, session_id, report_type, selected_item_ids_json, title,
              markdown_content, file_path, file_format, status,
              generated_by_model, prompt_version, created_by,
              created_at::text as created_at, metadata_json
            from recommendation_report
            where session_id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            order by created_at desc
            limit 100
            """
        ),
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _recommendation_relations(db: Session, session_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, buyer_intent_id, buyer_party_id, seller_target_id,
              status, last_event_at::text as last_event_at,
              last_event_summary, first_recommended_at::text as first_recommended_at,
              created_from_session_id, created_at::text as created_at,
              updated_at::text as updated_at, metadata_json
            from buyer_seller_relation
            where team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              and (
                created_from_session_id = :session_id
                or metadata_json ->> 'last_recommendation_session_id' = :session_id_text
                or exists (
                  select 1
                  from recommendation_selected_item ri
                  where ri.session_id = :session_id
                    and ri.metadata_json ->> 'relation_id' = buyer_seller_relation.id::text
                )
              )
            order by updated_at desc
            limit 100
            """
        ),
        {
            "session_id": session_id,
            "session_id_text": str(session_id),
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _recommendation_relation_events(db: Session, session_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, relation_id, buyer_intent_id, buyer_party_id, seller_target_id,
              event_type, event_time::text as event_time, title, content,
              source_type, source_id, metadata_json, created_by,
              created_at::text as created_at
            from relation_event
            where team_id = :team_id
              and workspace_id = :workspace_id
              and metadata_json ->> 'recommendation_session_id' = :session_id_text
            order by event_time desc
            limit 200
            """
        ),
        {
            "session_id_text": str(session_id),
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


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
