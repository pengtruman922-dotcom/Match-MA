"""买家主体灌入链的处理状态，**从 job 表派生，不加状态列**。

照买家需求那份（``buyer_intent_processing_state.py``）的做法，而不是标的侧的
``seller_target.information_status``：那个方案有「任务挂了但状态位没释放」的
僵死态，需要 ``repair-stuck`` 工具去修。派生态没有这个问题 —— job 失败了，
派生出来的状态当场就是失败。

一次点击是三个 job（解析 / 调研 / 规范化），它们共用一个 ``correlation_id``。
这里按最近一条链聚合，前端据此把三段显示成一条进度。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.jobs.handlers.buyer_party_ingest import (
    NORMALIZE_JOB_TYPE,
    PARSE_JOB_TYPE,
    RESEARCH_JOB_TYPE,
    buyer_party_refresh_targets,
)

ACTIVE_JOB_STATUSES = frozenset({"queued", "running", "retry_waiting"})
FAILED_JOB_STATUSES = frozenset({"failed", "canceled", "cancelled"})

INGEST_JOB_TYPES = (PARSE_JOB_TYPE, RESEARCH_JOB_TYPE, NORMALIZE_JOB_TYPE)
_STAGE_BY_JOB_TYPE = {
    PARSE_JOB_TYPE: "parse",
    RESEARCH_JOB_TYPE: "research",
    NORMALIZE_JOB_TYPE: "normalize",
}

STATUS_LABELS = {
    "not_started": "未补全",
    "processing": "补全中",
    "succeeded": "已补全",
    "failed": "补全失败",
}

# 「跑完了」和「补到了」是两件事。任务成功但一个字段都没写时说「已补全」，
# 界面就在说反话 —— 顾问看到绿标以为好了，实际上什么都没变。
SUCCEEDED_WITHOUT_RESULT_LABELS = {
    "subject_unresolved": "未能确认主体",
    "no_public_information": "没查到可用信息",
}
EMPTY_RESULT_LABEL = "没有可写入的信息"

STAGE_LABELS = {
    "attachment_extraction": "正在读取附件",
    "parsing": "解析材料中",
    "researching": "联网调研中（约 5–10 分钟）",
    "normalizing": "整理结果中",
    "completed": "处理完成",
}

RESEARCH_OUTCOME_LABELS = {
    "found": "已找到公开信息",
    "no_public_information": "没查到可用的公开信息",
    # 脱敏名、重名、查无此公司。没有这个终态，agent 会对同一个买家反复空跑。
    "subject_unresolved": "无法确认这家公司",
    "failed": "调研失败",
}


def buyer_party_ingest_state(db: Session, buyer_party_id: UUID) -> dict[str, Any]:
    party = db.execute(
        text(
            """
            select id, listed_status, market_cap_as_of::text as market_cap_as_of,
                   financial_period_label
            from buyer_party
            where id = :party_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "party_id": buyer_party_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    stale_fields = buyer_party_refresh_targets(dict(party or {}))
    pending_proposals = _pending_proposal_count(db, buyer_party_id)

    latest = _latest_ingest_job(db, buyer_party_id)
    if latest is None:
        return _empty_state(
            buyer_party_id,
            stale_fields=stale_fields,
            pending_proposals=pending_proposals,
        )
    correlation_id = latest["correlation_id"] or latest["id"]
    jobs = _jobs_in_run(db, buyer_party_id, correlation_id)
    by_stage = {_STAGE_BY_JOB_TYPE[row["job_type"]]: row for row in jobs}

    stages = {stage: _stage_state(by_stage.get(stage)) for stage in ("parse", "research", "normalize")}
    parse_payload = (by_stage.get("parse") or {}).get("payload_json") or {}
    research_enabled = bool(parse_payload.get("enable_research")) or "research" in by_stage
    if not research_enabled and stages["research"]["status"] == "not_started":
        stages["research"]["status"] = "skipped"
    if "parse" not in by_stage:
        # 没有材料时整段跳过解析，直接调研。
        stages["parse"]["status"] = "skipped"

    active_stage = next(
        (stage for stage in ("parse", "research", "normalize") if stages[stage]["status"] in {"queued", "processing"}),
        None,
    )
    failed_stage = next(
        (stage for stage in ("normalize", "research", "parse") if stages[stage]["status"] == "failed"),
        None,
    )
    if active_stage:
        overall = "processing"
        current_stage = _active_stage_label_key(active_stage, by_stage.get(active_stage))
    elif stages["normalize"]["status"] == "succeeded":
        overall, current_stage = "succeeded", "completed"
    elif failed_stage:
        overall = "failed"
        current_stage = _active_stage_label_key(failed_stage, by_stage.get(failed_stage))
    elif stages["parse"]["status"] == "succeeded" or stages["research"]["status"] == "succeeded":
        # 三段都跑完但没有归一：调研判定主体无法确认且没有材料时会这样收口。
        overall, current_stage = "succeeded", "completed"
    else:
        overall, current_stage = "not_started", None

    normalize_result = (by_stage.get("normalize") or {}).get("result_json") or {}
    research_result = (by_stage.get("research") or {}).get("result_json") or {}
    parse_result = (by_stage.get("parse") or {}).get("result_json") or {}
    error_source = _error_source(by_stage, failed_stage)
    written_count = (normalize_result.get("auto_accepted_count") or 0) + (
        normalize_result.get("pending_review_count") or 0
    )
    status_label = _status_label(
        overall,
        research_outcome=str(research_result.get("research_outcome") or ""),
        written_count=written_count,
        normalize_finished=stages["normalize"]["status"] == "succeeded",
    )
    return {
        "buyer_party_id": str(buyer_party_id),
        "correlation_id": str(correlation_id),
        "overall_status": overall,
        "current_stage": current_stage,
        "status_label": status_label,
        "stage_label": STAGE_LABELS.get(current_stage or ""),
        "stages": stages,
        "mode": str(parse_payload.get("mode") or research_result.get("mode") or "fill"),
        "research_enabled": research_enabled,
        "research_outcome": research_result.get("research_outcome"),
        "research_outcome_label": RESEARCH_OUTCOME_LABELS.get(
            str(research_result.get("research_outcome") or "")
        ),
        # 缺口即使没勾选调研也产出并落库，顾问以后能一键「去补全」。
        "information_gaps": normalize_result.get("information_gaps")
        or parse_result.get("information_gaps")
        or [],
        # 顾问拍 20 页年报只有 5 页进上下文，而且不会报错 —— 所以被丢掉的每一张
        # 都要一路带回界面上。
        "skipped_images": parse_result.get("skipped_images") or [],
        "material_text_truncated": bool(parse_result.get("material_text_truncated")),
        "waiting_attachment_ids": _waiting_attachment_ids(by_stage.get("parse")),
        "auto_accepted_count": normalize_result.get("auto_accepted_count"),
        "pending_review_count": normalize_result.get("pending_review_count"),
        "apply_errors": normalize_result.get("apply_errors") or [],
        # 单来源时收口不调模型：没有可调和的冲突，再翻译一次只会多一次改写机会。
        "normalizer_invoked": normalize_result.get("normalizer_invoked"),
        "written_count": written_count,
        "pending_proposal_count": pending_proposals,
        "stale_financial_fields": stale_fields,
        "latest_job_id": str(latest["id"]),
        "error_code": (error_source or {}).get("error_code"),
        "error_message": _short_error((error_source or {}).get("error_message")),
        "recoverable": overall == "failed",
        "started_at": (by_stage.get("parse") or by_stage.get("research") or {}).get("created_at"),
        "finished_at": (by_stage.get("normalize") or {}).get("finished_at"),
    }


