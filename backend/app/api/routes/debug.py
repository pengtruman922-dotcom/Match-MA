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


class DebugEntityOut(BaseModel):
    entity_type: str
    entity_id: UUID
    summary: dict[str, Any]
    payload: dict[str, Any]


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


@router.get("/entities/{entity_type}/{entity_id}", response_model=DebugEntityOut)
def get_debug_entity(entity_type: str, entity_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    if entity_type == "business_update":
        payload = get_business_update_debug(entity_id, db)
    elif entity_type == "recommendation_session":
        payload = get_recommendation_session_debug(entity_id, db)
    elif entity_type == "background_job":
        payload = _background_job_debug(db, entity_id)
    elif entity_type == "model_node_config":
        payload = _model_node_debug(db, entity_id)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported debug entity_type: {entity_type}")
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "summary": _debug_summary(entity_type, payload),
        "payload": payload,
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


def _background_job_debug(db: Session, job_id: UUID) -> dict[str, Any]:
    job = _background_job(db, job_id)
    traces = _job_traces(db, job_id)
    related_jobs = _related_jobs(db, job)
    return {
        "job": job,
        "traces": traces,
        "related_jobs": related_jobs,
        "debug": {
            "trace_count": len(traces),
            "related_job_count": len(related_jobs),
            "status": job["status"],
            "queue_name": job["queue_name"],
        },
    }


def _model_node_debug(db: Session, node_id: UUID) -> dict[str, Any]:
    node = _model_node(db, node_id)
    jobs = _model_node_jobs(db, node_id)
    traces = _model_node_traces(db, node_id)
    return {
        "node": node,
        "jobs": jobs,
        "traces": traces,
        "debug": {
            "job_count": len(jobs),
            "trace_count": len(traces),
            "latest_job_status": jobs[0]["status"] if jobs else None,
            "latest_trace_status": traces[0]["status"] if traces else None,
        },
    }


def _debug_summary(entity_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if entity_type == "business_update":
        return {
            "title": "Business update debug",
            "status": payload["business_update"].get("processing_status"),
            "job_count": len(payload.get("jobs", [])),
            "trace_count": len(payload.get("traces", [])),
            "action_count": len(payload.get("actions", [])),
        }
    if entity_type == "recommendation_session":
        debug = payload.get("debug", {})
        return {
            "title": "Recommendation session debug",
            "status": payload["session"].get("status"),
            "job_count": debug.get("job_count"),
            "trace_count": debug.get("trace_count"),
            "message_count": debug.get("message_count"),
        }
    if entity_type == "background_job":
        job = payload["job"]
        return {
            "title": f"Background job: {job.get('job_type')}",
            "status": job.get("status"),
            "queue_name": job.get("queue_name"),
            "trace_count": len(payload.get("traces", [])),
        }
    if entity_type == "model_node_config":
        node = payload["node"]
        return {
            "title": f"Model node: {node.get('node_name')}",
            "status": "active" if node.get("is_active") else "inactive",
            "node_type": node.get("node_type"),
            "job_count": len(payload.get("jobs", [])),
            "trace_count": len(payload.get("traces", [])),
        }
    return {"title": entity_type}


def _background_job(db: Session, job_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            f"""
            select {_background_job_select_columns()}
            from background_job
            where id = :job_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "job_id": job_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Background job not found.")
    return dict(row)


def _job_traces(db: Session, job_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            select {_ai_trace_select_columns()}
            from ai_trace
            where team_id = :team_id
              and workspace_id = :workspace_id
              and job_id = :job_id
            order by started_at desc
            limit 100
            """
        ),
        {
            "job_id": job_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _related_jobs(db: Session, job: dict[str, Any]) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            select {_background_job_select_columns()}
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and id <> :job_id
              and (
                (cast(:correlation_id as uuid) is not null and correlation_id = cast(:correlation_id as uuid))
                or parent_job_id = :job_id
                or (
                  cast(:parent_job_id as uuid) is not null
                  and parent_job_id = cast(:parent_job_id as uuid)
                )
                or (
                  :entity_type is not null
                  and cast(:entity_id as uuid) is not null
                  and entity_type = :entity_type
                  and entity_id = cast(:entity_id as uuid)
                )
              )
            order by created_at desc
            limit 50
            """
        ),
        {
            "job_id": job["id"],
            "correlation_id": job.get("correlation_id"),
            "parent_job_id": job.get("parent_job_id"),
            "entity_type": job.get("entity_type"),
            "entity_id": job.get("entity_id"),
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _model_node(db: Session, node_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            f"""
            select {_model_node_select_columns()}
            from model_node_config node
            left join model_provider_config provider on provider.id = node.provider_config_id
            where node.id = :node_id
              and node.team_id = :team_id
              and node.workspace_id = :workspace_id
            """
        ),
        {
            "node_id": node_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Model node config not found.")
    return dict(row)


def _model_node_jobs(db: Session, node_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            select {_background_job_select_columns()}
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and (
                (entity_type = 'model_node_config' and entity_id = :node_id)
                or payload_json ->> 'node_id' = :node_id_text
              )
            order by created_at desc
            limit 50
            """
        ),
        {
            "node_id": node_id,
            "node_id_text": str(node_id),
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _model_node_traces(db: Session, node_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            with selected_node as (
              select id, node_name
              from model_node_config
              where id = :node_id
                and team_id = :team_id
                and workspace_id = :workspace_id
            )
            select {_ai_trace_select_columns("t")}
            from ai_trace t
            join selected_node node
              on t.node_config_id = node.id
              or t.node_name = node.node_name
            where t.team_id = :team_id
              and t.workspace_id = :workspace_id
            order by t.started_at desc
            limit 100
            """
        ),
        {
            "node_id": node_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _background_job_select_columns(prefix: str | None = None) -> str:
    p = f"{prefix}." if prefix else ""
    return f"""
      {p}id, {p}job_type, {p}status, {p}priority, {p}queue_name, {p}entity_type, {p}entity_id,
      {p}idempotency_key, {p}payload_json, {p}result_json, {p}error_code, {p}error_message,
      {p}error_detail_json, {p}attempt_count, {p}max_attempts, {p}run_after::text as run_after,
      {p}locked_by, {p}locked_at::text as locked_at, {p}started_at::text as started_at,
      {p}finished_at::text as finished_at, {p}parent_job_id, {p}correlation_id, {p}created_by,
      {p}created_at::text as created_at, {p}updated_at::text as updated_at, {p}metadata_json
    """


def _ai_trace_select_columns(prefix: str | None = None) -> str:
    p = f"{prefix}." if prefix else ""
    return f"""
      {p}id, {p}trace_type, {p}node_name, {p}job_id, {p}correlation_id,
      {p}entity_type, {p}entity_id, {p}provider_config_id, {p}node_config_id,
      {p}prompt_template_id, {p}provider_name, {p}model_name, {p}prompt_version, {p}status,
      {p}input_json, {p}prompt_messages_json, {p}raw_output_text, {p}parsed_output_json,
      {p}output_schema_json, {p}schema_validation_json, {p}retrieval_input_json,
      {p}retrieval_output_json, {p}tool_calls_json, {p}error_code, {p}error_message,
      {p}error_detail_json, {p}latency_ms, {p}prompt_tokens, {p}completion_tokens,
      {p}total_tokens, {p}cost_json, {p}started_at::text as started_at,
      {p}finished_at::text as finished_at, {p}created_by, {p}metadata_json
    """


def _model_node_select_columns() -> str:
    return """
      node.id, node.node_name, node.node_type, node.provider_config_id,
      provider.provider_name, provider.provider_type, provider.base_url, provider.api_key_secret_ref,
      node.model_name, node.temperature, node.top_p, node.max_tokens,
      node.timeout_seconds, node.response_format, node.output_mode,
      node.embedding_dimension, node.is_active, node.is_default,
      node.created_by, node.created_at::text as created_at, node.updated_at::text as updated_at,
      node.metadata_json
    """


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
