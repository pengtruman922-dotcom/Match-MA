from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.ai.llm_client import LlmCallError, call_openai_compatible_chat
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID, SYSTEM_USER_ID
from backend.app.jobs.queue import JobClaim

from backend.app.services.profile_sections import (
    PROFILE_TOTAL_BUDGET,
    buyer_party_fact_block,
    load_profile_sections,
    render_profile_text,
)

from backend.app.jobs.handlers.common import (
    _get_default_node_config,
    _json_dumps,
    _json_safe_dict,
    _optional_uuid,
    _render_prompt_messages,
    _resolve_entity_id,
)
from backend.app.jobs.handlers.traces import (
    _insert_recommendation_report_llm_trace,
    _insert_rerank_trace,
)

def _handle_recommendation_report_generate(db: Session, job: JobClaim) -> dict[str, object]:
    report_id = _resolve_entity_id(job, expected_entity_type="recommendation_report")
    if report_id is None:
        raise ValueError("recommendation_report_generate job requires a recommendation_report entity_id.")

    report = _get_recommendation_report_for_job(db, report_id)
    session = _get_recommendation_session_for_report(db, report["session_id"])
    selected_items = _get_selected_items_for_recommendation_report(
        db,
        session_id=report["session_id"],
        selected_item_ids=report["selected_item_ids_json"],
    )
    context_json = _build_recommendation_report_context(
        report=report,
        session=session,
        selected_items=selected_items,
    )
    fallback_markdown = report.get("markdown_content") or _build_fallback_recommendation_report_markdown(
        session=session,
        selected_items=selected_items,
        title=report.get("title") or "推荐报告",
        report_type=report["report_type"],
    )

    try:
        node_config = _get_default_node_config(db, "recommendation_report_writer")
    except Exception as exc:
        _update_recommendation_report_generated(
            db,
            report_id=report_id,
            markdown_content=fallback_markdown,
            generated_by_model="rule_template_v0",
            prompt_version=None,
            metadata_patch={
                "generation_mode": "fallback",
                "fallback_reason": "model_node_config_error",
                "fallback_error": str(exc),
                "job_id": str(job.id),
            },
        )
        _insert_recommendation_report_message(
            db,
            report_id=report_id,
            session_id=report["session_id"],
            markdown_content=fallback_markdown,
            job_id=job.id,
            generation_mode="fallback",
        )
        return {
            "handled": True,
            "job_type": job.job_type,
            "report_id": str(report_id),
            "generation_mode": "fallback",
            "fallback_reason": "model_node_config_error",
        }

    prompt_messages = _render_prompt_messages(node_config, {"context_json": context_json})
    input_json = {
        "report_id": str(report_id),
        "session_id": str(report["session_id"]),
        "report_type": report["report_type"],
        "selected_item_count": len(selected_items),
        "context_json": context_json,
    }
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
            timeout_seconds=node_config["timeout_seconds"] or 180,
            response_format=node_config["response_format"],
        )
    except LlmCallError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        _insert_recommendation_report_llm_trace(
            db,
            job=job,
            report_id=report_id,
            node_config=node_config,
            status="failed",
            input_json=input_json,
            prompt_messages_json=prompt_messages,
            raw_output_text=None,
            parsed_output_json=None,
            schema_validation_json={"valid": False, "error": str(exc)},
            latency_ms=latency_ms,
            error_code="llm_call_failed",
            error_message=str(exc),
        )
        _update_recommendation_report_generated(
            db,
            report_id=report_id,
            markdown_content=fallback_markdown,
            generated_by_model="rule_template_v0",
            prompt_version=node_config["prompt_version"],
            metadata_patch={
                "generation_mode": "fallback",
                "fallback_reason": "llm_call_failed",
                "fallback_error": str(exc),
                "job_id": str(job.id),
            },
        )
        _insert_recommendation_report_message(
            db,
            report_id=report_id,
            session_id=report["session_id"],
            markdown_content=fallback_markdown,
            job_id=job.id,
            generation_mode="fallback",
        )
        return {
            "handled": True,
            "job_type": job.job_type,
            "report_id": str(report_id),
            "generation_mode": "fallback",
            "fallback_reason": "llm_call_failed",
            "trace_created": True,
        }

    markdown_content = (llm_result.raw_output_text or "").strip()
    if not markdown_content:
        markdown_content = fallback_markdown
        generation_mode = "fallback"
        schema_validation_json = {"valid": False, "error": "LLM output is empty."}
    else:
        generation_mode = "llm"
        schema_validation_json = {"valid": True, "output_mode": "markdown"}

    _insert_recommendation_report_llm_trace(
        db,
        job=job,
        report_id=report_id,
        node_config=node_config,
        status="succeeded" if generation_mode == "llm" else "failed",
        input_json=input_json,
        prompt_messages_json=prompt_messages,
        raw_output_text=llm_result.raw_output_text,
        parsed_output_json=llm_result.parsed_output_json,
        schema_validation_json=schema_validation_json,
        latency_ms=llm_result.latency_ms,
        prompt_tokens=llm_result.prompt_tokens,
        completion_tokens=llm_result.completion_tokens,
        total_tokens=llm_result.total_tokens,
    )
    _update_recommendation_report_generated(
        db,
        report_id=report_id,
        markdown_content=markdown_content,
        generated_by_model=node_config["model_name"] if generation_mode == "llm" else "rule_template_v0",
        prompt_version=node_config["prompt_version"],
        metadata_patch={
            "generation_mode": generation_mode,
            "job_id": str(job.id),
            "trace_created": True,
            "llm_model_name": node_config["model_name"],
        },
    )
    _insert_recommendation_report_message(
        db,
        report_id=report_id,
        session_id=report["session_id"],
        markdown_content=markdown_content,
        job_id=job.id,
        generation_mode=generation_mode,
    )
    return {
        "handled": True,
        "job_type": job.job_type,
        "report_id": str(report_id),
        "generation_mode": generation_mode,
        "model_name": node_config["model_name"],
        "prompt_version": node_config["prompt_version"],
        "trace_created": True,
    }

