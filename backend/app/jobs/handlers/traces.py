from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID, SYSTEM_USER_ID
from backend.app.jobs.queue import JobClaim
from backend.app.services.json_values import json_safe_value


def _insert_llm_trace(
    db: Session,
    *,
    job: JobClaim,
    business_update_id: UUID,
    node_config: dict[str, Any],
    status: str,
    input_json: dict[str, Any],
    prompt_messages_json: list[dict[str, str]],
    raw_output_text: str | None,
    parsed_output_json: dict[str, Any] | None,
    schema_validation_json: dict[str, Any],
    latency_ms: int,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    node_name = str(node_config.get("node_name") or "business_update_extractor")
    db.execute(
        text(
            """
            insert into ai_trace (
              team_id, workspace_id, trace_type, node_name,
              job_id, correlation_id, entity_type, entity_id,
              provider_config_id, node_config_id, prompt_template_id,
              provider_name, model_name, prompt_version, status,
              input_json, prompt_messages_json, raw_output_text,
              parsed_output_json, output_schema_json, schema_validation_json,
              error_code, error_message, latency_ms, prompt_tokens,
              completion_tokens, total_tokens, created_by, finished_at,
              metadata_json
            )
            values (
              :team_id, :workspace_id, 'llm', :node_name,
              :job_id, :correlation_id, 'business_update', :business_update_id,
              :provider_config_id, :node_config_id, :prompt_template_id,
              :provider_name, :model_name, :prompt_version, :status,
              :input_json, :prompt_messages_json, :raw_output_text,
              :parsed_output_json, :output_schema_json, :schema_validation_json,
              :error_code, :error_message, :latency_ms, :prompt_tokens,
              :completion_tokens, :total_tokens, :created_by, now(),
              :metadata_json
            )
            """
        ).bindparams(
            bindparam("input_json", type_=JSONB),
            bindparam("prompt_messages_json", type_=JSONB),
            bindparam("parsed_output_json", type_=JSONB),
            bindparam("output_schema_json", type_=JSONB),
            bindparam("schema_validation_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "node_name": node_name,
            "job_id": job.id,
            "correlation_id": job.correlation_id,
            "business_update_id": business_update_id,
            "provider_config_id": node_config["provider_config_id"],
            "node_config_id": node_config["node_config_id"],
            "prompt_template_id": node_config["prompt_template_id"],
            "provider_name": node_config["provider_name"],
            "model_name": node_config["model_name"],
            "prompt_version": node_config["prompt_version"],
            "status": status,
            "input_json": json_safe_value(input_json),
            "prompt_messages_json": prompt_messages_json,
            "raw_output_text": raw_output_text,
            "parsed_output_json": parsed_output_json,
            "output_schema_json": node_config["output_schema_json"] or {},
            "schema_validation_json": schema_validation_json,
            "error_code": error_code,
            "error_message": error_message,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "created_by": SYSTEM_USER_ID,
            "metadata_json": {"source": node_name},
        },
    )

def _insert_buyer_intent_parse_trace(
    db: Session,
    *,
    job: JobClaim,
    buyer_intent_id: UUID,
    node_config: dict[str, Any],
    status: str,
    input_json: dict[str, Any],
    prompt_messages_json: list[dict[str, str]],
    raw_output_text: str | None,
    parsed_output_json: dict[str, Any] | None,
    schema_validation_json: dict[str, Any],
    latency_ms: int,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    node_name = str(node_config.get("node_name") or "buyer_intent_parser")
    db.execute(
        text(
            """
            insert into ai_trace (
              team_id, workspace_id, trace_type, node_name,
              job_id, correlation_id, entity_type, entity_id,
              provider_config_id, node_config_id, prompt_template_id,
              provider_name, model_name, prompt_version, status,
              input_json, prompt_messages_json, raw_output_text,
              parsed_output_json, output_schema_json, schema_validation_json,
              error_code, error_message, latency_ms, prompt_tokens,
              completion_tokens, total_tokens, created_by, finished_at,
              metadata_json
            )
            values (
              :team_id, :workspace_id, 'llm', :node_name,
              :job_id, :correlation_id, 'buyer_intent', :buyer_intent_id,
              :provider_config_id, :node_config_id, :prompt_template_id,
              :provider_name, :model_name, :prompt_version, :status,
              :input_json, :prompt_messages_json, :raw_output_text,
              :parsed_output_json, :output_schema_json, :schema_validation_json,
              :error_code, :error_message, :latency_ms, :prompt_tokens,
              :completion_tokens, :total_tokens, :created_by, now(),
              :metadata_json
            )
            """
        ).bindparams(
            bindparam("input_json", type_=JSONB),
            bindparam("prompt_messages_json", type_=JSONB),
            bindparam("parsed_output_json", type_=JSONB),
            bindparam("output_schema_json", type_=JSONB),
            bindparam("schema_validation_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "node_name": node_name,
            "job_id": job.id,
            "correlation_id": job.correlation_id,
            "buyer_intent_id": buyer_intent_id,
            "provider_config_id": node_config["provider_config_id"],
            "node_config_id": node_config["node_config_id"],
            "prompt_template_id": node_config["prompt_template_id"],
            "provider_name": node_config["provider_name"],
            "model_name": node_config["model_name"],
            "prompt_version": node_config["prompt_version"],
            "status": status,
            "input_json": input_json,
            "prompt_messages_json": prompt_messages_json,
            "raw_output_text": raw_output_text,
            "parsed_output_json": parsed_output_json,
            "output_schema_json": node_config["output_schema_json"] or {},
            "schema_validation_json": schema_validation_json,
            "error_code": error_code,
            "error_message": error_message,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "created_by": SYSTEM_USER_ID,
            "metadata_json": {"source": node_name},
        },
    )

def _insert_seller_target_parse_trace(
    db: Session,
    *,
    job: JobClaim,
    seller_target_id: UUID,
    node_config: dict[str, Any],
    status: str,
    input_json: dict[str, Any],
    prompt_messages_json: list[dict[str, str]],
    raw_output_text: str | None,
    parsed_output_json: dict[str, Any] | None,
    schema_validation_json: dict[str, Any],
    latency_ms: int,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    db.execute(
        text(
            """
            insert into ai_trace (
              team_id, workspace_id, trace_type, node_name,
              job_id, correlation_id, entity_type, entity_id,
              provider_config_id, node_config_id, prompt_template_id,
              provider_name, model_name, prompt_version, status,
              input_json, prompt_messages_json, raw_output_text,
              parsed_output_json, output_schema_json, schema_validation_json,
              error_code, error_message, latency_ms, prompt_tokens,
              completion_tokens, total_tokens, created_by, finished_at,
              metadata_json
            )
            values (
              :team_id, :workspace_id, 'llm', 'seller_target_parser',
              :job_id, :correlation_id, 'seller_target', :seller_target_id,
              :provider_config_id, :node_config_id, :prompt_template_id,
              :provider_name, :model_name, :prompt_version, :status,
              :input_json, :prompt_messages_json, :raw_output_text,
              :parsed_output_json, :output_schema_json, :schema_validation_json,
              :error_code, :error_message, :latency_ms, :prompt_tokens,
              :completion_tokens, :total_tokens, :created_by, now(),
              :metadata_json
            )
            """
        ).bindparams(
            bindparam("input_json", type_=JSONB),
            bindparam("prompt_messages_json", type_=JSONB),
            bindparam("parsed_output_json", type_=JSONB),
            bindparam("output_schema_json", type_=JSONB),
            bindparam("schema_validation_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "job_id": job.id,
            "correlation_id": job.correlation_id,
            "seller_target_id": seller_target_id,
            "provider_config_id": node_config["provider_config_id"],
            "node_config_id": node_config["node_config_id"],
            "prompt_template_id": node_config["prompt_template_id"],
            "provider_name": node_config["provider_name"],
            "model_name": node_config["model_name"],
            "prompt_version": node_config["prompt_version"],
            "status": status,
            "input_json": input_json,
            "prompt_messages_json": prompt_messages_json,
            "raw_output_text": raw_output_text,
            "parsed_output_json": parsed_output_json,
            "output_schema_json": node_config["output_schema_json"] or {},
            "schema_validation_json": schema_validation_json,
            "error_code": error_code,
            "error_message": error_message,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "created_by": SYSTEM_USER_ID,
            "metadata_json": {"source": "seller_target_parser"},
        },
    )

def _insert_model_node_test_trace(
    db: Session,
    *,
    job: JobClaim,
    node_config: dict[str, Any],
    trace_type: str,
    status: str,
    input_json: dict[str, Any],
    prompt_messages_json: list[dict[str, str]] | None = None,
    raw_output_text: str | None = None,
    parsed_output_json: dict[str, Any] | None = None,
    latency_ms: int | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    db.execute(
        text(
            """
            insert into ai_trace (
              team_id, workspace_id, trace_type, node_name,
              job_id, correlation_id, entity_type, entity_id,
              provider_config_id, node_config_id,
              provider_name, model_name, status,
              input_json, prompt_messages_json, raw_output_text,
              parsed_output_json, schema_validation_json,
              error_code, error_message, latency_ms, prompt_tokens,
              completion_tokens, total_tokens, created_by, finished_at, metadata_json
            )
            values (
              :team_id, :workspace_id, :trace_type, :node_name,
              :job_id, :correlation_id, 'model_node_config', :node_config_id,
              :provider_config_id, :node_config_id,
              :provider_name, :model_name, :status,
              :input_json, :prompt_messages_json, :raw_output_text,
              :parsed_output_json, :schema_validation_json,
              :error_code, :error_message, :latency_ms, :prompt_tokens,
              :completion_tokens, :total_tokens, :created_by, now(), :metadata_json
            )
            """
        ).bindparams(
            bindparam("input_json", type_=JSONB),
            bindparam("prompt_messages_json", type_=JSONB),
            bindparam("parsed_output_json", type_=JSONB),
            bindparam("schema_validation_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "trace_type": trace_type,
            "node_name": node_config["node_name"],
            "job_id": job.id,
            "correlation_id": job.correlation_id,
            "node_config_id": node_config["node_config_id"],
            "provider_config_id": node_config["provider_config_id"],
            "provider_name": node_config["provider_name"],
            "model_name": node_config["model_name"],
            "status": status,
            "input_json": input_json,
            "prompt_messages_json": prompt_messages_json or [],
            "raw_output_text": raw_output_text,
            "parsed_output_json": json_safe_value(parsed_output_json),
            "schema_validation_json": json_safe_value(
                {"valid": status in {"succeeded", "skipped"}}
            ),
            "error_code": error_code,
            "error_message": error_message,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "created_by": SYSTEM_USER_ID,
            "metadata_json": {"source": "model_node_test"},
        },
    )

def _insert_ocr_trace(
    db: Session,
    *,
    job: JobClaim,
    attachment_id: UUID,
    node_config: dict[str, Any],
    status: str,
    input_json: dict[str, Any],
    raw_output_text: str | None,
    parsed_output_json: dict[str, Any] | None,
    latency_ms: int,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    db.execute(
        text(
            """
            insert into ai_trace (
              team_id, workspace_id, trace_type, node_name,
              job_id, correlation_id, entity_type, entity_id,
              provider_config_id, node_config_id,
              provider_name, model_name, status,
              input_json, raw_output_text, parsed_output_json,
              schema_validation_json, error_code, error_message,
              latency_ms, created_by, finished_at, metadata_json
            )
            values (
              :team_id, :workspace_id, 'ocr', :node_name,
              :job_id, :correlation_id, 'attachment', :attachment_id,
              :provider_config_id, :node_config_id,
              :provider_name, :model_name, :status,
              :input_json, :raw_output_text, :parsed_output_json,
              :schema_validation_json, :error_code, :error_message,
              :latency_ms, :created_by, now(), :metadata_json
            )
            """
        ).bindparams(
            bindparam("input_json", type_=JSONB),
            bindparam("parsed_output_json", type_=JSONB),
            bindparam("schema_validation_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "node_name": node_config["node_name"],
            "job_id": job.id,
            "correlation_id": job.correlation_id,
            "attachment_id": attachment_id,
            "provider_config_id": node_config["provider_config_id"],
            "node_config_id": node_config["node_config_id"],
            "provider_name": node_config["provider_name"],
            "model_name": node_config["model_name"],
            "status": status,
            "input_json": json_safe_value(input_json),
            "raw_output_text": raw_output_text,
            "parsed_output_json": json_safe_value(parsed_output_json),
            "schema_validation_json": json_safe_value(
                {"valid": status in {"succeeded", "skipped"}}
            ),
            "error_code": error_code,
            "error_message": error_message,
            "latency_ms": latency_ms,
            "created_by": SYSTEM_USER_ID,
            "metadata_json": json_safe_value(
                {"source": "attachment_ocr_parse", "execution_mode": "skeleton"}
            ),
        },
    )

def _insert_embedding_trace(
    db: Session,
    *,
    job: JobClaim,
    entity_type: str,
    entity_id: UUID,
    node_config: dict[str, Any],
    status: str,
    input_json: dict[str, Any],
    parsed_output_json: dict[str, Any] | None,
    latency_ms: int,
    prompt_tokens: int | None = None,
    total_tokens: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    db.execute(
        text(
            """
            insert into ai_trace (
              team_id, workspace_id, trace_type, node_name,
              job_id, correlation_id, entity_type, entity_id,
              provider_config_id, node_config_id,
              provider_name, model_name, status,
              input_json, parsed_output_json, schema_validation_json,
              error_code, error_message, latency_ms, prompt_tokens,
              total_tokens, created_by, finished_at, metadata_json
            )
            values (
              :team_id, :workspace_id, 'embedding', :node_name,
              :job_id, :correlation_id, :entity_type, :entity_id,
              :provider_config_id, :node_config_id,
              :provider_name, :model_name, :status,
              :input_json, :parsed_output_json, :schema_validation_json,
              :error_code, :error_message, :latency_ms, :prompt_tokens,
              :total_tokens, :created_by, now(), :metadata_json
            )
            """
        ).bindparams(
            bindparam("input_json", type_=JSONB),
            bindparam("parsed_output_json", type_=JSONB),
            bindparam("schema_validation_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "node_name": node_config["node_name"],
            "job_id": job.id,
            "correlation_id": job.correlation_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "provider_config_id": node_config["provider_config_id"],
            "node_config_id": node_config["node_config_id"],
            "provider_name": node_config["provider_name"],
            "model_name": node_config["model_name"],
            "status": status,
            "input_json": {
                **input_json,
                "text_preview": (input_json.get("text") or "")[:1000],
                "text": None,
            },
            "parsed_output_json": parsed_output_json,
            "schema_validation_json": {"valid": status in {"succeeded", "skipped"}},
            "error_code": error_code,
            "error_message": error_message,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "total_tokens": total_tokens,
            "created_by": SYSTEM_USER_ID,
            "metadata_json": {"source": "embedding_generate"},
        },
    )
