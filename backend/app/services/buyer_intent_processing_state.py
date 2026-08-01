from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.registry.nodes import buyer_parse_node_names

ACTIVE_JOB_STATUSES = {"queued", "running", "retry_waiting"}
FAILED_JOB_STATUSES = {"failed", "canceled", "cancelled"}


def buyer_intent_processing_states(
    db: Session,
    intents: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Load page/detail processing states in bounded bulk queries, never per intent."""
    if not intents:
        return {}
    intent_ids = [UUID(str(item["id"])) for item in intents]
    id_texts = [str(item) for item in intent_ids]
    params = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "intent_ids": tuple(id_texts),
    }

    updates = db.execute(
        text(
            """
            select distinct on (bound.intent_id_text)
              bound.intent_id_text, bu.id, bu.processing_status, bu.raw_text,
              bu.metadata_json, bu.created_at::text as created_at,
              latest_job.id as latest_job_id, latest_job.status as latest_job_status,
              latest_job.job_type as latest_job_type,
              latest_job.error_code as latest_job_error_code,
              latest_job.error_message as latest_job_error_message,
              latest_job.created_at::text as latest_job_created_at,
              latest_job.started_at::text as latest_job_started_at,
              latest_job.finished_at::text as latest_job_finished_at,
              latest_job.metadata_json as latest_job_metadata_json
            from business_update bu
            cross join lateral jsonb_array_elements_text(bu.bound_buyer_intent_ids_json)
              as bound(intent_id_text)
            left join lateral (
              select bj.*
              from background_job bj
              where bj.team_id = bu.team_id
                and bj.workspace_id = bu.workspace_id
                and (
                  (bj.entity_type = 'business_update' and bj.entity_id = bu.id)
                  or bj.payload_json ->> 'business_update_id' = bu.id::text
                )
              order by bj.created_at desc
              limit 1
            ) latest_job on true
            where bu.team_id = :team_id
              and bu.workspace_id = :workspace_id
              and bound.intent_id_text in :intent_ids
            order by bound.intent_id_text,
              coalesce(latest_job.created_at, bu.created_at) desc,
              bu.created_at desc
            """
        ).bindparams(bindparam("intent_ids", expanding=True)),
        params,
    ).mappings().all()
    updates_by_intent = {str(row["intent_id_text"]): dict(row) for row in updates}
    update_ids = [row["id"] for row in updates]

    attachments_by_intent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if update_ids:
        attachment_rows = db.execute(
            text(
                """
                select
                  al.entity_id as business_update_id,
                  a.id, a.parse_status, a.metadata_json,
                  latest_job.id as latest_job_id,
                  latest_job.status as latest_job_status,
                  latest_job.error_code as latest_job_error_code,
                  latest_job.error_message as latest_job_error_message,
                  latest_job.created_at::text as latest_job_created_at,
                  latest_job.started_at::text as latest_job_started_at,
                  latest_job.finished_at::text as latest_job_finished_at
                from attachment_link al
                join attachment a on a.id = al.attachment_id
                left join lateral (
                  select bj.*
                  from background_job bj
                  where bj.team_id = al.team_id
                    and bj.workspace_id = al.workspace_id
                    and bj.entity_type = 'attachment'
                    and bj.entity_id = a.id
                    and bj.job_type in ('attachment_ocr_parse', 'attachment_ocr_poll')
                  order by bj.created_at desc
                  limit 1
                ) latest_job on true
                where al.team_id = :team_id
                  and al.workspace_id = :workspace_id
                  and al.entity_type = 'business_update'
                  and al.entity_id in :update_ids
                  and a.deleted_at is null
                order by al.created_at asc
                """
            ).bindparams(bindparam("update_ids", expanding=True)),
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "update_ids": tuple(update_ids),
            },
        ).mappings().all()
        intent_by_update = {str(row["id"]): str(row["intent_id_text"]) for row in updates}
        for row in attachment_rows:
            intent_id = intent_by_update.get(str(row["business_update_id"]))
            if intent_id:
                attachments_by_intent[intent_id].append(dict(row))

    parse_jobs = db.execute(
        text(
            """
            select distinct on (entity_id)
              id, entity_id, status, error_code, error_message, payload_json,
              metadata_json, result_json,
              created_at::text as created_at, started_at::text as started_at,
              finished_at::text as finished_at
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and job_type = 'buyer_intent_parse'
              and entity_type = 'buyer_intent'
              and entity_id in :entity_ids
            order by entity_id, created_at desc
            """
        ).bindparams(bindparam("entity_ids", expanding=True)),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "entity_ids": tuple(intent_ids)},
    ).mappings().all()
    parse_by_intent = {str(row["entity_id"]): dict(row) for row in parse_jobs}

    evidence_rows = db.execute(
        text(
            """
            select bi.id as entity_id,
              exists (
                select 1 from ai_trace trace
                where trace.team_id = bi.team_id and trace.workspace_id = bi.workspace_id
                  and trace.entity_type = 'buyer_intent' and trace.entity_id = bi.id
                  and trace.node_name = any(:buyer_parse_node_names)
                  and trace.status = 'succeeded'
              ) as has_success_trace,
              exists (
                select 1 from action_application_log log
                where log.team_id = bi.team_id and log.workspace_id = bi.workspace_id
                  and log.entity_type = 'buyer_intent' and log.entity_id = bi.id
                  and log.source_type = 'buyer_intent_parse'
              ) as has_parse_write,
              exists (
                select 1 from action_application_log log
                where log.team_id = bi.team_id and log.workspace_id = bi.workspace_id
                  and log.entity_type = 'buyer_intent' and log.entity_id = bi.id
                  and log.business_update_id is not null
              ) as has_business_update_write
            from buyer_intent bi
            where bi.team_id = :team_id and bi.workspace_id = :workspace_id
              and bi.id in :entity_ids
            """
        ).bindparams(bindparam("entity_ids", expanding=True)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "entity_ids": tuple(intent_ids),
            "buyer_parse_node_names": list(buyer_parse_node_names()),
        },
    ).mappings().all()
    evidence_by_intent = {str(row["entity_id"]): dict(row) for row in evidence_rows}

    return {
        str(intent["id"]): compute_buyer_intent_processing_state(
            intent=intent,
            business_update=updates_by_intent.get(str(intent["id"])),
            attachments=attachments_by_intent.get(str(intent["id"]), []),
            parse_job=parse_by_intent.get(str(intent["id"])),
            evidence=evidence_by_intent.get(str(intent["id"]), {}),
        )
        for intent in intents
    }


def compute_buyer_intent_processing_state(
    *,
    intent: dict[str, Any],
    business_update: dict[str, Any] | None,
    attachments: list[dict[str, Any]],
    parse_job: dict[str, Any] | None,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    attachment_states = [_effective_attachment_state(item) for item in attachments]
    summary = {key: 0 for key in ("pending", "processing", "succeeded", "failed", "skipped")}
    for state in attachment_states:
        summary[state] += 1
    summary["total"] = len(attachment_states)

    parse_status = str(parse_job.get("status") or "") if parse_job else ""
    parse_metadata = parse_job.get("metadata_json") if parse_job else {}
    parse_metadata = parse_metadata if isinstance(parse_metadata, dict) else {}
    parse_stage = str(parse_metadata.get("processing_stage") or "")
    update_job_status = str(business_update.get("latest_job_status") or "") if business_update else ""
    update_status = str(business_update.get("processing_status") or "") if business_update else ""
    parse_is_current = _parse_belongs_to_latest_chain(parse_job, business_update)

    active_attachment = any(state in {"pending", "processing"} for state in attachment_states)
    active_parse = parse_is_current and parse_status in ACTIVE_JOB_STATUSES
    active_update = update_job_status in ACTIVE_JOB_STATUSES
    attachment_failed = bool(attachment_states) and any(state == "failed" for state in attachment_states)
    all_attachments_failed = bool(attachment_states) and all(state == "failed" for state in attachment_states)
    parse_succeeded = parse_is_current and parse_status == "succeeded"
    update_succeeded = update_status in {"parsed", "partially_applied", "applied"}
    reliable_history = bool(
        parse_status == "succeeded"
        or evidence.get("has_success_trace")
        or evidence.get("has_parse_write")
    )

    if active_parse:
        overall = "processing"
        stage = parse_stage or ("semantic_parsing" if parse_status == "running" else "ai_queued")
    elif active_attachment:
        overall, stage = "processing", "attachment_extraction"
    elif active_update:
        overall, stage = "processing", "business_update_processing"
    elif parse_is_current and parse_status in FAILED_JOB_STATUSES:
        overall, stage = "failed", parse_stage or "ai_parse"
    elif business_update and (update_status == "failed" or update_job_status in FAILED_JOB_STATUSES):
        overall = "failed"
        stage = "attachment_extraction" if attachment_failed else "business_update_processing"
    elif all_attachments_failed:
        overall, stage = "failed", "attachment_extraction"
    elif parse_succeeded or (update_succeeded and evidence.get("has_business_update_write")):
        overall, stage = "succeeded", "completed"
    elif reliable_history:
        overall, stage = "succeeded", "completed"
    else:
        overall, stage = "not_started", None

    ai_status = _ai_parse_status(parse_job, parse_is_current)
    semantic_status, normalization_status, write_status = _stage_statuses(parse_job, parse_is_current)
    needs_count = len(intent.get("needs_confirmation_json") or [])
    review_status = (
        "reviewed" if intent.get("reviewed_at") else "needs_confirmation" if needs_count else "pending"
    )
    error_source = _latest_error_source(attachments, parse_job if parse_is_current else None, business_update)
    status_label = {
        "not_started": "未解析",
        "processing": "解析中",
        "succeeded": "已解析",
        "failed": "解析失败",
    }[overall]
    stage_label = {
        "attachment_extraction": "附件读取失败" if overall == "failed" else "正在读取附件",
        "business_update_processing": "业务更新处理失败" if overall == "failed" else "正在汇总材料",
        "ai_queued": "AI 解析排队中",
        "semantic_parsing": "语义解析中",
        "normalizing": "规范化中",
        "writing": "写入中",
        "ai_parse": "AI 需求解析失败",
        "completed": "处理完成",
    }.get(stage or "")
    return {
        "overall_status": overall,
        "current_stage": stage,
        "status_label": status_label,
        "stage_label": stage_label,
        "attachment_summary": summary,
        "attachment_warning_count": summary["failed"] if overall == "succeeded" else 0,
        "ai_parse_status": ai_status,
        "semantic_parse_status": semantic_status,
        "normalization_status": normalization_status,
        "write_status": write_status,
        "review_status": review_status,
        "needs_confirmation_count": needs_count,
        "source_business_update_id": str(business_update["id"]) if business_update else None,
        "latest_job_id": str(parse_job["id"]) if parse_job else (
            str(business_update["latest_job_id"]) if business_update and business_update.get("latest_job_id") else None
        ),
        "error_code": error_source.get("error_code") if error_source else None,
        "error_message": _short_error(error_source.get("error_message")) if error_source else None,
        "recoverable": overall == "failed",
        "started_at": (parse_job or {}).get("started_at") or (business_update or {}).get("latest_job_started_at"),
        "finished_at": (parse_job or {}).get("finished_at") or (business_update or {}).get("latest_job_finished_at"),
    }


def _effective_attachment_state(item: dict[str, Any]) -> str:
    stored = str(item.get("parse_status") or "pending")
    latest_job = str(item.get("latest_job_status") or "")
    if stored in {"pending", "parsing"} and latest_job in FAILED_JOB_STATUSES:
        return "failed"
    return {"pending": "pending", "parsing": "processing", "parsed": "succeeded", "failed": "failed", "skipped": "skipped"}.get(stored, "pending")


def _parse_belongs_to_latest_chain(parse_job: dict[str, Any] | None, update: dict[str, Any] | None) -> bool:
    if not parse_job:
        return False
    if not update:
        return True
    payload = parse_job.get("payload_json") or {}
    if str(payload.get("business_update_id") or "") == str(update.get("id") or ""):
        return True
    return _time_value(parse_job.get("created_at")) >= _time_value(update.get("created_at"))


def _ai_parse_status(job: dict[str, Any] | None, current: bool) -> str:
    if not job or not current:
        return "not_started"
    status = str(job.get("status") or "")
    stage = str((job.get("metadata_json") or {}).get("processing_stage") or "")
    if status == "queued" or status == "retry_waiting":
        return "queued"
    if status == "running":
        return stage if stage in {"semantic_parsing", "normalizing", "writing"} else "semantic_parsing"
    if status == "succeeded":
        return "succeeded"
    if status in FAILED_JOB_STATUSES:
        return "failed"
    return "not_started"


def _stage_statuses(job: dict[str, Any] | None, current: bool) -> tuple[str, str, str]:
    ai = _ai_parse_status(job, current)
    if ai == "succeeded":
        return "succeeded", "succeeded", "succeeded"
    if ai == "failed":
        metadata = (job or {}).get("metadata_json") or {}
        stage = str(metadata.get("processing_stage") or "semantic_parsing")
        return (
            "failed" if stage == "semantic_parsing" else "succeeded",
            "failed" if stage == "normalizing" else "succeeded" if stage == "writing" else "not_started",
            "failed" if stage == "writing" else "not_started",
        )
    if ai == "normalizing":
        return "succeeded", "processing", "not_started"
    if ai == "writing":
        return "succeeded", "succeeded", "processing"
    if ai in {"queued", "semantic_parsing"}:
        return "queued" if ai == "queued" else "processing", "not_started", "not_started"
    return "not_started", "not_started", "not_started"


def _latest_error_source(
    attachments: list[dict[str, Any]],
    parse_job: dict[str, Any] | None,
    update: dict[str, Any] | None,
) -> dict[str, Any] | None:
    candidates = [item for item in attachments if item.get("latest_job_error_message")]
    if parse_job and parse_job.get("error_message"):
        candidates.append(parse_job)
    if update and update.get("latest_job_error_message"):
        candidates.append({
            "error_code": update.get("latest_job_error_code"),
            "error_message": update.get("latest_job_error_message"),
            "created_at": update.get("latest_job_created_at"),
        })
    return max(candidates, key=lambda item: _time_value(item.get("latest_job_created_at") or item.get("created_at")), default=None)


def _time_value(value: Any) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _short_error(value: Any, limit: int = 500) -> str | None:
    if value is None:
        return None
    compact = " ".join(str(value).split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"