def _handle_recommendation_rerank(db: Session, job: JobClaim) -> dict[str, object]:
    session_id = _resolve_entity_id(job, expected_entity_type="recommendation_session")
    if session_id is None:
        raise ValueError("Recommendation deep-eval job requires a recommendation_session entity_id.")

    mode = str(job.payload_json.get("mode") or "")
    query = str(job.payload_json.get("query") or "").strip()
    candidates = job.payload_json.get("candidates") or []
    if mode not in {"buyer_to_target", "target_to_buyer"}:
        raise ValueError("Recommendation deep-eval job requires mode buyer_to_target or target_to_buyer.")
    if not isinstance(candidates, list) or len(candidates) < 2:
        raise ValueError("Recommendation deep-eval job requires at least two candidates.")
    deep_eval_config = _get_deep_eval_node_config(db, mode)
    return _run_recommendation_deep_eval(
        db,
        job,
        session_id=session_id,
        mode=mode,
        query=query,
        candidates=candidates,
        node_config=deep_eval_config,
    )

DEEP_EVAL_GRADES = ("A", "B", "C")

DEEP_EVAL_PROFILE_CHARS = 1200

# 单次评估、一套绝对标准；分片只切候选清单，不切上下文与评级标准。
# 交错分片（round-robin）保证片间若出现标准漂移，漂移方向与候选质量无关。
DEEP_EVAL_SHARD_SIZE = 15

DEEP_EVAL_MAX_WORKERS = 4

# 方向专属 prompt 节点；未在设置页建号时回落到共用节点，行为与改造前一致。
DEEP_EVAL_NODE_BY_MODE = {
    "buyer_to_target": "recommendation_deep_eval_to_target",
    "target_to_buyer": "recommendation_deep_eval_to_buyer",
}

DEEP_EVAL_FALLBACK_NODE = "recommendation_deep_eval"


def _get_deep_eval_node_config(db: Session, mode: str) -> dict[str, Any]:
    node_name = DEEP_EVAL_NODE_BY_MODE.get(mode)
    if node_name:
        try:
            return _get_default_node_config(db, node_name)
        except ValueError:
            # 方向节点未配置：回落共用节点，两个方向共享同一套提示词。
            pass
    return _get_default_node_config(db, DEEP_EVAL_FALLBACK_NODE)


def _candidate_profile_fields(
    sections: dict[str, dict[str, Any]] | None,
    fallback_document: str,
) -> dict[str, Any]:
    """Prefer the section profile; fall back to the search doc when empty.

    The section text is qualitative by construction, so it gets the larger
    per-section budget. The search-doc fallback keeps the old cap: it is mostly
    a restatement of structured fields the candidate payload already carries,
    and widening it would buy noise rather than new information.
    """
    profile_text = render_profile_text(sections)
    if profile_text:
        return {
            "profile": profile_text[:PROFILE_TOTAL_BUDGET],
            "profile_source": "profile_sections",
        }
    return {
        "profile": fallback_document[:DEEP_EVAL_PROFILE_CHARS],
        "profile_source": "search_doc",
    }


def _deep_eval_candidate_id(candidate: dict[str, Any], mode: str) -> str | None:
    """The entity the deep eval is judging, used to write results back."""
    key = "seller_target_id" if mode == "buyer_to_target" else "buyer_intent_id"
    value = candidate.get(key)
    return str(value) if value else None