def _status_label(
    overall: str,
    *,
    research_outcome: str,
    written_count: int,
    normalize_finished: bool,
) -> str:
    if overall != "succeeded":
        return STATUS_LABELS[overall]
    if written_count:
        return STATUS_LABELS["succeeded"]
    if research_outcome in SUCCEEDED_WITHOUT_RESULT_LABELS:
        return SUCCEEDED_WITHOUT_RESULT_LABELS[research_outcome]
    return EMPTY_RESULT_LABEL if normalize_finished else STATUS_LABELS["succeeded"]


def _empty_state(
    buyer_party_id: UUID,
    *,
    stale_fields: list[str],
    pending_proposals: int,
) -> dict[str, Any]:
    return {
        "buyer_party_id": str(buyer_party_id),
        "correlation_id": None,
        "overall_status": "not_started",
        "current_stage": None,
        "status_label": STATUS_LABELS["not_started"],
        "stage_label": None,
        "stages": {
            stage: {"status": "not_started", "job_id": None, "started_at": None, "finished_at": None}
            for stage in ("parse", "research", "normalize")
        },
        "mode": "fill",
        "research_enabled": False,
        "research_outcome": None,
        "research_outcome_label": None,
        "information_gaps": [],
        "skipped_images": [],
        "material_text_truncated": False,
        "waiting_attachment_ids": [],
        "auto_accepted_count": None,
        "pending_review_count": None,
        "apply_errors": [],
        "pending_proposal_count": pending_proposals,
        "stale_financial_fields": stale_fields,
        "latest_job_id": None,
        "error_code": None,
        "error_message": None,
        "recoverable": False,
        "started_at": None,
        "finished_at": None,
    }


