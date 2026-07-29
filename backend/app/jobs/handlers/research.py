"""Seller-target research as an agent with two tools.

The model decides what to search, which results are worth reading in full, and
when it has enough. Code supplies the tools, a budget, and the writeback rules —
it does not pre-filter pages or judge recency, because those are judgement calls
the model makes better than a substring match can.

What research produces are proposals, never direct writes to the canonical
target row: profile sections and a small whitelist of structured facts, each
carrying the URLs it came from.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.ai.llm_client import LlmCallError, call_openai_compatible_chat
from backend.app.ai.tool_loop import ToolCall, ToolLoopResult, run_tool_loop
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID, SYSTEM_USER_ID
from backend.app.jobs.handlers.common import (
    _get_default_node_config,
    _json_safe_value,
    _render_prompt_messages,
    _safe_prompt_messages_for_trace,
)
from backend.app.jobs.queue import JobClaim
from backend.app.services.profile_sections import (
    PROFILE_SECTION_CODES,
    PROFILE_SECTION_LABELS,
    load_profile_sections,
    normalize_profile_section_items,
)
from backend.app.services.research_apply import (
    CORE_FINANCIAL_FIELDS,
    RESEARCH_AGENT_STRUCTURED_FIELDS,
    RESEARCH_STRUCTURED_FIELDS,
    ResearchApplyError,
    apply_research_proposal,
    normalize_structured_fact,
)
from backend.app.services.search_providers import SearchError
from backend.app.services.search_providers.fetch import fetch_page_text
from backend.app.services.search_service import (
    get_default_search_provider,
    resolve_search_api_key,
    run_search,
)

RESEARCH_NODE_NAME = "seller_target_researcher"
# 规范化节点：把 agent 的报告翻译成本系统的契约（单位、字典、白名单、枚举）。
# 它必须留在有数据库的这一侧 —— 行业字典和可写字段是活的库状态，
# 写进调研提示词就会随着字典更新而过期。
RESEARCH_MAPPER_NODE_NAME = "seller_target_research_mapper"

# 工具调用预算。这是成本刹车，不是质量控制 —— 限额内 agent 完全自主。
MAX_TOOL_ITERATIONS = 12
SEARCH_RESULTS_PER_CALL = 6
MAX_SEARCH_RESULTS_PER_CALL = 10
FETCH_TEXT_LIMIT = 8000
SNIPPET_LIMIT = 600
MAX_CONSECUTIVE_SUBJECT_MISSES = 4

RELATION_KINDS = {"consistent", "supplement", "temporal_update", "same_period_conflict"}
DEFAULT_RELATION = "supplement"


@dataclass
class ResearchClaimApplySummary:
    auto_accepted_count: int = 0
    pending_review_count: int = 0
    ignored_count: int = 0
    errors: list[str] = field(default_factory=list)


class ResearchContentInspectionError(LlmCallError):
    """The model rejected retrieved page text even after safe degradation."""

PROFILE_SECTION_CATALOG: list[dict[str, str]] = [
    {"code": code, "label": label} for code, label in PROFILE_SECTION_LABELS.items()
]

RESEARCH_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "联网搜索，返回标题、链接与摘要，不含正文。"
                "每类信息搜一次即可，不要对同一主题反复检索。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索词"},
                    "max_results": {
                        "type": "integer",
                        "description": f"返回条数，默认 {SEARCH_RESULTS_PER_CALL}，上限 {MAX_SEARCH_RESULTS_PER_CALL}",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_page",
            "description": "抓取指定网页的正文。搜索摘要不足以判断时使用。",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "要抓取的页面地址"}},
                "required": ["url"],
            },
        },
    },
]


class ResearchTools:
    """The two tools the agent drives, plus the page text already paid for.

    Search providers return page text alongside the snippet. Handing that to
    the model up front would take the "is this worth reading" decision away from
    it, but discarding it means paying twice for the same page, so it is kept
    here and served to fetch_page when the model asks.
    """

    def __init__(
        self,
        provider: dict[str, Any],
        api_key: str,
        *,
        subject_names: list[str] | None = None,
    ) -> None:
        self._provider = provider
        self._api_key = api_key
        self._page_text_by_url: dict[str, str] = {}
        self._subject_anchors = _subject_anchors(subject_names or [])
        self._low_relevance_urls: set[str] = set()
        self.searched_queries: list[str] = []
        self.fetched_urls: list[str] = []
        self.skipped_urls: list[dict[str, str]] = []
        self.consecutive_subject_misses = 0
        self.early_stop_reason: str | None = None
        self.content_inspection_retry_count = 0

    def __call__(self, call: ToolCall) -> Any:
        if call.name == "web_search":
            return self.web_search(str(call.arguments.get("query") or ""), call.arguments.get("max_results"))
        if call.name == "fetch_page":
            return self.fetch_page(str(call.arguments.get("url") or ""))
        return {"error": f"未知工具：{call.name}"}

    def web_search(self, query: str, max_results: Any = None) -> Any:
        query = query.strip()
        if not query:
            return {"error": "query 不能为空"}
        if self.early_stop_reason:
            return {"error": self.early_stop_reason, "stop_research": True}
        try:
            count = int(max_results)
        except (TypeError, ValueError):
            count = SEARCH_RESULTS_PER_CALL
        count = max(1, min(count, MAX_SEARCH_RESULTS_PER_CALL))
        self.searched_queries.append(query)
        try:
            hits = run_search(self._provider, query, max_results=count, api_key=self._api_key)
        except SearchError as exc:
            return {"error": f"搜索失败：{exc}"}
        results = []
        matched_count = 0
        for hit in hits:
            subject_match = self._matches_subject(hit.title, hit.snippet)
            if subject_match:
                matched_count += 1
            elif self._subject_anchors:
                self._low_relevance_urls.add(hit.url)
            if hit.raw_content and subject_match:
                self._page_text_by_url[hit.url] = hit.raw_content
            results.append(
                {
                    "url": hit.url,
                    "title": hit.title,
                    "snippet": (hit.snippet or "")[:SNIPPET_LIMIT],
                    "published_at": hit.published_at,
                    "full_text_available": bool(hit.raw_content and subject_match),
                    "subject_match": subject_match,
                }
            )
        if self._subject_anchors and matched_count == 0:
            self.consecutive_subject_misses += 1
        elif matched_count:
            self.consecutive_subject_misses = 0
        if self.consecutive_subject_misses >= MAX_CONSECUTIVE_SUBJECT_MISSES:
            self.early_stop_reason = (
                f"已连续 {self.consecutive_subject_misses} 次检索未找到与标的主体名称准确匹配的结果，"
                "为避免混入同名或近似主体的信息，本次调研停止继续检索。"
            )
        return {
            "query": query,
            "results": results,
            "matched_result_count": matched_count,
            "stop_research": bool(self.early_stop_reason),
        }

    def fetch_page(self, url: str) -> Any:
        url = url.strip()
        if not url:
            return {"error": "url 不能为空"}
        if url in self._low_relevance_urls:
            self._record_skipped_url(url, "subject_mismatch")
            return {"url": url, "error": "该搜索结果未匹配标的主体名称，已跳过正文抓取以避免主体混淆。"}
        self.fetched_urls.append(url)
        cached = self._page_text_by_url.get(url)
        if cached:
            return {"url": url, "text": cached[:FETCH_TEXT_LIMIT], "source": "search_provider"}
        text_value = fetch_page_text(url)
        if not text_value:
            return {"url": url, "error": "无法抓取该页面正文，可只依据搜索摘要判断或换一个来源。"}
        self._page_text_by_url[url] = text_value
        return {"url": url, "text": text_value[:FETCH_TEXT_LIMIT], "source": "direct_fetch"}

    def _matches_subject(self, title: str | None, snippet: str | None) -> bool:
        if not self._subject_anchors:
            return True
        haystack = _normalize_subject_text(f"{title or ''} {snippet or ''}")
        return any(anchor in haystack for anchor in self._subject_anchors)

    def _record_skipped_url(self, url: str, reason: str) -> None:
        item = {"url": url, "reason": reason}
        if item not in self.skipped_urls:
            self.skipped_urls.append(item)

    def record_content_inspection_skip(self, urls: list[str], reason: str) -> None:
        self.content_inspection_retry_count += 1
        for url in urls:
            self._record_skipped_url(url, reason)

    def stop_instruction(self) -> str | None:
        if not self.early_stop_reason:
            return None
        return (
            f"{self.early_stop_reason} 请立即基于已经确认的信息输出最终 JSON；"
            "没有准确主体证据的模块放入 coverage.no_public_information，不要再调用工具。"
        )


def _handle_seller_target_research(db: Session, job: JobClaim) -> dict[str, object]:
    target_id = job.entity_id
    if job.entity_type != "seller_target" or target_id is None:
        raise ValueError("seller_target_research requires a seller_target entity_id.")

    target = _get_research_target(db, target_id)
    provider = get_default_search_provider(db)
    if provider is None:
        _mark_research_outcome(db, target_id, "failed")
        db.commit()
        raise ValueError("No active search provider is configured.")

    node_config = _get_default_node_config(db, RESEARCH_NODE_NAME)
    current_profiles = load_profile_sections(
        db,
        entity_type="seller_target",
        entity_ids=[target_id],
    ).get(str(target_id), {})
    research_context = {
        "target": _research_target_prompt_view(target),
        "current_profile_sections": _current_profiles_for_prompt(current_profiles),
        "profile_section_catalog": PROFILE_SECTION_CATALOG,
        "allowed_structured_fields": sorted(RESEARCH_STRUCTURED_FIELDS),
        "allowed_relations": sorted(RELATION_KINDS),
        "max_tool_calls": MAX_TOOL_ITERATIONS,
    }
    messages = _render_prompt_messages(node_config, {"research_context_json": research_context})

    try:
        api_key = resolve_search_api_key(provider)
    except SearchError as exc:
        _mark_research_outcome(db, target_id, "failed")
        db.commit()
        raise ValueError(str(exc)) from exc

    tools = ResearchTools(
        provider,
        api_key,
        subject_names=[
            str(target.get("target_subject_name") or ""),
            str(target.get("target_name") or ""),
        ],
    )
    started = time.perf_counter()
    try:
        loop = run_tool_loop(
            chat=_chat_caller(node_config, research_tools=tools),
            messages=messages,
            tools=RESEARCH_TOOLS,
            execute_tool=tools,
            max_iterations=MAX_TOOL_ITERATIONS,
            tool_result_limit=FETCH_TEXT_LIMIT,
            early_stop_instruction=tools.stop_instruction,
        )
    except LlmCallError as exc:
        _insert_research_trace(
            db,
            job=job,
            target_id=target_id,
            node_config=node_config,
            status="failed",
            input_json=research_context,
            conversation=messages,
            loop=None,
            schema_validation_json={"valid": False, "error": str(exc)},
            latency_ms=int((time.perf_counter() - started) * 1000),
            tools=tools,
            error_code=(
                "research_content_inspection_failed"
                if isinstance(exc, ResearchContentInspectionError)
                else "llm_call_failed"
            ),
            error_message=str(exc),
        )
        _mark_research_outcome(db, target_id, "failed")
        db.commit()
        raise

    claims, notes = normalize_research_output(
        loop.result.parsed_output_json,
        current_profiles=current_profiles,
    )
    parsed_ok = isinstance(loop.result.parsed_output_json, dict)
    schema_validation = {
        "valid": parsed_ok,
        "claim_count": len(claims),
        "normalization_notes": notes,
        "hit_iteration_limit": loop.hit_iteration_limit,
        "error": None if parsed_ok else "Research output is not a JSON object.",
    }
    _insert_research_trace(
        db,
        job=job,
        target_id=target_id,
        node_config=node_config,
        status="succeeded" if parsed_ok else "failed",
        input_json=research_context,
        conversation=loop.messages + [{"role": "assistant", "content": loop.result.raw_output_text}],
        loop=loop,
        schema_validation_json=schema_validation,
        latency_ms=loop.usage.latency_ms,
        tools=tools,
    )
    if not parsed_ok:
        _mark_research_outcome(db, target_id, "failed")
        db.commit()
        raise ValueError(str(schema_validation["error"]))

    usage_summary = {
        "llm_calls": loop.usage.llm_calls,
        "tool_calls": loop.usage.tool_calls_by_name,
        "hit_iteration_limit": loop.hit_iteration_limit,
        "prompt_version": node_config["prompt_version"],
        # B-7 的判据：一次跑完六个模块到底吃掉多少上下文，只能靠实测。
        "prompt_tokens": loop.usage.prompt_tokens,
        "completion_tokens": loop.usage.completion_tokens,
    }
    # 报告先落库，映射才可以重跑 —— 检索 5~15 分钟很贵，映射几秒很便宜，
    # 改了映射提示词不该逼着重新联网。
    report = {
        "report_text": loop.result.raw_output_text,
        "agent_output_json": loop.result.parsed_output_json,
    }

    if _research_mapper_available(db):
        map_job_id = _enqueue_research_map_job(db, job=job, target_id=target_id)
        has_content = _agent_output_has_content(loop.result.parsed_output_json)
        outcome = "found" if has_content else "no_public_information"
        # The mapper is part of the same user-visible operation.  Keep the
        # target reserved as ``researching`` until mapping and writeback finish;
        # otherwise a page refresh re-enables the button while the second half
        # of the pipeline is still running.
        db.commit()
        return {
            "handled": True,
            "job_type": job.job_type,
            "seller_target_id": str(target_id),
            # provisional：字段和画像要等映射 job 落地，它会覆写这个结论。
            "research_outcome": outcome,
            "mapping_job_id": str(map_job_id),
            **report,
            **usage_summary,
        }

    # 未配置映射节点时退回内联采纳，让修复批次可以独立发版验证。
    apply_summary = apply_research_claims(
        db,
        job=job,
        target_id=target_id,
        claims=claims,
        target_website=target.get("website"),
    )
    proposal_count = len([claim for claim in claims if claim["proposal_kind"] != "not_found"])
    outcome = "found" if proposal_count else "no_public_information"
    _mark_research_outcome(db, target_id, outcome)
    db.commit()
    return {
        "handled": True,
        "job_type": job.job_type,
        "seller_target_id": str(target_id),
        "research_outcome": outcome,
        "mapper_configured": False,
        "proposal_count": len(claims),
        "auto_accepted_count": apply_summary.auto_accepted_count,
        "pending_review_count": apply_summary.pending_review_count,
        "ignored_count": apply_summary.ignored_count,
        "apply_errors": apply_summary.errors,
        **report,
        **usage_summary,
    }


def apply_research_claims(
    db: Session,
    *,
    job: JobClaim,
    target_id: UUID,
    claims: list[dict[str, Any]],
    target_website: str | None,
) -> ResearchClaimApplySummary:
    """Turn normalized claims into proposals and accept them.

    Shared by the research handler's inline fallback and the mapping job, so
    both write the same audit trail.  Traceable supplements and newer-period
    updates are accepted automatically; same-period conflicts stay pending.
    Malformed facts are retained as ignored audit records and never shown as
    actionable.
    """
    summary = ResearchClaimApplySummary()
    prepared_claims = _prepare_research_claims(db, target_id=target_id, claims=claims)
    for claim in prepared_claims:
        proposal = _insert_research_proposal(
            db,
            job=job,
            target_id=target_id,
            claim=claim,
            target_website=target_website,
        )
        label = str(proposal.get("section_code") or proposal.get("field_path") or "unknown")
        validation_error = str(claim.get("validation_error") or "").strip()
        if validation_error:
            summary.ignored_count += 1
            summary.errors.append(f"{label}: {validation_error}")
            continue
        if not _should_auto_accept_research_proposal(proposal):
            summary.pending_review_count += 1
            continue
        try:
            apply_research_proposal(
                db,
                proposal,
                user_id=SYSTEM_USER_ID,
                review_status="auto_accepted",
            )
        except ResearchApplyError as exc:
            _mark_proposal_invalid(db, proposal, str(exc))
            summary.ignored_count += 1
            summary.errors.append(f"{label}: {exc}")
            continue
        _mark_proposal_auto_accepted(db, proposal["id"])
        summary.auto_accepted_count += 1
    return summary


def _prepare_research_claims(
    db: Session,
    *,
    target_id: UUID,
    claims: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach deterministic current-value and period decisions to claims.

    The mapper chooses which report period is semantically appropriate.  Code
    only enforces facts that should never be left to a prompt: numeric validity,
    one core-finance period per batch, and no older-period overwrite.
    """
    prepared = [dict(claim) for claim in claims]
    structured = [claim for claim in prepared if claim.get("proposal_kind") == "structured_fact"]
    if not structured:
        return prepared

    current = _load_current_research_facts(db, target_id=target_id)
    # The new comparison column is null on historical rows.  Reuse the
    # consultant-facing label as a one-time compatibility key so an existing
    # "2024年度" snapshot can still be compared with a 2025 research result.
    # Once any core financial fact is accepted, research_apply persists the
    # machine date and this fallback is no longer needed for that target.
    current_financial_period = (
        _valid_date(current.get("financial_period_end_date"))
        or _financial_period_from_label(current.get("financial_period_label"))
    )
    for claim in structured:
        field_path = str(claim.get("field_path") or "")
        current_value = current.get(field_path)
        claim["current_value_json"] = {
            "value": _json_safe_value(current_value),
            "financial_period_end_date": current_financial_period,
        }
        try:
            normalized_value = normalize_structured_fact(db, field_path, claim.get("value"))
        except ResearchApplyError as exc:
            claim["validation_error"] = str(exc)
            continue
        claim["relation"] = _structured_fact_relation(
            field_path=field_path,
            current_value=current_value,
            new_value=normalized_value,
            current_period=current_financial_period,
            new_period=claim.get("as_of_date"),
        )
        if field_path in CORE_FINANCIAL_FIELDS:
            new_period = _valid_date(claim.get("as_of_date"))
            if new_period is None:
                claim["validation_error"] = f"{field_path} 缺少合法财务期间截止日。"
                continue
            if current_financial_period and new_period < current_financial_period:
                claim["validation_error"] = (
                    f"{field_path} 的期间 {new_period} 早于当前期间 {current_financial_period}，已阻止覆盖。"
                )

    finance_periods = {
        str(claim.get("as_of_date"))
        for claim in structured
        if claim.get("field_path") in CORE_FINANCIAL_FIELDS
        and not claim.get("validation_error")
        and claim.get("as_of_date")
    }
    if len(finance_periods) > 1:
        message = f"同批核心财务指标期间不一致：{', '.join(sorted(finance_periods))}。"
        for claim in structured:
            if claim.get("field_path") in CORE_FINANCIAL_FIELDS:
                claim["validation_error"] = message
    return prepared


