import json
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db
from backend.app.services.attachment_storage import (
    AttachmentStorageError,
    AttachmentTooLargeError,
    save_upload_file,
)

router = APIRouter(prefix="/attachments", tags=["attachments"])

ATTACHMENT_VISIBILITY_VALUES = {"workspace", "team", "private"}
ATTACHMENT_PARSE_STATUS_VALUES = {"pending", "parsing", "parsed", "failed", "skipped"}
ATTACHMENT_LINK_ENTITY_TYPES = {
    "seller_target",
    "buyer_party",
    "buyer_intent",
    "business_update",
    "recommendation_session",
    "recommendation_report",
}


class AttachmentLinkCreate(BaseModel):
    entity_type: str = Field(min_length=1, max_length=80)
    entity_id: UUID
    link_type: str | None = Field(default="source_document", max_length=80)


class AttachmentCreate(BaseModel):
    file_name: str = Field(min_length=1, max_length=500)
    storage_path: str = Field(min_length=1, max_length=2000)
    visibility: str = "workspace"
    file_type: str | None = Field(default=None, max_length=80)
    mime_type: str | None = Field(default=None, max_length=200)
    file_size: int | None = Field(default=None, ge=0)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    links: list[AttachmentLinkCreate] = Field(default_factory=list)
    entity_type: str | None = Field(default=None, max_length=80)
    entity_id: UUID | None = None
    link_type: str | None = Field(default=None, max_length=80)


class AttachmentLinkOut(BaseModel):
    id: UUID
    attachment_id: UUID
    entity_type: str
    entity_id: UUID
    link_type: str | None
    created_at: str
    created_by: UUID | None


class AttachmentOut(BaseModel):
    id: UUID
    visibility: str
    file_name: str
    file_type: str | None
    mime_type: str | None
    file_size: int | None
    storage_path: str
    uploaded_by: UUID | None
    uploaded_at: str
    parse_status: str
    metadata_json: dict[str, Any]
    deleted_at: str | None
    links: list[AttachmentLinkOut] = Field(default_factory=list)


class AttachmentOcrRequest(BaseModel):
    force: bool = False
    mock_extracted_text: str | None = Field(default=None, max_length=200000)
    auto_parse_linked_objects: bool = False
    parse_entity_types: list[str] = Field(default_factory=list)


class AttachmentOcrJobOut(BaseModel):
    job_id: UUID
    job_type: str
    status: str
    queue_name: str
    attachment_id: UUID
    reused_existing: bool = False


class AttachmentUploadOut(BaseModel):
    attachment: AttachmentOut
    ocr_job: AttachmentOcrJobOut | None = None


class AttachmentOcrStatusOut(BaseModel):
    attachment: AttachmentOut
    linked_entities: list[dict[str, Any]]
    latest_job: dict[str, Any] | None
    latest_trace: dict[str, Any] | None
    latest_parsed_document: dict[str, Any] | None
    evidence_spans: list[dict[str, Any]]
    child_parse_jobs: list[dict[str, Any]] = Field(default_factory=list)
    debug_ref: dict[str, Any]


ATTACHMENT_SELECT_COLUMNS = """
      id, visibility, file_name, file_type, mime_type, file_size, storage_path,
      uploaded_by, uploaded_at::text as uploaded_at, parse_status, metadata_json,
      deleted_at::text as deleted_at
"""


