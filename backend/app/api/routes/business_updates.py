import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser, require_admin
from backend.app.api.routes.utils import (
    business_update_visible_sql,
    ensure_business_update_visible,
    ensure_entity_writable,
    owner_scope_required,
)
from backend.app.config import get_settings
from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db
from backend.app.services.attachment_storage import (
    AttachmentStorageError,
    AttachmentTooLargeError,
    save_upload_file,
)
from backend.app.services.image_inputs import is_supported_multimodal_image, multimodal_image_constraints
from backend.app.services.business_update_flow import (  # noqa: F401 - re-exported for compatibility
    ACTION_LABELS,
    APPLY_SUPPORTED_ACTION_TYPES,
    ATTACHMENT_PARSE_ENTITY_TYPES,
    ATTACHMENT_VISIBILITY_VALUES,
    BUSINESS_UPDATE_INPUT_TYPES,
    REVIEW_GROUP_LABELS,
    REVIEW_STATUS_LABELS,
    _action_change_preview,
    _action_target_display,
    _action_target_ref,
    _append_ingest_metadata,
    _bound_attachment_link_targets,
    _buyer_intents_by_ids,
    _buyer_parties_by_ids,
    _clean_optional_text,
    _collect_entity_ids,
    _compact_log_evidence,
    _compact_review_attachment,
    _compact_review_job,
    _compact_review_trace,
    _compact_sample_attachment,
    _compact_sample_failed_job,
    _compact_sample_run,
    _debug_ref,
    _enqueue_attachment_ocr_job,
    _enqueue_business_update_process_job,
    _enrich_application_log,
    _enrich_review_action,
    _ensure_attachment_exists,
    _ensure_bound_entities_writable,
    _ensure_business_update_exists,
    _entity_ref,
    _history_route,
    _insert_business_update_row,
    _job_failure_ignored,
    _json_safe_value,
    _latest_active_business_update_process_job,
    _latest_active_ocr_job,
    _link_attachment_if_missing,
    _logs_by_action,
    _mark_attachment_parsing,
    _mark_bound_seller_targets_parsing,
    _mark_business_update_processing,
    _metadata_truthy,
    _optional_float,
    _optional_int,
    _optional_uuid,
    _parse_entity_types_form,
    _parse_metadata_json_form,
    _parse_uuid_list_form,
    _patch_business_update_attachment_ingest_metadata,
    _recommendation_session_summary,
    _relations_by_ids,
    _review_action_group_key,
    _review_action_groups,
    _review_action_priority,
    _review_attachment_available_text,
    _review_attachment_is_binary_or_document,
    _review_attachment_parse_readiness,
    _review_page_actions,
    _review_page_application_logs,
    _review_page_attachments,
    _review_page_bound_entities,
    _review_page_jobs,
    _review_page_overview,
    _review_page_quick_actions,
    _review_page_traces,
    _review_target_snapshots,
    _save_business_update_upload_files,
    _seller_targets_by_ids,
    _should_auto_ocr_uploaded_attachment,
    _target_snapshot_key,
    _truncate_review_text,
    _unique_uuid_list,
    _upload_ocr_policy,
    _uuid_list,
    _validate_business_update_input_type,
    _validate_parse_entity_types,
)

router = APIRouter(prefix="/business-updates", tags=["business-updates"])


class BusinessUpdateAttachmentCreate(BaseModel):
    file_name: str = Field(min_length=1, max_length=500)
    storage_path: str = Field(min_length=1, max_length=2000)
    visibility: str = "workspace"
    file_type: str | None = Field(default=None, max_length=80)
    mime_type: str | None = Field(default=None, max_length=200)
    file_size: int | None = Field(default=None, ge=0)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    mock_extracted_text: str | None = Field(default=None, max_length=200000)
    link_type: str = Field(default="source_document", max_length=80)
    link_to_bound_objects: bool = True


