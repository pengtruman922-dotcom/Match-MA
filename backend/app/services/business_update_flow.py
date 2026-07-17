"""Business update intake/processing flow logic shared with API routes."""

import json
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser
from backend.app.api.routes.utils import (
    ensure_entity_writable,
)
from backend.app.config import get_settings
from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.services.attachment_storage import (
    AttachmentStorageError,
    AttachmentTooLargeError,
    save_upload_file,
)
from backend.app.services.image_inputs import is_supported_multimodal_image, multimodal_image_constraints

ATTACHMENT_VISIBILITY_VALUES = {"workspace", "team", "private"}


ATTACHMENT_PARSE_ENTITY_TYPES = {"seller_target", "buyer_intent"}


BUSINESS_UPDATE_INPUT_TYPES = {"text", "screenshot", "attachment", "mixed"}


def _ensure_business_update_exists(db: Session, business_update_id: UUID) -> None:
    row = db.execute(
        text(
            """
            select 1
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
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business update not found.")


def _ensure_bound_entities_writable(
    db: Session,
    current_user: CurrentUser,
    *,
    seller_target_ids: list[UUID],
    buyer_party_ids: list[UUID],
    buyer_intent_ids: list[UUID],
) -> None:
    for seller_target_id in dict.fromkeys(seller_target_ids):
        ensure_entity_writable(db, current_user, entity_type="seller_target", entity_id=seller_target_id)
    for buyer_party_id in dict.fromkeys(buyer_party_ids):
        ensure_entity_writable(db, current_user, entity_type="buyer_party", entity_id=buyer_party_id)
    for buyer_intent_id in dict.fromkeys(buyer_intent_ids):
        ensure_entity_writable(db, current_user, entity_type="buyer_intent", entity_id=buyer_intent_id)


def _insert_business_update_row(
    db: Session,
    *,
    raw_text: str,
    input_type: str,
    bound_seller_target_ids: list[UUID] | None = None,
    bound_buyer_party_ids: list[UUID] | None = None,
    bound_buyer_intent_ids: list[UUID] | None = None,
    metadata_json: dict[str, Any],
    actor_user_id: UUID | None = None,
) -> dict[str, Any]:
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
    return dict(
        db.execute(
            statement,
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "raw_text": raw_text,
                "input_type": input_type,
                "bound_seller_target_ids_json": [str(item) for item in (bound_seller_target_ids or [])],
                "bound_buyer_party_ids_json": [str(item) for item in (bound_buyer_party_ids or [])],
                "bound_buyer_intent_ids_json": [str(item) for item in (bound_buyer_intent_ids or [])],
                "created_by": actor_user_id or DEFAULT_ADMIN_USER_ID,
                "metadata_json": metadata_json,
            },
        )
        .mappings()
        .one()
    )


def _save_business_update_upload_files(
    db: Session,
    files: list[UploadFile],
    *,
    settings: Any,
    actor_user_id: UUID | None = None,
) -> dict[str, list[UUID]]:
    if len(files) > settings.business_update_max_upload_files:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                "Too many attachments for one business update. "
                f"Maximum is {settings.business_update_max_upload_files} files."
            ),
        )

    uploaded_attachment_ids: list[UUID] = []
    ocr_attachment_ids: list[UUID] = []
    multimodal_image_attachment_ids: list[UUID] = []
    skipped_ocr_attachment_ids: list[UUID] = []

    for file in files:
        attachment_id = uuid4()
        original_file_name = file.filename or "upload.bin"
        try:
            uploaded = save_upload_file(
                file.file,
                attachment_id=attachment_id,
                original_file_name=original_file_name,
                content_type=file.content_type,
                storage_dir=settings.attachment_storage_dir,
                storage_backend=settings.effective_attachment_storage_backend,
                max_bytes=settings.attachment_max_upload_bytes,
                text_capture_max_bytes=settings.attachment_text_capture_max_bytes,
                s3_endpoint_url=settings.effective_attachment_s3_endpoint_url,
                s3_region=settings.effective_attachment_s3_region,
                s3_bucket=settings.effective_attachment_s3_bucket,
                s3_access_key_id=settings.effective_attachment_s3_access_key_id,
                s3_secret_access_key=settings.effective_attachment_s3_secret_access_key,
                s3_force_path_style=settings.attachment_s3_force_path_style,
            )
        except AttachmentTooLargeError as exc:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
        except AttachmentStorageError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "business_update_upload_failed",
                    "file_name": original_file_name,
                    "message": _truncate_review_text(str(exc), 500),
                },
            ) from exc

        metadata = {
            **uploaded.metadata_json(),
            "uploaded_via": "business_update_multipart_upload",
            "ocr_policy": _upload_ocr_policy(uploaded.file_type, file.content_type),
        }
        row = db.execute(
            text(
                """
                insert into attachment (
                  id, team_id, workspace_id, visibility, file_name, file_type, mime_type,
                  file_size, storage_path, uploaded_by, metadata_json
                )
                values (
                  :id, :team_id, :workspace_id, 'workspace', :file_name, :file_type, :mime_type,
                  :file_size, :storage_path, :uploaded_by, :metadata_json
                )
                returning id, file_type, mime_type, file_size, metadata_json
                """
            ).bindparams(bindparam("metadata_json", type_=JSONB)),
            {
                "id": attachment_id,
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "file_name": original_file_name[:500],
                "file_type": uploaded.file_type,
                "mime_type": file.content_type,
                "file_size": uploaded.file_size,
                "storage_path": uploaded.storage_uri,
                "uploaded_by": actor_user_id or DEFAULT_ADMIN_USER_ID,
                "metadata_json": metadata,
            },
        ).mappings().one()
        attachment = dict(row)
        uploaded_attachment_ids.append(attachment_id)
        if is_supported_multimodal_image(attachment):
            multimodal_image_attachment_ids.append(attachment_id)
        if _should_auto_ocr_uploaded_attachment(attachment):
            ocr_attachment_ids.append(attachment_id)
        else:
            skipped_ocr_attachment_ids.append(attachment_id)

    return {
        "uploaded_attachment_ids": uploaded_attachment_ids,
        "ocr_attachment_ids": ocr_attachment_ids,
        "multimodal_image_attachment_ids": multimodal_image_attachment_ids,
        "skipped_ocr_attachment_ids": skipped_ocr_attachment_ids,
    }


def _append_ingest_metadata(row: dict[str, Any], follow_up: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(row.get("metadata_json") or {})
    if follow_up["linked_attachment_ids"] or follow_up["process_job"]:
        metadata["attachment_ingest"] = {
            "linked_attachment_ids": [str(item) for item in follow_up["linked_attachment_ids"]],
            "created_attachment_ids": [str(item) for item in follow_up["created_attachment_ids"]],
            "ocr_job_ids": [str(item["id"]) for item in follow_up["ocr_jobs"]],
            "process_job_id": str(follow_up["process_job"]["id"]) if follow_up["process_job"] else None,
        }
    return {**row, "metadata_json": metadata}


def _patch_business_update_attachment_ingest_metadata(
    db: Session,
    business_update_id: UUID,
    follow_up: dict[str, Any],
) -> None:
    if not (follow_up["linked_attachment_ids"] or follow_up["process_job"]):
        return
    db.execute(
        text(
            """
            update business_update
            set metadata_json = metadata_json || :metadata_patch
            where id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "metadata_patch": {
                "attachment_ingest": {
                    "linked_attachment_ids": [str(item) for item in follow_up["linked_attachment_ids"]],
                    "created_attachment_ids": [str(item) for item in follow_up["created_attachment_ids"]],
                    "ocr_job_ids": [str(item["id"]) for item in follow_up["ocr_jobs"]],
                    "process_job_id": str(follow_up["process_job"]["id"]) if follow_up["process_job"] else None,
                }
            },
        },
    )


