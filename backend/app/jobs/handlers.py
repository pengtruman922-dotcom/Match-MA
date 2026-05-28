from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.jobs.queue import JobClaim


def execute_job(db: Session, job: JobClaim) -> dict[str, object]:
    if job.job_type == "business_update_extract_actions":
        return _handle_business_update_extract_actions(db, job)

    return {
        "handled": False,
        "job_type": job.job_type,
        "message": "No real job handler is implemented for this job type yet.",
    }


def _handle_business_update_extract_actions(db: Session, job: JobClaim) -> dict[str, object]:
    started = time.perf_counter()
    business_update_id = _resolve_business_update_id(job)
    if business_update_id is None:
        raise ValueError("business_update_extract_actions job requires a business_update_id.")

    business_update = db.execute(
        text(
            """
            select
              id, raw_text, input_type, processing_status,
              bound_seller_target_ids_json, bound_buyer_party_ids_json,
              bound_buyer_intent_ids_json, bound_recommendation_session_id,
              metadata_json
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
    if business_update is None:
        raise ValueError(f"Business update not found: {business_update_id}")

    node_config = _get_default_node_config(db, "business_update_extractor")
    input_json = {
        "business_update_id": str(business_update["id"]),
        "raw_text": business_update["raw_text"],
        "input_type": business_update["input_type"],
        "bound_seller_target_ids": business_update["bound_seller_target_ids_json"],
        "bound_buyer_party_ids": business_update["bound_buyer_party_ids_json"],
        "bound_buyer_intent_ids": business_update["bound_buyer_intent_ids_json"],
        "bound_recommendation_session_id": (
            str(business_update["bound_recommendation_session_id"])
            if business_update["bound_recommendation_session_id"]
            else None
        ),
    }
    parsed_output_json = {
        "actions": [],
        "extraction_status": "placeholder",
        "message": "Placeholder handler completed; real LLM extraction is not implemented yet.",
    }
    latency_ms = int((time.perf_counter() - started) * 1000)

    _insert_placeholder_trace(
        db,
        job=job,
        business_update_id=business_update_id,
        node_config=node_config,
        input_json=input_json,
        parsed_output_json=parsed_output_json,
        latency_ms=latency_ms,
    )

    db.execute(
        text(
            """
            update business_update
            set processing_status = 'parsed',
                metadata_json = metadata_json || :metadata_patch
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
                "last_processed_job_id": str(job.id),
                "last_processing_result": "placeholder_parsed",
            },
        },
    )

    return {
        "handled": True,
        "job_type": job.job_type,
        "business_update_id": str(business_update_id),
        "actions_created": 0,
        "trace_created": True,
        "message": "Placeholder handler completed; real LLM extraction is not implemented yet.",
    }


def _resolve_business_update_id(job: JobClaim) -> UUID | None:
    if job.entity_type == "business_update" and job.entity_id is not None:
        return job.entity_id

    payload_value = job.payload_json.get("business_update_id")
    if not payload_value:
        return None
    return UUID(str(payload_value))


def _get_default_node_config(db: Session, node_name: str) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              node.id as node_config_id,
              node.model_name,
              provider.id as provider_config_id,
              provider.provider_name,
              prompt.id as prompt_template_id,
              prompt.version as prompt_version,
              prompt.output_schema_json
            from model_node_config node
            join model_provider_config provider
              on provider.id = node.provider_config_id
            left join prompt_template prompt
              on prompt.team_id = node.team_id
             and prompt.workspace_id = node.workspace_id
             and prompt.node_name = node.node_name
             and prompt.is_default = true
            where node.team_id = :team_id
              and node.workspace_id = :workspace_id
              and node.node_name = :node_name
              and node.is_default = true
              and node.is_active = true
            limit 1
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "node_name": node_name,
        },
    ).mappings().one_or_none()
    if row is None:
        return {
            "node_config_id": None,
            "model_name": "placeholder",
            "provider_config_id": None,
            "provider_name": "placeholder",
            "prompt_template_id": None,
            "prompt_version": "v0.1.0",
            "output_schema_json": {},
        }
    return dict(row)


def _insert_placeholder_trace(
    db: Session,
    *,
    job: JobClaim,
    business_update_id: UUID,
    node_config: dict[str, Any],
    input_json: dict[str, Any],
    parsed_output_json: dict[str, Any],
    latency_ms: int,
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
              latency_ms, created_by, finished_at, metadata_json
            )
            values (
              :team_id, :workspace_id, 'parser', 'business_update_extractor',
              :job_id, :correlation_id, 'business_update', :business_update_id,
              :provider_config_id, :node_config_id, :prompt_template_id,
              :provider_name, :model_name, :prompt_version, 'succeeded',
              :input_json, :prompt_messages_json, :raw_output_text,
              :parsed_output_json, :output_schema_json, :schema_validation_json,
              :latency_ms, :created_by, now(), :metadata_json
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
            "business_update_id": business_update_id,
            "provider_config_id": node_config["provider_config_id"],
            "node_config_id": node_config["node_config_id"],
            "prompt_template_id": node_config["prompt_template_id"],
            "provider_name": node_config["provider_name"],
            "model_name": node_config["model_name"],
            "prompt_version": node_config["prompt_version"],
            "input_json": input_json,
            "prompt_messages_json": [
                {
                    "role": "system",
                    "content": (
                        "Placeholder trace only; real prompt rendering is not implemented yet."
                    ),
                },
                {
                    "role": "user",
                    "content": input_json.get("raw_text") or "",
                },
            ],
            "raw_output_text": (
                '{"actions":[],"extraction_status":"placeholder",'
                '"message":"Placeholder handler completed; real LLM extraction is not '
                'implemented yet."}'
            ),
            "parsed_output_json": parsed_output_json,
            "output_schema_json": node_config["output_schema_json"] or {},
            "schema_validation_json": {"valid": True, "placeholder": True},
            "latency_ms": latency_ms,
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {
                "source": "worker_placeholder_handler",
                "warning": (
                    "No extracted_action rows are created before real LLM extraction is "
                    "implemented."
                ),
            },
        },
    )
