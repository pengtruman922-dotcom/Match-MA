from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.ai.llm_client import LlmCallError, call_openai_compatible_chat
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID, SYSTEM_USER_ID
from backend.app.jobs.handlers.common import (
    CLOSED_LIST_FIELD_VALUES,
    REQUIREMENT_STRENGTH_FIELDS,
    YES_NO_LIKE_FIELDS,
    _diff_json_safe,
    _get_default_node_config,
    _json_safe_dict,
    _json_safe_value,
    _normalize_closed_list_values,
    _normalize_equity_requirement_type,
    _normalize_listed_status,
    _normalize_listing_market_region,
    _normalize_requirement_strength,
    _normalize_yes_no_like,
    _optional_decimal,
    _parse_source_context,
    _render_prompt_messages,
    _resolve_entity_id,
    _safe_prompt_messages_for_trace,
    _write_field_value_sources,
)
from backend.app.jobs.handlers.traces import (
    _insert_buyer_intent_parse_trace,
)
from backend.app.jobs.queue import JobClaim
from backend.app.registry.indicators import (
    buyer_intent_fact_columns,
    buyer_party_fact_columns,
    indicator_by_column,
    indicators_for,
    writable_columns,
)
from backend.app.registry.nodes import buyer_intent_legacy_node_name, buyer_intent_two_stage_node_names
from backend.app.services.business_tags import normalize_business_tags
from backend.app.services.buyer_risk_tolerance import normalize_unacceptable_risk_flags
from backend.app.services.entity_grade import BUYER_GRADE, resolve_grade_pair
from backend.app.services.listed_status import legacy_listed_status
from backend.app.services.profile_sections import apply_profile_section, normalize_profile_section_items
# 行业字典在买家需求侧已于 0828 下线，这里只剩两个**提示词变量**。
# 留着不是遗漏：prompt_template 是数据库里的版本化资源，部署新代码时线上跑的
# 仍可能是引用 {industry_l1_list} 的旧版本，变量一撤那一版当场渲染失败。
# 等新版 buyer_intent_normalizer 发布并确认无回滚需求后，这两行才能删。
from backend.app.services.industry_taxonomy import (
    industry_l1_prompt_list,
    industry_l2_prompt_list,
)
from backend.app.services.recommendation_conditions import CONDITION_EFFECTS
from backend.app.services.region_dictionary import PROVINCES, normalize_buyer_regions
from backend.app.services.search_docs import (
    create_search_doc_rebuild_job,
)


def _handle_buyer_intent_parse(db: Session, job: JobClaim) -> dict[str, object]:
    buyer_intent_id = _resolve_entity_id(job, expected_entity_type="buyer_intent")
    if buyer_intent_id is None:
        raise ValueError("buyer_intent_parse job requires a buyer_intent entity_id.")

    buyer_intent = _get_buyer_intent_for_parse(db, buyer_intent_id)
    buyer_profile_json = _build_buyer_profile_context(db, buyer_intent)
    raw_requirement_text = str(job.payload_json.get("raw_requirement_text") or buyer_intent.get("raw_requirement_text") or "")
    if not raw_requirement_text.strip():
        raise ValueError("buyer_intent_parse job requires raw_requirement_text.")

    semantic_name, normalizer_name = buyer_intent_two_stage_node_names()
    semantic_node = _optional_node_config(db, semantic_name)
    normalizer_node = _optional_node_config(db, normalizer_name)
    semantic_output_json: dict[str, Any] | None = None
    pipeline_mode = "two_stage" if semantic_node and normalizer_node else "legacy_fallback"

    _set_buyer_intent_parse_stage(db, job.id, "semantic_parsing")

    if semantic_node and normalizer_node:
        semantic_output_json, semantic_validation = _call_buyer_intent_node(
            db,
            job=job,
            buyer_intent_id=buyer_intent_id,
            node_config=semantic_node,
            variables={
                "raw_requirement_text": raw_requirement_text,
                "buyer_profile_json": json.dumps(buyer_profile_json, ensure_ascii=False, default=str),
            },
            input_json={
                "stage": "semantic_parse",
                "buyer_intent_id": str(buyer_intent_id),
                "raw_requirement_text": raw_requirement_text,
                "buyer_profile_json": buyer_profile_json,
            },
            validator=_validate_buyer_intent_semantic_output,
        )
        if not semantic_validation["valid"]:
            raise ValueError(semantic_validation.get("error") or "Buyer intent semantic output is invalid.")
        _set_buyer_intent_parse_stage(db, job.id, "normalizing")
        parsed_output_json, schema_validation_json = _call_buyer_intent_node(
            db,
            job=job,
            buyer_intent_id=buyer_intent_id,
            node_config=normalizer_node,
            variables={
                "semantic_parse_json": json.dumps(semantic_output_json, ensure_ascii=False, default=str),
                "buyer_profile_json": json.dumps(buyer_profile_json, ensure_ascii=False, default=str),
                "field_contract_json": json.dumps(_buyer_intent_field_contract(), ensure_ascii=False),
                "industry_l1_list": industry_l1_prompt_list(db),
                "industry_l2_list": industry_l2_prompt_list(db),
                "province_list": "、".join(PROVINCES),
                "enum_contract_json": json.dumps(_buyer_intent_enum_contract(), ensure_ascii=False),
            },
            input_json={
                "stage": "normalization",
                "buyer_intent_id": str(buyer_intent_id),
                "semantic_parse_json": semantic_output_json,
                "dictionary_snapshot": {
                    "industry_l1": industry_l1_prompt_list(db),
                    "industry_l2": industry_l2_prompt_list(db),
                    "provinces": list(PROVINCES),
                },
            },
            validator=_validate_buyer_intent_parse_output,
        )
        node_config = normalizer_node
    else:
        node_config = _get_default_node_config(db, buyer_intent_legacy_node_name())
        parsed_output_json, schema_validation_json = _call_buyer_intent_node(
            db,
            job=job,
            buyer_intent_id=buyer_intent_id,
            node_config=node_config,
            variables={
                "raw_requirement_text": raw_requirement_text,
                "buyer_profile_json": json.dumps(buyer_profile_json, ensure_ascii=False, default=str),
                "industry_l1_list": industry_l1_prompt_list(db),
                "industry_l2_list": industry_l2_prompt_list(db),
            },
            input_json={
                "stage": "legacy_parse_and_normalize",
                "buyer_intent_id": str(buyer_intent_id),
                "raw_requirement_text": raw_requirement_text,
                "buyer_profile_json": buyer_profile_json,
                "fallback_reason": "Two-stage nodes are not both configured.",
            },
            validator=_validate_buyer_intent_parse_output,
        )

    _set_buyer_intent_parse_stage(db, job.id, "writing")
    parsed_output_json = _route_scoped_confirmation_items(parsed_output_json)
    changes, normalization_notes = _normalize_buyer_intent_parse_changes(parsed_output_json, raw_requirement_text)
    _normalize_buyer_intent_regions(changes)
    changes = _reconcile_buyer_intent_scope(
        db,
        current_fields=buyer_intent,
        candidate_changes=changes,
        normalization_notes=normalization_notes,
        scope_label="公共条件",
    )
    changes["parsed_requirement_json"] = {
        "source": "buyer_intent_two_stage" if pipeline_mode == "two_stage" else "buyer_intent_parser",
        "raw_requirement_text": raw_requirement_text,
        "semantic_output": semantic_output_json,
        "normalization_output": parsed_output_json,
        "pipeline_mode": pipeline_mode,
        "nodes": [
            {
                "node_name": config["node_name"],
                "prompt_version": config.get("prompt_version"),
            }
            for config in ([semantic_node, normalizer_node] if pipeline_mode == "two_stage" else [node_config])
            if config
        ],
    }
    if not schema_validation_json["valid"]:
        raise ValueError(schema_validation_json.get("error") or "Buyer intent parser output is invalid.")

    source_context = _parse_source_context(
        job,
        default_source_type="buyer_intent_parse",
        default_source_label="Buyer intent parser",
    )

    applied_fields: list[str] = []
    if changes:
        applied_fields = _apply_buyer_intent_parse_changes(
            db,
            buyer_intent,
            changes,
            job.id,
            normalization_notes,
            source_context,
        )
    section_count = _apply_buyer_intent_profile_sections(
        db,
        buyer_intent_id=buyer_intent_id,
        raw_sections=(parsed_output_json or {}).get("profile_sections"),
        structured_fields={**buyer_intent, **changes},
        normalization_notes=normalization_notes,
    )
    scenario_count = _replace_buyer_intent_scenarios(
        db,
        buyer_intent_id=buyer_intent_id,
        raw_scenarios=(parsed_output_json or {}).get("scenarios"),
        raw_requirement_text=raw_requirement_text,
        notes=normalization_notes,
    )

    return {
        "handled": True,
        "job_type": job.job_type,
        "buyer_intent_id": str(buyer_intent_id),
        "applied_fields": applied_fields,
        "field_count": len(applied_fields),
        "applied_buyer_party_fields": [],
        "buyer_party_field_count": 0,
        "scenario_count": scenario_count,
        "profile_section_count": section_count,
        "trace_created": True,
        "model_name": node_config["model_name"],
        "prompt_version": node_config["prompt_version"],
        "pipeline_mode": pipeline_mode,
        "pipeline_nodes": changes["parsed_requirement_json"]["nodes"],
        "schema_valid": schema_validation_json["valid"],
    }