@router.post("", response_model=AttachmentOut, status_code=status.HTTP_201_CREATED)
def create_attachment(payload: AttachmentCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    _validate_attachment_payload(payload)
    links = _attachment_link_payloads(payload)
    for link in links:
        _validate_attachment_link(db, link)

    row = db.execute(
        text(
            f"""
            insert into attachment (
              team_id, workspace_id, visibility, file_name, file_type, mime_type,
              file_size, storage_path, uploaded_by, metadata_json
            )
            values (
              :team_id, :workspace_id, :visibility, :file_name, :file_type, :mime_type,
              :file_size, :storage_path, :uploaded_by, :metadata_json
            )
            returning
{ATTACHMENT_SELECT_COLUMNS}
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
            "metadata_json": _json_safe_value(payload.metadata_json),
        },
    ).mappings().one()
    attachment = dict(row)

    for link in links:
        _insert_attachment_link(db, attachment["id"], link)

    db.commit()
    return _attachment_with_links(db, attachment["id"])


@router.post("/upload", response_model=AttachmentUploadOut, status_code=status.HTTP_201_CREATED)
def upload_attachment(
    file: UploadFile = File(...),
    visibility: str = Form(default="workspace"),
    entity_type: str | None = Form(default=None),
    entity_id: UUID | None = Form(default=None),
    link_type: str | None = Form(default="source_document"),
    auto_start_ocr: bool = Form(default=False),
    auto_parse_linked_objects: bool = Form(default=False),
    parse_entity_types: str | None = Form(default=None),
    metadata_json: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if visibility not in ATTACHMENT_VISIBILITY_VALUES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid visibility.")
    if entity_id and not entity_type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="entity_type is required when entity_id is provided.",
        )
    links = []
    if entity_type and entity_id:
        link = AttachmentLinkCreate(entity_type=entity_type, entity_id=entity_id, link_type=link_type)
        _validate_attachment_link(db, link)
        links.append(link)

    parse_types = _parse_entity_types_form(parse_entity_types)
    _validate_parse_entity_types(parse_types)
    form_metadata = _parse_metadata_json_form(metadata_json)

    settings = get_settings()
    attachment_id = uuid4()
    original_file_name = file.filename or "upload.bin"
    try:
        uploaded = save_upload_file(
            file.file,
            attachment_id=attachment_id,
            original_file_name=original_file_name,
            content_type=file.content_type,
            storage_dir=settings.attachment_storage_dir,
            storage_backend=settings.attachment_storage_backend,
            max_bytes=settings.attachment_max_upload_bytes,
            text_capture_max_bytes=settings.attachment_text_capture_max_bytes,
        )
    except AttachmentTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except AttachmentStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        ) from exc

    metadata = {
        **form_metadata,
        **uploaded.metadata_json(),
    }

    row = db.execute(
        text(
            f"""
            insert into attachment (
              id, team_id, workspace_id, visibility, file_name, file_type, mime_type,
              file_size, storage_path, uploaded_by, metadata_json
            )
            values (
              :id, :team_id, :workspace_id, :visibility, :file_name, :file_type, :mime_type,
              :file_size, :storage_path, :uploaded_by, :metadata_json
            )
            returning
{ATTACHMENT_SELECT_COLUMNS}
            """
        ).bindparams(bindparam("metadata_json", type_=JSONB)),
        {
            "id": attachment_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "visibility": visibility,
            "file_name": original_file_name[:500],
            "file_type": uploaded.file_type,
            "mime_type": file.content_type,
            "file_size": uploaded.file_size,
            "storage_path": uploaded.storage_uri,
            "uploaded_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": _json_safe_value(metadata),
        },
    ).mappings().one()

    for link in links:
        _insert_attachment_link(db, attachment_id, link)

    ocr_job = None
    if auto_start_ocr:
        ocr_job = _enqueue_attachment_ocr_job(
            db,
            attachment_id=attachment_id,
            force=False,
            mock_extracted_text=None,
            auto_parse_linked_objects=auto_parse_linked_objects,
            parse_entity_types=parse_types,
            source="attachment_upload_auto_ocr",
        )

    db.commit()
    return {
        "attachment": _attachment_with_links(db, row["id"]),
        "ocr_job": _ocr_job_out(ocr_job) if ocr_job else None,
    }


@router.get("", response_model=list[AttachmentOut])
def list_attachments(
    db: Session = Depends(get_db),
    parse_status: str | None = Query(default=None),
    entity_type: str | None = Query(default=None, max_length=80),
    entity_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    if parse_status and parse_status not in ATTACHMENT_PARSE_STATUS_VALUES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid parse_status.")
    if entity_type and entity_type not in ATTACHMENT_LINK_ENTITY_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid entity_type.")

    where = ["a.team_id = :team_id", "a.workspace_id = :workspace_id", "a.deleted_at is null"]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
        "offset": offset,
    }
    if parse_status:
        where.append("a.parse_status = :parse_status")
        params["parse_status"] = parse_status
    if entity_type:
        where.append(
            """
            exists (
              select 1
              from attachment_link al
              where al.attachment_id = a.id
                and al.team_id = a.team_id
                and al.workspace_id = a.workspace_id
                and al.entity_type = :entity_type
                and (:entity_id is null or al.entity_id = :entity_id)
            )
            """
        )
        params["entity_type"] = entity_type
        params["entity_id"] = entity_id
    elif entity_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="entity_type is required when entity_id is provided.",
        )

    rows = db.execute(
        text(
            """
            select
              a.id, a.visibility, a.file_name, a.file_type, a.mime_type, a.file_size,
              a.storage_path, a.uploaded_by, a.uploaded_at::text as uploaded_at,
              a.parse_status, a.metadata_json, a.deleted_at::text as deleted_at
            from attachment a
            where {where}
            order by a.uploaded_at desc
            limit :limit offset :offset
            """.format(where=" and ".join(where))
        ),
        params,
    ).mappings().all()
    return [_attach_links_to_row(db, dict(row)) for row in rows]


@router.get("/{attachment_id}", response_model=AttachmentOut)
def get_attachment(attachment_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _attachment_with_links(db, attachment_id)


@router.post("/{attachment_id}/ocr", response_model=AttachmentOcrJobOut)
def create_attachment_ocr_job(
    attachment_id: UUID,
    payload: AttachmentOcrRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    request = payload or AttachmentOcrRequest()
    _get_attachment_or_404(db, attachment_id)
    _validate_parse_entity_types(request.parse_entity_types)
    row = _enqueue_attachment_ocr_job(
        db,
        attachment_id=attachment_id,
        force=request.force,
        mock_extracted_text=request.mock_extracted_text,
        auto_parse_linked_objects=request.auto_parse_linked_objects,
        parse_entity_types=request.parse_entity_types,
        source="attachment_ocr_api",
    )
    db.commit()
    return _ocr_job_out(row)


@router.get("/{attachment_id}/ocr-status", response_model=AttachmentOcrStatusOut)
def get_attachment_ocr_status(
    attachment_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    attachment = _attachment_with_links(db, attachment_id)
    latest_job = _latest_ocr_job(db, attachment_id)
    latest_trace = _latest_ocr_trace(db, attachment_id)
    parsed_document = _latest_parsed_document(db, attachment_id)
    evidence_spans = _evidence_spans(db, attachment_id)
    child_parse_jobs = _child_parse_jobs(db, latest_job["id"]) if latest_job else []
    return {
        "attachment": attachment,
        "linked_entities": _linked_entity_refs(attachment["links"]),
        "latest_job": _compact_ocr_job(latest_job) if latest_job else None,
        "latest_trace": _compact_ocr_trace(latest_trace) if latest_trace else None,
        "latest_parsed_document": _compact_parsed_document(parsed_document) if parsed_document else None,
        "evidence_spans": [_compact_evidence_span(item) for item in evidence_spans],
        "child_parse_jobs": [_compact_child_parse_job(item) for item in child_parse_jobs],
        "debug_ref": _debug_ref("attachment", attachment_id),
    }


def _enqueue_attachment_ocr_job(
    db: Session,
    *,
    attachment_id: UUID,
    force: bool,
    mock_extracted_text: str | None,
    auto_parse_linked_objects: bool,
    parse_entity_types: list[str],
    source: str,
) -> dict[str, Any]:
    if not force:
        existing_job = _latest_active_ocr_job(db, attachment_id)
        if existing_job:
            return {**existing_job, "reused_existing": True}

    row = db.execute(
        text(
            """
            insert into background_job (
              team_id, workspace_id, job_type, priority, queue_name,
              entity_type, entity_id, idempotency_key, payload_json,
              max_attempts, created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, 'attachment_ocr_parse', 100, 'ocr',
              'attachment', :attachment_id, :idempotency_key, :payload_json,
              1, :created_by, :metadata_json
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
            "idempotency_key": f"attachment_ocr_parse:{attachment_id}:{uuid4()}",
            "payload_json": {
                "attachment_id": str(attachment_id),
                "mock_extracted_text": mock_extracted_text,
                "auto_parse_linked_objects": auto_parse_linked_objects,
                "parse_entity_types": parse_entity_types,
            },
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {"source": source, "force": force},
        },
    ).mappings().one()
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
                "last_ocr_job_id": str(row["id"]),
                "last_ocr_status": "queued",
            },
        },
    )
    return {**dict(row), "reused_existing": False}


