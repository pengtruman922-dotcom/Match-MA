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
from backend.app.ai.tool_loop import ToolLoopAborted, run_tool_loop
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID, SYSTEM_USER_ID
from backend.app.config import get_settings
from backend.app.jobs.handlers.common import (
    _attach_multimodal_images,
    _attachment_file_bytes,
    _get_default_node_config,
    _json_dumps,
    _json_safe_dict,
    _optional_uuid,
    _render_prompt_messages,
    _resolve_entity_id,
)
from backend.app.services.image_inputs import (
    ImageInputError,
    is_supported_multimodal_image,
    prepare_image_for_multimodal,
)
from backend.app.jobs.handlers.traces import (
    _insert_recommendation_report_llm_trace,
    _insert_rerank_trace,
)
from backend.app.jobs.queue import JobClaim
from backend.app.registry.nodes import (
    deep_eval_node_by_mode,
    deep_eval_understudy_node_name,
    recommendation_agent_node_by_mode,
    report_writer_node_by_type,
)
from backend.app.services.recommendation_agent_tools import (
    MAX_DETAIL_TARGETS_TOTAL,
    MAX_SEARCH_CALLS,
    RecommendationAgentTools,
    build_agent_tools,
)
from backend.app.services.recommendation_conditions import (
    describe_intent_snapshot,
    parse_recommendation_intent,
)
from backend.app.services.recommendation_flow import (
    agent_turn_aborted,
    target_facts_for_agent,
)
from backend.app.services.profile_sections import (
    PROFILE_TOTAL_BUDGET,
    buyer_party_fact_block,
    load_profile_sections,
    render_profile_text,
)
from backend.app.services.recommendation_report import (
    build_fallback_report_markdown as _build_fallback_recommendation_report_markdown,
)
from backend.app.services.recommendation_report import (
    build_recommendation_report_context as _build_recommendation_report_context,
)
from backend.app.services.recommendation_report import (
    normalize_report_markdown,
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
        db,
        report=report,
        session=session,
        selected_items=selected_items,
    )
    fallback_markdown = _build_fallback_recommendation_report_markdown(
        context_json,
        title=report.get("title") or "推荐报告",
    )
    node_name = report_writer_node_by_type()[report["report_type"]]

    try:
        node_config = _get_default_node_config(db, node_name)
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
                "node_name": node_name,
                "report_context_version": context_json.get("schema_version"),
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

    prompt_messages = _render_prompt_messages(
        node_config,
        {"report_context_json": context_json},
    )
    input_json = {
        "report_id": str(report_id),
        "session_id": str(report["session_id"]),
        "report_type": report["report_type"],
        "selected_item_count": len(selected_items),
        "report_context_json": context_json,
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
            node_name=node_name,
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
                "node_name": node_name,
                "report_context_version": context_json.get("schema_version"),
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

    markdown_content = normalize_report_markdown(
        llm_result.raw_output_text or "",
        title=report.get("title") or "推荐报告",
    )
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
        node_name=node_name,
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
            "node_name": node_name,
            "report_context_version": context_json.get("schema_version"),
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
# 映射与回落目标都来自代码目录 registry/nodes.py，此处不再各自声明一份。
DEEP_EVAL_NODE_BY_MODE = deep_eval_node_by_mode()

DEEP_EVAL_FALLBACK_NODE = deep_eval_understudy_node_name()


# 编排 Agent。刻意没有共用兜底节点：两个方向的工具集不同，一份提示词兜不住。
RECOMMENDATION_AGENT_NODE_BY_MODE = recommendation_agent_node_by_mode()

# tool_loop 的默认 8000 装不下 30 条候选摘要；调大到能容纳一次满额 search_targets。
AGENT_TOOL_RESULT_LIMIT = 16000
AGENT_MAX_ITERATIONS = 12

# 用户对整次推荐的耐心是 2-5 分钟，编排阶段留 4 分钟，剩下的给流式写作。
# 这同时是对 worker stale 窗口（1800s）的第二道保险：迭代上限管不住单次调用
# 很慢的情况，墙钟能。
AGENT_WALL_CLOCK_BUDGET_SECONDS = 240


def _handle_recommendation_agent(db: Session, job: JobClaim) -> dict[str, object]:
    """Run one agent turn: understand, screen, read a few, hand over a brief.

    The turn deliberately stops at the brief. Prose generation is a separate,
    tool-free node the API streams (see the answer-stream endpoint), which is
    what lets the user watch words appear instead of a spinner.
    """
    session_id = _resolve_entity_id(job, expected_entity_type="recommendation_session")
    if session_id is None:
        raise ValueError("recommendation_agent job requires a recommendation_session entity_id.")

    payload = job.payload_json or {}
    mode = str(payload.get("mode") or "")
    turn_id = str(payload.get("turn_id") or "")
    user_message = str(payload.get("user_message") or "").strip()
    if mode not in RECOMMENDATION_AGENT_NODE_BY_MODE:
        raise ValueError(f"No recommendation agent node is registered for mode {mode!r}.")
    if not turn_id:
        raise ValueError("recommendation_agent job requires a turn_id.")
    if not user_message:
        raise ValueError("recommendation_agent job requires a user_message.")

    node_name = RECOMMENDATION_AGENT_NODE_BY_MODE[mode]
    node_config = _get_default_node_config(db, node_name)
    history_context = str(payload.get("history_context") or "")

    # ① 先把这句话解析成一份需求快照，再让主 Agent 动手。多花 3-8 秒换来的是
    # 一条可比对的基线：用户说了什么与 agent 筛了什么从此是两份可以并排看的
    # 东西，「agent 自己编条件」不再是一件查不出来的事。
    # 解析失败不中断本轮 —— 退化成「没有结构化条件的一轮」比直接报错有用得多，
    # 但状态会如实写进消息与 trace，不会假装成功（见 parser_status）。
    if agent_turn_aborted(db, session_id, turn_id):
        # 排队期间就被停掉了：一次模型调用都不该花。
        return _aborted_agent_turn_result(job, session_id=session_id, turn_id=turn_id)
    intent_snapshot = parse_recommendation_intent(
        db,
        mode=mode,
        user_message=user_message,
        history_context=history_context,
    )
    _insert_agent_understanding_message(
        db,
        session_id=session_id,
        turn_id=turn_id,
        job_id=job.id,
        snapshot=intent_snapshot,
    )
    # 立刻提交，与 agent_step 同样的理由：前端轮询要在 agent 还在跑的时候
    # 就能看到「已读懂需求」。
    db.commit()
    if agent_turn_aborted(db, session_id, turn_id):
        return _aborted_agent_turn_result(job, session_id=session_id, turn_id=turn_id)

    agent_context = {
        "user_message": user_message,
        "budgets": {
            "max_search_calls": MAX_SEARCH_CALLS,
            "max_detail_targets": MAX_DETAIL_TARGETS_TOTAL,
            "max_tool_iterations": AGENT_MAX_ITERATIONS,
        },
    }
    # 历史单独一个变量而不是塞进 JSON：塞进去会被转义成一行 \n，标签就不再是
    # 模型看得见的边界了。
    attachment_ids = [str(value) for value in (payload.get("attachment_ids") or []) if str(value or "").strip()]
    images, image_summaries = _agent_image_inputs(db, attachment_ids)
    if images:
        # 只放摘要，不放 data_url —— 图片本身走 multimodal parts，塞进 JSON 会被
        # 重复计费一次。
        agent_context["images"] = image_summaries

    messages = _render_prompt_messages(
        node_config,
        {
            "recommendation_context_json": agent_context,
            "history_context": history_context,
        },
    )
    if images:
        messages = _attach_multimodal_images(
            messages,
            images,
            instruction=(
                "以下图片是客户发来的需求材料，请直接阅读并从中提取并购或出售需求。"
                "不要输出附件 id 或图片链接。"
            ),
        )

    def step_sink(step: dict[str, Any]) -> None:
        _insert_agent_step_message(
            db,
            session_id=session_id,
            turn_id=turn_id,
            job_id=job.id,
            step=step,
        )
        # 立刻提交，否则前端要等整个 agent 跑完才看得到过程。
        db.commit()

    tools = RecommendationAgentTools(
        db,
        target_facts_fn=target_facts_for_agent,
        step_sink=step_sink,
    )
    started = time.perf_counter()
    try:
        loop = run_tool_loop(
            chat=_agent_chat_caller(node_config),
            messages=messages,
            tools=build_agent_tools(db),
            execute_tool=tools.execute,
            max_iterations=AGENT_MAX_ITERATIONS,
            tool_result_limit=AGENT_TOOL_RESULT_LIMIT,
            early_stop_instruction=lambda: _agent_early_stop(tools, started),
            should_abort=lambda: agent_turn_aborted(db, session_id, turn_id),
        )
    except ToolLoopAborted as aborted:
        # 标记已经由取消接口写好了，这里只留一条轨迹说明跑到哪一步停的。
        _insert_recommendation_agent_trace(
            db,
            job=job,
            session_id=session_id,
            node_config=node_config,
            status="succeeded",
            input_json=agent_context,
            conversation=aborted.messages,
            loop=None,
            latency_ms=int((time.perf_counter() - started) * 1000),
            tools=tools,
            intent_snapshot=intent_snapshot,
            error_message="用户中止了本轮编排。",
        )
        db.commit()
        return {
            "handled": True,
            "job_type": job.job_type,
            "session_id": str(session_id),
            "turn_id": turn_id,
            "outcome": "aborted",
            "search_calls": len(tools.search_calls),
            "detail_targets": len(tools.detail_target_ids),
            "recommended_count": 0,
        }
    except LlmCallError as exc:
        _insert_recommendation_agent_trace(
            db,
            job=job,
            session_id=session_id,
            node_config=node_config,
            status="failed",
            input_json=agent_context,
            conversation=messages,
            loop=None,
            latency_ms=int((time.perf_counter() - started) * 1000),
            tools=tools,
            intent_snapshot=intent_snapshot,
            error_message=str(exc),
        )
        db.commit()
        raise

    if agent_turn_aborted(db, session_id, turn_id):
        # 停止发生在最后一次模型调用期间：素材不落库，否则页面会在「任务已停止」
        # 底下再冒出一段回答。
        _insert_recommendation_agent_trace(
            db,
            job=job,
            session_id=session_id,
            node_config=node_config,
            status="succeeded",
            input_json=agent_context,
            conversation=loop.messages,
            loop=loop,
            latency_ms=loop.usage.latency_ms,
            tools=tools,
            intent_snapshot=intent_snapshot,
            error_message="用户中止了本轮编排。",
        )
        db.commit()
        return {
            "handled": True,
            "job_type": job.job_type,
            "session_id": str(session_id),
            "turn_id": turn_id,
            "outcome": "aborted",
            "search_calls": len(tools.search_calls),
            "detail_targets": len(tools.detail_target_ids),
            "recommended_count": 0,
        }

    if tools.ask_user_payload is not None:
        _insert_agent_question_message(
            db,
            session_id=session_id,
            turn_id=turn_id,
            job_id=job.id,
            payload=tools.ask_user_payload,
        )
        outcome = "asked_user"
        brief = None
    else:
        brief = _build_answer_brief(loop.result.parsed_output_json, tools=tools, mode=mode)
        _insert_agent_brief_message(
            db,
            session_id=session_id,
            turn_id=turn_id,
            job_id=job.id,
            brief=brief,
        )
        outcome = "brief_ready"

    _insert_recommendation_agent_trace(
        db,
        job=job,
        session_id=session_id,
        node_config=node_config,
        status="succeeded",
        input_json=agent_context,
        conversation=loop.messages + [{"role": "assistant", "content": loop.result.raw_output_text}],
        loop=loop,
        latency_ms=loop.usage.latency_ms,
        tools=tools,
        intent_snapshot=intent_snapshot,
    )
    db.commit()
    return {
        "handled": True,
        "job_type": job.job_type,
        "session_id": str(session_id),
        "turn_id": turn_id,
        "outcome": outcome,
        "search_calls": len(tools.search_calls),
        "detail_targets": len(tools.detail_target_ids),
        "recommended_count": len((brief or {}).get("recommended") or []),
    }


def _agent_image_inputs(db: Session, attachment_ids: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Screenshots the consultant pasted, ready to hand to a multimodal model.

    Images never went through OCR — the platform's policy is that they go
    straight to the model — so unlike a document there is no text to preview.
    Attachments are looked up by id and not by entity link, because this page
    creates no entity to link them to.
    """
    if not attachment_ids:
        return [], []
    settings = get_settings()
    rows = db.execute(
        text(
            """
            select a.id, a.file_name, a.file_type, a.mime_type, a.file_size,
                   a.storage_path, a.metadata_json
            from attachment a
            where a.team_id = :team_id
              and a.workspace_id = :workspace_id
              and a.deleted_at is null
              and a.id in :attachment_ids
            """
        ).bindparams(bindparam("attachment_ids", expanding=True)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "attachment_ids": attachment_ids,
        },
    ).mappings().all()

    images: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for row in rows:
        attachment = _json_safe_dict(row)
        if not is_supported_multimodal_image(attachment):
            continue
        if len(images) >= settings.image_multimodal_max_count:
            break
        if int(attachment.get("file_size") or 0) > settings.image_multimodal_max_upload_bytes:
            continue
        try:
            prepared = prepare_image_for_multimodal(
                _attachment_file_bytes(attachment, max_bytes=settings.image_multimodal_max_upload_bytes),
                attachment_id=str(attachment["id"]),
                file_name=str(attachment.get("file_name") or "image"),
                mime_type=str(attachment.get("mime_type") or ""),
                max_side=settings.image_multimodal_max_side,
                jpeg_quality=settings.image_multimodal_jpeg_quality,
                target_bytes=settings.image_multimodal_target_bytes,
            )
        except ImageInputError:
            # 一张读不出来的图不该让整轮推荐失败。
            continue
        images.append(
            {
                "attachment_id": prepared.attachment_id,
                "file_name": prepared.file_name,
                "data_url": prepared.data_url,
                "mime_type": prepared.mime_type,
            }
        )
        summaries.append(prepared.trace_summary())
    return images, summaries


def _agent_early_stop(tools: RecommendationAgentTools, started: float) -> str | None:
    """Two reasons to cut the loop short, both of which must still produce output."""
    if tools.should_stop:
        return (
            "已向用户提问，本轮到此结束。请只输出一个 JSON 对象，"
            '形如 {"asked_user": true}，不要再调用任何工具。'
        )
    if time.perf_counter() - started >= AGENT_WALL_CLOCK_BUDGET_SECONDS:
        return (
            "本轮编排时间已用尽。请立即基于已获得的候选给出最终 JSON 结果，"
            "不要再调用任何工具。"
        )
    return None


def _agent_chat_caller(node_config: dict[str, Any]):
    """Bind node config for the loop; JSON format only on the tool-free turn."""

    def chat(*, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None):
        return call_openai_compatible_chat(
            base_url=node_config["base_url"],
            api_key_secret_ref=node_config["api_key_secret_ref"],
            api_key_encrypted=node_config.get("api_key_encrypted"),
            model_name=node_config["model_name"],
            messages=messages,
            temperature=node_config["temperature"],
            top_p=node_config["top_p"],
            max_tokens=node_config["max_tokens"],
            timeout_seconds=node_config["timeout_seconds"] or 300,
            response_format=None if tools else node_config["response_format"],
            tools=tools,
        )

    return chat


def _build_answer_brief(
    raw_output: dict[str, Any] | None,
    *,
    tools: RecommendationAgentTools,
    mode: str,
) -> dict[str, Any]:
    """Merge the agent's picks with code-held facts.

    The numbers in the final answer come from `facts` here, not from whatever
    the model retyped — a model that paraphrases 2800万 as 2800万元 is fine, one
    that invents 3200万 is not, and this is the join that removes the chance.
    """
    data = raw_output if isinstance(raw_output, dict) else {}
    recommended: list[dict[str, Any]] = []
    for item in (data.get("recommended") or [])[:10]:
        if not isinstance(item, dict):
            continue
        target_id = str(item.get("id") or "").strip()
        candidate = tools.candidates_by_id.get(target_id)
        if candidate is None:
            # 模型报了一个不在候选里的 id：丢掉而不是照抄，宁可少推荐一家。
            continue
        recommended.append(
            {
                "id": target_id,
                "name": candidate.get("seller_target_name"),
                "facts": candidate.get("facts") or {},
                "reason_points": [str(point) for point in (item.get("reason_points") or [])][:5],
                "watch_out": str(item.get("watch_out") or "").strip() or None,
                "already_in_progress": candidate.get("relation_status"),
                "other_buyer_in_deep_progress": bool(
                    candidate.get("seller_target_has_other_deep_progress")
                ),
            }
        )
    runner_ups = [
        {
            "name": str(item.get("name") or "").strip(),
            "note": str(item.get("note") or "").strip() or None,
        }
        for item in (data.get("runner_ups") or [])[:5]
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    last_eligible = next(
        (
            call.get("eligible_count")
            for call in reversed(tools.search_calls)
            if call.get("eligible_count") is not None
        ),
        None,
    )
    return {
        "mode": mode,
        "understanding": str(data.get("understanding") or "").strip() or None,
        "search_story": tools.process_steps(),
        "total_eligible": last_eligible,
        "recommended": recommended,
        "runner_ups": runner_ups,
        "follow_up_suggestions": [
            str(item).strip()
            for item in (data.get("follow_up_suggestions") or [])[:4]
            if str(item or "").strip()
        ],
    }


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
              latest_condition_snapshot_json, condition_overrides_json,
              selected_count, report_count,
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

def _insert_agent_message(
    db: Session,
    *,
    session_id: UUID,
    turn_id: str,
    job_id: UUID,
    message_type: str,
    content: dict[str, Any],
) -> None:
    """One shape for every agent-produced message; turn_id is what groups them."""
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
            "content": _json_dumps({"message_type": message_type, "turn_id": turn_id, **content}),
            "metadata_json": {
                "message_type": message_type,
                "turn_id": turn_id,
                "job_id": str(job_id),
            },
            "created_by": SYSTEM_USER_ID,
        },
    )


def _insert_agent_step_message(
    db: Session,
    *,
    session_id: UUID,
    turn_id: str,
    job_id: UUID,
    step: dict[str, Any],
) -> None:
    _insert_agent_message(
        db,
        session_id=session_id,
        turn_id=turn_id,
        job_id=job_id,
        message_type="agent_step",
        content={"step": _json_safe_dict(step)},
    )


def _insert_agent_question_message(
    db: Session,
    *,
    session_id: UUID,
    turn_id: str,
    job_id: UUID,
    payload: dict[str, Any],
) -> None:
    _insert_agent_message(
        db,
        session_id=session_id,
        turn_id=turn_id,
        job_id=job_id,
        message_type="agent_question",
        content={"question": _json_safe_dict(payload)},
    )


def _insert_agent_understanding_message(
    db: Session,
    *,
    session_id: UUID,
    turn_id: str,
    job_id: UUID,
    snapshot: dict[str, Any],
) -> None:
    """这一轮读懂了什么，原样落库。

    本阶段前端还不渲染这条消息（无 UI 变更），但它必须先存在：解析结果是这一轮
    唯一可审计的需求基线，而「解析器返回的结构对不上代码」这种失配只有落进
    对话记录才有人看得见 —— 上一轮正是因为没有任何地方标注它，全链路零报错地
    错了一整轮。
    """
    _insert_agent_message(
        db,
        session_id=session_id,
        turn_id=turn_id,
        job_id=job_id,
        message_type="agent_understanding",
        content={
            "understanding": _json_safe_dict(snapshot),
            "summary": describe_intent_snapshot(snapshot),
        },
    )


def _intent_trace_summary(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """trace 里只留摘要：完整快照在 agent_understanding 消息里，不存两份。"""
    if not isinstance(snapshot, dict):
        return {"parser_status": "not_run"}
    return {
        "parser_status": snapshot.get("parser_status"),
        "prompt_version": snapshot.get("prompt_version") or None,
        "condition_groups": len(snapshot.get("condition_groups") or []),
        "qualitative_requirements": len(snapshot.get("qualitative_requirements") or []),
        "unstructured_notes": len(snapshot.get("unstructured_notes") or []),
        "parser_notes": list(snapshot.get("parser_notes") or []),
    }


def _aborted_agent_turn_result(
    job: JobClaim,
    *,
    session_id: UUID,
    turn_id: str,
) -> dict[str, object]:
    """本轮在动手之前就被停掉了。中止标记由取消接口写，这里只管退出。"""
    return {
        "handled": True,
        "job_type": job.job_type,
        "session_id": str(session_id),
        "turn_id": turn_id,
        "outcome": "aborted",
        "search_calls": 0,
        "detail_targets": 0,
        "recommended_count": 0,
    }


def _insert_agent_brief_message(
    db: Session,
    *,
    session_id: UUID,
    turn_id: str,
    job_id: UUID,
    brief: dict[str, Any],
) -> None:
    _insert_agent_message(
        db,
        session_id=session_id,
        turn_id=turn_id,
        job_id=job_id,
        message_type="agent_brief",
        content={"brief": _json_safe_dict(brief)},
    )


def _insert_recommendation_agent_trace(
    db: Session,
    *,
    job: JobClaim,
    session_id: UUID,
    node_config: dict[str, Any],
    status: str,
    input_json: dict[str, Any],
    conversation: list[dict[str, Any]],
    loop: Any | None,
    latency_ms: int,
    tools: RecommendationAgentTools,
    intent_snapshot: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    """One row per agent turn, not per LLM call — same rule as research."""
    usage = loop.usage if loop else None
    db.execute(
        text(
            """
            insert into ai_trace (
              team_id, workspace_id, trace_type, node_name,
              job_id, correlation_id, entity_type, entity_id,
              provider_config_id, node_config_id, prompt_template_id,
              provider_name, model_name, prompt_version, status,
              input_json, prompt_messages_json, raw_output_text,
              parsed_output_json, schema_validation_json,
              error_message, latency_ms, prompt_tokens,
              completion_tokens, total_tokens, created_by, finished_at,
              metadata_json
            ) values (
              :team_id, :workspace_id, 'llm', :node_name,
              :job_id, :correlation_id, 'recommendation_session', :entity_id,
              :provider_config_id, :node_config_id, :prompt_template_id,
              :provider_name, :model_name, :prompt_version, :status,
              :input_json, :prompt_messages_json, :raw_output_text,
              :parsed_output_json, :schema_validation_json,
              :error_message, :latency_ms, :prompt_tokens,
              :completion_tokens, :total_tokens, :created_by, now(),
              :metadata_json
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
            "node_name": node_config["node_name"],
            "job_id": job.id,
            "correlation_id": job.correlation_id,
            "entity_id": session_id,
            "provider_config_id": node_config["provider_config_id"],
            "node_config_id": node_config["node_config_id"],
            "prompt_template_id": node_config.get("prompt_template_id"),
            "provider_name": node_config["provider_name"],
            "model_name": node_config["model_name"],
            "prompt_version": node_config.get("prompt_version"),
            "status": status,
            "input_json": _json_safe_dict(input_json),
            "prompt_messages_json": {"messages": _json_safe_dict({"value": conversation})["value"]},
            "raw_output_text": (loop.result.raw_output_text if loop else None),
            "parsed_output_json": (
                _json_safe_dict(loop.result.parsed_output_json)
                if loop and isinstance(loop.result.parsed_output_json, dict)
                else None
            ),
            "schema_validation_json": {
                "valid": bool(loop and isinstance(loop.result.parsed_output_json, dict)),
                "hit_iteration_limit": bool(loop and loop.hit_iteration_limit),
            },
            "error_message": error_message,
            "latency_ms": latency_ms,
            "prompt_tokens": usage.prompt_tokens if usage else None,
            "completion_tokens": usage.completion_tokens if usage else None,
            "total_tokens": usage.total_tokens if usage else None,
            "created_by": SYSTEM_USER_ID,
            "metadata_json": {
                "llm_calls": usage.llm_calls if usage else 0,
                "tool_calls_by_name": usage.tool_calls_by_name if usage else {},
                "intent_parser": _intent_trace_summary(intent_snapshot),
                **tools.as_trace_payload(),
            },
        },
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
