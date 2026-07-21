"""Demand-driven seller-target research.

The search provider only retrieves evidence. A configured research LLM turns
trusted, entity-anchored pages into profile or structured-fact proposals; the
conflict layer then decides whether a profile supplement is safe to accept or
must wait for a consultant. Structured facts never silently overwrite the
canonical target row.
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
    load_profile_sections,
    normalize_profile_section_items,
    profile_coverage,
    upsert_profile_section,
)
from backend.app.services.research_anchor import (
    AnchorMatch,
    build_anchors,
    is_evidence_trusted,
    match_anchors,
)
from backend.app.services.search_providers import SearchError, SearchHit
from backend.app.services.search_service import get_default_search_provider, run_search

RESEARCH_NODE_NAME = "seller_target_researcher"
MAX_TRUSTED_EVIDENCE = 8
MAX_EVIDENCE_TEXT = 3500

# Research may propose these canonical facts. They remain pending until a
# consultant accepts them; values outside this deliberately small list never
# enter research_proposal.
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

HIGH_AUTHORITY_SOURCE_TYPES = {"regulatory_disclosure", "government"}
COMPANY_AUTO_SECTION_CODES = {"business_product", "tech_team"}


def _handle_seller_target_research(db: Session, job: JobClaim) -> dict[str, object]:
    target_id = job.entity_id
    if job.entity_type != "seller_target" or target_id is None:
        raise ValueError("seller_target_research requires a seller_target entity_id.")

    target = _get_research_target(db, target_id)
    provider = get_default_search_provider(db)
    if provider is None:
        _mark_research_outcome(db, target_id, "failed", retry_days=1)
        db.commit()
        raise ValueError("No active search provider is configured.")

    try:
        evidence = _collect_trusted_evidence(provider, target)
    except SearchError:
        _mark_research_outcome(db, target_id, "failed", retry_days=1)
        db.commit()
        raise

    if not evidence:
        _mark_research_outcome(db, target_id, "no_public_information", retry_days=30)
        db.commit()
        return {
            "handled": True,
            "job_type": job.job_type,
            "seller_target_id": str(target_id),
            "research_outcome": "no_public_information",
            "trusted_evidence_count": 0,
            "proposal_count": 0,
            "auto_accepted_count": 0,
        }

    _assign_evidence_refs(evidence)
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
        "allowed_profile_section_codes": list(PROFILE_SECTION_CODES),
        "allowed_structured_fields": sorted(RESEARCH_STRUCTURED_FIELDS),
        "trusted_evidence": [_evidence_prompt_view(item) for item in evidence],
    }
    prompt_messages = _render_prompt_messages(
        node_config,
        {"research_context_json": research_context},
    )
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
            timeout_seconds=node_config["timeout_seconds"] or 120,
            response_format=node_config["response_format"],
        )
    except LlmCallError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        _insert_research_trace(
            db,
            job=job,
            target_id=target_id,
            node_config=node_config,
            status="failed",
            input_json=research_context,
            prompt_messages=prompt_messages,
            raw_output_text=None,
            parsed_output_json=None,
            schema_validation_json={"valid": False, "error": str(exc)},
            latency_ms=latency_ms,
            error_code="llm_call_failed",
            error_message=str(exc),
        )
        _mark_research_outcome(db, target_id, "failed", retry_days=1)
        db.commit()
        raise

    claims, normalization_notes = normalize_research_output(
        llm_result.parsed_output_json,
        evidence=evidence,
    )
    schema_validation = {
        "valid": isinstance(llm_result.parsed_output_json, dict),
        "proposal_count": len(claims),
        "normalization_notes": normalization_notes,
        "error": None if isinstance(llm_result.parsed_output_json, dict) else "Research output is not an object.",
    }
    _insert_research_trace(
        db,
        job=job,
        target_id=target_id,
        node_config=node_config,
        status="succeeded" if schema_validation["valid"] else "failed",
        input_json=research_context,
        prompt_messages=prompt_messages,
        raw_output_text=llm_result.raw_output_text,
        parsed_output_json=llm_result.parsed_output_json,
        schema_validation_json=schema_validation,
        latency_ms=llm_result.latency_ms,
        prompt_tokens=llm_result.prompt_tokens,
        completion_tokens=llm_result.completion_tokens,
        total_tokens=llm_result.total_tokens,
        error_code=None if schema_validation["valid"] else "schema_validation_failed",
        error_message=schema_validation["error"],
    )
    if not schema_validation["valid"]:
        _mark_research_outcome(db, target_id, "failed", retry_days=1)
        db.commit()
        raise ValueError(str(schema_validation["error"]))

    proposal_count = 0
    auto_accepted_count = 0
    for claim in claims:
        if claim["proposal_kind"] == "profile_section":
            current = current_profiles.get(claim["section_code"])
            conflict_kind = classify_research_conflict(
                current_value=(current or {}).get("content_text"),
                proposed_value=claim["value"],
                current_as_of_date=(current or {}).get("as_of_date"),
                proposed_as_of_date=claim.get("as_of_date"),
            )
            current_value_json = _json_safe_value(current or {})
        else:
            current_value = target.get(claim["field_path"])
            conflict_kind = classify_research_conflict(
                current_value=current_value,
                proposed_value=claim["value"],
                current_as_of_date=_fact_current_period(target, claim["field_path"]),
                proposed_as_of_date=claim.get("as_of_date") or claim.get("period_label"),
            )
            current_value_json = {"value": _json_safe_value(current_value)}

        auto_accept = _should_auto_accept_profile_claim(claim, conflict_kind)
        review_status = "auto_accepted" if auto_accept else "pending_review"
        _insert_research_proposal(
            db,
            job=job,
            target_id=target_id,
            claim=claim,
            conflict_kind=conflict_kind,
            current_value_json=current_value_json,
            review_status=review_status,
        )
        proposal_count += 1
        if auto_accept:
            _write_researched_profile_section(db, target_id=target_id, claim=claim)
            auto_accepted_count += 1

    outcome = "found" if proposal_count else "no_public_information"
    _mark_research_outcome(
        db,
        target_id,
        outcome,
        retry_days=30 if outcome == "no_public_information" else None,
    )
    db.commit()
    return {
        "handled": True,
        "job_type": job.job_type,
        "seller_target_id": str(target_id),
        "research_outcome": outcome,
        "trusted_evidence_count": len(evidence),
        "proposal_count": proposal_count,
        "auto_accepted_count": auto_accepted_count,
        "prompt_version": node_config["prompt_version"],
    }


def build_research_queries(target: dict[str, Any]) -> list[str]:
    name = str(target.get("legal_name") or target.get("target_subject_name") or target.get("target_name") or "").strip()
    region = str(
        target.get("registered_city")
        or target.get("headquarter_city")
        or target.get("registered_province")
        or target.get("headquarter_province")
        or ""
    ).strip()
    prefix = " ".join(part for part in (f'"{name}"' if name else "", region) if part)
    return [
        f"{prefix} 主营业务 核心产品 商业模式 产业链 行业地位",
        f"{prefix} 核心技术 专利 研发 团队 产能 资质",
        f"{prefix} 经营质量 客户 增长 股权 交易 出售 风险",
    ]


def _collect_trusted_evidence(
    provider: dict[str, Any],
    target: dict[str, Any],
) -> list[dict[str, Any]]:
    anchors = build_anchors(target)
    trusted: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for query in build_research_queries(target):
        for hit in run_search(provider, query, max_results=6):
            if hit.url in seen_urls:
                continue
            seen_urls.add(hit.url)
            matches = match_anchors(
                anchors,
                evidence_text=hit.evidence_text(),
                source_url=hit.url,
            )
            if not is_evidence_trusted(matches):
                continue
            trusted.append(_trusted_evidence_item(hit, matches, target=target))
            if len(trusted) >= MAX_TRUSTED_EVIDENCE:
                return trusted
    return trusted


def _trusted_evidence_item(
    hit: SearchHit,
    matches: list[AnchorMatch],
    *,
    target: dict[str, Any],
) -> dict[str, Any]:
    return {
        "evidence_ref": "",
        "url": hit.url,
        "title": hit.title,
        "snippet": hit.snippet[:2000],
        "raw_content": (hit.raw_content or "")[:MAX_EVIDENCE_TEXT],
        "published_at": hit.published_at,
        "provider": hit.provider,
        "source_type": research_source_type(hit.url, target=target),
        "anchor_matches": [{"kind": match.kind, "value": match.value} for match in matches],
    }


def _evidence_prompt_view(item: dict[str, Any], index: int | None = None) -> dict[str, Any]:
    result = dict(item)
    result["evidence_ref"] = item.get("evidence_ref") or (f"E{index}" if index else "")
    return {key: value for key, value in result.items() if key != "anchor_matches"}


def _assign_evidence_refs(evidence: list[dict[str, Any]]) -> None:
    for index, item in enumerate(evidence, start=1):
        item["evidence_ref"] = f"E{index}"


def normalize_research_output(
    parsed_output_json: dict[str, Any] | None,
    *,
    evidence: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(parsed_output_json, dict):
        return [], ["research_output:not_an_object"]
    _assign_evidence_refs(evidence)
    evidence_by_ref = {str(item["evidence_ref"]): item for item in evidence}
    claims: list[dict[str, Any]] = []
    notes: list[str] = []

    profile_values = parsed_output_json.get("profile_sections")
    normalized_profiles, profile_notes = normalize_profile_section_items(profile_values)
    notes.extend(profile_notes)
    raw_profiles = profile_values if isinstance(profile_values, list) else []
    raw_profile_by_code = {
        str(item.get("section_code")): item for item in raw_profiles if isinstance(item, dict)
    }
    for item in normalized_profiles:
        raw = raw_profile_by_code.get(item["section_code"], {})
        source = _claim_source(raw, evidence_by_ref, notes=notes, label=item["section_code"])
        if source is None:
            continue
        claims.append(
            {
                "proposal_kind": "profile_section",
                "section_code": item["section_code"],
                "field_path": None,
                "value": item["content_text"],
                "period_label": str(raw.get("period_label") or "").strip()[:100] or None,
                "as_of_date": item.get("as_of_date"),
                "confidence": item.get("confidence"),
                **source,
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
        source = _claim_source(raw, evidence_by_ref, notes=notes, label=field_path)
        if source is None:
            continue
        try:
            confidence = max(0.0, min(float(raw.get("confidence")), 1.0))
        except (TypeError, ValueError):
            confidence = None
        claims.append(
            {
                "proposal_kind": "structured_fact",
                "section_code": None,
                "field_path": field_path,
                "value": str(value).strip()[:2000] if isinstance(value, str) else value,
                "period_label": str(raw.get("period_label") or "").strip()[:100] or None,
                "as_of_date": _valid_date(raw.get("as_of_date")),
                "confidence": confidence,
                **source,
            }
        )
    return claims, notes


def _claim_source(
    raw: dict[str, Any],
    evidence_by_ref: dict[str, dict[str, Any]],
    *,
    notes: list[str],
    label: str,
) -> dict[str, Any] | None:
    refs = raw.get("evidence_refs")
    if not isinstance(refs, list):
        refs = [raw.get("evidence_ref")] if raw.get("evidence_ref") else []
    source = next((evidence_by_ref.get(str(ref)) for ref in refs if evidence_by_ref.get(str(ref))), None)
    if source is None:
        notes.append(f"claim:{label}:missing_trusted_evidence_ref")
        return None
    evidence_text = "\n".join(
        str(value or "") for value in (source.get("title"), source.get("snippet"), source.get("raw_content"))
    )
    quote = str(raw.get("evidence_quote") or "").strip()
    if not quote or quote not in evidence_text:
        if quote:
            notes.append(f"claim:{label}:evidence_quote_not_verbatim")
        quote = str(source.get("snippet") or source.get("raw_content") or "").strip()[:2000]
    return {
        "source_type": source["source_type"],
        "source_url": source["url"],
        "source_title": source["title"],
        "source_excerpt": quote[:2000] or None,
        "anchor_matches": source["anchor_matches"],
    }


def classify_research_conflict(
    *,
    current_value: Any,
    proposed_value: Any,
    current_as_of_date: Any = None,
    proposed_as_of_date: Any = None,
) -> str:
    current_text = _comparable_value(current_value)
    proposed_text = _comparable_value(proposed_value)
    if not current_text:
        return "supplement"
    if current_text == proposed_text:
        return "consistent"
    current_period = str(current_as_of_date or "").strip()
    proposed_period = str(proposed_as_of_date or "").strip()
    if current_period and proposed_period and current_period != proposed_period:
        return "temporal_update"
    return "same_period_conflict"


def research_source_type(url: str, *, target: dict[str, Any]) -> str:
    domain = _domain(url)
    official_domain = _domain(str(target.get("website") or ""))
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


def _should_auto_accept_profile_claim(claim: dict[str, Any], conflict_kind: str) -> bool:
    if claim["proposal_kind"] != "profile_section":
        return False
    if conflict_kind not in {"supplement", "temporal_update"}:
        return False
    if claim["source_type"] in HIGH_AUTHORITY_SOURCE_TYPES:
        return True
    return (
        claim["source_type"] == "company_website"
        and claim["section_code"] in COMPANY_AUTO_SECTION_CODES
        and conflict_kind == "supplement"
    )


def _insert_research_proposal(
    db: Session,
    *,
    job: JobClaim,
    target_id: UUID,
    claim: dict[str, Any],
    conflict_kind: str,
    current_value_json: Any,
    review_status: str,
) -> UUID:
    proposed_value_json = (
        {"content_text": claim["value"], "info_status": "filled"}
        if claim["proposal_kind"] == "profile_section"
        else {"value": claim["value"]}
    )
    row = db.execute(
        text(
            """
            insert into research_proposal (
              team_id, workspace_id, entity_type, entity_id, job_id,
              proposal_kind, section_code, field_path,
              proposed_value_json, current_value_json, conflict_kind,
              period_label, as_of_date, source_type, source_url, source_title,
              source_excerpt, anchor_matches_json, confidence, review_status,
              created_by
            ) values (
              :team_id, :workspace_id, 'seller_target', :entity_id, :job_id,
              :proposal_kind, :section_code, :field_path,
              :proposed_value_json, :current_value_json, :conflict_kind,
              :period_label, :as_of_date, :source_type, :source_url, :source_title,
              :source_excerpt, :anchor_matches_json, :confidence, :review_status,
              :created_by
            ) returning id
            """
        ).bindparams(
            bindparam("proposed_value_json", type_=JSONB),
            bindparam("current_value_json", type_=JSONB),
            bindparam("anchor_matches_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "entity_id": target_id,
            "job_id": job.id,
            "proposal_kind": claim["proposal_kind"],
            "section_code": claim.get("section_code"),
            "field_path": claim.get("field_path"),
            "proposed_value_json": proposed_value_json,
            "current_value_json": current_value_json or {},
            "conflict_kind": conflict_kind,
            "period_label": claim.get("period_label"),
            "as_of_date": claim.get("as_of_date"),
            "source_type": claim.get("source_type"),
            "source_url": claim.get("source_url"),
            "source_title": claim.get("source_title"),
            "source_excerpt": claim.get("source_excerpt"),
            "anchor_matches_json": claim.get("anchor_matches") or [],
            "confidence": claim.get("confidence"),
            "review_status": review_status,
            "created_by": SYSTEM_USER_ID,
        },
    ).mappings().one()
    return row["id"]


def _write_researched_profile_section(
    db: Session,
    *,
    target_id: UUID,
    claim: dict[str, Any],
) -> None:
    upsert_profile_section(
        db,
        entity_type="seller_target",
        entity_id=target_id,
        section_code=claim["section_code"],
        info_status="filled",
        content_text=str(claim["value"]),
        source_type=claim.get("source_type"),
        source_url=claim.get("source_url"),
        source_title=claim.get("source_title"),
        source_excerpt=claim.get("source_excerpt"),
        as_of_date=claim.get("as_of_date"),
        confidence=claim.get("confidence"),
        review_status="auto_accepted",
        user_id=SYSTEM_USER_ID,
        supersede_current=False,
    )


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
        if key not in {"id", "unified_credit_code"} and value not in (None, "", [], {})
    }


def _mark_research_outcome(
    db: Session,
    target_id: UUID,
    outcome: str,
    *,
    retry_days: int | None,
) -> None:
    db.execute(
        text(
            """
            update seller_target
            set last_research_at = now(),
                research_last_outcome = :outcome,
                research_retry_after = case
                  when :retry_days is null then null
                  else now() + (:retry_days * interval '1 day')
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
            "retry_days": retry_days,
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
    prompt_messages: list[dict[str, Any]],
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
            "prompt_messages_json": _safe_prompt_messages_for_trace(prompt_messages),
            "raw_output_text": raw_output_text,
            "parsed_output_json": parsed_output_json,
            "output_schema_json": node_config.get("output_schema_json") or {},
            "schema_validation_json": schema_validation_json,
            "error_code": error_code,
            "error_message": error_message,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "created_by": SYSTEM_USER_ID,
            "metadata_json": {"source": RESEARCH_NODE_NAME},
        },
    )


def _fact_current_period(target: dict[str, Any], field_path: str) -> Any:
    if field_path in {"business_summary"}:
        return target.get("financial_period_label")
    return None


def _valid_date(value: Any) -> str | None:
    raw = str(value or "").strip()[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        return None


def _comparable_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return "".join(value.lower().split())
    return str(_json_safe_value(value)).strip().lower()


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