def _ocr_job_out(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": row["id"],
        "job_type": row["job_type"],
        "status": row["status"],
        "queue_name": row["queue_name"],
        "attachment_id": row["entity_id"],
        "reused_existing": row.get("reused_existing", False),
    }


def _validate_attachment_payload(payload: AttachmentCreate) -> None:
    if payload.visibility not in ATTACHMENT_VISIBILITY_VALUES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid visibility.")
    if payload.entity_id and not payload.entity_type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="entity_type is required when entity_id is provided.",
        )


def _validate_parse_entity_types(parse_entity_types: list[str]) -> None:
    supported = {"seller_target", "buyer_intent"}
    invalid = [item for item in parse_entity_types if item not in supported]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported OCR auto-parse entity types: {', '.join(invalid)}",
        )


def _attachment_link_payloads(payload: AttachmentCreate) -> list[AttachmentLinkCreate]:
    links = list(payload.links)
    if payload.entity_type and payload.entity_id:
        links.append(
            AttachmentLinkCreate(
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
                link_type=payload.link_type or "source_document",
            )
        )

    unique: dict[tuple[str, str, str | None], AttachmentLinkCreate] = {}
    for link in links:
        key = (link.entity_type, str(link.entity_id), link.link_type)
        unique[key] = link
    return list(unique.values())


