from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.db import get_db
from backend.app.registry.indicators import GROUPS, indicators_for

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/indicators")
def list_indicators(entity: str = "seller_target") -> dict[str, Any]:
    """The indicator registry as the frontend renders it: groups + display fields.

    Structure (which fields, their group, label, kind, screening badge, and how
    province/city fold together) comes from here; value formatting stays in the
    frontend. Adding a field to the registry makes it appear on the page.
    """
    indicators = indicators_for(entity)
    return {
        "groups": [
            {"key": group.key, "label": group.label, "section_code": group.section_code}
            for group in GROUPS
        ],
        "indicators": [
            {
                "column": ind.column,
                "label": ind.label,
                "group": ind.group,
                "kind": ind.kind,
                "screening": ind.screening,
                "fold_into": ind.fold_into,
            }
            for ind in indicators
            if ind.group is not None
        ],
    }


@router.get("/version")
def version() -> dict[str, Any]:
    return _version_payload()


def _version_payload() -> dict[str, Any]:
    settings = get_settings()
    return {
        "app": settings.app_name,
        "environment": settings.app_env,
        "railway": {
            "service_name": settings.railway_service_name,
            "environment_name": settings.railway_environment_name,
            "git_branch": settings.railway_git_branch,
            "git_commit_sha": settings.railway_git_commit_sha,
        },
    }


@router.get("/seed-status")
def seed_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    default_team_id = "00000000-0000-0000-0000-000000000001"
    default_workspace_id = "00000000-0000-0000-0000-000000000101"
    default_admin_id = "00000000-0000-0000-0000-000000000201"

    checks = {
        "default_team": _exists(db, "team", default_team_id),
        "default_workspace": _exists(db, "workspace", default_workspace_id),
        "default_admin_user": _exists(db, "app_user", default_admin_id),
    }

    industry_terms = int(
        db.execute(
            text("select count(*) from industry_taxonomy where active = true")
        ).scalar_one()
    )

    ok = all(checks.values()) and industry_terms > 0

    return {
        "status": "ok" if ok else "degraded",
        "checks": checks,
        "industry_taxonomy_terms": industry_terms,
    }