def _upload_ocr_policy(file_type: str | None, mime_type: str | None) -> str:
    attachment = {"file_type": file_type, "mime_type": mime_type}
    if is_supported_multimodal_image(attachment):
        return "multimodal_image_only"
    if _should_auto_ocr_uploaded_attachment(attachment):
        return "auto_ocr"
    return "skip_ocr"


def _should_auto_ocr_uploaded_attachment(attachment: dict[str, Any]) -> bool:
    file_type = str(attachment.get("file_type") or "").lower()
    mime_type = str(attachment.get("mime_type") or "").split(";")[0].strip().lower()
    if is_supported_multimodal_image(attachment):
        return False
    if file_type in {"txt", "md", "csv", "json", "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx"}:
        return True
    return mime_type.startswith("text/") or mime_type in {
        "application/json",
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }


def _enqueue_attachment_ocr_job(
    db: Session,
    *,
    attachment_id: UUID,
    business_update_id: UUID,
    mock_extracted_text: str | None,
    auto_parse_linked_objects: bool,
    parse_entity_types: list[str],
    process_after_ocr: bool,
    include_attachment_text: bool,
) -> dict[str, Any]:
    existing = _latest_active_ocr_job(db, attachment_id, business_update_id)
    if existing:
        return {**existing, "reused_existing": True}

    row = db.execute(
        text(
            """
            insert into background_job (
              team_id, workspace_id, job_type, priority, queue_name,
              entity_type, entity_id, idempotency_key, payload_json,
              max_attempts, correlation_id, created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, 'attachment_ocr_parse', 100, 'ocr',
              'attachment', :attachment_id, :idempotency_key, :payload_json,
              1, :correlation_id, :created_by, :metadata_json
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
            "attachment_id": attachment_id,
            "idempotency_key": f"attachment_ocr_parse:business_update:{business_update_id}:{attachment_id}:{uuid4()}",
            "payload_json": {
                "attachment_id": str(attachment_id),
                "business_update_id": str(business_update_id),
                "mock_extracted_text": mock_extracted_text,
                "auto_parse_linked_objects": auto_parse_linked_objects,
                "parse_entity_types": parse_entity_types,
                "process_business_update_after_ocr": process_after_ocr,
                "include_attachment_text": include_attachment_text,
            },
            "correlation_id": business_update_id,
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {
                "source": "business_update_attachment_ingest",
                "business_update_id": str(business_update_id),
                "process_after_ocr": process_after_ocr,
            },
        },
    ).mappings().one()
    _mark_attachment_parsing(db, attachment_id, row["id"])
    return {**dict(row), "reused_existing": False}


def _enqueue_business_update_process_job(
    db: Session,
    *,
    business_update_id: UUID,
    include_attachment_text: bool,
    source: str,
) -> dict[str, Any]:
    existing_job = _latest_active_business_update_process_job(db, business_update_id)
    if existing_job:
        return {**existing_job, "reused_existing": True}

    row = db.execute(
        text(
            """
            insert into background_job (
              team_id, workspace_id, job_type, priority, queue_name,
              entity_type, entity_id, idempotency_key, payload_json,
              correlation_id, created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, 'business_update_extract_actions', 100, 'llm',
              'business_update', :business_update_id, :idempotency_key, :payload_json,
              :correlation_id, :created_by, :metadata_json
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
            "business_update_id": business_update_id,
            "idempotency_key": f"business_update_extract_actions:{business_update_id}:{uuid4()}",
            "payload_json": {
                "business_update_id": str(business_update_id),
                "include_attachment_text": include_attachment_text,
            },
            "correlation_id": business_update_id,
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {"source": source},
        },
    ).mappings().one()
    return {**dict(row), "reused_existing": False}


def _latest_active_business_update_process_job(db: Session, business_update_id: UUID) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select id, job_type, status, queue_name, entity_id
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and job_type = 'business_update_extract_actions'
              and entity_type = 'business_update'
              and entity_id = :business_update_id
              and status in ('queued', 'running', 'retry_waiting')
            order by created_at desc
            limit 1
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "business_update_id": business_update_id,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _latest_active_ocr_job(db: Session, attachment_id: UUID, business_update_id: UUID) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select id, job_type, status, queue_name, entity_id
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and job_type = 'attachment_ocr_parse'
              and entity_type = 'attachment'
              and entity_id = :attachment_id
              and payload_json ->> 'business_update_id' = :business_update_id
              and status in ('queued', 'running', 'retry_waiting')
            order by created_at desc
            limit 1
            """
        ),
        {
            "attachment_id": attachment_id,
            "business_update_id": str(business_update_id),
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _mark_business_update_processing(db: Session, business_update_id: UUID) -> None:
    db.execute(
        text(
            """
            update business_update
            set processing_status = 'processing'
            where id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and processing_status in ('pending', 'failed', 'parsed', 'partially_applied', 'applied')
            """
        ),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    _mark_bound_seller_targets_parsing(db, business_update_id)


def _mark_bound_seller_targets_parsing(db: Session, business_update_id: UUID) -> None:
    """Show bound targets as parsing so the list/detail polling picks the run up.

    The extract-actions handler releases them afterwards: field applies flip to
    normal, follow-up-only applies release to normal, leftovers become
    pending_review, failures become parse_failed.
    """
    db.execute(
        text(
            """
            update seller_target st
            set information_status = 'parsing',
                updated_at = now(),
                updated_by = :updated_by
            from business_update bu
            where bu.id = :business_update_id
              and bu.team_id = :team_id
              and bu.workspace_id = :workspace_id
              and st.team_id = :team_id
              and st.workspace_id = :workspace_id
              and st.deleted_at is null
              and st.information_status <> 'parsing'
              and st.id::text in (
                select jsonb_array_elements_text(bu.bound_seller_target_ids_json)
              )
            """
        ),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "updated_by": DEFAULT_ADMIN_USER_ID,
        },
    )


def _mark_attachment_parsing(db: Session, attachment_id: UUID, job_id: UUID) -> None:
    db.execute(
        text(
            """
            update attachment
            set parse_status = 'parsing',
                metadata_json = metadata_json || :metadata_patch
            where id = :attachment_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "attachment_id": attachment_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "metadata_patch": {
                "last_ocr_job_id": str(job_id),
                "last_ocr_status": "queued",
            },
        },
    )