def _validate_attachment_link(db: Session, link: AttachmentLinkCreate) -> None:
    if link.entity_type not in ATTACHMENT_LINK_ENTITY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported attachment link entity_type: {link.entity_type}",
        )
    if not _linked_entity_exists(db, link.entity_type, link.entity_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Linked entity not found: {link.entity_type}/{link.entity_id}",
        )


def _parse_entity_types_form(value: str | None) -> list[str]:
    if not value:
        return []
    stripped = value.strip()
    if not stripped:
        return []
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
    return parsed


def _linked_entity_exists(db: Session, entity_type: str, entity_id: UUID) -> bool:
    table_map = {
        "seller_target": "seller_target",
        "buyer_party": "buyer_party",
        "buyer_intent": "buyer_intent",
        "business_update": "business_update",
        "recommendation_session": "recommendation_session",
        "recommendation_report": "recommendation_report",
    }
    table_name = table_map[entity_type]
    deleted_clause = "and deleted_at is null" if entity_type in {"seller_target", "buyer_party", "buyer_intent"} else ""
    return bool(
        db.execute(
            text(
                f"""
                select exists(
                  select 1
                  from {table_name}
                  where id = :entity_id
                    and team_id = :team_id
                    and workspace_id = :workspace_id
                    {deleted_clause}
                )
                """
            ),
            {
                "entity_id": entity_id,
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
            },
        ).scalar_one()
    )


