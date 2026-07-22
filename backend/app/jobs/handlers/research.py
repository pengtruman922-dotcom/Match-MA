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

import time
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
    profile_coverage,
)
from backend.app.services.search_providers import SearchError
from backend.app.services.search_providers.fetch import fetch_page_text
from backend.app.services.search_service import (
    get_default_search_provider,
    resolve_search_api_key,
    run_search,
)

RESEARCH_NODE_NAME = "seller_target_researcher"

# 工具调用预算。这是成本刹车，不是质量控制 —— 限额内 agent 完全自主。
MAX_TOOL_ITERATIONS = 12
SEARCH_RESULTS_PER_CALL = 6
MAX_SEARCH_RESULTS_PER_CALL = 10
FETCH_TEXT_LIMIT = 8000
SNIPPET_LIMIT = 600

# Research may propose these canonical facts. They stay proposals until a
# consultant accepts them; values outside this deliberately small list never
# enter research_proposal. No numeric fields: a wrong revenue figure costs more
# and is harder to spot than a wrong industry label.
RESEARCH_STRUCTURED_FIELDS = {
    "target_subject_name",
    "industry_primary",
    "industry_secondary",
    "industry_l1",
    "industry_l2",
    "registered_province",
    "registered_city",
    "headquarter_province",
    "headquarter_city",
    "listed_status",
    "business_summary",
}