def _load_current_research_facts(db: Session, *, target_id: UUID) -> dict[str, Any]:
    columns = sorted(RESEARCH_STRUCTURED_FIELDS | {"financial_period_end_date"})
    row = db.execute(
        text(
            f"""
            select {', '.join(columns)}
            from seller_target
            where id = :target_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "target_id": target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"Seller target not found: {target_id}")
    return dict(row)


def _structured_fact_relation(
    *,
    field_path: str,
    current_value: Any,
    new_value: Any,
    current_period: Any,
    new_period: Any,
) -> str:
    current_missing = current_value in (None, "", [], {})
    values_match = _json_safe_value(current_value) == _json_safe_value(new_value)
    if field_path not in CORE_FINANCIAL_FIELDS:
        if current_missing:
            return "supplement"
        return "consistent" if values_match else "same_period_conflict"

    current_period_text = _valid_date(current_period)
    new_period_text = _valid_date(new_period)
    if current_period_text and new_period_text:
        if new_period_text > current_period_text:
            return "temporal_update"
        if new_period_text < current_period_text:
            return "same_period_conflict"
        if current_missing:
            return "supplement"
        return "consistent" if values_match else "same_period_conflict"
    if current_missing:
        return "supplement"
    return "consistent" if values_match else "same_period_conflict"


def _should_auto_accept_research_proposal(proposal: dict[str, Any]) -> bool:
    relation = str(proposal.get("conflict_kind") or "")
    return (
        relation in {"consistent", "supplement", "temporal_update"}
        and bool(str(proposal.get("source_url") or "").strip())
        and bool(str(proposal.get("source_excerpt") or "").strip())
    )


def _agent_output_has_content(parsed: Any) -> bool:
    if not isinstance(parsed, dict):
        return False
    return any(bool(parsed.get(key)) for key in ("profile_sections", "structured_facts"))


def _research_mapper_available(db: Session) -> bool:
    """Whether the normalization node is configured yet.

    Without it the handler accepts its own claims exactly as before, so the
    fix batch can ship and be verified before the mapping node exists.
    """
    try:
        _get_default_node_config(db, RESEARCH_MAPPER_NODE_NAME)
    except ValueError:
        return False
    return True


def _enqueue_research_map_job(db: Session, *, job: JobClaim, target_id: UUID) -> UUID:
    return db.execute(
        text(
            """
            insert into background_job (
              team_id, workspace_id, job_type, priority, queue_name,
              entity_type, entity_id, idempotency_key, payload_json,
              max_attempts, parent_job_id, correlation_id, created_by, metadata_json
            ) values (
              :team_id, :workspace_id, 'seller_target_research_map', 40, :queue_name,
              'seller_target', :target_id, :idempotency_key, :payload_json,
              3, :parent_job_id, :correlation_id, :created_by, :metadata_json
            ) returning id
            """
        ).bindparams(
            bindparam("payload_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            # Mapping and web research share the dedicated research worker.
            # Do not inherit a legacy parent queue (old research jobs used
            # "llm"), otherwise a remap could land on the wrong service.
            "queue_name": "research",
            "target_id": target_id,
            "idempotency_key": f"seller_target_research_map:{job.id}",
            "payload_json": {"seller_target_id": str(target_id), "research_job_id": str(job.id)},
            "parent_job_id": job.id,
            "correlation_id": job.correlation_id,
            "created_by": SYSTEM_USER_ID,
            "metadata_json": {"source": RESEARCH_MAPPER_NODE_NAME},
        },
    ).scalar_one()


def _chat_caller(
    node_config: dict[str, Any],
    *,
    research_tools: ResearchTools | None = None,
):
    """Bind the node config so the loop only has to pass messages and tools.

    response_format is attached only on turns that carry no tools: several
    OpenAI-compatible layers reject json_object and tools together, and the
    turn that produces the answer is the one that needs the JSON guarantee.
    """

    def call(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None):
        return call_openai_compatible_chat(
            base_url=node_config["base_url"],
            api_key_secret_ref=node_config["api_key_secret_ref"],
            api_key_encrypted=node_config.get("api_key_encrypted"),
            model_name=node_config["model_name"],
            messages=messages,
            temperature=node_config["temperature"],
            top_p=node_config["top_p"],
            max_tokens=node_config["max_tokens"],
            timeout_seconds=node_config["timeout_seconds"] or 120,
            response_format=None if tools else node_config["response_format"],
            tools=tools,
        )

    def chat(*, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None):
        try:
            return call(messages, tools)
        except LlmCallError as exc:
            if not _is_data_inspection_error(exc):
                raise

        omitted = _omit_fetched_page_text(messages, only_last=True)
        if omitted:
            research_tools and research_tools.record_content_inspection_skip(
                omitted, "content_inspection_last_page_omitted"
            )
            try:
                return call(messages, tools)
            except LlmCallError as exc:
                if not _is_data_inspection_error(exc):
                    raise

        omitted = _omit_fetched_page_text(messages, only_last=False)
        if omitted:
            research_tools and research_tools.record_content_inspection_skip(
                omitted, "content_inspection_all_pages_omitted"
            )
            try:
                return call(messages, tools)
            except LlmCallError as exc:
                if not _is_data_inspection_error(exc):
                    raise

        raise ResearchContentInspectionError(
            "模型内容安全检查拦截了检索网页；系统已自动省略可疑网页正文并重试，仍未能完成。"
            "请稍后重试，系统会保留搜索摘要但不会写入未经确认的信息。"
        )

    return chat


def _is_data_inspection_error(exc: BaseException) -> bool:
    message = str(exc).lower().replace("_", "")
    return "datainspectionfailed" in message or "inappropriate content" in message


def _omit_fetched_page_text(messages: list[dict[str, Any]], *, only_last: bool) -> list[str]:
    """Remove fetched page bodies while preserving URLs and search snippets."""
    omitted_urls: list[str] = []
    indexes = range(len(messages) - 1, -1, -1) if only_last else range(len(messages))
    for index in indexes:
        message = messages[index]
        if message.get("role") != "tool" or not isinstance(message.get("content"), str):
            continue
        try:
            payload = json.loads(message["content"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or not payload.get("text"):
            continue
        url = str(payload.get("url") or "")
        payload.pop("text", None)
        payload["content_omitted"] = "网页正文触发模型内容检查，已省略；请仅依据 URL 和搜索摘要。"
        message["content"] = json.dumps(payload, ensure_ascii=False)
        if url:
            omitted_urls.append(url)
        if only_last:
            break
    return omitted_urls


def _normalize_subject_text(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", value).lower()


def _subject_anchors(values: list[str]) -> list[str]:
    suffixes = ("股份有限公司", "有限责任公司", "集团有限公司", "有限公司", "股份公司", "公司")
    anchors: list[str] = []
    for value in values:
        normalized = _normalize_subject_text(value)
        if len(normalized) >= 4 and normalized not in anchors:
            anchors.append(normalized)
        for suffix in suffixes:
            normalized_suffix = _normalize_subject_text(suffix)
            if normalized.endswith(normalized_suffix):
                core = normalized[: -len(normalized_suffix)]
                if len(core) >= 4 and core not in anchors:
                    anchors.append(core)
                break
    return anchors


def normalize_research_output(
    parsed_output_json: dict[str, Any] | None,
    *,
    current_profiles: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Turn the agent's answer into proposals, dropping what cannot be used.

    Unknown section codes, fields outside the whitelist and claims with no
    source URL are discarded with a note rather than silently repaired — a
    proposal a reviewer cannot trace back to a page is not reviewable.
    """
    if not isinstance(parsed_output_json, dict):
        return [], ["research_output:not_an_object"]
    current_profiles = current_profiles or {}
    claims: list[dict[str, Any]] = []
    notes: list[str] = []

    profile_values = parsed_output_json.get("profile_sections")
    normalized_profiles, profile_notes = normalize_profile_section_items(profile_values)
    notes.extend(profile_notes)
    raw_by_code = {
        str(item.get("section_code")): item
        for item in (profile_values if isinstance(profile_values, list) else [])
        if isinstance(item, dict)
    }
    for item in normalized_profiles:
        raw = raw_by_code.get(item["section_code"], {})
        sources = _claim_sources(raw)
        if not sources:
            notes.append(f"profile_sections:{item['section_code']}:missing_sources")
            continue
        source_excerpt = _short_text(raw.get("source_excerpt"), 2000)
        current = current_profiles.get(item["section_code"]) or {}
        claims.append(
            {
                "proposal_kind": "profile_section",
                "section_code": item["section_code"],
                "field_path": None,
                "value": item["content_text"],
                "info_status": "filled",
                "current_value_json": _json_safe_value(current),
                "relation": _relation_of(
                    current=current,
                    new_content=item["content_text"],
                    new_as_of_date=item.get("as_of_date"),
                ),
                "period_label": _short_text(raw.get("period_label"), 100),
                "as_of_date": item.get("as_of_date"),
                "sources": sources,
                "source_title": _short_text(raw.get("source_title"), 300),
                "source_excerpt": source_excerpt,
                "validation_error": None if source_excerpt else "缺少字段级原文摘录，无法自动写入。",
            }
        )

    structured_values = parsed_output_json.get("structured_facts")
    if structured_values is not None and not isinstance(structured_values, list):
        notes.append("structured_facts:not_a_list")
    for index, raw in enumerate(structured_values or []):
        if not isinstance(raw, dict):
            notes.append(f"structured_facts[{index}]:not_an_object")
            continue
        field_path = str(raw.get("field_path") or "").strip()
        if field_path not in RESEARCH_AGENT_STRUCTURED_FIELDS:
            notes.append(f"structured_facts[{index}]:unsupported_field:{field_path[:50]}")
            continue
        value = raw.get("value")
        if value is None or (isinstance(value, str) and not value.strip()):
            notes.append(f"structured_facts[{index}]:empty_value:{field_path}")
            continue
        sources = _claim_sources(raw)
        if not sources:
            notes.append(f"structured_facts[{index}]:missing_sources:{field_path}")
            continue
        source_excerpt = _short_text(raw.get("source_excerpt"), 2000)
        claims.append(
            {
                "proposal_kind": "structured_fact",
                "section_code": None,
                "field_path": field_path,
                "value": value.strip()[:2000] if isinstance(value, str) else value,
                "info_status": None,
                # 结构化字段的当前值不在这里加载（field_writer 落库时才读），
                # 所以没有可比对的旧值，一律记为补充。
                "current_value_json": {},
                "relation": "supplement",
                "period_label": _short_text(raw.get("period_label"), 100),
                "as_of_date": _valid_date(raw.get("as_of_date")),
                "sources": sources,
                "source_title": _short_text(raw.get("source_title"), 300),
                "source_excerpt": source_excerpt,
                "validation_error": None if source_excerpt else "缺少字段级原文摘录，无法自动写入。",
            }
        )

    for code in _coverage_not_found_codes(parsed_output_json, notes=notes):
        # Coverage belongs to the stored research report.  "Nothing public was
        # found" is not a field update and must not become a proposal, a profile
        # row, or a confirmation card.
        notes.append(f"not_found:{code}:report_only")
    return claims, notes


def _not_found_codes(value: Any, *, notes: list[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        notes.append("not_found:not_a_list")
        return []
    codes: list[str] = []
    for item in value:
        code = str(item or "").strip()
        if code not in PROFILE_SECTION_CODES:
            notes.append(f"not_found:unknown_section:{code[:50]}")
            continue
        if code not in codes:
            codes.append(code)
    return codes


def _claim_sources(raw: dict[str, Any]) -> list[str]:
    values = raw.get("sources")
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        values = [raw.get("source_url")] if raw.get("source_url") else []
    sources: list[str] = []
    for item in values:
        url = str(item or "").strip()
        if url.lower().startswith(("http://", "https://")) and url not in sources:
            sources.append(url[:1000])
    return sources[:5]


def _relation_of(
    *,
    current: dict[str, Any] | None,
    new_content: str,
    new_as_of_date: str | None,
) -> str:
    """Classify a claim against what is already on file — in code, not by asking.

    The prompt never asked for `relation`, so every proposal came back
    `supplement` and the UI could only ever say 「补充信息」. Whether two
    statements describe the same period is a comparison, not a judgement call:
    the model supplies the fact and its date, and this decides what that means
    relative to the current revision.
    """
    current_content = str((current or {}).get("content_text") or "").strip()
    if not current_content:
        return "supplement"
    if current_content == new_content.strip():
        return "consistent"
    current_as_of = str((current or {}).get("as_of_date") or "").strip()
    new_as_of = str(new_as_of_date or "").strip()
    if new_as_of and new_as_of != current_as_of:
        # 新的一期覆盖旧的一期；没有旧日期时新日期同样算推进。
        return "temporal_update" if new_as_of > current_as_of else "same_period_conflict"
    # 同期（或都没标期间）却说得不一样 —— 这才是需要人看一眼的冲突。
    return "same_period_conflict"


def _coverage_not_found_codes(payload: dict[str, Any], *, notes: list[str]) -> list[str]:
    """Read report-only coverage codes without turning them into writes."""
    coverage = payload.get("coverage")
    values: Any = payload.get("not_found")
    if isinstance(coverage, dict):
        values = (
            coverage.get("no_public_information")
            or coverage.get("searched_without_result")
            or values
        )
    elif coverage is not None:
        notes.append("coverage:not_an_object")
    return _not_found_codes(values, notes=notes)


def _short_text(value: Any, limit: int) -> str | None:
    return str(value or "").strip()[:limit] or None


def _insert_research_proposal(
    db: Session,
    *,
    job: JobClaim,
    target_id: UUID,
    claim: dict[str, Any],
    target_website: str | None = None,
) -> dict[str, Any]:
    sources = claim.get("sources") or []
    if claim["proposal_kind"] == "structured_fact":
        proposal_kind = "structured_fact"
        proposed_value_json: dict[str, Any] = {"value": claim["value"], "sources": sources}
    else:
        proposal_kind = "profile_section"
        proposed_value_json = {
            "content_text": claim["value"],
            "info_status": claim["info_status"],
            "sources": sources,
        }
    validation_error = str(claim.get("validation_error") or "").strip() or None
    if validation_error:
        proposed_value_json["validation_error"] = validation_error
    row = db.execute(
        text(
            """
            insert into research_proposal (
              team_id, workspace_id, entity_type, entity_id, job_id,
              proposal_kind, section_code, field_path,
              proposed_value_json, current_value_json, conflict_kind,
              period_label, as_of_date, source_type, source_url,
              source_title, source_excerpt, review_status, created_by
            ) values (
              :team_id, :workspace_id, 'seller_target', :entity_id, :job_id,
              :proposal_kind, :section_code, :field_path,
              :proposed_value_json, :current_value_json, :conflict_kind,
              :period_label, :as_of_date, :source_type, :source_url,
              :source_title, :source_excerpt, :review_status, :created_by
            ) returning
              id, entity_id, proposal_kind, section_code, field_path,
              job_id, proposed_value_json, conflict_kind, period_label, as_of_date,
              source_type, source_url, source_title, source_excerpt, review_status
            """
        ).bindparams(
            bindparam("proposed_value_json", type_=JSONB),
            bindparam("current_value_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "entity_id": target_id,
            "job_id": job.id,
            "proposal_kind": proposal_kind,
            "section_code": claim.get("section_code"),
            "field_path": claim.get("field_path"),
            "proposed_value_json": proposed_value_json,
            "current_value_json": claim.get("current_value_json") or {},
            "conflict_kind": claim["relation"],
            "period_label": claim.get("period_label"),
            "as_of_date": claim.get("as_of_date"),
            "source_type": research_source_type(sources[0], target_website=target_website)
            if sources
            else None,
            "source_url": sources[0] if sources else None,
            "source_title": claim.get("source_title"),
            "source_excerpt": claim.get("source_excerpt"),
            "review_status": "ignored" if validation_error else "pending_review",
            "created_by": SYSTEM_USER_ID,
        },
    ).mappings().one()
    return dict(row)


def _mark_proposal_auto_accepted(db: Session, proposal_id: UUID) -> None:
    db.execute(
        text(
            """
            update research_proposal
            set review_status = 'auto_accepted', reviewed_at = now(), updated_at = now()
            where id = :proposal_id
            """
        ),
        {"proposal_id": proposal_id},
    )


def _mark_proposal_invalid(db: Session, proposal: dict[str, Any], error: str) -> None:
    proposed_value = dict(proposal.get("proposed_value_json") or {})
    proposed_value["validation_error"] = error[:1000]
    db.execute(
        text(
            """
            update research_proposal
            set review_status = 'ignored', proposed_value_json = :proposed_value_json,
                reviewed_at = now(), updated_at = now()
            where id = :proposal_id
            """
        ).bindparams(bindparam("proposed_value_json", type_=JSONB)),
        {"proposal_id": proposal["id"], "proposed_value_json": proposed_value},
    )


def research_source_type(url: str, *, target_website: str | None = None) -> str:
    domain = _domain(url)
    official_domain = _domain(str(target_website or ""))
    if official_domain and (domain == official_domain or domain.endswith(f".{official_domain}")):
        return "company_website"
    if domain.endswith(".gov.cn"):
        return "government"
    if any(
        domain == item or domain.endswith(f".{item}")
        for item in ("cninfo.com.cn", "sse.com.cn", "szse.cn", "hkexnews.hk")
    ):
        return "regulatory_disclosure"
    return "public_web"


def _get_research_target(db: Session, target_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              st.id, st.target_name, st.target_subject_name,
              st.industry_l1, st.industry_l2, st.industry_pairs_json,
              st.location_province, st.location_city, st.location_district,
              st.listed_status, st.financial_period_label, st.business_summary
            from seller_target st
            where st.id = :target_id
              and st.team_id = :team_id
              and st.workspace_id = :workspace_id
              and st.deleted_at is null
            """
        ),
        {
            "target_id": target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"Seller target not found: {target_id}")
    return dict(row)


def _research_target_prompt_view(target: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _json_safe_value(value)
        for key, value in target.items()
        if key != "id" and value not in (None, "", [], {})
    }


def _current_profiles_for_prompt(
    profiles: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert loaded profile sections into a prompt-friendly list.

    Each element carries the section code, its label (so the model knows what
    the section is about), and the current content — or a note that it is
    missing.  This avoids feeding the raw internal dict structure into the
    prompt and lets the model focus on what matters: which sections are filled
    and what they already say.
    """
    items: list[dict[str, Any]] = []
    for entry in PROFILE_SECTION_CATALOG:
        code = entry["code"]
        label = entry["label"]
        section = profiles.get(code)
        if section and str(section.get("info_status") or "filled") == "filled":
            items.append({
                "section_code": code,
                "label": label,
                "info_status": "filled",
                "content_text": str(section.get("content_text") or "").strip(),
                # 这份 dict 直接进 ai_trace 的 JSONB 绑定，日期必须已经是字符串。
                "as_of_date": _json_safe_value(section.get("as_of_date")),
                "sources": _json_safe_value(section.get("sources") or []),
            })
        else:
            items.append({
                "section_code": code,
                "label": label,
                "info_status": str(section.get("info_status")) if section else "missing",
                "content_text": None,
            })
    return items


def _mark_research_outcome(db: Session, target_id: UUID, outcome: str) -> None:
    """Record the complete pipeline result and release ``researching``.

    With a mapper configured, successful web research deliberately does not
    call this function.  The mapping job owns the final outcome and releases
    the target only after its writeback has committed.  Failures from either
    job still route through here at their final-attempt boundary.
    """
    db.execute(
        text(
            """
            update seller_target
            set last_research_at = now(),
                research_last_outcome = :outcome,
                information_status = case
                  when information_status = 'researching' then 'normal'
                  else information_status
                end,
                updated_at = now()
            where id = :target_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "target_id": target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "outcome": outcome,
        },
    )


def _insert_research_trace(
    db: Session,
    *,
    job: JobClaim,
    target_id: UUID,
    node_config: dict[str, Any],
    status: str,
    input_json: dict[str, Any],
    conversation: list[dict[str, Any]],
    loop: ToolLoopResult | None,
    schema_validation_json: dict[str, Any],
    latency_ms: int,
    tools: ResearchTools,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    """One trace row per research job, not per LLM call.

    An agent run is five to ten round trips; a row each would bury the table
    and still leave no single place to read one run end to end.
    """
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
            "node_name": RESEARCH_NODE_NAME,
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
            # 最后一道防线：这一行是整次运行的收口，任何一个漏网的日期对象
            # 都会让 JSONB 绑定抛错并回滚掉几分钟的检索成果。
            "input_json": _json_safe_value(input_json),
            "prompt_messages_json": _safe_prompt_messages_for_trace(conversation),
            "raw_output_text": loop.result.raw_output_text if loop else None,
            "parsed_output_json": loop.result.parsed_output_json if loop else None,
            "output_schema_json": node_config.get("output_schema_json") or {},
            "schema_validation_json": schema_validation_json,
            "error_code": error_code,
            "error_message": error_message,
            "latency_ms": latency_ms,
            "prompt_tokens": usage.prompt_tokens if usage else None,
            "completion_tokens": usage.completion_tokens if usage else None,
            "total_tokens": usage.total_tokens if usage else None,
            "created_by": SYSTEM_USER_ID,
            "metadata_json": {
                "source": RESEARCH_NODE_NAME,
                "llm_calls": usage.llm_calls if usage else 0,
                "tool_calls": usage.tool_calls_by_name if usage else {},
                "searched_queries": tools.searched_queries,
                "fetched_urls": tools.fetched_urls,
                "skipped_urls": tools.skipped_urls,
                "content_inspection_retry_count": tools.content_inspection_retry_count,
                "early_stop_reason": tools.early_stop_reason,
                "hit_iteration_limit": bool(loop and loop.hit_iteration_limit),
            },
        },
    )


def _valid_date(value: Any) -> str | None:
    raw = str(value or "").strip()[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        return None


def _financial_period_from_label(value: Any) -> str | None:
    """Parse only common, unambiguous Chinese financial-period labels.

    This is deliberately narrower than natural-language date parsing. Unknown
    labels remain unknown and therefore cannot trigger an automatic overwrite.
    """
    label = re.sub(r"\s+", "", str(value or "")).lower()
    year_match = re.search(r"(?<!\d)(20\d{2})(?!\d)", label)
    if year_match is None:
        return None
    year = int(year_match.group(1))
    quarter_ends = (
        (("一季度", "第一季度", "1季度", "q1"), (3, 31)),
        (("半年度", "半年报", "中期", "二季度", "第二季度", "2季度", "q2"), (6, 30)),
        (("三季度", "第三季度", "3季度", "q3"), (9, 30)),
        (("年度", "年报", "年末", "四季度", "第四季度", "4季度", "q4"), (12, 31)),
    )
    for markers, (month, day) in quarter_ends:
        if any(marker in label for marker in markers):
            return date(year, month, day).isoformat()
    return None


def _domain(url: str) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"https://{value}"
    try:
        host = urlparse(value).netloc.lower().split("@")[-1].split(":")[0]
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host
