"""买家主体的「AI 补全信息」入口：上传材料、触发链路、读取进度。

一次点击对应三个 job（解析 →（可选）调研 → 规范化），它们共用一个
``correlation_id``；进度是**从 job 表派生**的，这里不写任何状态列。
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser
from backend.app.api.routes.utils import (
    attachment_visible_sql,
    ensure_entity_visible,
    ensure_entity_writable,
)
# OCR 入队与附件落库这两件事已经有实现，这里复用而不是抄一份：抄一份的表现是
# 「另一条上传路径的 ocr_policy 元数据缺失」，而那会让图片被送进 OCR。
from backend.app.api.routes.attachments import _enqueue_attachment_ocr_job
from backend.app.config import get_settings
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db
from backend.app.jobs.handlers.buyer_party_ingest import (
    LLM_QUEUE_NAME,
    PARSE_JOB_TYPE,
    RESEARCH_JOB_TYPE,
    RESEARCH_QUEUE_NAME,
    NORMALIZE_JOB_TYPE,
    PARSER_NODE_NAME,
    RESEARCHER_NODE_NAME,
    NORMALIZER_NODE_NAME,
    buyer_party_refresh_targets,
    enqueue_buyer_party_ingest_job,
)
from backend.app.jobs.handlers.common import _get_default_node_config
from backend.app.services.attachment_storage import (
    AttachmentStorageError,
    AttachmentTooLargeError,
    save_upload_file,
)
from backend.app.services.business_update_flow import (
    _link_attachment_if_missing,
    _should_auto_ocr_uploaded_attachment,
    _upload_ocr_policy,
)
from backend.app.services.buyer_party_processing_state import buyer_party_ingest_state
from backend.app.services.image_inputs import (
    is_supported_multimodal_image,
    multimodal_image_constraints,
)
from backend.app.services.search_service import get_default_search_provider

router = APIRouter(prefix="/buyer-parties", tags=["buyer-parties"])


class BuyerPartyMaterialAttachmentOut(BaseModel):
    attachment_id: UUID
    file_name: str
    file_type: str | None
    file_size: int | None
    ocr_policy: str
    is_image: bool
    ocr_job_id: UUID | None = None


class BuyerPartyMaterialUploadOut(BaseModel):
    buyer_party_id: UUID
    attachments: list[BuyerPartyMaterialAttachmentOut]
    attachment_ids: list[UUID]
    image_attachment_ids: list[UUID]
    # 图片上限是 5 张，超出的会被静默截断且不报错，所以这个约束必须能被界面读到。
    image_constraints: dict[str, Any]


class BuyerPartyParseRequest(BaseModel):
    raw_text: str | None = Field(default=None, max_length=200_000)
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=20)
    # 默认不勾（用户 0825 决定）：联网调研要 5–10 分钟且要花钱。
    enable_research: bool = False
    mode: Literal["fill", "refresh"] = "fill"
    refresh_fields: list[str] = Field(default_factory=list, max_length=8)
    force: bool = False


class BuyerPartyIngestJobOut(BaseModel):
    job_id: UUID
    job_type: str
    status: str
    queue_name: str
    buyer_party_id: UUID
    correlation_id: UUID
    reused_existing: bool = False


class BuyerPartyBatchParseRequest(BaseModel):
    buyer_party_ids: list[UUID] = Field(min_length=1, max_length=50)
    enable_research: bool = True
    mode: Literal["fill", "refresh"] = "refresh"


class BuyerPartyBatchParseOut(BaseModel):
    jobs: list[BuyerPartyIngestJobOut]
    queued_count: int
    reused_count: int


class BuyerPartyIngestStatusOut(BaseModel):
    buyer_party_id: UUID
    state: dict[str, Any]
    nodes_ready: dict[str, bool]
    search_provider_ready: bool


@router.post(
    "/{buyer_party_id}/materials",
    response_model=BuyerPartyMaterialUploadOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_buyer_party_materials(
    buyer_party_id: UUID,
    current_user: CurrentUser,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """把材料文件挂到买家主体上，并按类型决定走不走 OCR。

    文档进 doc2x 异步 OCR，图片**不进 OCR**，留给解析节点直读多模态 ——
    这条策略只维护在 ``_upload_ocr_policy`` 一处。
    """
    _ensure_party_writable(db, current_user, buyer_party_id)
    settings = get_settings()
    if len(files) > settings.business_update_max_upload_files:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"一次最多上传 {settings.business_update_max_upload_files} 个文件。",
        )

    uploaded: list[dict[str, Any]] = []
    for file in files:
        attachment_id = uuid4()
        original_file_name = file.filename or "upload.bin"
        try:
            stored = save_upload_file(
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
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
            ) from exc
        except AttachmentStorageError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            ) from exc

        ocr_policy = _upload_ocr_policy(stored.file_type, file.content_type)
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
                returning id, file_name, file_type, mime_type, file_size, metadata_json
                """
            ).bindparams(bindparam("metadata_json", type_=JSONB)),
            {
                "id": attachment_id,
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "file_name": original_file_name[:500],
                "file_type": stored.file_type,
                "mime_type": file.content_type,
                "file_size": stored.file_size,
                "storage_path": stored.storage_uri,
                "uploaded_by": current_user.user_id,
                "metadata_json": {
                    **stored.metadata_json(),
                    "uploaded_via": "buyer_party_material_upload",
                    "ocr_policy": ocr_policy,
                },
            },
        ).mappings().one()
        attachment = dict(row)
        _link_attachment_if_missing(
            db, attachment_id, "buyer_party", buyer_party_id, "source_document"
        )
        ocr_job = None
        if _should_auto_ocr_uploaded_attachment(attachment):
            ocr_job = _enqueue_attachment_ocr_job(
                db,
                attachment_id=attachment_id,
                force=False,
                mock_extracted_text=None,
                # 解析由 /parse 显式触发（它还要带上粘贴文本、图片与是否联网），
                # 所以这里不让 OCR 自己扇出。
                auto_parse_linked_objects=False,
                parse_entity_types=[],
                source="buyer_party_material_upload",
            )
        uploaded.append(
            {
                "attachment_id": attachment_id,
                "file_name": attachment.get("file_name") or original_file_name,
                "file_type": attachment.get("file_type"),
                "file_size": attachment.get("file_size"),
                "ocr_policy": ocr_policy,
                "is_image": is_supported_multimodal_image(attachment),
                "ocr_job_id": ocr_job["id"] if ocr_job else None,
            }
        )
    db.commit()
    return {
        "buyer_party_id": buyer_party_id,
        "attachments": uploaded,
        "attachment_ids": [item["attachment_id"] for item in uploaded],
        "image_attachment_ids": [item["attachment_id"] for item in uploaded if item["is_image"]],
        "image_constraints": multimodal_image_constraints(
            max_count=settings.image_multimodal_max_count,
            max_upload_bytes=settings.image_multimodal_max_upload_bytes,
            max_side=settings.image_multimodal_max_side,
            target_bytes=settings.image_multimodal_target_bytes,
        ),
    }