class BusinessUpdateCreate(BaseModel):
    raw_text: str = Field(min_length=1)
    input_type: str = "text"
    bound_seller_target_ids: list[UUID] = Field(default_factory=list)
    bound_buyer_party_ids: list[UUID] = Field(default_factory=list)
    bound_buyer_intent_ids: list[UUID] = Field(default_factory=list)
    attachment_ids: list[UUID] = Field(default_factory=list)
    attachments: list[BusinessUpdateAttachmentCreate] = Field(default_factory=list)
    auto_start_ocr: bool = False
    auto_process: bool = False
    process_after_ocr: bool = True
    include_attachment_text: bool = True
    auto_parse_linked_objects: bool = False
    parse_entity_types: list[str] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class BusinessUpdateOut(BaseModel):
    id: UUID
    raw_text: str | None
    input_type: str
    processing_status: str
    bound_seller_target_ids_json: list[Any]
    bound_buyer_party_ids_json: list[Any]
    bound_buyer_intent_ids_json: list[Any]
    bound_recommendation_session_id: UUID | None
    created_by: UUID | None
    created_at: str
    metadata_json: dict[str, Any]


class BusinessUpdateProcessOut(BaseModel):
    job_id: UUID
    job_type: str
    status: str
    queue_name: str
    business_update_id: UUID


class BusinessUpdateProcessRequest(BaseModel):
    include_attachment_text: bool = True


class BusinessUpdateAttachmentIngest(BaseModel):
    attachment_ids: list[UUID] = Field(default_factory=list)
    attachments: list[BusinessUpdateAttachmentCreate] = Field(default_factory=list)
    auto_start_ocr: bool = False
    process_after_ocr: bool = True
    include_attachment_text: bool = True
    auto_parse_linked_objects: bool = False
    parse_entity_types: list[str] = Field(default_factory=list)


class BusinessUpdateAttachmentIngestOut(BaseModel):
    business_update_id: UUID
    linked_attachment_ids: list[UUID]
    created_attachment_ids: list[UUID]
    ocr_jobs: list[dict[str, Any]]
    process_job: dict[str, Any] | None = None


class BusinessUpdateUploadOut(BaseModel):
    business_update: BusinessUpdateOut
    uploaded_attachment_ids: list[UUID]
    ocr_attachment_ids: list[UUID]
    multimodal_image_attachment_ids: list[UUID]
    skipped_ocr_attachment_ids: list[UUID]
    ocr_jobs: list[dict[str, Any]]
    process_job: dict[str, Any] | None = None


class BusinessUpdateReviewPageOut(BaseModel):
    business_update: dict[str, Any]
    overview: dict[str, Any]
    action_groups: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    application_logs: list[dict[str, Any]]
    jobs: list[dict[str, Any]]
    traces: list[dict[str, Any]]
    attachments: list[dict[str, Any]]
    bound_entities: dict[str, Any]
    quick_actions: list[dict[str, Any]]
    debug_ref: dict[str, Any]


class BusinessUpdateSampleRunsOut(BaseModel):
    generated_at: str
    lookback_hours: int
    limit: int
    include_all: bool
    sample_label: str | None
    total_count: int
    runs: list[dict[str, Any]]
    debug_ref: dict[str, Any]