def _link_attachment_if_missing(
    db: Session,
    attachment_id: UUID,
    entity_type: str,
    entity_id: UUID,
    link_type: str,
) -> None:
    db.execute(
        text(
            """
            insert into attachment_link (
              team_id, workspace_id, attachment_id, entity_type, entity_id, link_type, created_by
            )
            select :team_id, :workspace_id, :attachment_id, :entity_type, :entity_id, :link_type, :created_by
            where not exists (
              select 1
              from attachment_link
              where team_id = :team_id
                and workspace_id = :workspace_id
                and attachment_id = :attachment_id
                and entity_type = :entity_type
                and entity_id = :entity_id
                and link_type = :link_type
            )
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "attachment_id": attachment_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "link_type": link_type,
            "created_by": DEFAULT_ADMIN_USER_ID,
        },
    )


def _ensure_attachment_exists(db: Session, attachment_id: UUID) -> None:
    exists = db.execute(
        text(
            """
            select exists(
              select 1
              from attachment
              where id = :attachment_id
                and team_id = :team_id
                and workspace_id = :workspace_id
                and deleted_at is null
            )
            """
        ),
        {
            "attachment_id": attachment_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).scalar_one()
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found.")


def _bound_attachment_link_targets(
    *,
    seller_target_ids: list[UUID],
    buyer_party_ids: list[UUID],
    buyer_intent_ids: list[UUID],
) -> list[tuple[str, list[UUID]]]:
    return [
        ("seller_target", seller_target_ids),
        ("buyer_party", buyer_party_ids),
        ("buyer_intent", buyer_intent_ids),
    ]


def _validate_parse_entity_types(parse_entity_types: list[str]) -> None:
    invalid = [item for item in parse_entity_types if item not in ATTACHMENT_PARSE_ENTITY_TYPES]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unsupported OCR auto-parse entity types: {', '.join(invalid)}",
        )


def _validate_business_update_input_type(input_type: str) -> None:
    if input_type not in BUSINESS_UPDATE_INPUT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unsupported business update input_type: {input_type}",
        )


def _parse_entity_types_form(value: str | None) -> list[str]:
    if not value or not value.strip():
        return []
    stripped = value.strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = [item.strip() for item in stripped.split(",")]
    if isinstance(parsed, str):
        return [parsed]
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="parse_entity_types must be a JSON array or comma-separated string.",
    )


def _parse_uuid_list_form(value: str | None) -> list[UUID]:
    if not value or not value.strip():
        return []
    stripped = value.strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = [item.strip() for item in stripped.split(",")]
    if isinstance(parsed, str):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Bound ids must be a JSON array or comma-separated string.",
        )
    result: list[UUID] = []
    invalid: list[str] = []
    for item in parsed:
        item_uuid = _optional_uuid(item)
        if item_uuid:
            result.append(item_uuid)
        elif str(item).strip():
            invalid.append(str(item))
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid bound ids: {', '.join(invalid)}",
        )
    return _unique_uuid_list(result)


def _parse_metadata_json_form(value: str | None) -> dict[str, Any]:
    if not value or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="metadata_json must be valid JSON.",
        ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="metadata_json must be a JSON object.",
        )
    return _json_safe_value(parsed)


def _unique_uuid_list(items: list[UUID]) -> list[UUID]:
    seen: set[UUID] = set()
    result: list[UUID] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _review_page_actions(db: Session, business_update_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              a.id, a.business_update_id, a.action_type, a.target_entity_type, a.target_entity_id,
              a.proposed_changes_json, a.raw_evidence_text, a.evidence_id, a.confidence, a.review_status,
              a.reviewed_by, a.reviewed_at::text as reviewed_at, a.applied_at::text as applied_at,
              a.metadata_json, a.created_at::text as created_at,
              st.target_name as seller_target_name,
              bi.intent_name as buyer_intent_name,
              bp.buyer_name
            from extracted_action a
            left join seller_target st
              on st.id = a.target_entity_id and a.target_entity_type = 'seller_target'
            left join buyer_intent bi
              on bi.id = a.target_entity_id and a.target_entity_type = 'buyer_intent'
            left join buyer_party bp
              on bp.id = a.target_entity_id and a.target_entity_type = 'buyer_party'
            where a.business_update_id = :business_update_id
              and a.team_id = :team_id
              and a.workspace_id = :workspace_id
            order by a.created_at desc
            limit 200
            """
        ),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _review_page_application_logs(db: Session, business_update_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              log.id, log.extracted_action_id, log.business_update_id,
              log.entity_type, log.entity_id, log.field_path,
              log.old_value_json, log.new_value_json,
              log.source_type, log.source_id, log.evidence_id,
              log.applied_by, log.applied_at::text as applied_at,
              log.edited_before_apply, log.can_rollback,
              log.rollback_at::text as rollback_at,
              log.metadata_json,
              ev.text_excerpt as evidence_text_excerpt,
              ev.attachment_id as evidence_attachment_id,
              ev.parsed_document_id as evidence_parsed_document_id,
              ev.page_no as evidence_page_no,
              st.target_name as seller_target_name,
              bi.intent_name as buyer_intent_name,
              bp.buyer_name
            from action_application_log log
            left join evidence_span ev on ev.id = log.evidence_id
            left join seller_target st
              on st.id = log.entity_id and log.entity_type = 'seller_target'
            left join buyer_intent bi
              on bi.id = log.entity_id and log.entity_type = 'buyer_intent'
            left join buyer_party bp
              on bp.id = log.entity_id and log.entity_type = 'buyer_party'
            where log.business_update_id = :business_update_id
              and log.team_id = :team_id
              and log.workspace_id = :workspace_id
            order by log.applied_at desc
            limit 500
            """
        ),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [_enrich_application_log(dict(row)) for row in rows]


def _review_page_jobs(db: Session, business_update_id: UUID) -> list[dict[str, Any]]:
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
                (entity_type = 'business_update' and entity_id = :business_update_id)
                or payload_json ->> 'business_update_id' = :business_update_id_text
              )
            order by created_at desc
            limit 100
            """
        ),
        {
            "business_update_id": business_update_id,
            "business_update_id_text": str(business_update_id),
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _review_page_traces(db: Session, business_update_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              trace.id, trace.trace_type, trace.node_name, trace.job_id, trace.correlation_id,
              trace.entity_type, trace.entity_id, trace.provider_name, trace.model_name,
              trace.prompt_version, trace.status, trace.input_json, trace.raw_output_text,
              trace.parsed_output_json, trace.schema_validation_json, trace.error_code,
              trace.error_message, trace.latency_ms, trace.prompt_tokens, trace.completion_tokens,
              trace.total_tokens, trace.started_at::text as started_at,
              trace.finished_at::text as finished_at, trace.metadata_json
            from ai_trace trace
            where trace.team_id = :team_id
              and trace.workspace_id = :workspace_id
              and (
                (trace.entity_type = 'business_update' and trace.entity_id = :business_update_id)
                or trace.job_id in (
                  select id
                  from background_job
                  where team_id = :team_id
                    and workspace_id = :workspace_id
                    and (
                      (entity_type = 'business_update' and entity_id = :business_update_id)
                      or payload_json ->> 'business_update_id' = :business_update_id_text
                    )
                )
              )
            order by trace.started_at desc
            limit 100
            """
        ),
        {
            "business_update_id": business_update_id,
            "business_update_id_text": str(business_update_id),
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _review_page_attachments(db: Session, business_update_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              a.id, a.visibility, a.file_name, a.file_type, a.mime_type, a.file_size,
              a.storage_path, a.uploaded_by, a.uploaded_at::text as uploaded_at,
              a.parse_status, a.metadata_json, a.deleted_at::text as deleted_at,
              al.link_type, al.created_at::text as linked_at,
              job.id as latest_job_id, job.status as latest_job_status,
              job.queue_name as latest_job_queue, job.error_message as latest_job_error_message,
              ev.id as latest_evidence_id, ev.text_excerpt as latest_evidence_text_excerpt,
              ev.page_no as latest_evidence_page_no,
              pd.id as latest_parsed_document_id, pd.parse_status as latest_parsed_document_status
            from attachment_link al
            join attachment a on a.id = al.attachment_id
            left join lateral (
              select id, status, queue_name, error_message
              from background_job
              where team_id = al.team_id
                and workspace_id = al.workspace_id
                and job_type in ('attachment_ocr_parse', 'attachment_ocr_poll')
                and entity_type = 'attachment'
                and entity_id = al.attachment_id
              order by created_at desc
              limit 1
            ) job on true
            left join lateral (
              select id, parse_status
              from parsed_document
              where team_id = al.team_id
                and workspace_id = al.workspace_id
                and attachment_id = al.attachment_id
              order by created_at desc
              limit 1
            ) pd on true
            left join lateral (
              select id, text_excerpt, page_no
              from evidence_span
              where team_id = al.team_id
                and workspace_id = al.workspace_id
                and attachment_id = al.attachment_id
              order by created_at desc
              limit 1
            ) ev on true
            where al.team_id = :team_id
              and al.workspace_id = :workspace_id
              and al.entity_type = 'business_update'
              and al.entity_id = :business_update_id
              and a.deleted_at is null
            order by al.created_at asc
            limit 100
            """
        ),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [_compact_review_attachment(dict(row)) for row in rows]


def _review_page_bound_entities(
    db: Session,
    business_update: dict[str, Any],
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    seller_target_ids = _collect_entity_ids(
        business_update.get("bound_seller_target_ids_json"),
        actions,
        target_entity_type="seller_target",
        proposed_change_keys=["seller_target_id"],
    )
    buyer_intent_ids = _collect_entity_ids(
        business_update.get("bound_buyer_intent_ids_json"),
        actions,
        target_entity_type="buyer_intent",
        proposed_change_keys=["buyer_intent_id"],
    )
    buyer_party_ids = _collect_entity_ids(
        business_update.get("bound_buyer_party_ids_json"),
        actions,
        target_entity_type="buyer_party",
        proposed_change_keys=["buyer_party_id"],
    )
    relation_ids = _collect_entity_ids(
        [],
        actions,
        target_entity_type="buyer_seller_relation",
        proposed_change_keys=["relation_id", "source_relation_id"],
    )
    return {
        "seller_targets": _seller_targets_by_ids(db, seller_target_ids),
        "buyer_intents": _buyer_intents_by_ids(db, buyer_intent_ids),
        "buyer_parties": _buyer_parties_by_ids(db, buyer_party_ids),
        "relations": _relations_by_ids(db, relation_ids),
        "recommendation_session": _recommendation_session_summary(
            db,
            business_update.get("bound_recommendation_session_id"),
        ),
    }


def _seller_targets_by_ids(db: Session, ids: list[UUID]) -> list[dict[str, Any]]:
    if not ids:
        return []
    rows = db.execute(
        text(
            """
            select
              id, target_name, target_type, industry_primary, industry_secondary,
              headquarter_province, headquarter_city, listed_status,
              current_revenue_yuan, current_net_profit_yuan, current_total_profit_yuan,
              valuation_yuan, asking_price_yuan, pe_ratio, is_for_sale,
              can_control, can_consolidate, accepts_minority_investment,
              transfer_ratio_min, transfer_ratio_max, transfer_ratio_text,
              transfer_flexibility_type, recommendation_status, information_status,
              business_summary, transaction_summary, risk_summary, gap_summary,
              updated_at::text as updated_at
            from seller_target
            where team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              and id in :ids
            order by target_name asc
            """
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": tuple(ids), "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().all()
    return [dict(row) for row in rows]


def _buyer_intents_by_ids(db: Session, ids: list[UUID]) -> list[dict[str, Any]]:
    if not ids:
        return []
    rows = db.execute(
        text(
            """
            select
              bi.id, bi.buyer_party_id, bp.buyer_name, bi.intent_name, bi.status,
              bi.pause_reason, bi.contact_name, bi.raw_requirement_text,
              bi.intent_summary, bi.industry_primary, bi.industry_secondary,
              bi.region_scope_summary, bi.min_revenue_yuan, bi.min_net_profit_yuan,
              bi.min_total_profit_yuan, bi.max_pe, bi.max_valuation_yuan,
              bi.min_market_cap_yuan, bi.max_market_cap_yuan, bi.market_cap_range_summary,
              bi.requires_control, bi.requires_consolidation, bi.accepts_minority_investment,
              bi.desired_equity_ratio_min, bi.desired_equity_ratio_max,
              bi.equity_ratio_summary, bi.equity_requirement_type,
              bi.preferred_listed_status, bi.listing_board_requirement_summary,
              bi.financing_stage_requirement_summary, bi.transaction_type,
              bi.transaction_types_json, bi.premium_tolerance_summary, bi.max_premium_rate,
              bi.max_debt_ratio, bi.debt_ratio_requirement_summary,
              bi.major_risk_tolerance_summary, bi.buyer_industry_advantage_summary,
              bi.negative_summary, bi.priority_summary, bi.preference_summary,
              bi.unknown_summary, bi.updated_at::text as updated_at
            from buyer_intent bi
            left join buyer_party bp on bp.id = bi.buyer_party_id
            where bi.team_id = :team_id
              and bi.workspace_id = :workspace_id
              and bi.deleted_at is null
              and bi.id in :ids
            order by bi.intent_name asc
            """
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": tuple(ids), "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().all()
    return [dict(row) for row in rows]


def _buyer_parties_by_ids(db: Session, ids: list[UUID]) -> list[dict[str, Any]]:
    if not ids:
        return []
    rows = db.execute(
        text(
            """
            select
              id, buyer_name, buyer_type, group_name, listed_status,
              region_province, region_city, main_business,
              capital_strength_summary, profile_summary, status,
              updated_at::text as updated_at
            from buyer_party
            where team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              and id in :ids
            order by buyer_name asc
            """
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": tuple(ids), "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().all()
    return [dict(row) for row in rows]


def _relations_by_ids(db: Session, ids: list[UUID]) -> list[dict[str, Any]]:
    if not ids:
        return []
    rows = db.execute(
        text(
            """
            select
              r.id, r.buyer_intent_id, bi.intent_name,
              r.buyer_party_id, bp.buyer_name,
              r.seller_target_id, st.target_name,
              r.status, r.status_reason, r.first_recommended_at::text as first_recommended_at,
              r.last_contact_at::text as last_contact_at, r.last_event_at::text as last_event_at,
              r.last_event_summary, r.updated_at::text as updated_at
            from buyer_seller_relation r
            join buyer_intent bi on bi.id = r.buyer_intent_id
            join seller_target st on st.id = r.seller_target_id
            left join buyer_party bp on bp.id = r.buyer_party_id
            where r.team_id = :team_id
              and r.workspace_id = :workspace_id
              and r.deleted_at is null
              and r.id in :ids
            order by r.updated_at desc
            """
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": tuple(ids), "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().all()
    return [dict(row) for row in rows]


def _recommendation_session_summary(db: Session, session_id: Any) -> dict[str, Any] | None:
    parsed_id = _optional_uuid(session_id)
    if parsed_id is None:
        return None
    row = db.execute(
        text(
            """
            select
              rs.id, rs.mode, rs.status, rs.selected_count, rs.report_count,
              rs.buyer_intent_id, bi.intent_name as buyer_intent_name,
              rs.buyer_party_id, bp.buyer_name,
              rs.seller_target_id, st.target_name as seller_target_name,
              rs.created_at::text as created_at, rs.updated_at::text as updated_at
            from recommendation_session rs
            left join buyer_intent bi on bi.id = rs.buyer_intent_id
            left join buyer_party bp on bp.id = rs.buyer_party_id
            left join seller_target st on st.id = rs.seller_target_id
            where rs.team_id = :team_id
              and rs.workspace_id = :workspace_id
              and rs.id = :session_id
            """
        ),
        {"session_id": parsed_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().one_or_none()
    if row is None:
        return None
    result = dict(row)
    result["debug_ref"] = _debug_ref("recommendation_session", result["id"])
    return result


REVIEW_GROUP_LABELS = {
    "seller_update": "标的更新",
    "buyer_intent_update": "买家意向更新",
    "relation_progress": "关系/跟进",
    "exception": "异常/备注",
}


ACTION_LABELS = {
    "seller_fact_update": "标的字段更新",
    "seller_event": "标的事件",
    "target_follow_up": "标的跟进记录",
    "buyer_intent_follow_up": "买家意向跟进记录",
    "buyer_intent_update": "买家意向更新",
    "buyer_seller_relation_update": "关系进展更新",
    "buyer_intent_target_exclusion": "买家排除标的",
    "buyer_level_blacklist_suggestion": "买家级黑名单建议",
    "internal_note": "内部备注",
    "unresolved_item": "待人工判断",
}


REVIEW_STATUS_LABELS = {
    "pending_review": "待复核",
    "accepted": "已接受",
    "rejected": "已拒绝",
    "auto_accepted": "已自动应用，待复核",
    "ignored": "已忽略",
}


APPLY_SUPPORTED_ACTION_TYPES = {
    "seller_fact_update",
    "buyer_intent_update",
    "buyer_seller_relation_update",
    "buyer_intent_target_exclusion",
    "target_follow_up",
    "buyer_intent_follow_up",
}


def _enrich_review_action(
    action: dict[str, Any],
    logs: list[dict[str, Any]],
    target_snapshots: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    group_key = _review_action_group_key(action)
    action_type = action["action_type"]
    target_ref = _action_target_ref(action)
    target_snapshot = target_snapshots.get(_target_snapshot_key(target_ref.get("entity_type"), target_ref.get("entity_id")))
    apply_supported = action_type in APPLY_SUPPORTED_ACTION_TYPES
    applied_fields = [log["field_path"] for log in logs]
    return {
        **action,
        "action_label": ACTION_LABELS.get(action_type, action_type),
        "review_status_label": REVIEW_STATUS_LABELS.get(action["review_status"], action["review_status"]),
        "group_key": group_key,
        "group_label": REVIEW_GROUP_LABELS[group_key],
        "priority": _review_action_priority(action),
        "target_display": _action_target_display(action, target_snapshot),
        "target_ref": target_ref,
        "change_preview": _action_change_preview(action, logs, target_snapshot),
        "application_logs": logs,
        "application_log_count": len(logs),
        "applied_fields": applied_fields,
        "is_auto_applied": action["review_status"] == "auto_accepted" and action["applied_at"] is not None,
        "apply_supported": apply_supported,
        "can_accept": action["review_status"] == "pending_review",
        "can_reject": action["review_status"] in {"pending_review", "auto_accepted"},
        "can_apply": apply_supported
        and action["applied_at"] is None
        and action["review_status"] in {"accepted", "auto_accepted"},
        "review_route": _history_route(target_ref.get("entity_type"), target_ref.get("entity_id")),
        "debug_ref": _debug_ref("business_update", action["business_update_id"]),
    }


def _review_action_group_key(action: dict[str, Any]) -> str:
    action_type = action.get("action_type")
    target_type = action.get("target_entity_type")
    if action_type in {"seller_fact_update", "seller_event"} or target_type == "seller_target":
        return "seller_update"
    if action_type == "buyer_intent_update" or target_type == "buyer_intent":
        return "buyer_intent_update"
    if action_type in {"buyer_seller_relation_update", "buyer_intent_target_exclusion"}:
        return "relation_progress"
    return "exception"


def _review_action_priority(action: dict[str, Any]) -> str:
    confidence = _optional_float(action.get("confidence"))
    if action.get("action_type") == "unresolved_item" or confidence is None:
        return "high"
    if confidence < 0.6:
        return "high"
    if confidence < 0.8:
        return "medium"
    return "normal"


def _review_action_groups(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for key, label in REVIEW_GROUP_LABELS.items():
        items = [action for action in actions if action["group_key"] == key]
        if not items:
            continue
        groups.append(
            {
                "key": key,
                "label": label,
                "count": len(items),
                "pending_count": len([item for item in items if item["review_status"] == "pending_review"]),
                "auto_applied_count": len([item for item in items if item["is_auto_applied"]]),
                "high_priority_count": len([item for item in items if item["priority"] == "high"]),
                "items": items,
            }
        )
    return groups


def _action_change_preview(
    action: dict[str, Any],
    logs: list[dict[str, Any]],
    target_snapshot: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if logs:
        return [
            {
                "field_path": log["field_path"],
                "old_value": log.get("old_value_json"),
                "new_value": log.get("new_value_json"),
                "source": "application_log",
                "can_rollback": log.get("can_rollback") and log.get("rollback_at") is None,
            }
            for log in logs[:50]
        ]

    changes = action.get("proposed_changes_json") or {}
    if not isinstance(changes, dict):
        return []
    preview: list[dict[str, Any]] = []
    for key, value in list(changes.items())[:50]:
        preview.append(
            {
                "field_path": key,
                "old_value": target_snapshot.get(key) if target_snapshot else None,
                "new_value": value,
                "source": "proposed_changes",
                "can_rollback": False,
            }
        )
    return preview


def _review_page_overview(
    business_update: dict[str, Any],
    actions: list[dict[str, Any]],
    application_logs: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    traces: list[dict[str, Any]],
) -> dict[str, Any]:
    pending_count = len([action for action in actions if action["review_status"] == "pending_review"])
    auto_applied_count = len([action for action in actions if action["is_auto_applied"]])
    applied_action_count = len([action for action in actions if action["applied_at"] is not None])
    failed_job_count = len([job for job in jobs if job["status"] == "failed" and not _job_failure_ignored(job)])
    ignored_failed_job_count = len([job for job in jobs if job["status"] == "failed" and _job_failure_ignored(job)])
    running_job_count = len([job for job in jobs if job["status"] in {"queued", "running", "retry_waiting"}])
    failed_trace_count = len([trace for trace in traces if trace["status"] == "failed" or trace.get("error_code")])
    return {
        "processing_status": business_update["processing_status"],
        "action_count": len(actions),
        "pending_review_count": pending_count,
        "auto_applied_count": auto_applied_count,
        "applied_action_count": applied_action_count,
        "application_log_count": len(application_logs),
        "failed_job_count": failed_job_count,
        "ignored_failed_job_count": ignored_failed_job_count,
        "running_job_count": running_job_count,
        "trace_count": len(traces),
        "failed_trace_count": failed_trace_count,
        "mode": "auto_apply_then_review",
        "needs_review": pending_count > 0 or auto_applied_count > 0 or failed_job_count > 0 or failed_trace_count > 0,
    }


def _compact_sample_run(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else {}
    overview = {
        "processing_status": row.get("processing_status"),
        "action_count": int(row.get("action_count") or 0),
        "pending_review_count": int(row.get("pending_review_count") or 0),
        "auto_applied_count": int(row.get("auto_applied_count") or 0),
        "applied_action_count": int(row.get("applied_action_count") or 0),
        "job_count": int(row.get("job_count") or 0),
        "failed_job_count": int(row.get("failed_job_count") or 0),
        "ignored_failed_job_count": int(row.get("ignored_failed_job_count") or 0),
        "running_job_count": int(row.get("running_job_count") or 0),
        "trace_count": int(row.get("trace_count") or 0),
        "failed_trace_count": int(row.get("failed_trace_count") or 0),
        "attachment_count": int(row.get("attachment_count") or 0),
        "parsed_attachment_count": int(row.get("parsed_attachment_count") or 0),
        "multimodal_image_count": int(row.get("multimodal_image_count") or 0),
        "parsing_attachment_count": int(row.get("parsing_attachment_count") or 0),
        "skipped_attachment_count": int(row.get("skipped_attachment_count") or 0),
        "failed_attachment_count": int(row.get("failed_attachment_count") or 0),
    }
    overview["needs_attention"] = (
        overview["failed_job_count"] > 0
        or overview["failed_trace_count"] > 0
        or overview["failed_attachment_count"] > 0
        or overview["skipped_attachment_count"] > 0
        or overview["running_job_count"] > 0
        or overview["parsing_attachment_count"] > 0
    )
    latest_failed_job = _compact_sample_failed_job(row.get("latest_failed_job"))
    attachments = row.get("attachment_preview") if isinstance(row.get("attachment_preview"), list) else []
    business_update_id = row["id"]
    return {
        "business_update_id": business_update_id,
        "input_type": row.get("input_type"),
        "processing_status": row.get("processing_status"),
        "created_at": row.get("created_at"),
        "raw_text_preview": _truncate_review_text(row.get("raw_text"), 240),
        "sample_metadata": {
            "test_data": _metadata_truthy(metadata.get("test_data")) or _metadata_truthy(metadata.get("is_test_data")),
            "sample_label": metadata.get("sample_label") or metadata.get("label"),
            "sample_object": metadata.get("sample_object") or metadata.get("sample_entity") or metadata.get("object"),
            "sample_group": metadata.get("sample_group"),
            "source": metadata.get("source"),
        },
        "overview": overview,
        "latest_failed_job": latest_failed_job,
        "attachments": [_compact_sample_attachment(item) for item in attachments],
        "review_route": f"/business-updates/{business_update_id}/review-page",
        "debug_ref": _debug_ref("business_update", business_update_id),
    }


def _compact_sample_failed_job(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not value.get("id"):
        return None
    return {
        "id": value.get("id"),
        "job_type": value.get("job_type"),
        "status": value.get("status"),
        "queue_name": value.get("queue_name"),
        "error_code": value.get("error_code"),
        "error_message": _truncate_review_text(value.get("error_message"), 240),
        "created_at": value.get("created_at"),
        "finished_at": value.get("finished_at"),
        "debug_ref": _debug_ref("background_job", value.get("id")),
    }


def _compact_sample_attachment(value: Any) -> dict[str, Any]:
    item = value if isinstance(value, dict) else {}
    parsed_text_length = item.get("parsed_text_length")
    try:
        parsed_text_length = int(parsed_text_length) if parsed_text_length is not None else None
    except (TypeError, ValueError):
        parsed_text_length = None
    attachment_id = item.get("id")
    return {
        "id": attachment_id,
        "file_name": item.get("file_name"),
        "file_type": item.get("file_type"),
        "mime_type": item.get("mime_type"),
        "file_size": item.get("file_size"),
        "parse_status": item.get("parse_status"),
        "linked_at": item.get("linked_at"),
        "parsed_document_id": item.get("parsed_document_id"),
        "parsed_text_length": parsed_text_length,
        "multimodal_image_supported": item.get("multimodal_image_supported") is True,
        "debug_ref": _debug_ref("attachment", attachment_id) if attachment_id else None,
    }


def _metadata_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _job_failure_ignored(job: dict[str, Any]) -> bool:
    return (job.get("metadata_json") or {}).get("failure_ignored") is True


def _review_page_quick_actions(business_update: dict[str, Any], overview: dict[str, Any]) -> list[dict[str, Any]]:
    business_update_id = business_update["id"]
    return [
        {
            "key": "rerun_extraction",
            "label": "重新解析",
            "route": None,
            "action": "process_business_update",
            "enabled": business_update["processing_status"] in {"pending", "failed", "parsed", "partially_applied"},
            "badge_count": None,
        },
        {
            "key": "review_pending",
            "label": "复核待处理",
            "route": None,
            "action": "focus_pending_actions",
            "enabled": overview["pending_review_count"] > 0,
            "badge_count": overview["pending_review_count"],
        },
        {
            "key": "inspect_debug",
            "label": "查看 Debug",
            "route": f"/debug/entities/business_update/{business_update_id}",
            "action": "open_debug_entity",
            "enabled": True,
            "badge_count": overview["failed_job_count"] + overview["failed_trace_count"],
        },
    ]


def _logs_by_action(logs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for log in logs:
        if log.get("extracted_action_id") is None:
            continue
        grouped.setdefault(str(log["extracted_action_id"]), []).append(log)
    return grouped


def _review_target_snapshots(bound_entities: dict[str, Any]) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    for entity_type, collection_key in [
        ("seller_target", "seller_targets"),
        ("buyer_intent", "buyer_intents"),
        ("buyer_party", "buyer_parties"),
        ("buyer_seller_relation", "relations"),
    ]:
        for item in bound_entities.get(collection_key, []):
            snapshots[_target_snapshot_key(entity_type, item["id"])] = item
    return snapshots


def _action_target_ref(action: dict[str, Any]) -> dict[str, Any]:
    target_entity_type = action.get("target_entity_type")
    target_entity_id = action.get("target_entity_id")
    if target_entity_type and target_entity_id:
        return _entity_ref(target_entity_type, target_entity_id)
    changes = action.get("proposed_changes_json") or {}
    if isinstance(changes, dict):
        for entity_type, key in [
            ("seller_target", "seller_target_id"),
            ("buyer_intent", "buyer_intent_id"),
            ("buyer_party", "buyer_party_id"),
            ("buyer_seller_relation", "relation_id"),
        ]:
            entity_id = _optional_uuid(changes.get(key))
            if entity_id:
                return _entity_ref(entity_type, entity_id)
    return {"entity_type": None, "entity_id": None, "route": None, "debug_ref": None}


def _action_target_display(action: dict[str, Any], target_snapshot: dict[str, Any] | None) -> str:
    if action.get("seller_target_name"):
        return action["seller_target_name"]
    if action.get("buyer_intent_name"):
        return action["buyer_intent_name"]
    if action.get("buyer_name"):
        return action["buyer_name"]
    if target_snapshot:
        return (
            target_snapshot.get("target_name")
            or target_snapshot.get("intent_name")
            or target_snapshot.get("buyer_name")
            or target_snapshot.get("last_event_summary")
            or "已绑定对象"
        )
    return action.get("target_entity_type") or "未绑定对象"


def _enrich_application_log(log: dict[str, Any]) -> dict[str, Any]:
    target_display = (
        log.get("seller_target_name")
        or log.get("buyer_intent_name")
        or log.get("buyer_name")
        or log.get("entity_type")
    )
    return {
        **log,
        "target_display": target_display,
        "evidence_span": _compact_log_evidence(log),
        "can_rollback_now": bool(log.get("can_rollback")) and log.get("rollback_at") is None,
        "debug_ref": _debug_ref("business_update", log["business_update_id"]),
    }


def _compact_log_evidence(log: dict[str, Any]) -> dict[str, Any] | None:
    if not log.get("evidence_id"):
        return None
    return {
        "id": log.get("evidence_id"),
        "text_excerpt": log.get("evidence_text_excerpt"),
        "attachment_id": log.get("evidence_attachment_id"),
        "parsed_document_id": log.get("evidence_parsed_document_id"),
        "page_no": log.get("evidence_page_no"),
    }


def _compact_review_job(job: dict[str, Any]) -> dict[str, Any]:
    metadata = job.get("metadata_json") if isinstance(job.get("metadata_json"), dict) else {}
    return {
        "id": job["id"],
        "job_type": job["job_type"],
        "status": job["status"],
        "queue_name": job["queue_name"],
        "attempt_count": job["attempt_count"],
        "max_attempts": job["max_attempts"],
        "error_code": job.get("error_code"),
        "error_message": _truncate_review_text(job.get("error_message"), 240),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "ignored": metadata.get("failure_ignored") is True,
        "ignore_reason": metadata.get("failure_ignore_reason"),
        "ignored_at": metadata.get("failure_ignored_at"),
        "debug_ref": _debug_ref("background_job", job["id"]),
    }


def _compact_review_trace(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": trace["id"],
        "trace_type": trace["trace_type"],
        "node_name": trace["node_name"],
        "status": trace["status"],
        "provider_name": trace.get("provider_name"),
        "model_name": trace.get("model_name"),
        "prompt_version": trace.get("prompt_version"),
        "job_id": trace.get("job_id"),
        "error_code": trace.get("error_code"),
        "error_message": _truncate_review_text(trace.get("error_message"), 240),
        "raw_output_preview": _truncate_review_text(trace.get("raw_output_text"), 600),
        "parsed_output_json": trace.get("parsed_output_json"),
        "schema_validation_json": trace.get("schema_validation_json"),
        "latency_ms": trace.get("latency_ms"),
        "prompt_tokens": trace.get("prompt_tokens"),
        "completion_tokens": trace.get("completion_tokens"),
        "total_tokens": trace.get("total_tokens"),
        "started_at": trace.get("started_at"),
        "finished_at": trace.get("finished_at"),
        "debug_ref": _debug_ref("background_job", trace["job_id"]) if trace.get("job_id") else None,
    }


def _compact_review_attachment(row: dict[str, Any]) -> dict[str, Any]:
    parse_readiness = _review_attachment_parse_readiness(row)
    return {
        "id": row["id"],
        "file_name": row.get("file_name"),
        "file_type": row.get("file_type"),
        "mime_type": row.get("mime_type"),
        "file_size": row.get("file_size"),
        "storage_path": row.get("storage_path"),
        "parse_status": row.get("parse_status"),
        "parse_readiness": parse_readiness,
        "link_type": row.get("link_type"),
        "linked_at": row.get("linked_at"),
        "latest_job": {
            "id": row.get("latest_job_id"),
            "status": row.get("latest_job_status"),
            "queue_name": row.get("latest_job_queue"),
            "error_message": _truncate_review_text(row.get("latest_job_error_message"), 240),
            "debug_ref": _debug_ref("background_job", row["latest_job_id"]),
        }
        if row.get("latest_job_id")
        else None,
        "latest_parsed_document": {
            "id": row.get("latest_parsed_document_id"),
            "parse_status": row.get("latest_parsed_document_status"),
        }
        if row.get("latest_parsed_document_id")
        else None,
        "latest_evidence": {
            "id": row.get("latest_evidence_id"),
            "text_excerpt": _truncate_review_text(row.get("latest_evidence_text_excerpt"), 500),
            "page_no": row.get("latest_evidence_page_no"),
        }
        if row.get("latest_evidence_id")
        else None,
        "debug_ref": _debug_ref("attachment", row["id"]),
    }


def _review_attachment_parse_readiness(row: dict[str, Any]) -> dict[str, Any]:
    metadata_json = row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else {}
    text_source, text_value = _review_attachment_available_text(metadata_json)
    text_available = bool(text_value)
    binary_or_document = _review_attachment_is_binary_or_document(row)
    settings = get_settings()
    image_supported = is_supported_multimodal_image(row)
    image_constraints = multimodal_image_constraints(
        max_count=settings.image_multimodal_max_count,
        max_upload_bytes=settings.image_multimodal_max_upload_bytes,
        max_side=settings.image_multimodal_max_side,
        target_bytes=settings.image_multimodal_target_bytes,
    )
    blocking_reasons: list[str] = []
    recommended_actions: list[str] = []
    parsed_text_length = _optional_int(metadata_json.get("last_text_length"))
    already_parsed = (
        row.get("parse_status") == "parsed"
        or row.get("latest_parsed_document_status") == "parsed"
        or parsed_text_length > 0
        or bool(metadata_json.get("last_evidence_id"))
    )

    if already_parsed:
        readiness_status = "parsed"
        expected_parse_status = "parsed"
        text_source = "parsed_document"
        recommended_actions.append("View the parsed document/evidence or continue business update processing.")
        if text_value:
            recommended_actions.append("Retry OCR only if the parsed text looks incomplete or stale.")
    elif text_available:
        readiness_status = "ready"
        expected_parse_status = "parsed"
        recommended_actions.append("Start OCR parsing; v0.1 will use the available text as OCR output.")
    elif image_supported:
        readiness_status = "ready_for_multimodal"
        expected_parse_status = "skipped"
        recommended_actions.append(
            "Use business update processing with the multimodal LLM; image evidence will be recorded as model excerpts."
        )
        if int(row.get("file_size") or 0) > settings.image_multimodal_max_upload_bytes:
            readiness_status = "blocked"
            blocking_reasons.append("Image exceeds the multimodal per-image upload limit.")
            recommended_actions.append("Compress the image before processing.")
    elif binary_or_document:
        readiness_status = "blocked"
        expected_parse_status = "skipped"
        blocking_reasons.append("No extracted text is available for this binary/document attachment.")
        blocking_reasons.append("PDF OCR requires object storage and the configured OCR provider.")
        recommended_actions.append("Upload a text-like file or provide mock_extracted_text for current testing.")
        recommended_actions.append("For PDFs, start OCR; text PDFs are extracted locally and scanned PDFs use Doc2X.")
    else:
        readiness_status = "needs_text"
        expected_parse_status = "skipped"
        blocking_reasons.append("No extracted text is available for this attachment.")
        recommended_actions.append("Upload a supported text-like file or provide mock_extracted_text.")

    return {
        "readiness_status": readiness_status,
        "can_parse_now": text_available,
        "expected_parse_status": expected_parse_status,
        "available_text_source": text_source,
        "text_available": text_available or already_parsed,
        "text_preview": _truncate_review_text(text_value, 240) if text_value else None,
        "storage_backend": metadata_json.get("storage_backend"),
        "storage_uri": metadata_json.get("storage_uri") or row.get("storage_path"),
        "content_sha256": metadata_json.get("content_sha256"),
        "parsed_document_id": str(row.get("latest_parsed_document_id") or metadata_json.get("last_parsed_document_id") or "")
        or None,
        "evidence_id": str(row.get("latest_evidence_id") or metadata_json.get("last_evidence_id") or "") or None,
        "parsed_text_length": parsed_text_length,
        "is_binary_or_document": binary_or_document,
        "multimodal_image_supported": image_supported,
        "multimodal_image_constraints": image_constraints,
        "blocking_reasons": blocking_reasons,
        "recommended_actions": recommended_actions,
    }


def _review_attachment_available_text(metadata_json: dict[str, Any]) -> tuple[str | None, str | None]:
    for key in ("mock_extracted_text", "uploaded_text_content"):
        value = metadata_json.get(key)
        if value is not None and str(value).strip():
            return key, str(value).strip()
    return None, None


def _review_attachment_is_binary_or_document(row: dict[str, Any]) -> bool:
    file_type = str(row.get("file_type") or "").lower()
    mime_type = str(row.get("mime_type") or "").split(";")[0].strip().lower()
    return (
        file_type in {"pdf", "png", "jpg", "jpeg", "webp", "doc", "docx", "xls", "xlsx", "ppt", "pptx"}
        or mime_type.startswith("image/")
        or mime_type in {
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-powerpoint",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
    )


def _collect_entity_ids(
    seed_values: Any,
    actions: list[dict[str, Any]],
    *,
    target_entity_type: str,
    proposed_change_keys: list[str],
) -> list[UUID]:
    ids: list[UUID] = []
    for value in seed_values if isinstance(seed_values, list) else []:
        parsed = _optional_uuid(value)
        if parsed and parsed not in ids:
            ids.append(parsed)
    for action in actions:
        if action.get("target_entity_type") == target_entity_type:
            parsed = _optional_uuid(action.get("target_entity_id"))
            if parsed and parsed not in ids:
                ids.append(parsed)
        changes = action.get("proposed_changes_json") or {}
        if not isinstance(changes, dict):
            continue
        for key in proposed_change_keys:
            parsed = _optional_uuid(changes.get(key))
            if parsed and parsed not in ids:
                ids.append(parsed)
    return ids


def _target_snapshot_key(entity_type: Any, entity_id: Any) -> str:
    return f"{entity_type}:{entity_id}"


def _debug_ref(entity_type: str, entity_id: Any) -> dict[str, str]:
    entity_id_text = str(entity_id)
    return {
        "entity_type": entity_type,
        "entity_id": entity_id_text,
        "route": f"/debug/entities/{entity_type}/{entity_id_text}",
    }


def _entity_ref(entity_type: str, entity_id: Any) -> dict[str, Any]:
    entity_id_text = str(entity_id)
    route_map = {
        "seller_target": f"/targets/{entity_id_text}",
        "buyer_intent": f"/buyer-intents/{entity_id_text}",
        "buyer_party": f"/buyers/{entity_id_text}",
        "buyer_seller_relation": f"/relations/{entity_id_text}",
        "recommendation_session": f"/recommendations/sessions/{entity_id_text}",
    }
    debug_supported = {
        "business_update",
        "background_job",
        "model_node_config",
        "recommendation_session",
        "recommendation_report",
    }
    return {
        "entity_type": entity_type,
        "entity_id": entity_id_text,
        "route": route_map.get(entity_type),
        "debug_ref": _debug_ref(entity_type, entity_id_text) if entity_type in debug_supported else None,
    }


def _history_route(entity_type: Any, entity_id: Any) -> str | None:
    if not entity_type or not entity_id:
        return None
    base_route = _entity_ref(str(entity_type), entity_id).get("route")
    if not base_route:
        return None
    if entity_type in {"seller_target", "buyer_intent", "buyer_party"}:
        return f"{base_route}?tab=history"
    return base_route


def _truncate_review_text(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    if len(text_value) <= max_length:
        return text_value
    return text_value[: max_length - 1] + "…"


def _optional_uuid(value: Any) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _uuid_list(value: Any) -> list[UUID]:
    if not isinstance(value, list):
        return []
    result: list[UUID] = []
    for item in value:
        parsed = _optional_uuid(item)
        if parsed:
            result.append(parsed)
    return result


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe_value(item) for item in value]
    return value
