from __future__ import annotations

import json
import time
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
from backend.app.services.recommendation_agent_policy import compile_condition_groups
from backend.app.services.recommendation_answer import build_answer_brief_v2
from backend.app.services.recommendation_conditions import (
    describe_intent_snapshot,
    parse_recommendation_intent,
)
from backend.app.services.recommendation_deep_eval import (
    describe_deep_eval_result,
    run_recommendation_deep_eval,
)
from backend.app.services.recommendation_flow import (
    agent_turn_aborted,
    target_facts_for_agent,
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

# 方向专属 prompt 节点；未在设置页建号时回落到共用节点，行为与改造前一致。
# 映射与回落目标都来自代码目录 registry/nodes.py，此处不再各自声明一份。
DEEP_EVAL_NODE_BY_MODE = deep_eval_node_by_mode()

DEEP_EVAL_FALLBACK_NODE = deep_eval_understudy_node_name()


# 编排 Agent。刻意没有共用兜底节点：两个方向的工具集不同，一份提示词兜不住。
RECOMMENDATION_AGENT_NODE_BY_MODE = recommendation_agent_node_by_mode()

# 深评工具要把最多 40 家的判定与筛选来源完整回灌给主 Agent，不能沿用网页抓取
# 类工具的 8000 字截断。这里仍是防御上限；候选数量由策略层锁在 40。
AGENT_TOOL_RESULT_LIMIT = 240000
AGENT_MAX_ITERATIONS = 12

# 用户对整次推荐的耐心是 2-5 分钟，编排阶段留 4 分钟，剩下的给流式写作。
# 这同时是对 worker stale 窗口（1800s）的第二道保险：迭代上限管不住单次调用
# 很慢的情况，墙钟能。
AGENT_WALL_CLOCK_BUDGET_SECONDS = 240


def _build_recommendation_agent_context(
    *,
    user_message: str,
    intent_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Build the existing `recommendation_context_json` variable for the agent.

    The parser's complete snapshot is the only structured baseline. 4B will
    enforce condition-group calls at the tool boundary; 4A makes the data and
    failure semantics explicit before the agent sees them. In particular, a
    degraded parser result is sanitised again here so an accidental condition
    in a fallback payload can never masquerade as an approved baseline.

    History deliberately stays out of this JSON and continues through the
    separate `history_context` prompt variable, preserving its visible tags.
    """
    status = str(intent_snapshot.get("parser_status") or "fallback")
    if status == "ok":
        groups = intent_snapshot.get("condition_groups")
        qualitative = intent_snapshot.get("qualitative_requirements")
        exclusions = intent_snapshot.get("exclusions")
        notes = intent_snapshot.get("unstructured_notes")
        safe_snapshot = {
            "condition_groups": list(groups) if isinstance(groups, list) else [],
            "qualitative_requirements": list(qualitative) if isinstance(qualitative, list) else [],
            "exclusions": dict(exclusions) if isinstance(exclusions, dict) else {
                "industries": [],
                "risk_flags": [],
            },
            "unstructured_notes": list(notes) if isinstance(notes, list) else [],
            "parser_status": "ok",
        }
    else:
        # 解析失败时不信任任何结构化输出。当前原话只作为定性兜底，Agent 只可
        # 无条件初筛或提问；不能借「解析失败」重新发明一套筛选条件。
        raw_message = str(user_message or "").strip()
        safe_snapshot = {
            "condition_groups": [],
            "qualitative_requirements": [raw_message] if raw_message else [],
            "exclusions": {"industries": [], "risk_flags": []},
            "unstructured_notes": [],
            "parser_status": status,
        }

    return {
        "user_message": user_message,
        "intent_snapshot": safe_snapshot,
        "search_group_catalog": [
            group.as_context_dict() for group in compile_condition_groups(safe_snapshot)
        ],
        "intent_snapshot_policy": {
            "condition_groups_are_the_only_structured_baseline": True,
            "allow_agent_invent_structured_conditions": False,
            "on_parser_failure": "只允许无条件初筛或向用户提问",
        },
        "budgets": {
            "max_search_calls": MAX_SEARCH_CALLS,
            "max_detail_targets": MAX_DETAIL_TARGETS_TOTAL,
            "max_tool_iterations": AGENT_MAX_ITERATIONS,
        },
    }


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
    parser_started = time.perf_counter()
    intent_snapshot = parse_recommendation_intent(
        db,
        mode=mode,
        user_message=user_message,
        history_context=history_context,
    )
    parser_duration_ms = max(0, int((time.perf_counter() - parser_started) * 1000))
    _insert_agent_understanding_message(
        db,
        session_id=session_id,
        turn_id=turn_id,
        job_id=job.id,
        snapshot=intent_snapshot,
        duration_ms=parser_duration_ms,
    )
    # 立刻提交，与 agent_step 同样的理由：前端轮询要在 agent 还在跑的时候
    # 就能看到「已读懂需求」。
    db.commit()
    if agent_turn_aborted(db, session_id, turn_id):
        return _aborted_agent_turn_result(job, session_id=session_id, turn_id=turn_id)

    agent_context = _build_recommendation_agent_context(
        user_message=user_message,
        intent_snapshot=intent_snapshot,
    )
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
        intent_snapshot=agent_context["intent_snapshot"],
        deep_eval_fn=lambda *, candidates_by_id, candidate_pool: run_recommendation_deep_eval(
            db,
            mode=mode,
            intent_snapshot={**intent_snapshot, **agent_context["intent_snapshot"]},
            candidates_by_id=candidates_by_id,
        ),
    )
    started = time.perf_counter()
    try:
        loop = run_tool_loop(
            chat=_agent_chat_caller(node_config),
            messages=messages,
            tools=build_agent_tools(db, tools.compiled_groups),
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
            deep_eval=tools.deep_eval_result,
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
            deep_eval=tools.deep_eval_result,
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
            deep_eval=tools.deep_eval_result,
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

    # 深评现在是主 Agent 可见的受控工具。正常路径里 Agent 自己调用；如果它有真实
    # 候选却忘了调用，代码补跑一次，再把结果交回同一个节点做一次无工具收尾。
    # count_only、按 id 取详情都不构成深评候选；候选池只来自真实初筛批次。
    deep_eval: dict[str, Any] | None = tools.deep_eval_result
    auto_deep_eval = False
    if (
        tools.ask_user_payload is None
        and tools.candidate_pool().candidate_ids
        and not tools.deep_eval_called
    ):
        if agent_turn_aborted(db, session_id, turn_id):
            return _finish_aborted_agent_turn(
                db,
                job=job,
                session_id=session_id,
                turn_id=turn_id,
                node_config=node_config,
                agent_context=agent_context,
                conversation=loop.messages,
                loop=loop,
                tools=tools,
                intent_snapshot=intent_snapshot,
                error_message="用户在自动深评前中止了本轮编排。",
            )
        deep_eval = tools.run_deep_eval_if_needed()
        auto_deep_eval = True
        if agent_turn_aborted(db, session_id, turn_id):
            return _finish_aborted_agent_turn(
                db,
                job=job,
                session_id=session_id,
                turn_id=turn_id,
                node_config=node_config,
                agent_context=agent_context,
                conversation=loop.messages,
                loop=loop,
                tools=tools,
                intent_snapshot=intent_snapshot,
                error_message="用户在自动深评期间中止了本轮编排。",
            )
        loop = _agent_finalize_after_auto_deep_eval(
            loop,
            node_config=node_config,
            deep_eval=deep_eval,
        )
        if agent_turn_aborted(db, session_id, turn_id):
            return _finish_aborted_agent_turn(
                db,
                job=job,
                session_id=session_id,
                turn_id=turn_id,
                node_config=node_config,
                agent_context=agent_context,
                conversation=loop.messages,
                loop=loop,
                tools=tools,
                intent_snapshot=intent_snapshot,
                error_message="用户在深评后的无工具收尾期间中止了本轮编排。",
            )

    if deep_eval is not None:
        deep_eval = {**deep_eval, "auto_invoked": auto_deep_eval}
        tools.deep_eval_result = deep_eval
        _insert_agent_deep_eval_message(
            db,
            session_id=session_id,
            turn_id=turn_id,
            job_id=job.id,
            result=deep_eval,
            duration_ms=int(deep_eval.get("latency_ms") or 0),
        )
        db.commit()

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
            duration_ms=max(0, int(loop.usage.latency_ms or 0)),
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
        deep_eval=deep_eval,
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
        "deep_eval_status": (deep_eval or {}).get("deep_eval_status", "not_run"),
    }


def _agent_finalize_after_auto_deep_eval(
    loop: Any,
    *,
    node_config: dict[str, Any],
    deep_eval: dict[str, Any],
) -> Any:
    """Give an agent that forgot deep eval one tool-free chance to finish.

    The first draft is preserved in the conversation for audit.  The deep-eval
    result is then appended as authoritative tool output; the same configured
    agent node performs the final JSON turn without any tools.
    """
    conversation = list(loop.messages)
    previous = loop.result.raw_output_text
    if not previous and isinstance(loop.result.parsed_output_json, dict):
        previous = json.dumps(loop.result.parsed_output_json, ensure_ascii=False, default=str)
    conversation.append({"role": "assistant", "content": previous or "{}"})
    conversation.append(
        {
            "role": "user",
            "content": (
                "你在有真实候选时直接收尾，忘了调用必经的深评工具。代码已经自动补跑一次。"
                "下面是本轮唯一可用的深评结果。请读完后重新输出最终 JSON；不得再调用工具。"
                "deep_eval_status=ok 时，最终推荐 id 只能来自 ranked，不能来自 dropped 或候选池外；"
                "unavailable/schema_mismatch 时如实标明降级，可按 SQL 初筛顺序收尾。\n\n"
                + json.dumps(deep_eval, ensure_ascii=False, default=str)
            ),
        }
    )
    try:
        result = _agent_chat_caller(node_config)(messages=conversation, tools=None)
    except LlmCallError as exc:
        notes = deep_eval.setdefault("notes", [])
        notes.append(f"深评后的无工具收尾失败，沿用 Agent 首次原始输出：{exc}")
        return loop
    loop.usage.record_llm(result)
    loop.result = result
    loop.messages = conversation
    loop.json_finalization_attempted = True
    return loop


def _finish_aborted_agent_turn(
    db: Session,
    *,
    job: JobClaim,
    session_id: UUID,
    turn_id: str,
    node_config: dict[str, Any],
    agent_context: dict[str, Any],
    conversation: list[dict[str, Any]],
    loop: Any,
    tools: RecommendationAgentTools,
    intent_snapshot: dict[str, Any],
    error_message: str,
) -> dict[str, object]:
    """Abort wins before/after deep eval: trace the work, never write a brief."""
    _insert_recommendation_agent_trace(
        db,
        job=job,
        session_id=session_id,
        node_config=node_config,
        status="succeeded",
        input_json=agent_context,
        conversation=conversation,
        loop=loop,
        latency_ms=loop.usage.latency_ms,
        tools=tools,
        intent_snapshot=intent_snapshot,
        deep_eval=tools.deep_eval_result,
        error_message=error_message,
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
    """Build the one v2 brief shared by Writer, fallback and the front end."""
    brief, final_output, notes = build_answer_brief_v2(
        raw_output,
        mode=mode,
        intent_snapshot=tools.intent_snapshot,
        candidates_by_id=tools.candidates_by_id,
        candidate_pool=tools.candidate_pool(),
        deep_eval=tools.deep_eval_result,
        screening_runs=tools.process_steps(),
    )
    # The raw model JSON remains in ai_trace.parsed_output_json. These fields
    # add the executable, code-normalised contract and every rejection/truncate
    # decision to trace metadata instead of silently hiding model mistakes.
    tools.final_output_contract = final_output
    tools.final_output_normalization_notes = notes
    return brief


def _get_deep_eval_node_config(db: Session, mode: str) -> dict[str, Any]:
    node_name = DEEP_EVAL_NODE_BY_MODE.get(mode)
    if node_name:
        try:
            return _get_default_node_config(db, node_name)
        except ValueError:
            # 方向节点未配置：回落共用节点，两个方向共享同一套提示词。
            pass
    return _get_default_node_config(db, DEEP_EVAL_FALLBACK_NODE)


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
    duration_ms: int = 0,
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
            "content": _json_dumps(
                {
                    "message_type": message_type,
                    "turn_id": turn_id,
                    "duration_ms": max(0, int(duration_ms or 0)),
                    **content,
                }
            ),
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
        duration_ms=int(step.get("duration_ms") or 0),
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
    duration_ms: int = 0,
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
        duration_ms=duration_ms,
    )


def _insert_agent_deep_eval_message(
    db: Session,
    *,
    session_id: UUID,
    turn_id: str,
    job_id: UUID,
    result: dict[str, Any],
    duration_ms: int = 0,
) -> None:
    """这一轮深评判了什么、怎么排的，连同筛选来源原样落库。"""
    _insert_agent_message(
        db,
        session_id=session_id,
        turn_id=turn_id,
        job_id=job_id,
        message_type="agent_deep_eval",
        content={
            "deep_eval": _json_safe_dict(result),
            "summary": describe_deep_eval_result(result),
        },
        duration_ms=duration_ms,
    )


def _deep_eval_trace_summary(result: dict[str, Any] | None) -> dict[str, Any]:
    """trace 里只留摘要：完整结果在 agent_deep_eval 消息里，不存两份。"""
    if not isinstance(result, dict):
        return {"deep_eval_status": "not_run"}
    pool = result.get("candidate_pool") if isinstance(result.get("candidate_pool"), dict) else {}
    return {
        "deep_eval_status": result.get("deep_eval_status"),
        "auto_invoked": bool(result.get("auto_invoked")),
        "prompt_version": result.get("prompt_version") or None,
        "model_name": result.get("model_name") or None,
        "candidate_count": result.get("candidate_count"),
        "ranked": len(result.get("ranked") or []),
        "dropped": len(result.get("dropped") or []),
        "uncovered": len(result.get("uncovered") or []),
        "fallback_reason": result.get("fallback_reason"),
        "raw_occurrences": pool.get("raw_occurrences"),
        "unique_before_cap": pool.get("unique_before_cap"),
        "unique_after_cap": pool.get("unique_after_cap"),
        "capped": pool.get("capped"),
        "notes": list(result.get("notes") or []),
    }


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
    duration_ms: int = 0,
) -> None:
    _insert_agent_message(
        db,
        session_id=session_id,
        turn_id=turn_id,
        job_id=job_id,
        message_type="agent_brief",
        content={"brief": _json_safe_dict(brief)},
        duration_ms=duration_ms,
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
    deep_eval: dict[str, Any] | None = None,
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
                "deep_eval": _deep_eval_trace_summary(deep_eval),
                **tools.as_trace_payload(),
            },
        },
    )


