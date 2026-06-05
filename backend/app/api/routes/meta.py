from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.db import get_db

router = APIRouter(prefix="/meta", tags=["meta"])


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

    dictionaries = {
        "industry": _count_dictionary(db, "industry"),
        "deal_path": _count_dictionary(db, "deal_path"),
        "payment_method": _count_dictionary(db, "payment_method"),
        "control_path": _count_dictionary(db, "control_path"),
        "risk": _count_dictionary(db, "risk"),
    }

    region_alias_count = db.execute(
        text("select count(*) from region_alias_config where is_active = true")
    ).scalar_one()

    ok = all(checks.values()) and dictionaries["industry"] > 0 and dictionaries["risk"] > 0

    return {
        "status": "ok" if ok else "degraded",
        "checks": checks,
        "dictionary_counts": dictionaries,
        "region_alias_count": region_alias_count,
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
          where provider_name = 'aliyun_dashscope'
            and api_key_secret_ref = 'ALIYUN_API_KEY'
            and is_active = true
        )
        """,
        enabled=table_checks["model_provider_config"],
    )
    default_llm_nodes = _count_by_query(
        db,
        """
        select count(*)
        from model_node_config
        where model_name = 'qwen3.6-plus'
          and node_type = 'llm'
          and is_default = true
          and is_active = true
        """,
        enabled=table_checks["model_node_config"],
    )
    default_rerank_nodes = _count_by_query(
        db,
        """
        select count(*)
        from model_node_config
        where node_name = 'recommendation_reranker'
          and node_type = 'rerank'
          and model_name = 'qwen3-rerank'
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
    default_embedding_nodes = _count_by_query(
        db,
        """
        select count(*)
        from model_node_config
        where model_name = 'text-embedding-v4'
          and embedding_dimension = 1024
          and is_default = true
          and is_active = true
        """,
        enabled=table_checks["model_node_config"],
    )
    default_prompts = _count_by_query(
        db,
        """
        select count(*)
        from prompt_template
        where (
            (node_name = 'business_update_extractor' and version in ('v0.2.0', 'v0.3.0'))
            or (node_name = 'buyer_intent_parser' and version in ('v0.1.0', 'v0.2.0'))
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
            and version in ('v0.2.0', 'v0.3.0')
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
        "default_llm_nodes": default_llm_nodes >= 3,
        "default_rerank_nodes": default_rerank_nodes >= 1,
        "default_ocr_nodes": default_ocr_nodes >= 1,
        "default_embedding_nodes": default_embedding_nodes >= 2,
        "default_prompts": default_prompts >= 2,
        "real_business_update_prompt": real_business_update_prompt,
        "buyer_intent_update_allowed": buyer_intent_update_allowed,
        "buyer_intent_suggestion_removed": not buyer_intent_suggestion_allowed,
    }

    ok = (
        all(table_checks.values())
        and default_provider
        and default_llm_nodes >= 3
        and default_rerank_nodes >= 1
        and default_ocr_nodes >= 1
        and default_embedding_nodes >= 2
        and default_prompts >= 2
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
            "default_llm_nodes": default_llm_nodes,
            "default_rerank_nodes": default_rerank_nodes,
            "default_ocr_nodes": default_ocr_nodes,
            "default_embedding_nodes": default_embedding_nodes,
            "default_prompts": default_prompts,
        },
        "storage": {
            "attachment_storage_backend": settings.effective_attachment_storage_backend,
            "s3_configured": settings.attachment_s3_configured,
            "s3_endpoint_configured": bool(settings.effective_attachment_s3_endpoint_url),
            "s3_bucket_configured": bool(settings.effective_attachment_s3_bucket),
            "s3_access_key_configured": bool(settings.effective_attachment_s3_access_key_id),
            "s3_secret_key_configured": bool(settings.effective_attachment_s3_secret_access_key),
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


def _count_dictionary(db: Session, domain: str) -> int:
    result = db.execute(
        text(
            """
            select count(*)
            from tag_dictionary
            where domain = :domain
              and is_active = true
            """
        ),
        {"domain": domain},
    )
    return int(result.scalar_one())


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