@router.post("", response_model=BusinessUpdateOut, status_code=status.HTTP_201_CREATED)
def create_business_update(
    payload: BusinessUpdateCreate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _validate_business_update_input_type(payload.input_type)
    _ensure_bound_entities_writable(
        db,
        current_user,
        seller_target_ids=payload.bound_seller_target_ids,
        buyer_party_ids=payload.bound_buyer_party_ids,
        buyer_intent_ids=payload.bound_buyer_intent_ids,
    )
    statement = text(
        """
        insert into business_update (
          team_id, workspace_id, raw_text, input_type, processing_status,
          bound_seller_target_ids_json, bound_buyer_party_ids_json, bound_buyer_intent_ids_json,
          created_by, metadata_json
        )
        values (
          :team_id, :workspace_id, :raw_text, :input_type, 'pending',
          :bound_seller_target_ids_json, :bound_buyer_party_ids_json, :bound_buyer_intent_ids_json,
          :created_by, :metadata_json
        )
        returning
          id, raw_text, input_type, processing_status,
          bound_seller_target_ids_json, bound_buyer_party_ids_json, bound_buyer_intent_ids_json,
          bound_recommendation_session_id, created_by,
          created_at::text as created_at, metadata_json
        """
    ).bindparams(
        bindparam("bound_seller_target_ids_json", type_=JSONB),
        bindparam("bound_buyer_party_ids_json", type_=JSONB),
        bindparam("bound_buyer_intent_ids_json", type_=JSONB),
        bindparam("metadata_json", type_=JSONB),
    )

    row = db.execute(
        statement,
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "raw_text": payload.raw_text,
            "input_type": payload.input_type,
            "bound_seller_target_ids_json": [str(item) for item in payload.bound_seller_target_ids],
            "bound_buyer_party_ids_json": [str(item) for item in payload.bound_buyer_party_ids],
            "bound_buyer_intent_ids_json": [str(item) for item in payload.bound_buyer_intent_ids],
            "created_by": current_user.user_id,
            "metadata_json": payload.metadata_json,
        },
    ).mappings().one()
    follow_up = _ingest_business_update_attachments(
        db,
        business_update_id=row["id"],
        attachment_ids=payload.attachment_ids,
        attachments=payload.attachments,
        bound_seller_target_ids=payload.bound_seller_target_ids,
        bound_buyer_party_ids=payload.bound_buyer_party_ids,
        bound_buyer_intent_ids=payload.bound_buyer_intent_ids,
        auto_start_ocr=payload.auto_start_ocr,
        process_after_ocr=payload.process_after_ocr,
        include_attachment_text=payload.include_attachment_text,
        auto_parse_linked_objects=payload.auto_parse_linked_objects,
        parse_entity_types=payload.parse_entity_types,
    )
    defer_process_for_ocr = bool(follow_up["ocr_jobs"]) and payload.process_after_ocr
    if payload.auto_process and not defer_process_for_ocr and not follow_up["process_job"]:
        follow_up["process_job"] = _enqueue_business_update_process_job(
            db,
            business_update_id=row["id"],
            include_attachment_text=payload.include_attachment_text,
            source="business_update_create_auto_process",
        )
    if follow_up["process_job"] or defer_process_for_ocr:
        _mark_business_update_processing(db, row["id"])
        row = {**dict(row), "processing_status": "processing"}
    db.commit()
    return _append_ingest_metadata(dict(row), follow_up)