def _latest_ingest_job(db: Session, buyer_party_id: UUID) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select id, job_type, status, correlation_id
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = 'buyer_party'
              and entity_id = :party_id
              and job_type in :job_types
            order by created_at desc
            limit 1
            """
        ).bindparams(bindparam("job_types", expanding=True)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "party_id": buyer_party_id,
            "job_types": tuple(INGEST_JOB_TYPES),
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _jobs_in_run(db: Session, buyer_party_id: UUID, correlation_id: Any) -> list[dict[str, Any]]:
    """一条链里每段取最新一个。

    解析在等附件时会把自己往后排一档（后继 job 同 type、同 correlation），
    所以「最新那个」才是当前状态。
    """
    rows = db.execute(
        text(
            """
            select distinct on (job_type)
              id, job_type, status, error_code, error_message,
              payload_json, metadata_json, result_json,
              created_at::text as created_at,
              started_at::text as started_at,
              finished_at::text as finished_at
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = 'buyer_party'
              and entity_id = :party_id
              and job_type in :job_types
              and (correlation_id = :correlation_id or id = :correlation_id)
            order by job_type, created_at desc
            """
        ).bindparams(bindparam("job_types", expanding=True)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "party_id": buyer_party_id,
            "job_types": tuple(INGEST_JOB_TYPES),
            "correlation_id": correlation_id,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _stage_state(job: dict[str, Any] | None) -> dict[str, Any]:
    if job is None:
        return {"status": "not_started", "job_id": None, "started_at": None, "finished_at": None}
    status = str(job.get("status") or "")
    if status in {"queued", "retry_waiting"}:
        stage_status = "queued"
    elif status == "running":
        stage_status = "processing"
    elif status == "succeeded":
        stage_status = "succeeded"
    elif status in FAILED_JOB_STATUSES:
        stage_status = "failed"
    else:
        stage_status = "not_started"
    return {
        "status": stage_status,
        "job_id": str(job["id"]),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "error_code": job.get("error_code"),
        "error_message": _short_error(job.get("error_message")),
    }


def _active_stage_label_key(stage: str, job: dict[str, Any] | None) -> str:
    if stage == "parse" and _waiting_attachment_ids(job):
        return "attachment_extraction"
    return {"parse": "parsing", "research": "researching", "normalize": "normalizing"}[stage]


def _waiting_attachment_ids(job: dict[str, Any] | None) -> list[str]:
    metadata = (job or {}).get("metadata_json")
    if not isinstance(metadata, dict):
        return []
    if str(metadata.get("source") or "") != "buyer_party_parse_material_wait":
        return []
    return [str(item) for item in (metadata.get("waiting_attachment_ids") or [])]


def _error_source(by_stage: dict[str, dict[str, Any]], failed_stage: str | None) -> dict[str, Any] | None:
    if failed_stage is None:
        return None
    job = by_stage.get(failed_stage) or {}
    return {"error_code": job.get("error_code"), "error_message": job.get("error_message")}


def _pending_proposal_count(db: Session, buyer_party_id: UUID) -> int:
    return int(
        db.execute(
            text(
                """
                select count(*)
                from research_proposal
                where team_id = :team_id
                  and workspace_id = :workspace_id
                  and entity_type = 'buyer_party'
                  and entity_id = :party_id
                  and review_status = 'pending_review'
                  and deleted_at is null
                """
            ),
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "party_id": buyer_party_id,
            },
        ).scalar_one()
        or 0
    )


def _short_error(value: Any, limit: int = 500) -> str | None:
    if value is None:
        return None
    compact = " ".join(str(value).split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"