def _insert_attachment_link(db: Session, attachment_id: UUID, link: AttachmentLinkCreate) -> None:
    db.execute(
        text(
            """
            insert into attachment_link (
              team_id, workspace_id, attachment_id, entity_type, entity_id, link_type, created_by
            )
            values (
              :team_id, :workspace_id, :attachment_id, :entity_type, :entity_id, :link_type, :created_by
            )
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "attachment_id": attachment_id,
            "entity_type": link.entity_type,
            "entity_id": link.entity_id,
            "link_type": link.link_type,
            "created_by": DEFAULT_ADMIN_USER_ID,
        },
    )


def _get_attachment_or_404(db: Session, attachment_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            f"""
            select
{ATTACHMENT_SELECT_COLUMNS}
            from attachment
            where id = :attachment_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "attachment_id": attachment_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found.")
    return dict(row)


def _attachment_with_links(db: Session, attachment_id: UUID) -> dict[str, Any]:
    return _attach_links_to_row(db, _get_attachment_or_404(db, attachment_id))


def _attach_links_to_row(db: Session, attachment: dict[str, Any]) -> dict[str, Any]:
    attachment["links"] = _attachment_links(db, attachment["id"])
    return attachment


def _attachment_links(db: Session, attachment_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, attachment_id, entity_type, entity_id, link_type,
              created_at::text as created_at, created_by
            from attachment_link
            where attachment_id = :attachment_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            order by created_at asc
            """
        ),
        {
            "attachment_id": attachment_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _latest_active_ocr_job(db: Session, attachment_id: UUID) -> dict[str, Any] | None:
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
              and status in ('queued', 'running', 'retry_waiting')
            order by created_at desc
            limit 1
            """
        ),
        {
            "attachment_id": attachment_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _latest_ocr_job(db: Session, attachment_id: UUID) -> dict[str, Any] | None:
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
              and job_type = 'attachment_ocr_parse'
              and entity_type = 'attachment'
              and entity_id = :attachment_id
            order by created_at desc
            limit 1
            """
        ),
        {
            "attachment_id": attachment_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _latest_ocr_trace(db: Session, attachment_id: UUID) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select
              id, trace_type, node_name, job_id, provider_name, model_name,
              status, raw_output_text, parsed_output_json, schema_validation_json,
              error_code, error_message, latency_ms, prompt_tokens, completion_tokens,
              total_tokens, started_at::text as started_at, finished_at::text as finished_at
            from ai_trace
            where team_id = :team_id
              and workspace_id = :workspace_id
              and trace_type = 'ocr'
              and entity_type = 'attachment'
              and entity_id = :attachment_id
            order by started_at desc
            limit 1
            """
        ),
        {
            "attachment_id": attachment_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _latest_parsed_document(db: Session, attachment_id: UUID) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select
              id, attachment_id, parser_name, parser_version, parse_status,
              text_path, markdown_path, manifest_path, page_count, token_count,
              error_message, created_at::text as created_at, updated_at::text as updated_at
            from parsed_document
            where team_id = :team_id
              and workspace_id = :workspace_id
              and attachment_id = :attachment_id
            order by created_at desc
            limit 1
            """
        ),
        {
            "attachment_id": attachment_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _evidence_spans(db: Session, attachment_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, source_type, source_id, attachment_id, parsed_document_id,
              page_no, slide_no, sheet_name, cell_range, text_excerpt,
              char_start, char_end, created_at::text as created_at
            from evidence_span
            where team_id = :team_id
              and workspace_id = :workspace_id
              and attachment_id = :attachment_id
            order by created_at desc
            limit 100
            """
        ),
        {
            "attachment_id": attachment_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _child_parse_jobs(db: Session, ocr_job_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
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
              and parent_job_id = :ocr_job_id
            order by created_at asc
            limit 50
            """
        ),
        {
            "ocr_job_id": ocr_job_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _compact_ocr_job(job: dict[str, Any]) -> dict[str, Any]:
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


def _compact_child_parse_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job["id"],
        "job_type": job["job_type"],
        "status": job["status"],
        "queue_name": job["queue_name"],
        "entity_type": job.get("entity_type"),
        "entity_id": job.get("entity_id"),
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
        "target_debug_ref": _debug_ref(job.get("entity_type"), job.get("entity_id"))
        if job.get("entity_type") and job.get("entity_id")
        else None,
    }


def _compact_ocr_trace(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": trace["id"],
        "trace_type": trace["trace_type"],
        "node_name": trace["node_name"],
        "job_id": trace.get("job_id"),
        "provider_name": trace.get("provider_name"),
        "model_name": trace.get("model_name"),
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


def _compact_parsed_document(parsed_document: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": parsed_document["id"],
        "attachment_id": parsed_document["attachment_id"],
        "parser_name": parsed_document.get("parser_name"),
        "parser_version": parsed_document.get("parser_version"),
        "parse_status": parsed_document["parse_status"],
        "text_path": parsed_document.get("text_path"),
        "markdown_path": parsed_document.get("markdown_path"),
        "manifest_path": parsed_document.get("manifest_path"),
        "page_count": parsed_document.get("page_count"),
        "token_count": parsed_document.get("token_count"),
        "error_message": parsed_document.get("error_message"),
        "created_at": parsed_document.get("created_at"),
        "updated_at": parsed_document.get("updated_at"),
    }


def _compact_evidence_span(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": evidence["id"],
        "source_type": evidence["source_type"],
        "source_id": evidence.get("source_id"),
        "attachment_id": evidence.get("attachment_id"),
        "parsed_document_id": evidence.get("parsed_document_id"),
        "page_no": evidence.get("page_no"),
        "text_excerpt": evidence.get("text_excerpt"),
        "char_start": evidence.get("char_start"),
        "char_end": evidence.get("char_end"),
        "created_at": evidence.get("created_at"),
    }


def _linked_entity_refs(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "entity_type": link["entity_type"],
            "entity_id": str(link["entity_id"]),
            "link_type": link.get("link_type"),
            "route": _entity_route(link["entity_type"], link["entity_id"]),
            "debug_ref": _debug_ref(link["entity_type"], link["entity_id"]),
        }
        for link in links
    ]


def _entity_route(entity_type: str, entity_id: Any) -> str | None:
    entity_id_text = str(entity_id)
    routes = {
        "seller_target": f"/targets/{entity_id_text}",
        "buyer_party": f"/buyers/{entity_id_text}",
        "buyer_intent": f"/buyer-intents/{entity_id_text}",
        "business_update": f"/updates/{entity_id_text}",
        "recommendation_session": f"/recommendations/sessions/{entity_id_text}",
        "recommendation_report": f"/recommendations/reports/{entity_id_text}",
    }
    return routes.get(entity_type)


def _debug_ref(entity_type: str, entity_id: Any) -> dict[str, str]:
    entity_id_text = str(entity_id)
    return {
        "entity_type": entity_type,
        "entity_id": entity_id_text,
        "route": f"/debug/entities/{entity_type}/{entity_id_text}",
    }


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _truncate_text(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    if len(text_value) <= max_length:
        return text_value
    return text_value[: max_length - 3] + "..."


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe_value(item) for item in value]
    return value