@router.post("/upload", response_model=BusinessUpdateUploadOut, status_code=status.HTTP_201_CREATED)
def upload_business_update(
    current_user: CurrentUser,
    raw_text: str = Form(..., min_length=1),
    input_type: str = Form(default="mixed"),
    files: list[UploadFile] | None = File(default=None),
    bound_seller_target_ids: str | None = Form(default=None),
    bound_buyer_party_ids: str | None = Form(default=None),
    bound_buyer_intent_ids: str | None = Form(default=None),
    auto_process: bool = Form(default=True),
    process_after_ocr: bool = Form(default=True),
    include_attachment_text: bool = Form(default=True),
    auto_parse_linked_objects: bool = Form(default=False),
    parse_entity_types: str | None = Form(default=None),
    metadata_json: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _validate_business_update_input_type(input_type)
    parse_types = _parse_entity_types_form(parse_entity_types)
    _validate_parse_entity_types(parse_types)
    seller_target_ids = _parse_uuid_list_form(bound_seller_target_ids)
    buyer_party_ids = _parse_uuid_list_form(bound_buyer_party_ids)
    buyer_intent_ids = _parse_uuid_list_form(bound_buyer_intent_ids)
    _ensure_bound_entities_writable(
        db,
        current_user,
        seller_target_ids=seller_target_ids,
        buyer_party_ids=buyer_party_ids,
        buyer_intent_ids=buyer_intent_ids,
    )
    form_metadata = _parse_metadata_json_form(metadata_json)
    settings = get_settings()

    row = _insert_business_update_row(
        db,
        raw_text=raw_text,
        input_type=input_type,
        bound_seller_target_ids=seller_target_ids,
        bound_buyer_party_ids=buyer_party_ids,
        bound_buyer_intent_ids=buyer_intent_ids,
        metadata_json={
            **form_metadata,
            "source": "business_update_multipart_upload",
            "upload_mode": "mixed",
        },
        actor_user_id=current_user.user_id,
    )
    uploaded = _save_business_update_upload_files(
        db, files or [], settings=settings, actor_user_id=current_user.user_id
    )
    for attachment_id in uploaded["uploaded_attachment_ids"]:
        _link_attachment_if_missing(db, attachment_id, "business_update", row["id"], "source_document")
        for entity_type, ids in _bound_attachment_link_targets(
            seller_target_ids=seller_target_ids,
            buyer_party_ids=buyer_party_ids,
            buyer_intent_ids=buyer_intent_ids,
        ):
            for entity_id in ids:
                _link_attachment_if_missing(db, attachment_id, entity_type, entity_id, "business_update_context")

    ocr_jobs: list[dict[str, Any]] = []
    if uploaded["ocr_attachment_ids"]:
        for attachment_id in uploaded["ocr_attachment_ids"]:
            ocr_jobs.append(
                _enqueue_attachment_ocr_job(
                    db,
                    attachment_id=attachment_id,
                    business_update_id=row["id"],
                    mock_extracted_text=None,
                    auto_parse_linked_objects=auto_parse_linked_objects,
                    parse_entity_types=parse_types,
                    process_after_ocr=process_after_ocr,
                    include_attachment_text=include_attachment_text,
                )
            )

    process_job = None
    if auto_process and (not ocr_jobs or not process_after_ocr):
        process_job = _enqueue_business_update_process_job(
            db,
            business_update_id=row["id"],
            include_attachment_text=include_attachment_text,
            source="business_update_multipart_upload",
        )

    if process_job or ocr_jobs:
        _mark_business_update_processing(db, row["id"])
        row = {**row, "processing_status": "processing"}

    follow_up = {
        "linked_attachment_ids": uploaded["uploaded_attachment_ids"],
        "created_attachment_ids": uploaded["uploaded_attachment_ids"],
        "ocr_jobs": ocr_jobs,
        "process_job": process_job,
    }
    _patch_business_update_attachment_ingest_metadata(db, row["id"], follow_up)
    db.commit()
    business_update = _append_ingest_metadata(dict(row), follow_up)
    return {
        "business_update": business_update,
        "uploaded_attachment_ids": uploaded["uploaded_attachment_ids"],
        "ocr_attachment_ids": uploaded["ocr_attachment_ids"],
        "multimodal_image_attachment_ids": uploaded["multimodal_image_attachment_ids"],
        "skipped_ocr_attachment_ids": uploaded["skipped_ocr_attachment_ids"],
        "ocr_jobs": ocr_jobs,
        "process_job": process_job,
    }


@router.post("/{business_update_id}/process", response_model=BusinessUpdateProcessOut)
def process_business_update(
    business_update_id: UUID,
    current_user: CurrentUser,
    payload: BusinessUpdateProcessRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _ensure_business_update_exists(db, business_update_id)
    ensure_business_update_visible(db, current_user, business_update_id)
    request = payload or BusinessUpdateProcessRequest()
    job = _enqueue_business_update_process_job(
        db,
        business_update_id=business_update_id,
        include_attachment_text=request.include_attachment_text,
        source="api_process_endpoint",
    )
    _mark_business_update_processing(db, business_update_id)
    db.commit()
    return {
        "job_id": job["id"],
        "job_type": job["job_type"],
        "status": job["status"],
        "queue_name": job["queue_name"],
        "business_update_id": job["entity_id"],
    }


@router.post("/{business_update_id}/attachments", response_model=BusinessUpdateAttachmentIngestOut)
def add_business_update_attachments(
    business_update_id: UUID,
    payload: BusinessUpdateAttachmentIngest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    business_update = get_business_update(business_update_id, current_user, db)
    ensure_business_update_visible(db, current_user, business_update_id)
    result = _ingest_business_update_attachments(
        db,
        business_update_id=business_update_id,
        attachment_ids=payload.attachment_ids,
        attachments=payload.attachments,
        bound_seller_target_ids=_uuid_list(business_update["bound_seller_target_ids_json"]),
        bound_buyer_party_ids=_uuid_list(business_update["bound_buyer_party_ids_json"]),
        bound_buyer_intent_ids=_uuid_list(business_update["bound_buyer_intent_ids_json"]),
        auto_start_ocr=payload.auto_start_ocr,
        process_after_ocr=payload.process_after_ocr,
        include_attachment_text=payload.include_attachment_text,
        auto_parse_linked_objects=payload.auto_parse_linked_objects,
        parse_entity_types=payload.parse_entity_types,
    )
    if result["process_job"] or (result["ocr_jobs"] and payload.process_after_ocr):
        _mark_business_update_processing(db, business_update_id)
    db.commit()
    return result


@router.get("", response_model=list[BusinessUpdateOut])
def list_business_updates(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    processing_status: str | None = None,
    seller_target_id: UUID | None = None,
    buyer_intent_id: UUID | None = None,
) -> list[dict[str, Any]]:
    where = ["team_id = :team_id", "workspace_id = :workspace_id"]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
        "offset": offset,
    }
    if owner_scope_required(current_user):
        where.append(business_update_visible_sql("business_update"))
        params["scope_user_id"] = current_user.user_id

    if processing_status:
        where.append("processing_status = :processing_status")
        params["processing_status"] = processing_status
    if seller_target_id:
        where.append("bound_seller_target_ids_json ? :seller_target_id")
        params["seller_target_id"] = str(seller_target_id)
    if buyer_intent_id:
        where.append("bound_buyer_intent_ids_json ? :buyer_intent_id")
        params["buyer_intent_id"] = str(buyer_intent_id)

    rows = db.execute(
        text(
            f"""
            select
              id, raw_text, input_type, processing_status,
              bound_seller_target_ids_json, bound_buyer_party_ids_json, bound_buyer_intent_ids_json,
              bound_recommendation_session_id, created_by,
              created_at::text as created_at, metadata_json
            from business_update
            where {' and '.join(where)}
            order by created_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


@router.get("/summary/sample-runs", response_model=BusinessUpdateSampleRunsOut)
def summarize_business_update_sample_runs(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    lookback_hours: int = Query(default=720, ge=1, le=8760),
    limit: int = Query(default=50, ge=1, le=200),
    include_all: bool = False,
    sample_label: str | None = Query(default=None, max_length=200),
) -> dict[str, Any]:
    require_admin(current_user)
    generated_at = datetime.now(UTC)
    created_after = generated_at - timedelta(hours=lookback_hours)
    where = [
        "bu.team_id = :team_id",
        "bu.workspace_id = :workspace_id",
        "bu.created_at >= :created_after",
    ]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "created_after": created_after,
        "limit": limit,
    }
    if not include_all:
        where.append(
            """
            (
              lower(coalesce(bu.metadata_json ->> 'test_data', '')) in ('true', '1', 'yes')
              or lower(coalesce(bu.metadata_json ->> 'is_test_data', '')) in ('true', '1', 'yes')
            )
            """
        )
    if sample_label:
        where.append("bu.metadata_json ->> 'sample_label' = :sample_label")
        params["sample_label"] = sample_label

    rows = db.execute(
        text(
            f"""
            select
              bu.id, bu.raw_text, bu.input_type, bu.processing_status,
              bu.created_at::text as created_at, bu.metadata_json,
              (count(*) over ())::int as total_count,
              coalesce(action_stats.action_count, 0) as action_count,
              coalesce(action_stats.pending_review_count, 0) as pending_review_count,
              coalesce(action_stats.auto_applied_count, 0) as auto_applied_count,
              coalesce(action_stats.applied_action_count, 0) as applied_action_count,
              coalesce(job_stats.job_count, 0) as job_count,
              coalesce(job_stats.failed_job_count, 0) as failed_job_count,
              coalesce(job_stats.ignored_failed_job_count, 0) as ignored_failed_job_count,
              coalesce(job_stats.running_job_count, 0) as running_job_count,
              job_stats.latest_failed_job,
              coalesce(trace_stats.trace_count, 0) as trace_count,
              coalesce(trace_stats.failed_trace_count, 0) as failed_trace_count,
              coalesce(attachment_stats.attachment_count, 0) as attachment_count,
              coalesce(attachment_stats.parsed_attachment_count, 0) as parsed_attachment_count,
              coalesce(attachment_stats.multimodal_image_count, 0) as multimodal_image_count,
              coalesce(attachment_stats.parsing_attachment_count, 0) as parsing_attachment_count,
              coalesce(attachment_stats.skipped_attachment_count, 0) as skipped_attachment_count,
              coalesce(attachment_stats.failed_attachment_count, 0) as failed_attachment_count,
              coalesce(attachment_preview.attachments, '[]'::jsonb) as attachment_preview
            from business_update bu
            left join lateral (
              select
                count(*)::int as action_count,
                count(*) filter (where a.review_status = 'pending_review')::int as pending_review_count,
                count(*) filter (
                  where a.review_status = 'auto_accepted' and a.applied_at is not null
                )::int as auto_applied_count,
                count(*) filter (where a.applied_at is not null)::int as applied_action_count
              from extracted_action a
              where a.team_id = bu.team_id
                and a.workspace_id = bu.workspace_id
                and a.business_update_id = bu.id
            ) action_stats on true
            left join lateral (
              select
                count(*)::int as job_count,
                count(*) filter (
                  where bj.status = 'failed'
                    and not coalesce((bj.metadata_json ->> 'failure_ignored') = 'true', false)
                )::int as failed_job_count,
                count(*) filter (
                  where bj.status = 'failed'
                    and coalesce((bj.metadata_json ->> 'failure_ignored') = 'true', false)
                )::int as ignored_failed_job_count,
                count(*) filter (where bj.status in ('queued', 'running', 'retry_waiting'))::int as running_job_count,
                (
                  select jsonb_build_object(
                    'id', bj2.id,
                    'job_type', bj2.job_type,
                    'status', bj2.status,
                    'queue_name', bj2.queue_name,
                    'error_code', bj2.error_code,
                    'error_message', bj2.error_message,
                    'created_at', bj2.created_at::text,
                    'finished_at', bj2.finished_at::text
                  )
                  from background_job bj2
                  where bj2.team_id = bu.team_id
                    and bj2.workspace_id = bu.workspace_id
                    and (
                      (bj2.entity_type = 'business_update' and bj2.entity_id = bu.id)
                      or bj2.payload_json ->> 'business_update_id' = bu.id::text
                    )
                    and bj2.status = 'failed'
                    and not coalesce((bj2.metadata_json ->> 'failure_ignored') = 'true', false)
                  order by bj2.created_at desc
                  limit 1
                ) as latest_failed_job
              from background_job bj
              where bj.team_id = bu.team_id
                and bj.workspace_id = bu.workspace_id
                and (
                  (bj.entity_type = 'business_update' and bj.entity_id = bu.id)
                  or bj.payload_json ->> 'business_update_id' = bu.id::text
                )
            ) job_stats on true
            left join lateral (
              select
                count(*)::int as trace_count,
                count(*) filter (where trace.status = 'failed' or trace.error_code is not null)::int as failed_trace_count
              from ai_trace trace
              where trace.team_id = bu.team_id
                and trace.workspace_id = bu.workspace_id
                and (
                  (trace.entity_type = 'business_update' and trace.entity_id = bu.id)
                  or trace.job_id in (
                    select bj3.id
                    from background_job bj3
                    where bj3.team_id = bu.team_id
                      and bj3.workspace_id = bu.workspace_id
                      and (
                        (bj3.entity_type = 'business_update' and bj3.entity_id = bu.id)
                        or bj3.payload_json ->> 'business_update_id' = bu.id::text
                      )
                  )
                )
            ) trace_stats on true
            left join lateral (
              select
                count(*)::int as attachment_count,
                count(*) filter (where a.parse_status = 'parsed')::int as parsed_attachment_count,
                count(*) filter (
                  where lower(coalesce(a.file_type, '')) in ('jpg', 'jpeg', 'png', 'webp')
                    or lower(split_part(coalesce(a.mime_type, ''), ';', 1)) in ('image/jpeg', 'image/png', 'image/webp')
                )::int as multimodal_image_count,
                count(*) filter (where a.parse_status = 'parsing')::int as parsing_attachment_count,
                count(*) filter (where a.parse_status = 'skipped')::int as skipped_attachment_count,
                count(*) filter (where a.parse_status = 'failed')::int as failed_attachment_count
              from attachment_link al
              join attachment a on a.id = al.attachment_id
              where al.team_id = bu.team_id
                and al.workspace_id = bu.workspace_id
                and al.entity_type = 'business_update'
                and al.entity_id = bu.id
                and a.deleted_at is null
            ) attachment_stats on true
            left join lateral (
              select jsonb_agg(
                jsonb_build_object(
                  'id', item.id,
                  'file_name', item.file_name,
                  'file_type', item.file_type,
                  'mime_type', item.mime_type,
                  'file_size', item.file_size,
                  'parse_status', item.parse_status,
                  'linked_at', item.linked_at,
                  'parsed_document_id', item.parsed_document_id,
                  'parsed_text_length', item.parsed_text_length,
                  'multimodal_image_supported', item.multimodal_image_supported
                )
                order by item.linked_at asc
              ) as attachments
              from (
                select
                  a.id, a.file_name, a.file_type, a.mime_type, a.file_size,
                  a.parse_status, al.created_at::text as linked_at,
                  a.metadata_json ->> 'last_parsed_document_id' as parsed_document_id,
                  a.metadata_json ->> 'last_text_length' as parsed_text_length,
                  (
                    lower(coalesce(a.file_type, '')) in ('jpg', 'jpeg', 'png', 'webp')
                    or lower(split_part(coalesce(a.mime_type, ''), ';', 1)) in ('image/jpeg', 'image/png', 'image/webp')
                  ) as multimodal_image_supported
                from attachment_link al
                join attachment a on a.id = al.attachment_id
                where al.team_id = bu.team_id
                  and al.workspace_id = bu.workspace_id
                  and al.entity_type = 'business_update'
                  and al.entity_id = bu.id
                  and a.deleted_at is null
                order by al.created_at asc
                limit 20
              ) item
            ) attachment_preview on true
            where {' and '.join(where)}
            order by bu.created_at desc
            limit :limit
            """
        ),
        params,
    ).mappings().all()
    runs = [_compact_sample_run(dict(row)) for row in rows]
    total_count = int(rows[0]["total_count"]) if rows else 0
    return {
        "generated_at": generated_at.isoformat(),
        "lookback_hours": lookback_hours,
        "limit": limit,
        "include_all": include_all,
        "sample_label": sample_label,
        "total_count": total_count,
        "runs": runs,
        "debug_ref": {
            "entity_type": "business_update_sample_runs",
            "entity_id": "summary",
            "route": "/business-updates/summary/sample-runs",
        },
    }


@router.get("/{business_update_id}", response_model=BusinessUpdateOut)
def get_business_update(
    business_update_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business update not found.")

    ensure_business_update_visible(db, current_user, business_update_id)

    return dict(row)


@router.get("/{business_update_id}/review-page", response_model=BusinessUpdateReviewPageOut)
def get_business_update_review_page(
    business_update_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    business_update = get_business_update(business_update_id, current_user, db)
    actions = _review_page_actions(db, business_update_id)
    application_logs = _review_page_application_logs(db, business_update_id)
    jobs = _review_page_jobs(db, business_update_id)
    traces = _review_page_traces(db, business_update_id)
    attachments = _review_page_attachments(db, business_update_id)
    bound_entities = _review_page_bound_entities(db, business_update, actions)
    logs_by_action = _logs_by_action(application_logs)
    target_snapshots = _review_target_snapshots(bound_entities)
    enriched_actions = [
        _enrich_review_action(action, logs_by_action.get(str(action["id"]), []), target_snapshots)
        for action in actions
    ]
    overview = _review_page_overview(business_update, enriched_actions, application_logs, jobs, traces)
    return {
        "business_update": {
            **business_update,
            "raw_text_preview": _truncate_review_text(business_update.get("raw_text"), 240),
        },
        "overview": overview,
        "action_groups": _review_action_groups(enriched_actions),
        "actions": enriched_actions,
        "application_logs": application_logs,
        "jobs": [_compact_review_job(job) for job in jobs],
        "traces": [_compact_review_trace(trace) for trace in traces],
        "attachments": attachments,
        "bound_entities": bound_entities,
        "quick_actions": _review_page_quick_actions(business_update, overview),
        "debug_ref": _debug_ref("business_update", business_update_id),
    }


def _ingest_business_update_attachments(
    db: Session,
    *,
    business_update_id: UUID,
    attachment_ids: list[UUID],
    attachments: list[BusinessUpdateAttachmentCreate],
    bound_seller_target_ids: list[UUID],
    bound_buyer_party_ids: list[UUID],
    bound_buyer_intent_ids: list[UUID],
    auto_start_ocr: bool,
    process_after_ocr: bool,
    include_attachment_text: bool,
    auto_parse_linked_objects: bool,
    parse_entity_types: list[str],
) -> dict[str, Any]:
    _validate_parse_entity_types(parse_entity_types)
    created_attachment_ids = [_create_attachment_for_business_update(db, item) for item in attachments]
    linked_attachment_ids = _unique_uuid_list([*attachment_ids, *created_attachment_ids])
    for attachment_id in linked_attachment_ids:
        attachment_payload = _created_attachment_payload(attachments, created_attachment_ids, attachment_id)
        _ensure_attachment_exists(db, attachment_id)
        link_type = attachment_payload.link_type if attachment_payload else "source_document"
        _link_attachment_if_missing(db, attachment_id, "business_update", business_update_id, link_type)
        if attachment_payload is None or attachment_payload.link_to_bound_objects:
            for entity_type, ids in _bound_attachment_link_targets(
                seller_target_ids=bound_seller_target_ids,
                buyer_party_ids=bound_buyer_party_ids,
                buyer_intent_ids=bound_buyer_intent_ids,
            ):
                for entity_id in ids:
                    _link_attachment_if_missing(db, attachment_id, entity_type, entity_id, "business_update_context")

    ocr_jobs: list[dict[str, Any]] = []
    if auto_start_ocr:
        for attachment_id in linked_attachment_ids:
            attachment_payload = _created_attachment_payload(attachments, created_attachment_ids, attachment_id)
            ocr_jobs.append(
                _enqueue_attachment_ocr_job(
                    db,
                    attachment_id=attachment_id,
                    business_update_id=business_update_id,
                    mock_extracted_text=attachment_payload.mock_extracted_text if attachment_payload else None,
                    auto_parse_linked_objects=auto_parse_linked_objects,
                    parse_entity_types=parse_entity_types,
                    process_after_ocr=process_after_ocr,
                    include_attachment_text=include_attachment_text,
                )
            )

    process_job = None
    if process_after_ocr and linked_attachment_ids and not auto_start_ocr:
        process_job = _enqueue_business_update_process_job(
            db,
            business_update_id=business_update_id,
            include_attachment_text=include_attachment_text,
            source="business_update_attachment_ingest",
        )

    result = {
        "business_update_id": business_update_id,
        "linked_attachment_ids": linked_attachment_ids,
        "created_attachment_ids": created_attachment_ids,
        "ocr_jobs": ocr_jobs,
        "process_job": process_job,
    }
    _patch_business_update_attachment_ingest_metadata(db, business_update_id, result)
    return result


def _created_attachment_payload(
    attachments: list[BusinessUpdateAttachmentCreate],
    created_attachment_ids: list[UUID],
    attachment_id: UUID,
) -> BusinessUpdateAttachmentCreate | None:
    for created_id, payload in zip(created_attachment_ids, attachments, strict=False):
        if created_id == attachment_id:
            return payload
    return None


def _create_attachment_for_business_update(db: Session, payload: BusinessUpdateAttachmentCreate) -> UUID:
    if payload.visibility not in ATTACHMENT_VISIBILITY_VALUES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid visibility.")
    metadata = _json_safe_value(payload.metadata_json)
    if payload.mock_extracted_text:
        metadata["mock_extracted_text"] = payload.mock_extracted_text
    row = db.execute(
        text(
            """
            insert into attachment (
              team_id, workspace_id, visibility, file_name, file_type, mime_type,
              file_size, storage_path, uploaded_by, metadata_json
            )
            values (
              :team_id, :workspace_id, :visibility, :file_name, :file_type, :mime_type,
              :file_size, :storage_path, :uploaded_by, :metadata_json
            )
            returning id
            """
        ).bindparams(bindparam("metadata_json", type_=JSONB)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "visibility": payload.visibility,
            "file_name": payload.file_name.strip(),
            "file_type": _clean_optional_text(payload.file_type),
            "mime_type": _clean_optional_text(payload.mime_type),
            "file_size": payload.file_size,
            "storage_path": payload.storage_path.strip(),
            "uploaded_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": metadata,
        },
    ).mappings().one()
    return row["id"]