def _interleave_shards(items: list[Any], shard_size: int) -> list[list[Any]]:
    """Split by round-robin so每片的候选质量分布一致（不按分数切段）。"""
    if len(items) <= shard_size:
        return [items] if items else []
    shard_count = (len(items) + shard_size - 1) // shard_size
    shards: list[list[Any]] = [[] for _ in range(shard_count)]
    for position, item in enumerate(items):
        shards[position % shard_count].append(item)
    return [shard for shard in shards if shard]

def _run_recommendation_deep_eval(
    db: Session,
    job: JobClaim,
    *,
    session_id: UUID,
    mode: str,
    query: str,
    candidates: list[Any],
    node_config: dict[str, Any],
) -> dict[str, object]:
    raw_anchor = job.payload_json.get("anchor") if isinstance(job.payload_json.get("anchor"), dict) else {}
    anchor = raw_anchor
    if mode == "buyer_to_target":
        # 买家身份不进提示词正文；party_id 仅用于取"买方自身情况"事实块。
        anchor = {key: value for key, value in anchor.items() if key not in {"buyer_party_id", "buyer_name"}}
    anchor_doc_mode = "target_to_buyer" if mode == "buyer_to_target" else "buyer_to_target"
    anchor_doc_key = "buyer_intent_id" if mode == "buyer_to_target" else "seller_target_id"
    anchor_doc_text = None
    if anchor.get("id"):
        anchor_doc_text = _get_candidate_search_doc_text(
            db, mode=anchor_doc_mode, candidate={anchor_doc_key: anchor.get("id")}
        )
    # 协同性类诉求（"与现有业务有关联性""强链补链"）判不了，除非知道买家自己在做什么。
    # 只在买家为锚点的方向注入，反向的候选买家仍保持匿名。
    party_facts = ""
    anchor_profile_text = ""
    if mode == "buyer_to_target":
        party_facts = buyer_party_fact_block(db, raw_anchor.get("buyer_party_id"))
    else:
        anchor_sections = load_profile_sections(
            db, entity_type="seller_target", entity_ids=[anchor.get("id")] if anchor.get("id") else []
        ).get(str(anchor.get("id") or ""))
        anchor_profile_text = render_profile_text(anchor_sections)

    anchor_context = "\n\n".join(
        part
        for part in (
            query or None,
            json.dumps(anchor, ensure_ascii=False, default=str) if anchor else None,
            anchor_profile_text or None,
            anchor_doc_text,
            party_facts or None,
        )
        if part
    )

    documents = _build_rerank_documents(db, mode=mode, candidates=candidates)
    candidate_entity_type = "seller_target" if mode == "buyer_to_target" else "buyer_intent"
    candidate_ids = [
        _deep_eval_candidate_id(candidate, mode)
        for candidate in candidates
        if isinstance(candidate, dict)
    ]
    profiles_by_entity = load_profile_sections(
        db,
        entity_type=candidate_entity_type,
        entity_ids=[value for value in candidate_ids if value],
    )
    candidate_items: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        candidate_id = _deep_eval_candidate_id(candidate, mode)
        if not candidate_id:
            continue
        evidence_json = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
        candidate_items.append(
            {
                "candidate_id": candidate_id,
                # index 仅为兼容尚未改用 candidate_id 的历史提示词而保留，
                # 校验时优先认 candidate_id；提示词更新后这个字段就没人读了。
                "index": index,
                "name": candidate.get("seller_target_name") if mode == "buyer_to_target" else candidate.get("buyer_intent_name"),
                "rule_score": candidate.get("score"),
                "recommendation_level": candidate.get("recommendation_level"),
                "match_state": candidate.get("match_state"),
                "matched_scenarios": candidate.get("matched_scenarios") or [],
                "matches": evidence_json.get("matches") or [],
                "gaps": evidence_json.get("gaps") or [],
                "missing_dimensions": candidate.get("missing_dimensions") or [],
                **_candidate_profile_fields(
                    profiles_by_entity.get(candidate_id),
                    documents[index]["text"] if index < len(documents) else "",
                ),
            }
        )
    if not candidate_items:
        raise ValueError("Deep eval requires candidates carrying an entity id.")

    shards = _interleave_shards(candidate_items, DEEP_EVAL_SHARD_SIZE)
    # 快照：意向/画像/prompt/模型/输入 ID 集合，供日后解释"当时为何这样推荐"
    input_json = {
        "session_id": str(session_id),
        "mode": mode,
        "engine": "llm_deep_eval",
        "candidate_count": len(candidate_items),
        "shard_count": len(shards),
        "anchor_context_preview": anchor_context[:1000],
        "snapshot": {
            "node_name": node_config.get("node_name"),
            "prompt_version": node_config.get("prompt_version"),
            "model_name": str(node_config["model_name"]),
            "candidate_ids": [item["candidate_id"] for item in candidate_items],
            "profile_chars": DEEP_EVAL_PROFILE_CHARS,
        },
    }

    started = time.perf_counter()
    try:
        shard_outcomes = _run_deep_eval_shards(
            node_config=node_config,
            mode=mode,
            anchor_context=anchor_context,
            shards=shards,
        )
    except LlmCallError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        _insert_rerank_trace(
            db,
            job=job,
            session_id=session_id,
            node_config=node_config,
            status="failed",
            input_json=input_json,
            parsed_output_json=None,
            latency_ms=latency_ms,
            total_tokens=None,
            error_code="deep_eval_call_failed",
            error_message=str(exc),
        )
        raise

    results: list[dict[str, Any]] = []
    total_tokens = 0
    for outcome in shard_outcomes:
        results.extend(outcome["results"])
        total_tokens += outcome["total_tokens"] or 0
    latency_ms = int((time.perf_counter() - started) * 1000)

    valid_ids = {item["candidate_id"] for item in candidate_items}
    covered_ids = {result["candidate_id"] for result in results}
    if not covered_ids:
        raise ValueError("Deep eval returned no usable result for any candidate.")

    reranked_candidates = _apply_deep_eval_results_to_candidates(
        candidates=candidates,
        results=results,
        mode=mode,
        model_name=str(node_config["model_name"]),
    )
    _insert_rerank_trace(
        db,
        job=job,
        session_id=session_id,
        node_config=node_config,
        status="succeeded",
        input_json=input_json,
        parsed_output_json={
            "engine": "llm_deep_eval",
            "model": str(node_config["model_name"]),
            "shards": [
                {
                    "candidate_ids": outcome["candidate_ids"],
                    "retried": outcome["retried"],
                    "grade_counts": outcome["grade_counts"],
                }
                for outcome in shard_outcomes
            ],
            "uncovered_candidate_ids": sorted(valid_ids - covered_ids),
            "results": results,
            "reranked_candidates": reranked_candidates,
        },
        latency_ms=latency_ms,
        total_tokens=total_tokens or None,
    )
    _insert_recommendation_rerank_message(
        db,
        session_id=session_id,
        job_id=job.id,
        reranked_candidates=reranked_candidates,
        model_name=str(node_config["model_name"]),
    )
    return {
        "handled": True,
        "job_type": job.job_type,
        "session_id": str(session_id),
        "engine": "llm_deep_eval",
        "model_name": str(node_config["model_name"]),
        "candidate_count": len(candidate_items),
        "shard_count": len(shards),
        "evaluated_count": len(covered_ids),
        "uncovered_count": len(valid_ids - covered_ids),
        "reranked_count": len(reranked_candidates),
        "trace_created": True,
    }