@router.get("/ai-infra-status")
def ai_infra_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = get_settings()
    required_tables = [
        "model_provider_config",
        "model_node_config",
        "prompt_template",
        "background_job",
        "ai_trace",
    ]
    table_checks = {table: _table_exists(db, table) for table in required_tables}

    provider_counts = _count_by_query(
        db,
        """
        select count(*)
        from model_provider_config
        where is_active = true
        """,
        enabled=table_checks["model_provider_config"],
    )
    node_counts = _count_by_query(
        db,
        """
        select count(*)
        from model_node_config
        where is_active = true
        """,
        enabled=table_checks["model_node_config"],
    )
    prompt_counts = _count_by_query(
        db,
        """
        select count(*)
        from prompt_template
        where is_active = true
        """,
        enabled=table_checks["prompt_template"],
    )

    default_provider = _row_exists(
        db,
        """
        select exists(
          select 1
          from model_provider_config
          where is_active = true
            and coalesce(base_url, '') <> ''
            and (
              (coalesce(secret_mode, 'env') = 'env' and api_key_secret_ref is not null)
              or (secret_mode = 'direct' and api_key_encrypted is not null)
            )
        )
        """,
        enabled=table_checks["model_provider_config"],
    )
    default_llm_nodes = _count_by_query(
        db,
        """
        select count(*)
        from model_node_config
        where node_name in (
            'business_update_extractor',
            'seller_target_parser',
            'seller_target_update_parser',
            'buyer_intent_parser',
            'buyer_intent_update_parser',
            'recommendation_deep_eval',
            'recommendation_report_writer'
          )
          and node_type = 'llm'
          and is_default = true
          and is_active = true
        """,
        enabled=table_checks["model_node_config"],
    )
    default_deep_eval_nodes = _count_by_query(
        db,
        """
        select count(*)
        from model_node_config
        where node_name = 'recommendation_deep_eval'
          and node_type = 'llm'
          and is_default = true
          and is_active = true
        """,
        enabled=table_checks["model_node_config"],
    )
    default_ocr_nodes = _count_by_query(
        db,
        """
        select count(*)
        from model_node_config
        where node_name = 'ocr_attachment_parser'
          and node_type = 'ocr'
          and is_default = true
          and is_active = true
        """,
        enabled=table_checks["model_node_config"],
    )
    active_retired_recommendation_nodes = _count_by_query(
        db,
        """
        select count(*)
        from model_node_config
        where node_name in (
            'embedding_seller_doc',
            'embedding_buyer_intent',
            'recommendation_reranker'
          )
          and is_active = true
        """,
        enabled=table_checks["model_node_config"],
    )
    default_prompts = _count_by_query(
        db,
        """
        select count(*)
        from prompt_template
        where node_name in (
            'business_update_extractor',
            'seller_target_parser',
            'seller_target_update_parser',
            'buyer_intent_parser',
            'buyer_intent_update_parser',
            'recommendation_deep_eval',
            'recommendation_report_writer'
          )
          and is_default = true
          and is_active = true
        """,
        enabled=table_checks["prompt_template"],
    )
    real_business_update_prompt = _row_exists(
        db,
        """
        select exists(
          select 1
          from prompt_template
          where node_name = 'business_update_extractor'
            and is_default = true
            and is_active = true
        )
        """,
        enabled=table_checks["prompt_template"],
    )

    buyer_intent_update_allowed = _action_type_allowed(db, "buyer_intent_update")
    buyer_intent_suggestion_allowed = _action_type_allowed(db, "buyer_intent_suggestion")

    checks = {
        "tables": table_checks,
        "default_provider": default_provider,
        "required_llm_nodes": default_llm_nodes >= 7,
        "default_deep_eval_node": default_deep_eval_nodes >= 1,
        "default_ocr_nodes": default_ocr_nodes >= 1,
        "retired_recommendation_nodes_inactive": active_retired_recommendation_nodes == 0,
        "required_prompts": default_prompts >= 7,
        "real_business_update_prompt": real_business_update_prompt,
        "buyer_intent_update_allowed": buyer_intent_update_allowed,
        "buyer_intent_suggestion_removed": not buyer_intent_suggestion_allowed,
    }

    ok = (
        all(table_checks.values())
        and default_provider
        and default_llm_nodes >= 7
        and default_deep_eval_nodes >= 1
        and default_ocr_nodes >= 1
        and active_retired_recommendation_nodes == 0
        and default_prompts >= 7
        and real_business_update_prompt
        and buyer_intent_update_allowed
        and not buyer_intent_suggestion_allowed
    )

    return {
        "status": "ok" if ok else "degraded",
        "version": _version_payload(),
        "checks": checks,
        "counts": {
            "active_providers": provider_counts,
            "active_nodes": node_counts,
            "active_prompts": prompt_counts,
            "required_llm_nodes": default_llm_nodes,
            "default_deep_eval_nodes": default_deep_eval_nodes,
            "default_ocr_nodes": default_ocr_nodes,
            "active_retired_recommendation_nodes": active_retired_recommendation_nodes,
            "required_prompts": default_prompts,
        },
        "storage": {
            "attachment_storage_backend": settings.effective_attachment_storage_backend,
            "s3_configured": settings.attachment_s3_configured,
            "s3_endpoint_configured": bool(settings.effective_attachment_s3_endpoint_url),
            "s3_bucket_configured": bool(settings.effective_attachment_s3_bucket),
            "s3_access_key_configured": bool(settings.effective_attachment_s3_access_key_id),
            "s3_secret_key_configured": bool(settings.effective_attachment_s3_secret_access_key),
        },
        "ocr": {
            "provider": settings.ocr_provider,
            "doc2x_configured": bool(settings.effective_doc2x_api_key),
            "doc2x_base_url_configured": bool(settings.doc2x_base_url),
            "doc2x_model": settings.doc2x_model,
            "pdf_text_detection_page_limit": settings.pdf_text_detection_page_limit,
            "pdf_text_detection_min_chars": settings.pdf_text_detection_min_chars,
        },
        "business_update_upload": {
            "supported_input_types": ["text", "screenshot", "attachment", "mixed"],
            "max_upload_bytes_per_attachment": settings.attachment_max_upload_bytes,
            "image_supported_types": ["image/jpeg", "image/png", "image/webp"],
            "image_max_count_per_business_update": settings.image_multimodal_max_count,
            "image_max_upload_bytes_per_image": settings.image_multimodal_max_upload_bytes,
            "image_model_preprocess_max_side_px": settings.image_multimodal_max_side,
            "image_model_preprocess_target_bytes": settings.image_multimodal_target_bytes,
            "image_ocr_policy": "Images are linked as multimodal LLM evidence and are not sent to OCR.",
            "pdf_policy": "Text PDFs are extracted locally; scanned PDFs are sent to Doc2X when OCR_PROVIDER=doc2x.",
            "office_policy": "DOCX/XLSX/PPTX files are extracted locally from OOXML text before business update processing.",
        },
    }


def _exists(db: Session, table_name: str, entity_id: str) -> bool:
    if table_name not in {"team", "workspace", "app_user"}:
        raise ValueError(f"Unsupported table for seed check: {table_name}")

    result = db.execute(
        text(f"select exists(select 1 from {table_name} where id = :entity_id)"),
        {"entity_id": entity_id},
    )
    return bool(result.scalar_one())


def _table_exists(db: Session, table_name: str) -> bool:
    allowed_tables = {
        "model_provider_config",
        "model_node_config",
        "prompt_template",
        "background_job",
        "ai_trace",
    }
    if table_name not in allowed_tables:
        raise ValueError(f"Unsupported table for AI infra check: {table_name}")

    result = db.execute(
        text("select to_regclass(:table_name)"),
        {"table_name": f"public.{table_name}"},
    )
    return result.scalar_one() is not None


def _count_by_query(db: Session, query: str, *, enabled: bool) -> int:
    if not enabled:
        return 0
    return int(db.execute(text(query)).scalar_one())


def _row_exists(db: Session, query: str, *, enabled: bool) -> bool:
    if not enabled:
        return False
    return bool(db.execute(text(query)).scalar_one())


def _action_type_allowed(db: Session, action_type: str) -> bool:
    result = db.execute(
        text(
            """
            select exists(
              select 1
              from pg_constraint c
              join pg_class t on t.oid = c.conrelid
              where t.relname = 'extracted_action'
                and c.contype = 'c'
                and pg_get_constraintdef(c.oid) like :pattern
            )
            """
        ),
        {"pattern": f"%{action_type}%"},
    )
    return bool(result.scalar_one())
