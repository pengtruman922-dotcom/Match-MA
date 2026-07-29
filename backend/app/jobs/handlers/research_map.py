"""Translate a research report into this system's write contract.

The research agent is good at finding things and bad at knowing which of our
columns exist, what our industry dictionary contains this week, or which enum
codes are legal. Those are live database state — putting them in the research
prompt is how the prompt and the code drifted apart in the first place (a
prompt asking for `industry_l1` while the whitelist only ever accepted
`industry_pairs_json`, so every fact it produced was discarded).

So the split is: the agent reports what it found, in prose plus loose JSON,
with a source URL on every claim. This node, holding the dictionaries, turns
that into `profile_sections` / `structured_facts` / `coverage` that the
existing proposal path already knows how to apply. It runs as its own job so a
mapping change can be re-run against the stored report — seconds and pennies —
instead of paying for another ten minutes of searching.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.ai.llm_client import LlmCallError, call_openai_compatible_chat
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID, SYSTEM_USER_ID
from backend.app.jobs.handlers.common import (
    _get_default_node_config,
    _json_safe_value,
    _render_prompt_messages,
    _safe_prompt_messages_for_trace,
)
from backend.app.jobs.handlers.research import (
    RESEARCH_MAPPER_NODE_NAME,
    _mark_research_outcome,
    apply_research_claims,
    normalize_research_output,
)
from backend.app.jobs.queue import JobClaim
from backend.app.registry.indicators import Indicator, indicators_for
from backend.app.services.industry_taxonomy import list_l1_terms
from backend.app.services.profile_sections import PROFILE_SECTION_LABELS, load_profile_sections
from backend.app.services.research_apply import MONEY_UNIT_MULTIPLIERS, RESEARCH_STRUCTURED_FIELDS

# 报告全文进上下文，但不是无限：一份九模块报告正常在几千字，
# 明显超出的多半是模型跑飞了，截断比撑爆上下文好。
REPORT_TEXT_LIMIT = 40000


def _handle_seller_target_research_map(db: Session, job: JobClaim) -> dict[str, object]:
    target_id = job.entity_id
    if job.entity_type != "seller_target" or target_id is None:
        raise ValueError("seller_target_research_map requires a seller_target entity_id.")

    # JobClaim 不带 parent_job_id，所以来源 job 走 payload 传递。
    research_job_id = (job.payload_json or {}).get("research_job_id")
    if not research_job_id:
        raise ValueError("seller_target_research_map requires research_job_id in its payload.")
    report = _load_research_report(db, research_job_id)
    if not report.get("report_text") and not report.get("agent_output_json"):
        raise ValueError(f"Research job {research_job_id} stored no report to map.")

    node_config = _get_default_node_config(db, RESEARCH_MAPPER_NODE_NAME)
    current_profiles = load_profile_sections(
        db,
        entity_type="seller_target",
        entity_ids=[target_id],
    ).get(str(target_id), {})

    mapping_context = _mapping_context(db, report=report)
    messages = _render_prompt_messages(node_config, {"mapping_context_json": mapping_context})

    started = time.perf_counter()
    try:
        result = call_openai_compatible_chat(
            base_url=node_config["base_url"],
            api_key_secret_ref=node_config["api_key_secret_ref"],
            api_key_encrypted=node_config.get("api_key_encrypted"),
            model_name=node_config["model_name"],
            messages=messages,
            temperature=node_config["temperature"],
            top_p=node_config["top_p"],
            max_tokens=node_config["max_tokens"],
            timeout_seconds=node_config["timeout_seconds"] or 120,
            response_format=node_config["response_format"],
            tools=None,
        )
    except LlmCallError as exc:
        _insert_mapping_trace(
            db,
            job=job,
            target_id=target_id,
            node_config=node_config,
            status="failed",
            input_json=mapping_context,
            messages=messages,
            result=None,
            schema_validation_json={"valid": False, "error": str(exc)},
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_code="llm_call_failed",
            error_message=str(exc),
        )
        db.commit()
        raise

    claims, notes = normalize_research_output(
        result.parsed_output_json,
        current_profiles=current_profiles,
    )
    parsed_ok = isinstance(result.parsed_output_json, dict)
    schema_validation = {
        "valid": parsed_ok,
        "claim_count": len(claims),
        "normalization_notes": notes,
        "error": None if parsed_ok else "Mapping output is not a JSON object.",
    }
    _insert_mapping_trace(
        db,
        job=job,
        target_id=target_id,
        node_config=node_config,
        status="succeeded" if parsed_ok else "failed",
        input_json=mapping_context,
        messages=messages,
        result=result,
        schema_validation_json=schema_validation,
        latency_ms=result.latency_ms,
    )
    if not parsed_ok:
        db.commit()
        raise ValueError(str(schema_validation["error"]))

    # Proposals belong to the original research run. Keeping that job id is
    # important for the target's audit trail and for re-running only mapping:
    # a mapper retry should update the same proposal set, not look like a new
    # web-research run.
    research_job = _research_job_for_proposals(job, research_job_id)
    applied_count, apply_errors = apply_research_claims(
        db,
        job=research_job,
        target_id=target_id,
        claims=claims,
        target_website=None,
    )
    proposal_count = len([claim for claim in claims if claim["proposal_kind"] != "not_found"])
    # 调研 job 给的是暂定结论（agent 有没有产出），最终结论由这里覆写：
    # 报告写得再好，落不进字段和画像就不算「找到了」。
    if applied_count:
        outcome = "found"
    elif proposal_count:
        # 报告里有内容，但一条都没落进字段或画像 —— 和「真的查不到」不是一回事，
        # 界面上必须能分开，否则又变成一次静默的空转。
        outcome = "found_but_rejected"
    else:
        outcome = "no_public_information"
    _mark_research_outcome(db, target_id, outcome)
    db.commit()
    return {
        "handled": True,
        "job_type": job.job_type,
        "seller_target_id": str(target_id),
        "research_job_id": str(research_job_id),
        "research_outcome": outcome,
        "proposal_count": len(claims),
        "auto_accepted_count": applied_count,
        "pending_review_count": len(apply_errors),
        "apply_errors": apply_errors,
        "normalization_notes": notes,
        "prompt_version": node_config["prompt_version"],
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
    }


def _research_job_for_proposals(job: JobClaim, research_job_id: Any) -> JobClaim:
    return JobClaim(
        id=UUID(str(research_job_id)),
        job_type="seller_target_research",
        queue_name=job.queue_name,
        entity_type=job.entity_type,
        entity_id=job.entity_id,
        payload_json=job.payload_json,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        correlation_id=job.correlation_id,
    )


def _load_research_report(db: Session, research_job_id: Any) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select result_json
            from background_job
            where id = :job_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "job_id": research_job_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).scalar_one_or_none()
    result = dict(row or {})
    return {
        "report_text": str(result.get("report_text") or "")[:REPORT_TEXT_LIMIT],
        "agent_output_json": result.get("agent_output_json"),
    }


def _writable_indicators() -> list[Indicator]:
    return [
        item
        for item in indicators_for("seller_target")
        if item.column in RESEARCH_STRUCTURED_FIELDS
    ]


def _mapping_context(db: Session, *, report: dict[str, Any]) -> dict[str, Any]:
    """Everything the mapper needs, read fresh from the database every run.

    Dictionaries and the writable whitelist are handed over as data rather than
    baked into the prompt, so adding an industry term or opening a column takes
    effect on the next run without touching a prompt version.
    """
    fields: list[dict[str, Any]] = []
    for indicator in _writable_indicators():
        entry: dict[str, Any] = {
            "field_path": indicator.column,
            "label": indicator.label,
            "kind": indicator.kind,
        }
        if indicator.enum_options:
            entry["allowed_values"] = [
                {"value": code, "label": label} for code, label in indicator.enum_options
            ]
        if indicator.kind == "yuan":
            entry["note"] = (
                '给出 {"value": 数字, "unit": "万元"} —— 单位换算由代码完成，不要自己折算。'
            )
        fields.append(entry)

    return {
        "report": report,
        "profile_section_catalog": [
            {"code": code, "label": label} for code, label in PROFILE_SECTION_LABELS.items()
        ],
        "writable_fields": fields,
        "industry_l1_terms": list_l1_terms(db),
        "money_units": sorted(unit for unit in MONEY_UNIT_MULTIPLIERS if unit),
    }


def _insert_mapping_trace(
    db: Session,
    *,
    job: JobClaim,
    target_id: UUID,
    node_config: dict[str, Any],
    status: str,
    input_json: dict[str, Any],
    messages: list[dict[str, Any]],
    result: Any,
    schema_validation_json: dict[str, Any],
    latency_ms: int,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    research_job_id = (job.payload_json or {}).get("research_job_id")
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
            ) values (
              :team_id, :workspace_id, 'research', :node_name,
              :job_id, :correlation_id, 'seller_target', :entity_id,
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
            "node_name": RESEARCH_MAPPER_NODE_NAME,
            "job_id": job.id,
            "correlation_id": job.correlation_id,
            "entity_id": target_id,
            "provider_config_id": node_config["provider_config_id"],
            "node_config_id": node_config["node_config_id"],
            "prompt_template_id": node_config["prompt_template_id"],
            "provider_name": node_config["provider_name"],
            "model_name": node_config["model_name"],
            "prompt_version": node_config["prompt_version"],
            "status": status,
            "input_json": _json_safe_value(input_json),
            "prompt_messages_json": _safe_prompt_messages_for_trace(messages),
            "raw_output_text": result.raw_output_text if result else None,
            "parsed_output_json": result.parsed_output_json if result else None,
            "output_schema_json": node_config.get("output_schema_json") or {},
            "schema_validation_json": schema_validation_json,
            "error_code": error_code,
            "error_message": error_message,
            "latency_ms": latency_ms,
            "prompt_tokens": result.prompt_tokens if result else None,
            "completion_tokens": result.completion_tokens if result else None,
            "total_tokens": result.total_tokens if result else None,
            "created_by": SYSTEM_USER_ID,
            "metadata_json": {
                "source": RESEARCH_MAPPER_NODE_NAME,
                "research_job_id": str(research_job_id) if research_job_id else None,
            },
        },
    )