def _set_buyer_intent_parse_stage(db: Session, job_id: UUID, stage: str) -> None:
    db.execute(
        text(
            """
            update background_job
            set metadata_json = metadata_json || :metadata_patch,
                updated_at = now()
            where id = :job_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "job_id": job_id,
            "metadata_patch": {
                "processing_stage": stage,
                "processing_stage_updated_at": datetime.now(UTC).isoformat(),
            },
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    # Stage state is operational telemetry and must be visible while a long LLM
    # call is running. No buyer data is written before the final writing stage.
    db.commit()


def _optional_node_config(db: Session, node_name: str) -> dict[str, Any] | None:
    try:
        return _get_default_node_config(db, node_name)
    except ValueError:
        return None


def _call_buyer_intent_node(
    db: Session,
    *,
    job: JobClaim,
    buyer_intent_id: UUID,
    node_config: dict[str, Any],
    variables: dict[str, Any],
    input_json: dict[str, Any],
    validator: Callable[[dict[str, Any] | None], dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt_messages = _render_prompt_messages(node_config, variables)
    started = time.perf_counter()
    try:
        llm_result = call_openai_compatible_chat(
            base_url=node_config["base_url"],
            api_key_secret_ref=node_config["api_key_secret_ref"],
            api_key_encrypted=node_config.get("api_key_encrypted"),
            model_name=node_config["model_name"],
            messages=prompt_messages,
            temperature=node_config["temperature"],
            top_p=node_config["top_p"],
            max_tokens=node_config["max_tokens"],
            timeout_seconds=node_config["timeout_seconds"] or 90,
            response_format=node_config["response_format"],
        )
    except LlmCallError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        _insert_buyer_intent_parse_trace(
            db,
            job=job,
            buyer_intent_id=buyer_intent_id,
            node_config=node_config,
            status="failed",
            input_json=input_json,
            prompt_messages_json=_safe_prompt_messages_for_trace(prompt_messages),
            raw_output_text=None,
            parsed_output_json=None,
            schema_validation_json={"valid": False, "error": str(exc)},
            latency_ms=latency_ms,
            error_code="llm_call_failed",
            error_message=str(exc),
        )
        db.commit()
        raise

    parsed_output = llm_result.parsed_output_json
    schema_validation = validator(parsed_output)
    _insert_buyer_intent_parse_trace(
        db,
        job=job,
        buyer_intent_id=buyer_intent_id,
        node_config=node_config,
        status="succeeded" if schema_validation["valid"] else "failed",
        input_json=input_json,
        prompt_messages_json=_safe_prompt_messages_for_trace(prompt_messages),
        raw_output_text=llm_result.raw_output_text,
        parsed_output_json=parsed_output,
        schema_validation_json=schema_validation,
        latency_ms=llm_result.latency_ms,
        prompt_tokens=llm_result.prompt_tokens,
        completion_tokens=llm_result.completion_tokens,
        total_tokens=llm_result.total_tokens,
        error_code=None if schema_validation["valid"] else "schema_validation_failed",
        error_message=schema_validation.get("error"),
    )
    db.commit()
    return parsed_output or {}, schema_validation


def _validate_buyer_intent_semantic_output(parsed_output_json: dict[str, Any] | None) -> dict[str, Any]:
    valid = isinstance(parsed_output_json, dict) and bool(parsed_output_json)
    return {
        "valid": valid,
        "field_count": len(parsed_output_json or {}),
        "error": None if valid else "Buyer intent semantic parser output must be a non-empty JSON object.",
    }


def _apply_buyer_intent_profile_sections(
    db: Session,
    *,
    buyer_intent_id: UUID,
    raw_sections: Any,
    structured_fields: dict[str, Any],
    normalization_notes: list[str],
) -> int:
    """把模型产出的模块「其他」落库。

    标准化不了、也不适合拿去初筛的说法归这里 —— 它随搜索文档进深评，
    不进规则打分。栏目码由 BUYER_PROFILE_SECTIONS 校验，写错的整条丢弃并留痕。
    """
    sections, notes = normalize_profile_section_items(raw_sections, entity_type="buyer_intent")
    normalization_notes.extend(notes)
    sections = _remove_structured_profile_duplicates(
        sections,
        structured_fields=structured_fields,
        normalization_notes=normalization_notes,
    )
    written = 0
    for section in sections:
        try:
            apply_profile_section(
                db,
                entity_type="buyer_intent",
                entity_id=buyer_intent_id,
                section_code=section["section_code"],
                info_status="filled",
                content_text=section["content_text"],
                source_type="buyer_intent_parse",
                source_excerpt=section.get("source_excerpt"),
                as_of_date=section.get("as_of_date"),
                review_status="auto_accepted",
                user_id=SYSTEM_USER_ID,
                log_source_type="buyer_intent_parse",
            )
            written += 1
        except ValueError as exc:
            # 「其他」是补充说明，字段才是这次解析的正事。一块栏目写不进去
            # 不该把已经解析好的几十个字段一起回滚 —— 留痕，继续。
            normalization_notes.append(f"profile_section_rejected:{section['section_code']}:{exc}")
    return written


_PROFILE_CLAUSE_SPLIT = re.compile(r"[，,；;。\n]+")
_PROFILE_COMPARE_NOISE = re.compile(r"[\s：:，,；;。、“”‘’\"'（）()【】\[\]·—_-]+")


def _remove_structured_profile_duplicates(
    sections: list[dict[str, Any]],
    *,
    structured_fields: dict[str, Any],
    normalization_notes: list[str],
) -> list[dict[str, Any]]:
    """Keep “其他” for genuinely unstructured facts, not a second field copy.

    比对对象是**非条件**的文本字段：条件字段（营收下限、PE 上限那些）的值是
    数字，拿它去做子串比对只会误删「营收 5 亿」这种句子里的数字部分。
    以前这里用 `default_effect is not None` 表达「是条件」，0901 那个标志删掉了，
    改读 `screening` —— 它问的正是同一件事，而且是唯一还在生效的那个。
    """
    structured_texts: list[str] = []
    indicators = (
        *indicators_for("buyer_intent"),
        *indicators_for("buyer_intent_scenario"),
    )
    for indicator in indicators:
        if indicator.screening:
            continue
        value = structured_fields.get(indicator.column)
        if not _has_reconciliation_value(value):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, (dict, list)):
                continue
            normalized = _profile_compare_text(item)
            if len(normalized) >= 3:
                structured_texts.append(normalized)

    if not structured_texts:
        return sections

    output: list[dict[str, Any]] = []
    for section in sections:
        kept: list[str] = []
        removed = 0
        for clause in _PROFILE_CLAUSE_SPLIT.split(str(section.get("content_text") or "")):
            clause = clause.strip()
            if not clause:
                continue
            normalized_clause = _profile_compare_text(clause)
            duplicate = len(normalized_clause) >= 3 and any(
                normalized_clause in structured or structured in normalized_clause
                for structured in structured_texts
            )
            if duplicate:
                removed += 1
            else:
                kept.append(clause)
        if removed:
            normalization_notes.append(
                f"profile_section_removed_structured_duplicates:{section['section_code']}:{removed}"
            )
        if kept:
            output.append({**section, "content_text": "；".join(kept)})
    return output


def _profile_compare_text(value: Any) -> str:
    return _PROFILE_COMPARE_NOISE.sub("", str(value or "")).lower()


def _buyer_intent_field_contract() -> list[dict[str, Any]]:
    """模型能写的全部字段，注册表派生。

    0901 起契约的主体是**方案**的字段：需求本身只是容器（名称、级别、状态），
    业务方向与门槛全部住在方案里。所以这里合并两份 —— 需求侧剩下的系统列，
    加上方案侧的 13 列。

    ``is_condition`` 读 ``screening``：它是「这一条进不进初筛 schema」。
    0901 删掉了 default_effect（「这个买家有多想要」），那个标志从来没进过
    SQL，却在契约里告诉模型有强弱之分 —— 模型于是花注意力去判一个不存在的维度。
    """
    contract = [
        {
            "field": indicator.column,
            "label": indicator.label,
            "module": indicator.group,
            "value_kind": indicator.kind,
            "target_field": indicator.target_column,
            "operator": indicator.operator,
            "is_condition": indicator.screening,
            "scope": scope,
            "multi_value": indicator.multi_value,
            "enum_values": [value for value, _ in (indicator.enum_options or ())],
        }
        for scope, entity in (("intent", "buyer_intent"), ("scenario", "buyer_intent_scenario"))
        for indicator in indicators_for(entity)
        if "parse" in indicator.writable_by
    ]
    return contract


def _buyer_intent_enum_contract() -> dict[str, list[str]]:
    """模型能写的枚举列的合法取值。

    **必须与 `_buyer_intent_field_contract()` 同口径按 `parse` 过滤。**
    只按 `enum_options` 过滤的话，退役字段的闭集会继续出现在提示词里 ——
    模型看到一张它填不进任何东西的取值表，字段表变短了、取值表没变短，
    而多出来的那些取值每次解析都要占一次注意力。
    0828 实测：不过滤是 17 项 1385 字符，过滤后 8 项。
    """
    return {
        indicator.column: [value for value, _ in indicator.enum_options]
        for entity in ("buyer_intent", "buyer_intent_scenario")
        for indicator in indicators_for(entity)
        if indicator.enum_options and "parse" in indicator.writable_by
    }


def _merge_confirmation_items(left: Any, right: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in [*(left if isinstance(left, list) else []), *(right if isinstance(right, list) else [])]:
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("field") or ""),
            str(item.get("evidence") or ""),
            json.dumps(item.get("proposed_value"), ensure_ascii=False, sort_keys=True, default=str),
        )
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output


def _route_scoped_confirmation_items(parsed_output_json: dict[str, Any] | None) -> dict[str, Any] | None:
    """Move scenario questions out of the common layer before reconciliation.

    Normalizer versions in production may put every question at the top level.
    An explicit ``scope`` wins; when it is absent, a field that appears in
    exactly one scenario (and not in common fields) is still unambiguous.
    """
    if not isinstance(parsed_output_json, dict):
        return parsed_output_json
    raw_pending = parsed_output_json.get("needs_confirmation")
    raw_scenarios = parsed_output_json.get("scenarios")
    if not isinstance(raw_pending, list) or not isinstance(raw_scenarios, list):
        return parsed_output_json

    scenarios = [dict(item) for item in raw_scenarios if isinstance(item, dict)]
    if not scenarios:
        return parsed_output_json
    common_fields = parsed_output_json.get("fields")
    common_field_names = set(common_fields) if isinstance(common_fields, dict) else set()
    scenario_labels = [str(item.get("label") or item.get("name") or "").strip() for item in scenarios]
    fields_to_scenarios: dict[str, list[int]] = {}
    for index, scenario in enumerate(scenarios):
        fields = scenario.get("fields") or scenario.get("conditions")
        if not isinstance(fields, dict):
            continue
        for field in fields:
            fields_to_scenarios.setdefault(str(field), []).append(index)

    common_pending: list[Any] = []
    for raw_item in raw_pending:
        if not isinstance(raw_item, dict):
            common_pending.append(raw_item)
            continue
        field = str(raw_item.get("field") or raw_item.get("field_name") or "").strip()
        scope = _normalized_scope_label(raw_item.get("scope"))
        target_index = next(
            (
                index
                for index, label in enumerate(scenario_labels)
                if scope and scope == _normalized_scope_label(label)
            ),
            None,
        )
        candidates = fields_to_scenarios.get(field, [])
        if target_index is None and field not in common_field_names and len(candidates) == 1:
            target_index = candidates[0]
        if target_index is None:
            common_pending.append(raw_item)
            continue
        target = scenarios[target_index]
        target_pending = target.get("needs_confirmation")
        target["needs_confirmation"] = [
            *(target_pending if isinstance(target_pending, list) else []),
            {**raw_item, "scope": scenario_labels[target_index]},
        ]

    return {
        **parsed_output_json,
        "needs_confirmation": common_pending,
        "scenarios": scenarios,
    }


def _normalized_scope_label(value: Any) -> str:
    return re.sub(r"[\s（）()【】\[\]·_-]+", "", str(value or "")).lower()


_RECONCILIATION_INTERNAL_FIELDS = {
    "raw_requirement_text",
    "parsed_requirement_json",
    "needs_confirmation_json",
}


def _reconcile_buyer_intent_scope(
    db: Session,
    *,
    current_fields: dict[str, Any],
    candidate_changes: dict[str, Any],
    normalization_notes: list[str],
    scope_label: str,
) -> dict[str, Any]:
    """Apply empty/equal/conflict policy at the final database boundary."""
    candidates = dict(candidate_changes)
    raw_pending = candidates.pop("needs_confirmation_json", [])
    pending_fields = {
        str(item.get("field") or "")
        for item in raw_pending if isinstance(item, dict)
    } if isinstance(raw_pending, list) else set()
    pending_fallback_values: dict[str, Any] = {}
    accepted: dict[str, Any] = {}
    effective = dict(current_fields)
    generated_pending: list[dict[str, Any]] = []

    for field, proposed in candidates.items():
        if field in _RECONCILIATION_INTERNAL_FIELDS:
            accepted[field] = proposed
            effective[field] = proposed
            continue
        if not _has_reconciliation_value(proposed):
            normalization_notes.append(f"ignored_empty_parse_value:{scope_label}:{field}")
            continue
        current = current_fields.get(field)
        if field in pending_fields:
            pending_fallback_values[field] = proposed
        if not _has_reconciliation_value(current):
            accepted[field] = proposed
            effective[field] = proposed
            normalization_notes.append(f"auto_filled_empty:{scope_label}:{field}")
        elif _reconciliation_values_equal(current, proposed):
            normalization_notes.append(f"unchanged_parse_value:{scope_label}:{field}")
        else:
            if field not in pending_fields:
                generated_pending.append(
                    {
                        "field": field,
                        "proposed_value": _json_safe_value(proposed),
                        "reason": "新解析值与当前值不一致，请确认是否覆盖",
                        "uncertain_part": "value",
                        "scope": scope_label,
                        "item_key": f"conflict:{_normalized_scope_label(scope_label)}:{field}",
                    }
                )
            normalization_notes.append(f"held_conflict:{scope_label}:{field}")

    reconciled_pending: list[dict[str, Any]] = []
    for item in raw_pending if isinstance(raw_pending, list) else []:
        if not isinstance(item, dict):
            continue
        entry = dict(item)
        field = str(entry.get("field") or "")
        if not field:
            continue
        if scope_label != "公共条件":
            entry["scope"] = scope_label
        if "proposed_value" not in entry:
            reconciled_pending.append(entry)
            continue
        valid, normalized = _normalize_confirmation_proposed_value(
            db, field=field, proposed_value=entry.get("proposed_value")
        )
        if field in pending_fallback_values:
            fallback_valid, fallback_normalized = _normalize_confirmation_proposed_value(
                db, field=field, proposed_value=pending_fallback_values[field]
            )
            if fallback_valid:
                valid, normalized = fallback_valid, fallback_normalized
        if not valid:
            entry["proposed_value_status"] = "invalid"
            reconciled_pending.append(entry)
            normalization_notes.append(f"invalid_confirmation_value:{scope_label}:{field}")
            continue

        entry["proposed_value"] = _json_safe_value(normalized)
        uncertain_part = str(entry.get("uncertain_part") or "value").strip().lower()
        if uncertain_part not in {"", "value"}:
            entry["proposed_value_status"] = "requires_review"
            reconciled_pending.append(entry)
            continue
        current = effective.get(field)
        if not _has_reconciliation_value(current):
            accepted[field] = normalized
            effective[field] = normalized
            normalization_notes.append(f"auto_filled_confirmed_empty:{scope_label}:{field}")
        elif _reconciliation_values_equal(current, normalized):
            normalization_notes.append(f"dropped_equal_confirmation:{scope_label}:{field}")
        else:
            entry.pop("proposed_value_status", None)
            reconciled_pending.append(entry)

    accepted["needs_confirmation_json"] = _merge_confirmation_items(
        generated_pending, reconciled_pending
    )
    return accepted


def _normalize_confirmation_proposed_value(
    db: Session,
    *,
    field: str,
    proposed_value: Any,
) -> tuple[bool, Any]:
    """把一条待确认项的候选值过一遍它所属作用域的归一。

    作用域要**按字段找**，不能写死成需求侧：0901 起门槛住在方案里，
    用需求侧那份白名单去归一 max_pe，它会当场被判成 unsupported、
    返回「归一不出值」—— 于是「模型给的和当前值其实一样」这件事永远发现不了，
    每次重跑都往待确认里堆一条重复项。
    """
    scope = None
    indicator = None
    for candidate_scope, entity in (("scenario", "buyer_intent_scenario"), ("intent", "buyer_intent")):
        try:
            indicator = indicator_by_column(entity, field)
        except KeyError:
            continue
        scope = candidate_scope
        break
    if indicator is None or scope is None:
        return False, None
    value = proposed_value
    if indicator.multi_value and not isinstance(value, list):
        value = [value]
    normalized, _ = _normalize_buyer_intent_parse_changes(
        {"fields": {field: value}},
        "",
        scope=scope,
    )
    _normalize_buyer_intent_regions(normalized)
    result = normalized.get(field)
    return _has_reconciliation_value(result), result


def _has_reconciliation_value(value: Any) -> bool:
    if value is None or value == "" or value == "unknown":
        return False
    if isinstance(value, (list, dict)) and not value:
        return False
    return True


def _reconciliation_values_equal(left: Any, right: Any) -> bool:
    return _canonical_reconciliation_value(left) == _canonical_reconciliation_value(right)


def _canonical_reconciliation_value(value: Any) -> Any:
    safe = _json_safe_value(value)
    if isinstance(safe, dict):
        return {key: _canonical_reconciliation_value(safe[key]) for key in sorted(safe)}
    if isinstance(safe, list):
        normalized = [_canonical_reconciliation_value(item) for item in safe]
        return sorted(normalized, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, default=str))
    return safe

MAX_PARSED_SCENARIOS = 6


def _replace_buyer_intent_scenarios(
    db: Session,
    *,
    buyer_intent_id: UUID,
    raw_scenarios: Any,
    raw_requirement_text: str = "",
    notes: list[str] | None = None,
) -> int:
    """把解析产出的方案写进 buyer_intent_scenario 的真列。

    0901 起**方案是门槛唯一的住处**，需求本身只是容器。两条随之改变的规则：

    一、**单方案也要落库。** 0828 之前一个方案「不带任何新信息」所以被丢掉，
    留零行让初筛走扁平那条路。现在扁平那条路不存在了 —— 丢掉唯一的方案
    等于把这条需求的门槛全部丢掉，而且不报错。

    二、**按 sort_order 对齐，不按 label 对齐。** 方案不再有名称（判决三：
    摘要就是标题），拿摘要去做对齐键会在重跑改写摘要时把两条方案错配。
    """
    if not isinstance(raw_scenarios, list):
        return 0
    notes = [] if notes is None else notes
    existing_rows = _load_parser_scenarios(db, buyer_intent_id)
    parsed: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for index, item in enumerate(raw_scenarios[:MAX_PARSED_SCENARIOS]):
        if not isinstance(item, dict):
            continue
        normalized, scenario_notes = _normalize_buyer_intent_parse_changes(
            {
                "fields": item.get("fields") or item.get("conditions") or {},
                "needs_confirmation": item.get("needs_confirmation"),
            },
            raw_requirement_text,
            scope="scenario",
        )
        notes.extend(f"scenario{index}:{note}" for note in scenario_notes)
        pending = normalized.pop("needs_confirmation_json", [])
        normalized = _normalize_parsed_scenario_fields(normalized)
        existing = existing_rows[index] if index < len(existing_rows) else {}
        current = {
            column: existing.get(column)
            for column in BUYER_INTENT_SCENARIO_PARSE_FIELDS
            if existing.get(column) not in (None, "", [], {})
        }
        fields = {**current, **normalized}
        if not fields and not pending:
            continue
        parsed.append((fields, pending))

    if not parsed:
        return len(existing_rows)

    db.execute(
        text(
            """
            update buyer_intent_scenario
            set deleted_at = now(), updated_at = now()
            where buyer_intent_id = :buyer_intent_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              and source = 'parser'
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    columns = sorted(BUYER_INTENT_SCENARIO_PARSE_FIELDS)
    column_sql = ", ".join(columns)
    value_sql = ", ".join(f":{column}" for column in columns)
    binds = [
        bindparam(column, type_=JSONB)
        for column in columns
        if column in BUYER_INTENT_SCENARIO_JSON_FIELDS
    ]
    statement = text(
        f"""
        insert into buyer_intent_scenario (
          team_id, workspace_id, buyer_intent_id, label, sort_order,
          needs_confirmation_json, source, created_by, updated_by, {column_sql}
        )
        values (
          :team_id, :workspace_id, :buyer_intent_id, '', :sort_order,
          :needs_confirmation_json, 'parser', :user_id, :user_id, {value_sql}
        )
        """
    ).bindparams(bindparam("needs_confirmation_json", type_=JSONB), *binds)
    for sort_order, (fields, pending) in enumerate(parsed):
        params: dict[str, Any] = {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "buyer_intent_id": buyer_intent_id,
            "sort_order": sort_order,
            "needs_confirmation_json": pending,
            "user_id": SYSTEM_USER_ID,
        }
        for column in columns:
            value = fields.get(column)
            if value is None and column in BUYER_INTENT_SCENARIO_JSON_FIELDS:
                value = []
            params[column] = value
        db.execute(statement, params)
    db.commit()
    return len(parsed)


def _load_parser_scenarios(db: Session, buyer_intent_id: UUID) -> list[dict[str, Any]]:
    columns = ", ".join(sorted(BUYER_INTENT_SCENARIO_PARSE_FIELDS))
    rows = db.execute(
        text(
            f"""
            select sort_order, needs_confirmation_json, {columns}
            from buyer_intent_scenario
            where buyer_intent_id = :buyer_intent_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              and source = 'parser'
            order by sort_order, created_at
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _normalize_parsed_scenario_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """方案字段的最后一道：地区过省份词表。

    闭集、业务标签、金额单位都已经由 _normalize_buyer_intent_parse_changes
    （scope="scenario"）处理过 —— 这里只剩地区，因为它要访问地区词表，
    而那是个比形状归一重得多的依赖。
    """
    fields = dict(fields)
    if "required_regions_json" in fields:
        regions, _ = normalize_buyer_regions(
            fields["required_regions_json"], field="required_regions_json"
        )
        if regions:
            fields["required_regions_json"] = regions
        else:
            fields.pop("required_regions_json", None)
    return fields


def _normalize_buyer_intent_regions(changes: dict[str, Any]) -> None:
    """就地归一两个地区数组，无法落到标准省份的条目转成待确认项。

    公共条件与「方案」两条路都调它 —— 归一只写一次，否则「带不带方案」会决定
    地区要不要过省份词表（2026-08-01 在行业字段上实测过同一个问题）。

    ⚠️ 归一不出来的**不能直接丢**：丢掉的地区在筛选里表现为「这些标的进不来」，
    界面上看不出来。所以走 needs_confirmation_json 让人来判。
    """
    for column in ("acceptable_regions_json", "excluded_regions_json"):
        if column not in changes:
            continue
        regions, pending = normalize_buyer_regions(changes[column], field=column)
        changes[column] = regions
        if pending:
            changes["needs_confirmation_json"] = _merge_confirmation_items(
                changes.get("needs_confirmation_json"), pending
            )


def _get_buyer_intent_for_parse(db: Session, buyer_intent_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            f"""
            select
              id, buyer_party_id, intent_name, contact_name, contact_info_json,
              parsed_requirement_json, needs_confirmation_json, reviewed_at, reviewed_by,
              {', '.join(buyer_intent_fact_columns())}
            from buyer_intent
            where id = :buyer_intent_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"Buyer intent not found: {buyer_intent_id}")
    return _json_safe_dict(row)

def _get_buyer_party(db: Session, buyer_party_id: UUID) -> dict[str, Any] | None:
    row = db.execute(
        text(
            f"""
            select
              id, aliases_json, notes, status,
              {', '.join(buyer_party_fact_columns())}
            from buyer_party
            where id = :buyer_party_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "buyer_party_id": buyer_party_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return _json_safe_dict(row) if row else None

def _build_buyer_profile_context(db: Session, buyer_intent: dict[str, Any]) -> dict[str, Any]:
    buyer_party = None
    if buyer_intent.get("buyer_party_id"):
        buyer_party = _get_buyer_party(db, UUID(str(buyer_intent["buyer_party_id"])))
    return {
        "buyer_party": buyer_party,
        "current_intent": buyer_intent,
        "instructions": {
            "apply_policy": "Parser output is automatically applied to the bound buyer_intent and remains reviewable in update logs.",
            "money_unit": "Use CNY yuan numbers.",
            "percentage_unit": "Use numeric percentage values, e.g. 51 means 51 percent.",
        },
    }

# 三份写入白名单从注册表派生（0828 改），不再手抄。
#
# 手抄的代价在 0828 这一轮才真正显形：本轮退役 32 列、阶段 B 还要 drop 它们，
# 手抄清单意味着同一件事要在四个地方各改一遍，而漏掉任何一份都**不报错** ——
# 漏解析白名单，模型产出被当成 unsupported_field 静默丢掉；漏 JSONB 绑定，
# jsonb 列被当字符串写进去。tests/test_indicator_registry.py 钉的就是这条线。
#
# 三个系统列不在注册表里，所以单独列出来：intent_name 是实体名不是业务事实，
# parsed_requirement_json 是解析产物存档，needs_confirmation_json 是待确认清单。
_BUYER_INTENT_PARSE_SYSTEM_FIELDS = {
    "intent_name",
    "parsed_requirement_json",
    "needs_confirmation_json",
}

BUYER_INTENT_PARSE_FIELDS = writable_columns("parse", "buyer_intent") | _BUYER_INTENT_PARSE_SYSTEM_FIELDS

BUYER_INTENT_PARSE_JSON_FIELDS = {
    indicator.column
    for indicator in indicators_for("buyer_intent")
    if indicator.kind == "json" and "parse" in indicator.writable_by
} | {"parsed_requirement_json", "needs_confirmation_json"}

BUYER_INTENT_PARSE_NUMERIC_FIELDS = {
    indicator.column
    for indicator in indicators_for("buyer_intent")
    if indicator.kind in {"yuan", "ratio"} and "parse" in indicator.writable_by
}

BUYER_INTENT_TEXT_LIMITS = {
    "intent_name": 300,
}

# 方案侧的三份白名单，与需求侧同一手法派生。方案是 0901 起门槛的唯一住处，
# 所以这三份比需求侧那三份更要紧 —— 漏一列的表现是「模型写了、库里没有」，
# 而门槛悄悄少一条不报错，只会让候选池变宽。
BUYER_INTENT_SCENARIO_PARSE_FIELDS = writable_columns("parse", "buyer_intent_scenario")

BUYER_INTENT_SCENARIO_JSON_FIELDS = {
    indicator.column
    for indicator in indicators_for("buyer_intent_scenario")
    if indicator.kind == "json" and "parse" in indicator.writable_by
}

BUYER_INTENT_SCENARIO_NUMERIC_FIELDS = {
    indicator.column
    for indicator in indicators_for("buyer_intent_scenario")
    if indicator.kind in {"yuan", "ratio"} and "parse" in indicator.writable_by
}

def _all_parse_writable_fields() -> set[str]:
    """需求容器 + 方案，两张表可写列的并集。

    校验阶段还不知道一个字段最后落到哪张表 —— 分流在写入时做。
    只认需求侧那一半的话，模型正确产出的门槛会被判成「不支持的字段」，
    整次解析被判失败，而失败原因指向的是一个其实完全合法的输出。
    """
    return BUYER_INTENT_PARSE_FIELDS | BUYER_INTENT_SCENARIO_PARSE_FIELDS


def _validate_buyer_intent_parse_output(parsed_output_json: dict[str, Any] | None) -> dict[str, Any]:
    if parsed_output_json is None:
        return {"valid": False, "error": "LLM output is not a JSON object."}
    if "fields" in parsed_output_json and not isinstance(parsed_output_json["fields"], dict):
        return {"valid": False, "error": "Buyer intent parser output field 'fields' must be an object."}
    if "needs_confirmation" in parsed_output_json and not isinstance(parsed_output_json["needs_confirmation"], list):
        return {"valid": False, "error": "Buyer intent parser output field 'needs_confirmation' must be an array."}
    candidate = parsed_output_json.get("fields", parsed_output_json)
    if not isinstance(candidate, dict):
        return {"valid": False, "error": "Buyer intent parser output must be an object."}
    allowed = _all_parse_writable_fields()
    allowed_count = len([key for key in candidate if key in allowed])
    allowed_count += len(
        _normalize_confirmation_items(parsed_output_json.get("needs_confirmation"), allowed)
    )
    # 方案里的字段同样算数：一次解析可能只产出 scenarios（业务方向与门槛全在
    # 方案里，容器层什么都没变），那不是「没有可用字段」。
    for item in parsed_output_json.get("scenarios") or []:
        if not isinstance(item, dict):
            continue
        fields = item.get("fields") or item.get("conditions") or {}
        if isinstance(fields, dict):
            allowed_count += len([key for key in fields if key in allowed])
    return {
        "valid": allowed_count > 0,
        "field_count": allowed_count,
        "error": None if allowed_count > 0 else "Buyer intent parser output has no supported fields.",
    }

def _normalize_buyer_intent_parse_changes(
    parsed_output_json: dict[str, Any] | None,
    raw_requirement_text: str,
    *,
    scope: str = "intent",
) -> tuple[dict[str, Any], list[str]]:
    """解析产出 → 可落库的字段，两个作用域共用一份归一。

    ``scope="intent"`` 走需求容器那张表（0901 之后只剩名称/级别/状态/暂停原因/
    原始需求），``scope="scenario"`` 走方案表的 13 列。

    **两个作用域必须共用这一个函数。** 0828 时方案走的是另一条更薄的归一
    （normalize_scenario_fields），于是「5000万」这种写法在公共条件上会被换算成
    50000000、在方案里却原样留成 5000 —— 同一句话落在哪一层决定了它换不换算，
    而门槛 0901 起只住在方案里，那条薄路径正好接手了全部的数字。
    """
    if not parsed_output_json:
        return {}, []
    candidate = parsed_output_json.get("fields", parsed_output_json)
    if not isinstance(candidate, dict):
        return {}, []

    scenario_scope = scope == "scenario"
    allowed = BUYER_INTENT_SCENARIO_PARSE_FIELDS if scenario_scope else BUYER_INTENT_PARSE_FIELDS
    numeric = (
        BUYER_INTENT_SCENARIO_NUMERIC_FIELDS if scenario_scope else BUYER_INTENT_PARSE_NUMERIC_FIELDS
    )
    json_fields = (
        BUYER_INTENT_SCENARIO_JSON_FIELDS if scenario_scope else BUYER_INTENT_PARSE_JSON_FIELDS
    )

    notes: list[str] = []
    raw_pending = parsed_output_json.get("needs_confirmation")
    if raw_pending is None:
        raw_pending = candidate.get("needs_confirmation_json")
    pending = _normalize_confirmation_items(raw_pending, allowed)
    candidate = _remove_pending_condition_values(candidate, pending)
    notes.extend(f"held_for_confirmation:{item['field']}" for item in pending)
    changes: dict[str, Any] = {}
    for key, value in candidate.items():
        if key == "needs_confirmation_json":
            continue
        if key not in allowed:
            notes.append(f"ignored_unsupported_field:{key}")
            continue
        if key in numeric:
            changes[key] = _optional_decimal(value)
            continue
        if key in YES_NO_LIKE_FIELDS:
            changes[key] = _normalize_yes_no_like(value)
            continue
        if key == "preferred_listed_status":
            normalized_listed = _normalize_listed_status(value)
            changes[key] = "pre_ipo" if normalized_listed == "preparing_listing" else normalized_listed
            continue
        if key == "acceptable_listed_status_json":
            normalized_statuses = _normalize_acceptable_listed_statuses(value)
            changes[key] = normalized_statuses
            if not scenario_scope:
                # preferred_listed_status 是需求侧的兼容派生列，方案表上没有它。
                changes["preferred_listed_status"] = legacy_listed_status(normalized_statuses)
            continue
        if key == "equity_requirement_type":
            changes[key] = _normalize_equity_requirement_type(value)
            continue
        if key in REQUIREMENT_STRENGTH_FIELDS:
            changes[key] = _normalize_requirement_strength(value)
            continue
        if key in {"intent_business_tags_json", "business_tags_json"}:
            # 自由标签，只做形状归一（去空白、去空值、去重、限长），**不过任何词表**——
            # 过字典正是 0828 判决一要下线的东西。归空了就整列摘掉：
            # 空数组会被后面的 reconciliation 当成「未提及」，那是对的。
            tags = normalize_business_tags(value)
            if tags:
                changes[key] = tags
            else:
                notes.append(f"dropped_{key}:no_usable_tags")
            continue
        if key == "unacceptable_risk_flags_json":
            # 必须排在 CLOSED_LIST 分支**之前**：三态里的「不接受全部」可以是
            # "all" / "全部" / true，那些值不在闭集里，走通用分支会被整条丢掉，
            # 于是「全都不接受」静默变成「未提及」——方向恰好是错的那一边。
            normalized_flags = normalize_unacceptable_risk_flags(value)
            if normalized_flags is None:
                notes.append(f"dropped_{key}:no_recognised_values")
            else:
                changes[key] = normalized_flags
            continue
        if key in CLOSED_LIST_FIELD_VALUES:
            normalized_values = _normalize_closed_list_values(key, value)
            if normalized_values:
                changes[key] = normalized_values
            else:
                notes.append(f"dropped_{key}:no_recognised_values")
            continue
        if key in json_fields:
            changes[key] = value if isinstance(value, (list, dict)) else []
            continue
        text_value = str(value).strip() if value is not None else None
        if text_value and key in BUYER_INTENT_TEXT_LIMITS:
            text_value = text_value[: BUYER_INTENT_TEXT_LIMITS[key]]
        changes[key] = text_value

    source_text = raw_requirement_text.lower()
    mentions_valuation = "估值" in raw_requirement_text or "valuation" in source_text
    mentions_market_cap = "市值" in raw_requirement_text or "market cap" in source_text
    if mentions_valuation and not mentions_market_cap:
        for field in ("min_market_cap_yuan", "max_market_cap_yuan", "market_cap_range_summary"):
            if field in changes:
                changes.pop(field, None)
                notes.append(f"dropped_{field}:source_mentions_valuation_not_market_cap")

    changes["needs_confirmation_json"] = pending
    if scenario_scope:
        return {key: value for key, value in changes.items() if value is not None}, notes

    changes["raw_requirement_text"] = raw_requirement_text
    if "parsed_requirement_json" not in changes:
        changes["parsed_requirement_json"] = {
            "source": "buyer_intent_parser",
            "raw_requirement_text": raw_requirement_text,
            "llm_fields": parsed_output_json,
        }
    return {key: value for key, value in changes.items() if value is not None}, notes


def _normalize_acceptable_listed_statuses(raw: Any) -> list[str]:
    values = raw if isinstance(raw, list) else [raw]
    output: list[str] = []
    for value in values:
        normalized = _normalize_listed_status(value)
        if normalized == "preparing_listing":
            normalized = "pre_ipo"
        if normalized in {"listed", "unlisted", "pre_ipo"} and normalized not in output:
            output.append(normalized)
    return output


def _remove_pending_condition_values(raw_fields: Any, pending: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(raw_fields, dict):
        return {}
    output = dict(raw_fields)
    for item in pending:
        field = item["field"]
        current = output.get(field)
        proposed = item.get("proposed_value")
        if isinstance(current, list) and proposed is not None:
            proposed_items = proposed if isinstance(proposed, list) else [proposed]
            proposed_json = {
                json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
                for value in proposed_items
            }
            output[field] = [
                value
                for value in current
                if json.dumps(value, ensure_ascii=False, sort_keys=True, default=str) not in proposed_json
            ]
    return output


def _normalize_confirmation_items(raw: Any, allowed_fields: set[str]) -> list[dict[str, Any]]:
    """Normalize parser questions without carrying a confidence score."""
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or item.get("field_name") or "").strip()
        if field not in allowed_fields or field == "needs_confirmation_json":
            continue
        reason = str(item.get("reason") or item.get("question") or "AI 无法确定唯一取值").strip()[:500]
        evidence = str(item.get("evidence") or item.get("source_text") or "").strip()[:1000]
        entry: dict[str, Any] = {"field": field, "reason": reason}
        if evidence:
            entry["evidence"] = evidence
        proposed_value = item.get("proposed_value", item.get("suggested_value", item.get("value")))
        if proposed_value is not None:
            entry["proposed_value"] = _json_safe_value(proposed_value)
        uncertain_part = str(item.get("uncertain_part") or "").strip().lower()
        if uncertain_part in {"field", "value", "operator", "unit", "effect", "scope", "taxonomy_mapping"}:
            entry["uncertain_part"] = uncertain_part
        operator = str(item.get("operator") or "").strip().lower()
        if operator:
            entry["operator"] = operator[:80]
        effect = str(item.get("effect") or "").strip().lower()
        if effect in CONDITION_EFFECTS:
            entry["effect"] = effect
        scope = str(item.get("scope") or "").strip()
        if scope:
            entry["scope"] = scope[:120]
        item_key = str(item.get("item_key") or "").strip()
        if item_key:
            entry["item_key"] = item_key[:200]
        key = (
            field,
            item_key or evidence,
            json.dumps(entry.get("proposed_value"), ensure_ascii=False, sort_keys=True, default=str),
        )
        if key in seen:
            continue
        seen.add(key)
        normalized.append(entry)
    return normalized

# 规则本体搬进了服务层，因为带附件的那条路（extracted_action_apply）也必须走同一套。
# 这个别名保留原名，handlers 包的 re-export 和现有用例都依赖它。

def _apply_buyer_intent_parse_changes(
    db: Session,
    buyer_intent: dict[str, Any],
    changes: dict[str, Any],
    job_id: UUID,
    normalization_notes: list[str],
    source_context: dict[str, Any],
) -> list[str]:
    # 级别与推荐状态必须成对落地。买家侧没有统一的写入咽喉，三条路各自派生一次。
    resolved_grade = resolve_grade_pair(
        BUYER_GRADE,
        changes,
        buyer_intent,
        allow_reactivation=False,
    )
    changes.pop(BUYER_GRADE.grade_column, None)
    changes.pop(BUYER_GRADE.reason_column, None)
    changes.update(resolved_grade)

    diff = _diff_json_safe(buyer_intent, changes)
    if not diff:
        return []

    set_clauses = [f"{field} = :{field}" for field in diff]
    set_clauses.extend([
        "reviewed_at = null",
        "reviewed_by = null",
        "updated_at = now()",
        "updated_by = :updated_by",
    ])
    statement = text(
        f"""
        update buyer_intent
        set {', '.join(set_clauses)}
        where id = :buyer_intent_id
          and team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
        """
    )
    bind_params = [bindparam(field, type_=JSONB) for field in diff if field in BUYER_INTENT_PARSE_JSON_FIELDS]
    if bind_params:
        statement = statement.bindparams(*bind_params)
    db.execute(
        statement,
        {
            **{field: changes[field] for field in diff},
            "updated_by": SYSTEM_USER_ID,
            "buyer_intent_id": buyer_intent["id"],
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    _write_buyer_intent_parse_logs(db, buyer_intent, changes, diff, job_id, normalization_notes, source_context)
    _write_field_value_sources(
        db,
        entity_type="buyer_intent",
        entity_id=UUID(str(buyer_intent["id"])),
        changes=changes,
        diff=diff,
        source_context=source_context,
        review_status="auto_accepted",
    )
    create_search_doc_rebuild_job(
        db,
        entity_type="buyer_intent",
        entity_id=UUID(str(buyer_intent["id"])),
        source="buyer_intent_parse",
    )
    return list(diff.keys())

def _write_buyer_intent_parse_logs(
    db: Session,
    buyer_intent: dict[str, Any],
    changes: dict[str, Any],
    diff: dict[str, tuple[Any, Any]],
    job_id: UUID,
    normalization_notes: list[str],
    source_context: dict[str, Any],
) -> None:
    for field_path, (old_value, new_value) in diff.items():
        db.execute(
            text(
                """
                insert into action_application_log (
                  team_id, workspace_id, entity_type, entity_id, field_path,
                  old_value_json, new_value_json, source_type, source_id,
                  evidence_id, applied_by, edited_before_apply, metadata_json
                )
                values (
                  :team_id, :workspace_id, 'buyer_intent', :buyer_intent_id, :field_path,
                  :old_value_json, :new_value_json, 'buyer_intent_parse', :job_id,
                  :evidence_id, :applied_by, false, :metadata_json
                )
                """
            ).bindparams(
                bindparam("old_value_json", type_=JSONB),
                bindparam("new_value_json", type_=JSONB),
                bindparam("metadata_json", type_=JSONB),
            ),
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "buyer_intent_id": buyer_intent["id"],
                "field_path": field_path,
                "old_value_json": _json_safe_value(old_value),
                "new_value_json": _json_safe_value(new_value),
                "job_id": job_id,
                "evidence_id": source_context.get("evidence_id"),
                "applied_by": SYSTEM_USER_ID,
                "metadata_json": {
                    "source": "buyer_intent_parser",
                    "normalization_notes": normalization_notes,
                    "proposed_value": _json_safe_value(changes.get(field_path)),
                    "field_value_source": _json_safe_value(source_context),
                },
            },
        )