@router.post(
    "/batch-parse",
    response_model=BuyerPartyBatchParseOut,
    status_code=status.HTTP_201_CREATED,
)
def batch_parse_buyer_parties(
    payload: BuyerPartyBatchParseRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """批量补全 / 刷新。没有 cron，所以刷新是被动触发的可重入调用。"""
    jobs: list[dict[str, Any]] = []
    reused = 0
    for party_id in dict.fromkeys(payload.buyer_party_ids):
        _ensure_party_writable(db, current_user, party_id)
        job = _start_ingest(
            db,
            party_id=party_id,
            user_id=current_user.user_id,
            raw_text=None,
            attachment_ids=[],
            enable_research=payload.enable_research,
            mode=payload.mode,
            refresh_fields=[],
            force=False,
        )
        jobs.append(job)
        reused += int(bool(job["reused_existing"]))
    db.commit()
    return {"jobs": jobs, "queued_count": len(jobs) - reused, "reused_count": reused}


@router.post(
    "/{buyer_party_id}/parse",
    response_model=BuyerPartyIngestJobOut,
    status_code=status.HTTP_201_CREATED,
)
def parse_buyer_party(
    buyer_party_id: UUID,
    current_user: CurrentUser,
    payload: BuyerPartyParseRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _ensure_party_writable(db, current_user, buyer_party_id)
    request = payload or BuyerPartyParseRequest()
    attachment_ids = list(dict.fromkeys(request.attachment_ids))
    _link_materials_to_party(
        db, buyer_party_id=buyer_party_id, current_user=current_user, attachment_ids=attachment_ids
    )
    job = _start_ingest(
        db,
        party_id=buyer_party_id,
        user_id=current_user.user_id,
        raw_text=request.raw_text,
        attachment_ids=attachment_ids,
        enable_research=request.enable_research,
        mode=request.mode,
        refresh_fields=request.refresh_fields,
        force=request.force,
    )
    db.commit()
    return job


def _link_materials_to_party(
    db: Session,
    *,
    buyer_party_id: UUID,
    current_user: Any,
    attachment_ids: list[UUID],
) -> None:
    """把这次带进来的附件补链到买家主体上。

    一份文件常常两条链都要用（一份材料里既写了这家公司是谁、也写了它要买什么），
    而附件是独立表、`attachment_link` 是多对多、OCR 按 attachment 入队 —— 所以
    「都用」的正确形态是**一次上传两条链接**，不是传两遍、OCR 两遍。

    但少了这一步会**静默丢文件**：`_load_material_attachments` 硬要求
    `entity_type='buyer_party' and entity_id=:party_id`，传一个没链到本主体的
    attachment_id 进去返回零行、不报错，界面上看不出材料没被读。

    可见性按附件自己的规则判：不加这道检查，猜到一个 attachment_id 就能把别人的
    文件读进自己的买家资料里。链接本身幂等，重复调用不会长出第二行。
    """
    if not attachment_ids:
        return
    visible = db.execute(
        text(
            f"""
            select a.id
            from attachment a
            where a.team_id = :team_id
              and a.workspace_id = :workspace_id
              and a.deleted_at is null
              and a.id = any(:attachment_ids)
              and ({attachment_visible_sql("a")})
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "attachment_ids": attachment_ids,
            "scope_user_id": current_user.user_id,
        },
    ).scalars().all()
    missing = [item for item in attachment_ids if item not in set(visible)]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"这些附件不存在或无权访问：{[str(item) for item in missing]}",
        )
    for attachment_id in visible:
        _link_attachment_if_missing(
            db, attachment_id, "buyer_party", buyer_party_id, "source_document"
        )


@router.get("/{buyer_party_id}/parse-status", response_model=BuyerPartyIngestStatusOut)
def get_buyer_party_parse_status(
    buyer_party_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_entity_visible(db, current_user, entity_type="buyer_party", entity_id=buyer_party_id)
    _get_party_or_404(db, buyer_party_id)
    return {
        "buyer_party_id": buyer_party_id,
        "state": buyer_party_ingest_state(db, buyer_party_id),
        # 没配节点这条链跑不起来。界面要能在点之前就说清楚，而不是让人等一个失败。
        "nodes_ready": {
            "parser": _node_ready(db, PARSER_NODE_NAME),
            "researcher": _node_ready(db, RESEARCHER_NODE_NAME),
            "normalizer": _node_ready(db, NORMALIZER_NODE_NAME),
        },
        "search_provider_ready": get_default_search_provider(db) is not None,
    }


def _start_ingest(
    db: Session,
    *,
    party_id: UUID,
    user_id: UUID,
    raw_text: str | None,
    attachment_ids: list[UUID],
    enable_research: bool,
    mode: str,
    refresh_fields: list[str],
    force: bool,
) -> dict[str, Any]:
    """四种组合的行为都在这里定死。

    | 有材料 | 勾选联网 | 行为 |
    | --- | --- | --- |
    | ✅ | ❌ | 阶段1 → 阶段3 |
    | ✅ | ✅ | 阶段1 → 阶段2 → 阶段3 |
    | ❌ | ✅ | 跳过阶段1，直接阶段2（缺口 = 全部可调研字段）→ 阶段3 |
    | ❌ | ❌ | **400**，没有任何信息来源 |
    """
    party = _get_party_or_404(db, party_id)
    text_value = (raw_text or "").strip()
    has_material = bool(text_value or attachment_ids)
    if mode == "refresh":
        # 刷新只查财务数字、不重新认公司，所以它必须联网，也不走解析那一段。
        enable_research = True
        has_material = False
    if not has_material and not enable_research:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="没有任何信息来源：请粘贴材料、上传附件，或勾选「联网补全」。",
        )

    if not force:
        existing = _latest_active_ingest_job(db, party_id)
        if existing:
            return {
                "job_id": existing["id"],
                "job_type": existing["job_type"],
                "status": existing["status"],
                "queue_name": existing["queue_name"],
                "buyer_party_id": party_id,
                "correlation_id": existing["correlation_id"] or existing["id"],
                "reused_existing": True,
            }

    if has_material:
        _ensure_node_ready(db, PARSER_NODE_NAME, "买家主体解析")
    if enable_research:
        _ensure_node_ready(db, RESEARCHER_NODE_NAME, "买家主体 AI 调研")
        if get_default_search_provider(db) is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="尚未配置搜索供应商，请先在设置页配置联网搜索。",
            )
    if has_material and enable_research:
        # 归一节点只在「材料 + 联网」两个来源都有时才被调用（它的活是调和）。
        # 单来源时收口由代码直译，缺它不影响这一轮。
        _ensure_node_ready(db, NORMALIZER_NODE_NAME, "买家主体信息规范化")

    correlation_id = uuid4()
    if has_material:
        row = enqueue_buyer_party_ingest_job(
            db,
            job_type=PARSE_JOB_TYPE,
            party_id=party_id,
            payload_json={
                "buyer_party_id": str(party_id),
                "raw_text": text_value or None,
                "attachment_ids": [str(item) for item in attachment_ids],
                "enable_research": enable_research,
                "mode": mode,
                "refresh_fields": refresh_fields,
            },
            queue_name=LLM_QUEUE_NAME,
            correlation_id=correlation_id,
            created_by=user_id,
            source="buyer_party_parse_api",
            priority=100,
        )
    else:
        row = enqueue_buyer_party_ingest_job(
            db,
            job_type=RESEARCH_JOB_TYPE,
            party_id=party_id,
            payload_json={
                "buyer_party_id": str(party_id),
                "mode": mode,
                "parse_job_id": None,
                "refresh_fields": refresh_fields or (
                    buyer_party_refresh_targets(party) if mode == "refresh" else []
                ),
            },
            queue_name=RESEARCH_QUEUE_NAME,
            correlation_id=correlation_id,
            created_by=user_id,
            source="buyer_party_research_api",
            priority=45,
        )
    return {
        "job_id": row["id"],
        "job_type": row["job_type"],
        "status": row["status"],
        "queue_name": row["queue_name"],
        "buyer_party_id": party_id,
        "correlation_id": correlation_id,
        "reused_existing": False,
    }


def _latest_active_ingest_job(db: Session, party_id: UUID) -> dict[str, Any] | None:
    """并发保护：有正在跑的链就返回那一条，除非 force。

    派生态没有僵死问题，所以这里不需要「解锁」工具 —— 任务终止了，
    这个查询自然就查不到活跃行了。
    """
    row = db.execute(
        text(
            """
            select id, job_type, status, queue_name, correlation_id
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = 'buyer_party'
              and entity_id = :party_id
              and job_type in :job_types
              and status in ('queued', 'running', 'retry_waiting')
            order by created_at desc
            limit 1
            """
        ).bindparams(bindparam("job_types", expanding=True)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "party_id": party_id,
            "job_types": (PARSE_JOB_TYPE, RESEARCH_JOB_TYPE, NORMALIZE_JOB_TYPE),
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _node_ready(db: Session, node_name: str) -> bool:
    try:
        _get_default_node_config(db, node_name)
    except ValueError:
        return False
    return True


def _ensure_node_ready(db: Session, node_name: str, label: str) -> None:
    if not _node_ready(db, node_name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"尚未配置「{label}」节点及其 Prompt，请先在设置页创建。",
        )


def _ensure_party_writable(db: Session, current_user: CurrentUser, party_id: UUID) -> None:
    ensure_entity_writable(db, current_user, entity_type="buyer_party", entity_id=party_id)


def _get_party_or_404(db: Session, party_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select id, buyer_name, listed_status,
                   market_cap_as_of::text as market_cap_as_of,
                   financial_period_label
            from buyer_party
            where id = :party_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "party_id": party_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Buyer party not found.")
    return dict(row)