RELATION_KINDS = {"consistent", "supplement", "temporal_update", "same_period_conflict"}
DEFAULT_RELATION = "supplement"

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

    def __init__(self, provider: dict[str, Any], api_key: str) -> None:
        self._provider = provider
        self._api_key = api_key
        self._page_text_by_url: dict[str, str] = {}
        self.searched_queries: list[str] = []
        self.fetched_urls: list[str] = []

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
        for hit in hits:
            if hit.raw_content:
                self._page_text_by_url[hit.url] = hit.raw_content
            results.append(
                {
                    "url": hit.url,
                    "title": hit.title,
                    "snippet": (hit.snippet or "")[:SNIPPET_LIMIT],
                    "published_at": hit.published_at,
                    "full_text_available": bool(hit.raw_content),
                }
            )
        return {"query": query, "results": results}

    def fetch_page(self, url: str) -> Any:
        url = url.strip()
        if not url:
            return {"error": "url 不能为空"}
        self.fetched_urls.append(url)
        cached = self._page_text_by_url.get(url)
        if cached:
            return {"url": url, "text": cached[:FETCH_TEXT_LIMIT], "source": "search_provider"}
        text_value = fetch_page_text(url)
        if not text_value:
            return {"url": url, "error": "无法抓取该页面正文，可只依据搜索摘要判断或换一个来源。"}
        self._page_text_by_url[url] = text_value
        return {"url": url, "text": text_value[:FETCH_TEXT_LIMIT], "source": "direct_fetch"}


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
        "profile_coverage": profile_coverage(current_profiles),
        "current_profile_sections": _json_safe_value(current_profiles),
        "profile_section_catalog": [
            {"code": code, "label": label} for code, label in PROFILE_SECTION_LABELS.items()
        ],
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

    tools = ResearchTools(provider, api_key)
    started = time.perf_counter()
    try:
        loop = run_tool_loop(
            chat=_chat_caller(node_config),
            messages=messages,
            tools=RESEARCH_TOOLS,
            execute_tool=tools,
            max_iterations=MAX_TOOL_ITERATIONS,
            tool_result_limit=FETCH_TEXT_LIMIT,
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
            error_code="llm_call_failed",
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

    for claim in claims:
        _insert_research_proposal(
            db,
            job=job,
            target_id=target_id,
            claim=claim,
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
        "proposal_count": len(claims),
        "llm_calls": loop.usage.llm_calls,
        "tool_calls": loop.usage.tool_calls_by_name,
        "hit_iteration_limit": loop.hit_iteration_limit,
        "prompt_version": node_config["prompt_version"],
    }


def _chat_caller(node_config: dict[str, Any]):
    """Bind the node config so the loop only has to pass messages and tools.

    response_format is attached only on turns that carry no tools: several
    OpenAI-compatible layers reject json_object and tools together, and the
    turn that produces the answer is the one that needs the JSON guarantee.
    """

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
            timeout_seconds=node_config["timeout_seconds"] or 120,
            response_format=None if tools else node_config["response_format"],
            tools=tools,
        )

    return chat


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
        current = current_profiles.get(item["section_code"]) or {}
        claims.append(
            {
                "proposal_kind": "profile_section",
                "section_code": item["section_code"],
                "field_path": None,
                "value": item["content_text"],
                "info_status": "filled",
                "current_value_json": _json_safe_value(current),
                "relation": _relation_of(raw, notes=notes, label=item["section_code"]),
                "period_label": _short_text(raw.get("period_label"), 100),
                "as_of_date": item.get("as_of_date"),
                "confidence": item.get("confidence"),
                "sources": sources,
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
        if field_path not in RESEARCH_STRUCTURED_FIELDS:
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
        claims.append(
            {
                "proposal_kind": "structured_fact",
                "section_code": None,
                "field_path": field_path,
                "value": value.strip()[:2000] if isinstance(value, str) else value,
                "info_status": None,
                "current_value_json": {},
                "relation": _relation_of(raw, notes=notes, label=field_path),
                "period_label": _short_text(raw.get("period_label"), 100),
                "as_of_date": _valid_date(raw.get("as_of_date")),
                "confidence": _confidence_of(raw.get("confidence")),
                "sources": sources,
            }
        )

    for code in _not_found_codes(parsed_output_json.get("not_found"), notes=notes):
        # 「查过但没有」和「从未查过」在推荐里不是一回事：前者是确认的缺口。
        if (current_profiles.get(code) or {}).get("info_status") == "filled":
            notes.append(f"not_found:{code}:already_filled")
            continue
        claims.append(
            {
                "proposal_kind": "not_found",
                "section_code": code,
                "field_path": None,
                "value": None,
                "info_status": "not_found",
                "current_value_json": _json_safe_value(current_profiles.get(code) or {}),
                "relation": "supplement",
                "period_label": None,
                "as_of_date": None,
                "confidence": None,
                "sources": [],
            }
        )
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


def _relation_of(raw: dict[str, Any], *, notes: list[str], label: str) -> str:
    value = str(raw.get("relation") or "").strip()
    if value in RELATION_KINDS:
        return value
    if value:
        notes.append(f"claim:{label}:unknown_relation:{value[:50]}")
    return DEFAULT_RELATION


def _confidence_of(value: Any) -> float | None:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return None


def _short_text(value: Any, limit: int) -> str | None:
    return str(value or "").strip()[:limit] or None


def _insert_research_proposal(
    db: Session,
    *,
    job: JobClaim,
    target_id: UUID,
    claim: dict[str, Any],
    target_website: str | None = None,
) -> UUID:
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
    row = db.execute(
        text(
            """
            insert into research_proposal (
              team_id, workspace_id, entity_type, entity_id, job_id,
              proposal_kind, section_code, field_path,
              proposed_value_json, current_value_json, conflict_kind,
              period_label, as_of_date, source_type, source_url,
              confidence, review_status, created_by
            ) values (
              :team_id, :workspace_id, 'seller_target', :entity_id, :job_id,
              :proposal_kind, :section_code, :field_path,
              :proposed_value_json, :current_value_json, :conflict_kind,
              :period_label, :as_of_date, :source_type, :source_url,
              :confidence, 'pending_review', :created_by
            ) returning id
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
            "confidence": claim.get("confidence"),
            "created_by": SYSTEM_USER_ID,
        },
    ).mappings().one()
    return row["id"]


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
              st.industry_l1, st.industry_l2, st.industry_primary, st.industry_secondary,
              st.registered_province, st.registered_city,
              st.headquarter_province, st.headquarter_city,
              st.listed_status, st.financial_period_label, st.business_summary,
              sp.legal_name, sp.aliases_json, sp.unified_credit_code,
              sp.region_province, sp.region_city, sp.website
            from seller_target st
            left join seller_party sp on sp.id = st.seller_party_id and sp.deleted_at is null
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


def _mark_research_outcome(db: Session, target_id: UUID, outcome: str) -> None:
    db.execute(
        text(
            """
            update seller_target
            set last_research_at = now(),
                research_last_outcome = :outcome,
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
            "input_json": input_json,
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
