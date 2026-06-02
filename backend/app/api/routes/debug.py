from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
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


class DebugCenterOut(BaseModel):
    overview: dict[str, Any]
    failed_jobs: list[dict[str, Any]]
    running_jobs: list[dict[str, Any]]
    recent_traces: list[dict[str, Any]]
    failed_traces: list[dict[str, Any]]
    recent_business_updates: list[dict[str, Any]]
    recent_recommendation_sessions: list[dict[str, Any]]
    model_node_test_failures: list[dict[str, Any]]
    quick_actions: list[dict[str, Any]]


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


@router.get("/center", response_model=DebugCenterOut)
def get_debug_center(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    overview = _debug_center_overview(db)
    return {
        "overview": overview,
        "failed_jobs": _debug_center_failed_jobs(db, limit),
        "running_jobs": _debug_center_running_jobs(db, limit),
        "recent_traces": _debug_center_recent_traces(db, limit),
        "failed_traces": _debug_center_failed_traces(db, limit),
        "recent_business_updates": _debug_center_recent_business_updates(db, limit),
        "recent_recommendation_sessions": _debug_center_recent_recommendation_sessions(db, limit),
        "model_node_test_failures": _debug_center_model_node_test_failures(db, limit),
        "quick_actions": _debug_center_quick_actions(overview),
    }


@router.get("/entities/{entity_type}/{entity_id}", response_model=DebugEntityOut)
def get_debug_entity(entity_type: str, entity_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    if entity_type == "business_update":
        payload = get_business_update_debug(entity_id, db)
    elif entity_type == "recommendation_session":
        payload = get_recommendation_session_debug(entity_id, db)
    elif entity_type == "background_job":
        payload = _background_job_debug(db, entity_id)
    elif entity_type == "seller_target":
        payload = _business_object_debug(db, entity_type, entity_id)
    elif entity_type == "buyer_intent":
        payload = _business_object_debug(db, entity_type, entity_id)
    elif entity_type == "buyer_party":
        payload = _business_object_debug(db, entity_type, entity_id)
    elif entity_type == "model_node_config":
        payload = _model_node_debug(db, entity_id)
    elif entity_type == "recommendation_report":
        payload = _recommendation_report_debug(db, entity_id)
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


def _get_recommendation_report(db: Session, report_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, session_id, report_type, selected_item_ids_json, title,
              markdown_content, file_path, file_format, status,
              generated_by_model, prompt_version, created_by,
              created_at::text as created_at, metadata_json
            from recommendation_report
            where id = :report_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "report_id": report_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Recommendation report not found.")
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


def _recommendation_report_debug(db: Session, report_id: UUID) -> dict[str, Any]:
    report = _get_recommendation_report(db, report_id)
    jobs = _recommendation_report_jobs(db, report_id)
    traces = _recommendation_report_traces(db, report_id)
    messages = _recommendation_report_messages(db, report_id)
    session = _get_recommendation_session(db, report["session_id"])
    return {
        "report": report,
        "session": session,
        "jobs": jobs,
        "traces": traces,
        "messages": messages,
        "debug": {
            "job_count": len(jobs),
            "trace_count": len(traces),
            "message_count": len(messages),
            "session_debug_ref": _debug_ref("recommendation_session", report["session_id"]),
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
    if entity_type in {"seller_target", "buyer_intent", "buyer_party"}:
        entity = payload["entity"]
        return {
            "title": f"{entity_type}: {entity.get('name') or entity.get('title') or entity.get('id')}",
            "status": entity.get("status") or entity.get("recommendation_status"),
            "job_count": len(payload.get("jobs", [])),
            "trace_count": len(payload.get("traces", [])),
            "update_log_count": len(payload.get("application_logs", [])),
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
    if entity_type == "recommendation_report":
        report = payload["report"]
        return {
            "title": f"Recommendation report: {report.get('title') or report.get('report_type')}",
            "status": report.get("status"),
            "job_count": len(payload.get("jobs", [])),
            "trace_count": len(payload.get("traces", [])),
            "message_count": len(payload.get("messages", [])),
        }
    return {"title": entity_type}


BUSINESS_OBJECT_SELECTS = {
    "seller_target": """
        select
          id, target_name as name, target_name as title, target_type,
          recommendation_status, information_status, industry_primary, industry_secondary,
          headquarter_province, headquarter_city, listed_status,
          current_revenue_yuan, current_net_profit_yuan, current_total_profit_yuan,
          valuation_yuan, asking_price_yuan, pe_ratio, is_for_sale,
          can_control, can_consolidate, accepts_minority_investment,
          transfer_ratio_min, transfer_ratio_max, transfer_ratio_text,
          transfer_flexibility_type, business_summary, transaction_summary,
          risk_summary, gap_summary, created_at::text as created_at,
          updated_at::text as updated_at, metadata_json
        from seller_target
        where id = :entity_id
          and team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
    """,
    "buyer_intent": """
        select
          id, intent_name as name, intent_name as title, status, buyer_party_id,
          contact_name, raw_requirement_text, intent_summary, parsed_requirement_json,
          industry_primary, industry_secondary, region_scope_summary,
          region_constraints_json, min_revenue_yuan, min_net_profit_yuan,
          min_total_profit_yuan, max_pe, max_valuation_yuan, market_cap_range_summary,
          requires_control, requires_consolidation, accepts_minority_investment,
          desired_equity_ratio_min, desired_equity_ratio_max, equity_ratio_summary,
          equity_requirement_type, acceptable_control_paths_json, preferred_listed_status,
          transaction_type, negative_summary, priority_summary, preference_summary,
          unknown_summary, created_at::text as created_at, updated_at::text as updated_at,
          metadata_json
        from buyer_intent
        where id = :entity_id
          and team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
    """,
    "buyer_party": """
        select
          id, buyer_name as name, buyer_name as title, legal_name, buyer_type,
          status, listed_status, region_province, region_city, main_business,
          profile_summary, contact_info_json, created_at::text as created_at,
          updated_at::text as updated_at, metadata_json
        from buyer_party
        where id = :entity_id
          and team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
    """,
}


def _business_object(db: Session, entity_type: str, entity_id: UUID) -> dict[str, Any]:
    query = BUSINESS_OBJECT_SELECTS.get(entity_type)
    if query is None:
        raise HTTPException(status_code=400, detail=f"Unsupported business entity_type: {entity_type}")
    row = db.execute(
        text(query),
        {"entity_id": entity_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{entity_type} not found.")
    return dict(row)


def _entity_jobs(db: Session, entity_type: str, entity_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            select {_background_job_select_columns()}
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = :entity_type
              and entity_id = :entity_id
            order by created_at desc
            limit 100
            """
        ),
        {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _entity_traces(db: Session, entity_type: str, entity_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            select {_ai_trace_select_columns()}
            from ai_trace
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = :entity_type
              and entity_id = :entity_id
            order by started_at desc
            limit 100
            """
        ),
        {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _entity_application_logs(db: Session, entity_type: str, entity_id: UUID) -> list[dict[str, Any]]:
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
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = :entity_type
              and entity_id = :entity_id
            order by applied_at desc
            limit 100
            """
        ),
        {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _entity_relations(db: Session, entity_type: str, entity_id: UUID) -> list[dict[str, Any]]:
    if entity_type == "seller_target":
        where = "rel.seller_target_id = :entity_id"
    elif entity_type == "buyer_intent":
        where = "rel.buyer_intent_id = :entity_id"
    else:
        return []
    rows = db.execute(
        text(
            f"""
            select
              rel.id, rel.buyer_intent_id, bi.intent_name as buyer_intent_name,
              rel.buyer_party_id, bp.buyer_name, rel.seller_target_id,
              st.target_name as seller_target_name, rel.status, rel.stage,
              rel.last_event_at::text as last_event_at, rel.created_at::text as created_at,
              rel.updated_at::text as updated_at, rel.metadata_json
            from buyer_seller_relation rel
            left join buyer_intent bi on bi.id = rel.buyer_intent_id
            left join buyer_party bp on bp.id = rel.buyer_party_id
            left join seller_target st on st.id = rel.seller_target_id
            where rel.team_id = :team_id
              and rel.workspace_id = :workspace_id
              and {where}
            order by coalesce(rel.last_event_at, rel.updated_at, rel.created_at) desc
            limit 100
            """
        ),
        {"entity_id": entity_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().all()
    return [dict(row) for row in rows]


def _entity_relation_events(db: Session, entity_type: str, entity_id: UUID) -> list[dict[str, Any]]:
    if entity_type == "seller_target":
        where = "event.seller_target_id = :entity_id"
    elif entity_type == "buyer_intent":
        where = "event.buyer_intent_id = :entity_id"
    else:
        return []
    rows = db.execute(
        text(
            f"""
            select
              id, relation_id, buyer_intent_id, buyer_party_id, seller_target_id,
              event_type, event_status, event_date, note, source_type, source_id,
              created_by, created_at::text as created_at, metadata_json
            from relation_event event
            where team_id = :team_id
              and workspace_id = :workspace_id
              and {where}
            order by created_at desc
            limit 100
            """
        ),
        {"entity_id": entity_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().all()
    return [dict(row) for row in rows]


def _entity_search_doc(db: Session, entity_type: str, entity_id: UUID) -> dict[str, Any] | None:
    if entity_type == "seller_target":
        query = """
            select id, seller_target_id as entity_id, doc_type, title, full_text,
                   embedding_model, embedding_dim, source_version, updated_at::text as updated_at,
                   embedding is not null as has_embedding
            from seller_target_search_doc
            where team_id = :team_id
              and workspace_id = :workspace_id
              and seller_target_id = :entity_id
            order by updated_at desc
            limit 1
        """
    elif entity_type == "buyer_intent":
        query = """
            select id, buyer_intent_id as entity_id, title, full_text,
                   embedding_model, embedding_dim, source_version, updated_at::text as updated_at,
                   embedding is not null as has_embedding
            from buyer_intent_search_doc
            where team_id = :team_id
              and workspace_id = :workspace_id
              and buyer_intent_id = :entity_id
            order by updated_at desc
            limit 1
        """
    else:
        return None
    row = db.execute(
        text(query),
        {"entity_id": entity_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().one_or_none()
    return dict(row) if row else None


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
    clauses = ["parent_job_id = :job_id"]
    params: dict[str, Any] = {
        "job_id": job["id"],
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
    }
    if job.get("correlation_id") is not None:
        clauses.append("correlation_id = :correlation_id")
        params["correlation_id"] = job["correlation_id"]
    if job.get("parent_job_id") is not None:
        clauses.append("parent_job_id = :parent_job_id")
        params["parent_job_id"] = job["parent_job_id"]
    if job.get("entity_type") is not None and job.get("entity_id") is not None:
        clauses.append("(entity_type = :entity_type and entity_id = :entity_id)")
        params["entity_type"] = job["entity_type"]
        params["entity_id"] = job["entity_id"]

    rows = db.execute(
        text(
            f"""
            select {_background_job_select_columns()}
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and id <> :job_id
              and (
                {" or ".join(clauses)}
              )
            order by created_at desc
            limit 50
            """
        ),
        params,
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


def _recommendation_report_jobs(db: Session, report_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            select {_background_job_select_columns()}
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and (
                (entity_type = 'recommendation_report' and entity_id = :report_id)
                or payload_json ->> 'report_id' = :report_id_text
              )
            order by created_at desc
            limit 50
            """
        ),
        {
            "report_id": report_id,
            "report_id_text": str(report_id),
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _recommendation_report_traces(db: Session, report_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            select {_ai_trace_select_columns()}
            from ai_trace
            where team_id = :team_id
              and workspace_id = :workspace_id
              and (
                (entity_type = 'recommendation_report' and entity_id = :report_id)
                or input_json ->> 'report_id' = :report_id_text
              )
            order by started_at desc
            limit 100
            """
        ),
        {
            "report_id": report_id,
            "report_id_text": str(report_id),
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _recommendation_report_messages(db: Session, report_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, session_id, role, content, content_type,
              metadata_json, created_by, created_at::text as created_at
            from recommendation_message
            where team_id = :team_id
              and workspace_id = :workspace_id
              and metadata_json ->> 'report_id' = :report_id_text
            order by created_at desc
            limit 50
            """
        ),
        {
            "report_id_text": str(report_id),
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _debug_center_overview(db: Session) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              (select count(*) from background_job
               where team_id = :team_id and workspace_id = :workspace_id
                 and status = 'failed') as failed_job_count,
              (select count(*) from background_job
               where team_id = :team_id and workspace_id = :workspace_id
                 and status = 'queued') as queued_job_count,
              (select count(*) from background_job
               where team_id = :team_id and workspace_id = :workspace_id
                 and status = 'running') as running_job_count,
              (select count(*) from background_job
               where team_id = :team_id and workspace_id = :workspace_id
                 and status = 'retry_waiting') as retry_waiting_job_count,
              (select count(*) from ai_trace
               where team_id = :team_id and workspace_id = :workspace_id
                 and (status = 'failed' or error_code is not null)) as failed_trace_count,
              (select count(*) from ai_trace
               where team_id = :team_id and workspace_id = :workspace_id
                 and started_at >= now() - interval '24 hours') as recent_trace_count,
              (select count(*) from background_job
               where team_id = :team_id and workspace_id = :workspace_id
                 and job_type = 'model_node_test' and status = 'failed') as failed_model_node_test_count,
              (select count(*) from business_update
               where team_id = :team_id and workspace_id = :workspace_id
                 and processing_status = 'failed') as failed_business_update_count,
              (select count(*) from business_update
               where team_id = :team_id and workspace_id = :workspace_id
                 and created_at >= now() - interval '7 days') as recent_business_update_count,
              (select count(*) from recommendation_session
               where team_id = :team_id and workspace_id = :workspace_id
                 and created_at >= now() - interval '7 days') as recent_recommendation_session_count,
              now()::text as generated_at
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().one()
    overview = {key: int(value) if key.endswith("_count") else value for key, value in dict(row).items()}
    overview["active_job_count"] = (
        overview["queued_job_count"] + overview["running_job_count"] + overview["retry_waiting_job_count"]
    )
    overview["health_level"] = _debug_center_health_level(overview)
    overview["mode"] = "debug_mode"
    return overview


def _debug_center_failed_jobs(db: Session, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            select {_background_job_select_columns()}
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and status = 'failed'
            order by updated_at desc
            limit :limit
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "limit": limit},
    ).mappings().all()
    return [_compact_job_for_debug_center(dict(row)) for row in rows]


def _debug_center_running_jobs(db: Session, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            select {_background_job_select_columns()}
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and status in ('queued', 'running', 'retry_waiting')
            order by priority asc, run_after asc, created_at asc
            limit :limit
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "limit": limit},
    ).mappings().all()
    return [_compact_job_for_debug_center(dict(row)) for row in rows]


def _debug_center_recent_traces(db: Session, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            select {_ai_trace_select_columns()}
            from ai_trace
            where team_id = :team_id
              and workspace_id = :workspace_id
            order by started_at desc
            limit :limit
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "limit": limit},
    ).mappings().all()
    return [_compact_trace_for_debug_center(dict(row)) for row in rows]


def _debug_center_failed_traces(db: Session, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            select {_ai_trace_select_columns()}
            from ai_trace
            where team_id = :team_id
              and workspace_id = :workspace_id
              and (status = 'failed' or error_code is not null)
            order by started_at desc
            limit :limit
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "limit": limit},
    ).mappings().all()
    return [_compact_trace_for_debug_center(dict(row)) for row in rows]


def _debug_center_recent_business_updates(db: Session, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              bu.id, bu.raw_text, bu.input_type, bu.processing_status,
              bu.created_by, bu.created_at::text as created_at, bu.metadata_json,
              (select count(*) from extracted_action a
               where a.team_id = bu.team_id and a.workspace_id = bu.workspace_id
                 and a.business_update_id = bu.id) as action_count,
              (select count(*) from extracted_action a
               where a.team_id = bu.team_id and a.workspace_id = bu.workspace_id
                 and a.business_update_id = bu.id and a.review_status = 'pending_review') as pending_action_count,
              (select count(*) from action_application_log log
               where log.team_id = bu.team_id and log.workspace_id = bu.workspace_id
                 and log.business_update_id = bu.id) as application_log_count,
              (select count(*) from background_job job
               where job.team_id = bu.team_id and job.workspace_id = bu.workspace_id
                 and job.entity_type = 'business_update' and job.entity_id = bu.id) as job_count,
              (select count(*) from background_job job
               where job.team_id = bu.team_id and job.workspace_id = bu.workspace_id
                 and job.entity_type = 'business_update' and job.entity_id = bu.id
                 and job.status = 'failed') as failed_job_count,
              (select count(*) from ai_trace trace
               where trace.team_id = bu.team_id and trace.workspace_id = bu.workspace_id
                 and trace.entity_type = 'business_update' and trace.entity_id = bu.id) as trace_count
            from business_update bu
            where bu.team_id = :team_id
              and bu.workspace_id = :workspace_id
            order by bu.created_at desc
            limit :limit
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "limit": limit},
    ).mappings().all()
    return [_compact_business_update_for_debug_center(dict(row)) for row in rows]


def _debug_center_recent_recommendation_sessions(db: Session, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              rs.id, rs.mode, rs.status, rs.selected_count, rs.report_count,
              rs.buyer_intent_id, bi.intent_name as buyer_intent_name,
              rs.buyer_party_id, bp.buyer_name,
              rs.seller_target_id, st.target_name as seller_target_name,
              rs.created_by, rs.created_at::text as created_at, rs.updated_at::text as updated_at,
              (select count(*) from background_job job
               where job.team_id = rs.team_id and job.workspace_id = rs.workspace_id
                 and (
                   job.payload_json ->> 'session_id' = rs.id::text
                   or job.entity_id in (
                     select report.id
                     from recommendation_report report
                     where report.team_id = rs.team_id and report.workspace_id = rs.workspace_id
                       and report.session_id = rs.id
                   )
                 )) as job_count,
              (select count(*) from background_job job
               where job.team_id = rs.team_id and job.workspace_id = rs.workspace_id
                 and job.status = 'failed'
                 and (
                   job.payload_json ->> 'session_id' = rs.id::text
                   or job.entity_id in (
                     select report.id
                     from recommendation_report report
                     where report.team_id = rs.team_id and report.workspace_id = rs.workspace_id
                       and report.session_id = rs.id
                   )
                 )) as failed_job_count,
              (select count(*) from ai_trace trace
               where trace.team_id = rs.team_id and trace.workspace_id = rs.workspace_id
                 and (
                   trace.input_json ->> 'session_id' = rs.id::text
                   or trace.entity_id in (
                     select report.id
                     from recommendation_report report
                     where report.team_id = rs.team_id and report.workspace_id = rs.workspace_id
                       and report.session_id = rs.id
                   )
                 )) as trace_count
            from recommendation_session rs
            left join buyer_intent bi on bi.id = rs.buyer_intent_id
            left join buyer_party bp on bp.id = rs.buyer_party_id
            left join seller_target st on st.id = rs.seller_target_id
            where rs.team_id = :team_id
              and rs.workspace_id = :workspace_id
            order by rs.updated_at desc, rs.created_at desc
            limit :limit
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "limit": limit},
    ).mappings().all()
    return [_compact_recommendation_session_for_debug_center(dict(row)) for row in rows]


def _debug_center_model_node_test_failures(db: Session, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            select
              {_background_job_select_columns("job")},
              node.id as node_id, node.node_name, node.node_type, node.model_name,
              provider.provider_name, provider.provider_type
            from background_job job
            left join model_node_config node
              on node.id = job.entity_id
             and job.entity_type = 'model_node_config'
             and node.team_id = job.team_id
             and node.workspace_id = job.workspace_id
            left join model_provider_config provider on provider.id = node.provider_config_id
            where job.team_id = :team_id
              and job.workspace_id = :workspace_id
              and job.job_type = 'model_node_test'
              and job.status = 'failed'
            order by job.updated_at desc
            limit :limit
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "limit": limit},
    ).mappings().all()
    return [_compact_model_node_test_failure_for_debug_center(dict(row)) for row in rows]


def _debug_center_health_level(overview: dict[str, Any]) -> str:
    if overview.get("failed_job_count", 0) or overview.get("failed_trace_count", 0):
        return "error"
    if overview.get("retry_waiting_job_count", 0) or overview.get("active_job_count", 0):
        return "warning"
    return "ok"


def _debug_center_quick_actions(overview: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "key": "view_failed_jobs",
            "label": "查看失败任务",
            "route": "/debug?tab=failed_jobs",
            "action": "filter_failed_jobs",
            "badge_count": overview.get("failed_job_count"),
        },
        {
            "key": "view_failed_traces",
            "label": "查看失败 Trace",
            "route": "/debug?tab=failed_traces",
            "action": "filter_failed_traces",
            "badge_count": overview.get("failed_trace_count"),
        },
        {
            "key": "view_model_node_tests",
            "label": "查看模型测试",
            "route": "/settings?section=models",
            "action": "open_model_node_tests",
            "badge_count": overview.get("failed_model_node_test_count"),
        },
        {
            "key": "open_workbench",
            "label": "返回工作台",
            "route": "/workbench",
            "action": "open_workbench",
            "badge_count": overview.get("active_job_count"),
        },
    ]


def _compact_job_for_debug_center(job: dict[str, Any]) -> dict[str, Any]:
    entity_type = job.get("entity_type")
    entity_id = job.get("entity_id")
    return {
        "id": job["id"],
        "title": f"{job.get('job_type')} / {job.get('queue_name')}",
        "job_type": job.get("job_type"),
        "status": job.get("status"),
        "queue_name": job.get("queue_name"),
        "priority": job.get("priority"),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "error_code": job.get("error_code"),
        "error_message": _truncate_debug_text(job.get("error_message"), 240),
        "attempt_count": job.get("attempt_count"),
        "max_attempts": job.get("max_attempts"),
        "run_after": job.get("run_after"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "debug_ref": _debug_ref("background_job", job["id"]),
        "related_entity_ref": _debug_ref(entity_type, entity_id) if entity_type and entity_id else None,
    }


def _compact_trace_for_debug_center(trace: dict[str, Any]) -> dict[str, Any]:
    job_id = trace.get("job_id")
    entity_type = trace.get("entity_type")
    entity_id = trace.get("entity_id")
    return {
        "id": trace["id"],
        "title": f"{trace.get('node_name')} / {trace.get('trace_type')}",
        "trace_type": trace.get("trace_type"),
        "node_name": trace.get("node_name"),
        "status": trace.get("status"),
        "provider_name": trace.get("provider_name"),
        "model_name": trace.get("model_name"),
        "prompt_version": trace.get("prompt_version"),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "job_id": job_id,
        "error_code": trace.get("error_code"),
        "error_message": _truncate_debug_text(trace.get("error_message"), 240),
        "raw_output_preview": _truncate_debug_text(trace.get("raw_output_text"), 240),
        "latency_ms": trace.get("latency_ms"),
        "prompt_tokens": trace.get("prompt_tokens"),
        "completion_tokens": trace.get("completion_tokens"),
        "total_tokens": trace.get("total_tokens"),
        "started_at": trace.get("started_at"),
        "finished_at": trace.get("finished_at"),
        "debug_ref": _debug_ref("background_job", job_id) if job_id else None,
        "related_entity_ref": _debug_ref(entity_type, entity_id) if entity_type and entity_id else None,
    }


def _compact_business_update_for_debug_center(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": _truncate_debug_text(row.get("raw_text"), 80) or "业务更新",
        "raw_text_preview": _truncate_debug_text(row.get("raw_text"), 240),
        "input_type": row.get("input_type"),
        "processing_status": row.get("processing_status"),
        "action_count": int(row.get("action_count") or 0),
        "pending_action_count": int(row.get("pending_action_count") or 0),
        "application_log_count": int(row.get("application_log_count") or 0),
        "job_count": int(row.get("job_count") or 0),
        "failed_job_count": int(row.get("failed_job_count") or 0),
        "trace_count": int(row.get("trace_count") or 0),
        "created_at": row.get("created_at"),
        "review_route": f"/updates/{row['id']}",
        "debug_ref": _debug_ref("business_update", row["id"]),
    }


def _compact_recommendation_session_for_debug_center(row: dict[str, Any]) -> dict[str, Any]:
    title_parts = [
        row.get("buyer_intent_name") or row.get("buyer_name"),
        row.get("seller_target_name"),
    ]
    title = " × ".join([part for part in title_parts if part]) or f"推荐会话 {row['id']}"
    return {
        "id": row["id"],
        "title": _truncate_debug_text(title, 100),
        "mode": row.get("mode"),
        "status": row.get("status"),
        "selected_count": int(row.get("selected_count") or 0),
        "report_count": int(row.get("report_count") or 0),
        "job_count": int(row.get("job_count") or 0),
        "failed_job_count": int(row.get("failed_job_count") or 0),
        "trace_count": int(row.get("trace_count") or 0),
        "buyer_intent_id": row.get("buyer_intent_id"),
        "buyer_intent_name": row.get("buyer_intent_name"),
        "buyer_party_id": row.get("buyer_party_id"),
        "buyer_name": row.get("buyer_name"),
        "seller_target_id": row.get("seller_target_id"),
        "seller_target_name": row.get("seller_target_name"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "status_route": f"/recommendations/sessions/{row['id']}",
        "debug_ref": _debug_ref("recommendation_session", row["id"]),
    }


def _compact_model_node_test_failure_for_debug_center(row: dict[str, Any]) -> dict[str, Any]:
    item = _compact_job_for_debug_center(row)
    item.update(
        {
            "node_id": row.get("node_id"),
            "node_name": row.get("node_name"),
            "node_type": row.get("node_type"),
            "model_name": row.get("model_name"),
            "provider_name": row.get("provider_name"),
            "provider_type": row.get("provider_type"),
            "node_debug_ref": _debug_ref("model_node_config", row["node_id"]) if row.get("node_id") else None,
        }
    )
    return item


def _debug_ref(entity_type: str | None, entity_id: Any) -> dict[str, Any] | None:
    if not entity_type or entity_id is None:
        return None
    entity_id_text = str(entity_id)
    return {
        "entity_type": entity_type,
        "entity_id": entity_id_text,
        "route": f"/debug/entities/{entity_type}/{entity_id_text}",
    }


def _truncate_debug_text(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    if len(text_value) <= max_length:
        return text_value
    return text_value[: max_length - 1] + "…"


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
