"""One `ai_trace` row per recommendation sub-node call.

推荐一轮里其实调了四次模型：需求解析、深评、编排 Agent、正文撰写。但只有编排
Agent 写 trace —— 另外三个从头到尾没有任何落库记录。后果是设置页那一列
「最近生产调用」对这三个节点**永远**显示「无记录」：管理员配好了模型、发布了
提示词，却无法确认它到底有没有被调用过，看起来跟没接线一模一样。同时也意味着
解析降级、深评不可用这两类事故，事后除了看 agent 那行的 metadata 摘要之外，
拿不到当时的提示词、原始输出和真实耗时。

写在 services 层而不是 `jobs/handlers/` 里，是因为这三个调用点都在 services：
反向 import 会闭合 `services → jobs.handlers → jobs/__init__ → handlers` 这个环。

trace 写入**永远不能**让业务失败：它是观测，不是产出。所有插入都包在 savepoint
里并吞掉异常 —— 一次写 trace 失败换掉一整轮已经付过钱的推荐，是明显错误的交换。
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID, SYSTEM_USER_ID
from backend.app.db import savepoint
from backend.app.services.json_values import json_safe_value


@dataclass(frozen=True)
class RecommendationTraceContext:
    """把「这次调用属于哪一轮」带进 services，不用让它们认识 JobClaim。"""

    session_id: UUID
    job_id: UUID | None = None
    correlation_id: UUID | None = None
    turn_id: str | None = None


def insert_recommendation_node_trace(
    db: Session | None,
    *,
    context: RecommendationTraceContext | None,
    node_name: str,
    node_config: dict[str, Any] | None,
    status: str,
    input_json: dict[str, Any],
    prompt_messages: list[dict[str, Any]],
    latency_ms: int,
    raw_output_text: str | None = None,
    parsed_output_json: dict[str, Any] | None = None,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
) -> None:
    """写一行 trace；没有 db 或没有上下文就安静跳过（单测与非任务调用方）。"""
    if db is None or context is None:
        return
    if not node_name:
        # 连节点名都解析不出来，说明这次压根没有节点被调用（比如 mode 不认识）。
        # 硬塞一行空 node_name 的记录，只会在设置页上凭空多出一个不存在的节点。
        return
    config = node_config or {}
    try:
        with savepoint(db):
            db.execute(
                text(
                    """
                    insert into ai_trace (
                      team_id, workspace_id, trace_type, node_name,
                      job_id, correlation_id, entity_type, entity_id,
                      provider_config_id, node_config_id, prompt_template_id,
                      provider_name, model_name, prompt_version, status,
                      input_json, prompt_messages_json, raw_output_text,
                      parsed_output_json, error_message, latency_ms,
                      prompt_tokens, completion_tokens, total_tokens,
                      created_by, finished_at, metadata_json
                    ) values (
                      :team_id, :workspace_id, 'llm', :node_name,
                      :job_id, :correlation_id, 'recommendation_session', :entity_id,
                      :provider_config_id, :node_config_id, :prompt_template_id,
                      :provider_name, :model_name, :prompt_version, :status,
                      :input_json, :prompt_messages_json, :raw_output_text,
                      :parsed_output_json, :error_message, :latency_ms,
                      :prompt_tokens, :completion_tokens, :total_tokens,
                      :created_by, now(), :metadata_json
                    )
                    """
                ).bindparams(
                    bindparam("input_json", type_=JSONB),
                    bindparam("prompt_messages_json", type_=JSONB),
                    bindparam("parsed_output_json", type_=JSONB),
                    bindparam("metadata_json", type_=JSONB),
                ),
                {
                    "team_id": DEFAULT_TEAM_ID,
                    "workspace_id": DEFAULT_WORKSPACE_ID,
                    "node_name": node_name,
                    "job_id": context.job_id,
                    "correlation_id": context.correlation_id,
                    "entity_id": context.session_id,
                    "provider_config_id": config.get("provider_config_id"),
                    "node_config_id": config.get("node_config_id"),
                    "prompt_template_id": config.get("prompt_template_id"),
                    "provider_name": config.get("provider_name"),
                    "model_name": config.get("model_name"),
                    "prompt_version": config.get("prompt_version"),
                    "status": status,
                    "input_json": json_safe_value(input_json),
                    "prompt_messages_json": {
                        "messages": json_safe_value(prompt_messages)
                    },
                    "raw_output_text": raw_output_text,
                    "parsed_output_json": (
                        json_safe_value(parsed_output_json)
                        if isinstance(parsed_output_json, dict)
                        else None
                    ),
                    "error_message": error_message,
                    "latency_ms": latency_ms,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "created_by": SYSTEM_USER_ID,
                    "metadata_json": json_safe_value(
                        {"turn_id": context.turn_id, **(metadata or {})}
                    ),
                },
            )
    except Exception:  # noqa: BLE001 - 观测失败绝不能带走这一轮的产出
        # 堆栈进 worker 日志：静默跳过 trace 与「trace 从来没写过」在设置页上
        # 长得一模一样，而这两件事的排查方向完全相反。
        traceback.print_exc()