def _run_deep_eval_shards(
    *,
    node_config: dict[str, Any],
    mode: str,
    anchor_context: str,
    shards: list[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Evaluate every shard against the same prompt and grading standard.

    Shards run concurrently and never touch the database — the session is not
    thread safe, so all reads happen before this call and all writes after it.
    """
    if len(shards) == 1:
        return [_run_single_deep_eval_shard(node_config, mode, anchor_context, shards[0])]
    with ThreadPoolExecutor(max_workers=min(DEEP_EVAL_MAX_WORKERS, len(shards))) as executor:
        futures = [
            executor.submit(_run_single_deep_eval_shard, node_config, mode, anchor_context, shard)
            for shard in shards
        ]
        return [future.result() for future in futures]

def _run_single_deep_eval_shard(
    node_config: dict[str, Any],
    mode: str,
    anchor_context: str,
    shard: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_ids = [item["candidate_id"] for item in shard]
    results, problems, total_tokens = _call_deep_eval(node_config, mode, anchor_context, shard)

    retried = False
    covered = {result["candidate_id"] for result in results}
    missing = [item for item in shard if item["candidate_id"] not in covered]
    if missing:
        # 定向重发：只补没拿到合法结果的候选，不整批重来。
        retried = True
        retry_results, _, retry_tokens = _call_deep_eval(
            node_config,
            mode,
            anchor_context,
            missing,
            correction_notes=problems,
        )
        total_tokens += retry_tokens
        results.extend(result for result in retry_results if result["candidate_id"] not in covered)

    grade_counts: dict[str, int] = {}
    for result in results:
        grade_counts[result["grade"]] = grade_counts.get(result["grade"], 0) + 1
    return {
        "candidate_ids": expected_ids,
        "results": results,
        "retried": retried,
        "total_tokens": total_tokens,
        "grade_counts": grade_counts,
    }

def _call_deep_eval(
    node_config: dict[str, Any],
    mode: str,
    anchor_context: str,
    items: list[dict[str, Any]],
    *,
    correction_notes: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str], int]:
    variables = {
        "mode": mode,
        "anchor_context": anchor_context,
        "candidates_json": json.dumps(items, ensure_ascii=False, default=str),
    }
    prompt_messages = _render_prompt_messages(node_config, variables)
    if correction_notes:
        prompt_messages = [
            *prompt_messages,
            {
                "role": "user",
                "content": (
                    "上一次输出存在以下问题，请只针对本次给出的候选重新输出，"
                    "candidate_id 必须原样引用：\n" + "\n".join(correction_notes[:10])
                ),
            },
        ]
    llm_result = call_openai_compatible_chat(
        base_url=node_config["base_url"],
        api_key_secret_ref=node_config["api_key_secret_ref"],
        api_key_encrypted=node_config.get("api_key_encrypted"),
        model_name=node_config["model_name"],
        messages=prompt_messages,
        temperature=node_config["temperature"],
        top_p=node_config["top_p"],
        max_tokens=node_config["max_tokens"],
        timeout_seconds=node_config["timeout_seconds"] or 180,
        response_format=node_config["response_format"],
    )
    results, problems = _validate_deep_eval_results(
        llm_result.parsed_output_json,
        {item["candidate_id"] for item in items},
        index_fallback={
            item["index"]: item["candidate_id"] for item in items if item.get("index") is not None
        },
    )
    return results, problems, llm_result.total_tokens or 0

def _validate_deep_eval_results(
    parsed_output_json: dict[str, Any] | None,
    expected_ids: set[str],
    *,
    index_fallback: dict[int, str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Keep only results that name a candidate from this shard, exactly once.

    Validation is done in code rather than via json_schema: the LLM client only
    supports response_format=json_object, and OpenAI-compatible endpoints vary
    in whether they honour a schema at all.
    """
    problems: list[str] = []
    if not isinstance(parsed_output_json, dict):
        return [], ["输出不是 JSON 对象"]
    raw_results = parsed_output_json.get("results")
    if not isinstance(raw_results, list) or not raw_results:
        return [], ["输出缺少 results 数组"]

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_results:
        if not isinstance(item, dict):
            problems.append("results 中存在非对象元素")
            continue
        candidate_id = str(item.get("candidate_id") or "").strip()
        if candidate_id not in expected_ids and index_fallback:
            # 历史提示词只回 index；按本片的 index→id 映射补上，避免旧提示词全军覆没。
            try:
                candidate_id = index_fallback.get(int(item.get("index")), "")
            except (TypeError, ValueError):
                candidate_id = ""
        if candidate_id not in expected_ids:
            problems.append(f"candidate_id 不属于本次候选集合：{str(item.get('candidate_id'))[:60] or '(空)'}")
            continue
        if candidate_id in seen:
            problems.append(f"candidate_id 重复：{candidate_id}")
            continue
        grade = str(item.get("grade") or "").strip().upper()
        if grade not in DEEP_EVAL_GRADES:
            problems.append(f"{candidate_id} 的 grade 非法：{item.get('grade')!r}")
            grade = "C"
        seen.add(candidate_id)
        scenarios = item.get("matched_scenarios")
        results.append(
            {
                "candidate_id": candidate_id,
                "grade": grade,
                "matched_scenarios": [str(value) for value in scenarios] if isinstance(scenarios, list) else [],
                "reason": str(item.get("reason") or "").strip() or None,
                "risks": str(item.get("risks") or "").strip() or None,
                "info_gaps": str(item.get("info_gaps") or "").strip() or None,
            }
        )
    for missing_id in sorted(expected_ids - seen):
        problems.append(f"缺少 candidate_id 的评估结果：{missing_id}")
    return results, problems

def _apply_deep_eval_results_to_candidates(
    *,
    candidates: list[Any],
    results: list[dict[str, Any]],
    mode: str,
    model_name: str,
) -> list[dict[str, Any]]:
    normalized = [dict(candidate) for candidate in candidates if isinstance(candidate, dict)]
    result_by_id = {item["candidate_id"]: item for item in results}
    order_by_id = {item["candidate_id"]: position for position, item in enumerate(results)}
    result_by_index: dict[int, dict[str, Any]] = {}
    order_by_index: dict[int, int] = {}
    for index, candidate in enumerate(normalized):
        candidate_id = _deep_eval_candidate_id(candidate, mode)
        if candidate_id and candidate_id in result_by_id:
            result_by_index[index] = result_by_id[candidate_id]
            order_by_index[index] = order_by_id[candidate_id]

    for index, candidate in enumerate(normalized):
        result = result_by_index.get(index)
        if result is None:
            continue
        candidate["deep_eval"] = {
            "grade": result["grade"],
            "reason": result.get("reason"),
            "risks": result.get("risks"),
            "info_gaps": result.get("info_gaps"),
            "matched_scenarios": result.get("matched_scenarios") or [],
            "model": model_name,
        }
        evidence_json = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
        score_json = evidence_json.get("score") if isinstance(evidence_json.get("score"), dict) else {}
        candidate["evidence_json"] = {
            **evidence_json,
            "score": {
                **score_json,
                "deep_eval_grade": result["grade"],
                "deep_eval_model": model_name,
            },
        }

    # 评级是绝对标准，跨片无需归一化：先按档、再按片内顺序、最后按规则分。
    grade_rank = {"A": 0, "B": 1, "C": 2}
    decorated = []
    for index, candidate in enumerate(normalized):
        grade = (candidate.get("deep_eval") or {}).get("grade")
        decorated.append(
            (
                grade_rank.get(grade, 3),
                order_by_index.get(index, 999),
                -float(candidate.get("score") or 0),
                index,
                candidate,
            )
        )
    decorated.sort(key=lambda row: row[:4])
    ordered = [row[4] for row in decorated]
    for rank, candidate in enumerate(ordered, start=1):
        candidate["rank"] = rank
    return ordered

def _get_recommendation_report_for_job(db: Session, report_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, session_id, report_type, selected_item_ids_json, title,
              markdown_content, status, generated_by_model, prompt_version,
              metadata_json
            from recommendation_report
            where id = :report_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "report_id": report_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"Recommendation report not found: {report_id}")
    return dict(row)

def _get_recommendation_session_for_report(db: Session, session_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, mode, buyer_intent_id, buyer_party_id, seller_target_id,
              anonymous_input_snapshot, initial_condition_snapshot_json,
              latest_condition_snapshot_json, selected_count, report_count,
              metadata_json, created_at::text as created_at, updated_at::text as updated_at
            from recommendation_session
            where id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"Recommendation session not found: {session_id}")
    return _json_safe_dict(row)

def _get_selected_items_for_recommendation_report(
    db: Session,
    *,
    session_id: UUID,
    selected_item_ids: list[Any] | None,
) -> list[dict[str, Any]]:
    where = [
        "ri.session_id = :session_id",
        "ri.team_id = :team_id",
        "ri.workspace_id = :workspace_id",
        "ri.canceled_at is null",
    ]
    params: dict[str, Any] = {
        "session_id": session_id,
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
    }
    if selected_item_ids:
        where.append("ri.id in :selected_item_ids")
        params["selected_item_ids"] = tuple(UUID(str(item)) for item in selected_item_ids)

    statement = text(
        f"""
        select
          ri.id, ri.session_id, ri.mode,
          ri.seller_target_id, st.target_name as seller_target_name,
          ri.buyer_intent_id, bi.intent_name as buyer_intent_name,
          ri.buyer_party_id, bp.buyer_name,
          ri.rank_at_selection, ri.recommendation_level, ri.match_summary,
          ri.risk_summary, ri.gap_summary, ri.reason_snapshot,
          ri.evidence_snapshot_json, ri.selected_at::text as selected_at,
          ri.metadata_json
        from recommendation_selected_item ri
        left join seller_target st on st.id = ri.seller_target_id
        left join buyer_intent bi on bi.id = ri.buyer_intent_id
        left join buyer_party bp on bp.id = ri.buyer_party_id
        where {' and '.join(where)}
        order by ri.rank_at_selection nulls last, ri.selected_at asc
        """
    )
    if selected_item_ids:
        statement = statement.bindparams(bindparam("selected_item_ids", expanding=True))

    rows = db.execute(statement, params).mappings().all()
    return [_json_safe_dict(row) for row in rows]

def _build_recommendation_report_context(
    *,
    report: dict[str, Any],
    session: dict[str, Any],
    selected_items: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "report": {
            "id": str(report["id"]),
            "report_type": report["report_type"],
            "title": report.get("title"),
        },
        "session": session,
        "selected_items": selected_items,
        "instructions": {
            "source_policy": "Use only provided context. State missing information as review needed.",
            "output_format": "Chinese Markdown",
            "generation_boundary": "This is a draft report for human review, not an external final document.",
        },
    }

def _build_fallback_recommendation_report_markdown(
    *,
    session: dict[str, Any],
    selected_items: list[dict[str, Any]],
    title: str,
    report_type: str,
) -> str:
    lines = [
        f"# {title}",
        "",
        f"- 推荐会话：`{session['id']}`",
        f"- 推荐方向：{session['mode']}",
        f"- 报告类型：{report_type}",
        f"- 已采用候选数：{len(selected_items)}",
        "",
        "## 推荐清单",
        "",
    ]
    for index, item in enumerate(selected_items, start=1):
        lines.extend(
            [
                f"### {index}. {item.get('seller_target_name') or '未绑定标的'} / {item.get('buyer_intent_name') or '未绑定意向'}",
                "",
                f"- 买家：{item.get('buyer_name') or '未绑定买家'}",
                f"- 推荐等级：{item.get('recommendation_level') or '未评级'}",
                f"- 匹配理由：{item.get('match_summary') or '暂无'}",
                f"- 信息缺口：{item.get('gap_summary') or '暂无'}",
                f"- 风险提示：{item.get('risk_summary') or '暂无'}",
                "",
            ]
        )
    lines.extend(
        [
            "## 后续建议",
            "",
            "- 由业务人员复核推荐理由、信息缺口和风险提示。",
            "- 复核通过后，在买家-标的关系中继续记录推荐、反馈、尽调和终止等进展。",
        ]
    )
    return "\n".join(lines)

def _build_rerank_documents(
    db: Session,
    *,
    mode: str,
    candidates: list[Any],
) -> list[dict[str, str]]:
    documents: list[dict[str, str]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_key = _candidate_key(candidate)
        document_text = _get_candidate_search_doc_text(db, mode=mode, candidate=candidate)
        if not document_text:
            document_text = _candidate_fallback_text(candidate)
        documents.append({"candidate_key": candidate_key, "text": document_text})
    return documents

def _get_candidate_search_doc_text(db: Session, *, mode: str, candidate: dict[str, Any]) -> str | None:
    if mode == "buyer_to_target":
        seller_target_id = _optional_uuid(candidate.get("seller_target_id"))
        if not seller_target_id:
            return None
        row = db.execute(
            text(
                """
                select full_text
                from seller_target_search_doc
                where seller_target_id = :seller_target_id
                  and team_id = :team_id
                  and workspace_id = :workspace_id
                  and doc_type = 'profile'
                order by updated_at desc
                limit 1
                """
            ),
            {
                "seller_target_id": seller_target_id,
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
            },
        ).mappings().one_or_none()
    else:
        buyer_intent_id = _optional_uuid(candidate.get("buyer_intent_id"))
        if not buyer_intent_id:
            return None
        row = db.execute(
            text(
                """
                select
                  intent_name, raw_requirement_text, intent_summary,
                  industry_primary, industry_secondary, industries_json, industry_l2_json,
                  excluded_industries_json, industry_focus_tags_json,
                  region_scope_summary, region_constraints_json,
                  min_revenue_yuan, min_net_profit_yuan, min_total_profit_yuan,
                  min_valuation_yuan, max_valuation_yuan,
                  min_market_cap_yuan, max_market_cap_yuan, market_cap_range_summary,
                  max_pe, max_ps, min_net_margin, min_gross_margin,
                  requires_control, requires_consolidation, accepts_minority_investment,
                  desired_equity_ratio_min, desired_equity_ratio_max, equity_ratio_summary,
                  preferred_listed_status, acceptable_listed_status_json, condition_effects_json,
                  listing_board_requirement_summary,
                  financing_stage_requirement_summary, transaction_type, transaction_types_json,
                  premium_tolerance_summary, max_premium_rate, max_debt_ratio,
                  debt_ratio_requirement_summary, major_risk_tolerance_summary,
                  negative_summary, priority_summary, preference_summary, unknown_summary,
                  needs_confirmation_json,
                  coalesce((
                    select jsonb_agg(
                      jsonb_build_object(
                        'id', scenario.id,
                        'label', scenario.label,
                        'fields', scenario.fields_json,
                        'needs_confirmation', scenario.needs_confirmation_json,
                        'condition_effects', scenario.condition_effects_json
                      ) order by scenario.sort_order, scenario.created_at
                    )
                    from buyer_intent_scenario scenario
                    where scenario.buyer_intent_id = buyer_intent.id
                      and scenario.deleted_at is null
                      and scenario.active = true
                  ), '[]'::jsonb) as scenarios_json
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
        return json.dumps(dict(row), ensure_ascii=False, default=str) if row else None
    return str(row["full_text"]) if row and row["full_text"] else None

def _candidate_fallback_text(candidate: dict[str, Any]) -> str:
    parts = [
        candidate.get("seller_target_name"),
        candidate.get("buyer_intent_name"),
        candidate.get("buyer_name"),
        candidate.get("match_summary"),
        candidate.get("gap_summary"),
        candidate.get("risk_summary"),
        candidate.get("evidence_json"),
    ]
    return "\n".join(str(part) for part in parts if part)

def _candidate_key(candidate: dict[str, Any]) -> str:
    return "|".join(
        str(candidate.get(key) or "")
        for key in ["mode", "buyer_intent_id", "seller_target_id"]
    )

def _apply_rerank_results_to_candidates(
    *,
    candidates: list[Any],
    rerank_results: list[Any],
    model_name: str,
) -> list[dict[str, Any]]:
    normalized_candidates = [dict(candidate) for candidate in candidates if isinstance(candidate, dict)]
    score_by_index = {item.index: item.relevance_score for item in rerank_results}
    output: list[dict[str, Any]] = []
    for index, candidate in enumerate(normalized_candidates):
        rerank_score = float(score_by_index.get(index, 0.0))
        original_score = float(candidate.get("score") or 0)
        rerank_boost = round(max(0.0, min(rerank_score, 1.0)) * 15, 2)
        final_score = min(round(original_score + rerank_boost, 2), 100.0)
        evidence_json = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
        score_json = evidence_json.get("score") if isinstance(evidence_json.get("score"), dict) else {}
        candidate["score"] = final_score
        candidate["recommendation_level"] = _recommendation_level_from_score(final_score)
        candidate["evidence_json"] = {
            **evidence_json,
            "score": {
                **score_json,
                "rerank_score": rerank_score,
                "rerank_boost": rerank_boost,
                "rerank_model": model_name,
                "final_score": final_score,
            },
        }
        output.append(candidate)
    output.sort(
        key=lambda item: (
            item.get("evidence_json", {}).get("score", {}).get("rerank_score", 0),
            item.get("score") or 0,
        ),
        reverse=True,
    )
    for rank, candidate in enumerate(output, start=1):
        candidate["rank"] = rank
        candidate["evidence_json"]["score"]["rerank_rank"] = rank
    return output

def _recommendation_level_from_score(score: float) -> str:
    if score >= 80:
        return "strong"
    if score >= 60:
        return "recommended"
    if score >= 35:
        return "possible"
    return "weak"

def _update_recommendation_report_generated(
    db: Session,
    *,
    report_id: UUID,
    markdown_content: str,
    generated_by_model: str,
    prompt_version: str | None,
    metadata_patch: dict[str, Any],
) -> None:
    db.execute(
        text(
            """
            update recommendation_report
            set markdown_content = :markdown_content,
                status = 'generated',
                generated_by_model = :generated_by_model,
                prompt_version = :prompt_version,
                metadata_json = metadata_json || :metadata_patch
            where id = :report_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "report_id": report_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "markdown_content": markdown_content,
            "generated_by_model": generated_by_model,
            "prompt_version": prompt_version,
            "metadata_patch": metadata_patch,
        },
    )

def _insert_recommendation_report_message(
    db: Session,
    *,
    report_id: UUID,
    session_id: UUID,
    markdown_content: str,
    job_id: UUID,
    generation_mode: str,
) -> None:
    db.execute(
        text(
            """
            insert into recommendation_message (
              team_id, workspace_id, session_id, role, content,
              content_type, metadata_json, created_by
            )
            values (
              :team_id, :workspace_id, :session_id, 'assistant', :content,
              'markdown', :metadata_json, :created_by
            )
            """
        ).bindparams(bindparam("metadata_json", type_=JSONB)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "session_id": session_id,
            "content": markdown_content,
            "metadata_json": {
                "report_id": str(report_id),
                "job_id": str(job_id),
                "message_type": "recommendation_report",
                "generation_mode": generation_mode,
            },
            "created_by": SYSTEM_USER_ID,
        },
    )
    db.execute(
        text(
            """
            update recommendation_session
            set updated_at = now()
            where id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {"session_id": session_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    )

def _insert_recommendation_rerank_message(
    db: Session,
    *,
    session_id: UUID,
    job_id: UUID,
    reranked_candidates: list[dict[str, Any]],
    model_name: str,
) -> None:
    db.execute(
        text(
            """
            insert into recommendation_message (
              team_id, workspace_id, session_id, role, content,
              content_type, metadata_json, created_by
            )
            values (
              :team_id, :workspace_id, :session_id, 'tool', :content,
              'json', :metadata_json, :created_by
            )
            """
        ).bindparams(bindparam("metadata_json", type_=JSONB)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "session_id": session_id,
            "content": _json_dumps(
                {
                    "message_type": "reranked_candidates",
                    "candidate_count": len(reranked_candidates),
                    "candidates": reranked_candidates,
                }
            ),
            "metadata_json": {
                "job_id": str(job_id),
                "message_type": "reranked_candidates",
                "model_name": model_name,
            },
            "created_by": SYSTEM_USER_ID,
        },
    )
    db.execute(
        text(
            """
            update recommendation_session
            set latest_condition_snapshot_json = latest_condition_snapshot_json || :metadata_patch,
                updated_at = now()
            where id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "metadata_patch": {
                "last_rerank_job_id": str(job_id),
                "last_rerank_model": model_name,
                "last_reranked_candidate_count": len(reranked_candidates),
            },
        },
    )
