import json
import time
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.ai.llm_client import stream_openai_compatible_chat
from backend.app.api.authn import CurrentUser
from backend.app.jobs.handlers.common import _get_default_node_config, _render_prompt_messages
from backend.app.registry.nodes import recommendation_answer_writer_node_by_mode
from backend.app.services.recommendation_answer import (
    backfill_target_links,
    build_answer_prompt_variables,
    fallback_answer_markdown,
    sanitize_writer_output,
    target_link_map,
)
from backend.app.api.routes.utils import (
    ensure_entity_writable,
    ensure_recommendation_session_visible,
    owner_scope_required,
    recommendation_report_visible_sql,
    recommendation_session_visible_sql,
)
from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db, session_scope
from backend.app.services.recommendation_conditions import (
    apply_condition_actions,
    apply_overrides_to_anchor,
    conditions_snapshot,
    derive_route,
    describe_condition_ops,
    merge_condition_overrides,
    parse_recommendation_message,
    persist_session_overrides,
)
from backend.app.services.recommendation_flow import (  # noqa: F401 - re-exported for compatibility
    CANDIDATE_STATE_COMPATIBLE,
    CANDIDATE_STATE_CONFLICT,
    CANDIDATE_STATE_POSSIBLE,
    DEEP_EVAL_CANDIDATE_LIMIT,
    REGION_GROUPS,
    _annotate_candidate_ownership,
    _build_recommendation_activity,
    _build_recommendation_report_status,
    _build_recommendation_rerank_status,
    _build_recommendation_selected_status,
    _build_recommendation_session_bundle,
    _build_recommendation_session_summary,
    _build_recommendation_agent_status,
    _build_rerank_query,
    _candidate_display_badges,
    _candidate_display_meta,
    _candidate_intents_for_target,
    _candidate_pair_key,
    _candidate_score_breakdown,
    _candidate_targets_for_intent,
    _compact_background_job,
    _compact_recommendation_message,
    _compact_recommendation_report,
    _compact_selected_item,
    _count_by_key,
    agent_history_context,
    agent_turn_aborted,
    find_agent_turn_job,
    insert_agent_aborted_message,
    _create_recommendation_session,
    find_agent_turn_answer,
    find_agent_turn_brief,
    insert_agent_answer_message,
    _enqueue_recommendation_agent_job,
    _enqueue_recommendation_report_job,
    _enqueue_recommendation_rerank_job,
    _enrich_candidates_for_frontend,
    _enrich_candidates_with_selection,
    _ensure_recommendation_report_visible,
    _excluded_industry_hit,
    _extract_recommendation_candidate_sets,
    _filter_recommendation_session_summaries,
    _get_active_selected_item_for_pair,
    _get_buyer_intent_anchor,
    _get_buyer_party_id_for_intent,
    _get_latest_recommendation_rerank_job,
    _get_recommendation_report_jobs,
    _get_recommendation_session_or_404,
    _get_recommendation_session_overview_or_404,
    _get_rerank_anchor_for_session,
    _get_selected_item_or_404,
    _get_seller_target_anchor,
    _infer_recommendation_candidate_message_type,
    _insert_recommendation_message,
    _intent_industry_list,
    _join_display_parts,
    _json_dumps,
    _json_loads,
    _json_safe,
    _list_recommendation_messages,
    _list_recommendation_reports,
    _list_recommendation_session_overview_rows,
    _list_running_recommendation_session_ids,
    _list_selected_items,
    _list_selected_items_for_report,
    _message_returning_statement,
    _message_select_columns,
    _normalize_candidates,
    _optional_decimal,
    _optional_float,
    _optional_uuid,
    _optional_uuid_from_mapping,
    _recommendation_level,
    _recommendation_page_overview,
    _recommendation_quick_actions,
    _recommendation_session_display,
    _recommendation_session_is_processing,
    _recommendation_session_polling_hint,
    _refresh_session_report_count,
    _refresh_session_selected_count,
    _region_scope_matches,
    _report_returning_statement,
    _report_select_columns,
    _score_target_against_intent,
    _selected_item_returning_statement,
    _selected_item_select_columns,
    _session_overview_select_columns,
    _session_returning_statement,
    _session_select_columns,
    _string_or_none,
    _strip_region_suffix,
    _summary_text,
    _touch_recommendation_session,
    _with_frontend_candidate_fields,
    _yes_like,
)
from backend.app.services.recommendation_report import (
    build_fallback_report_markdown,
    build_recommendation_report_context,
    default_report_title,
    default_report_type,
    ensure_report_item_count,
    report_type_matches_mode,
)
from backend.app.services.report_docx import (
    DOCX_MEDIA_TYPE,
    render_report_docx,
    safe_docx_filename,
)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

# 一次输入的上限。4000 是给手打需求定的，一份上传的需求文档轻松超过；
# 正文由前端从附件正文取出后走同一个字段，所以两处共用这个上限。
AGENT_INPUT_MAX_CHARS = 20000
# 与 image_multimodal_max_count 同量级；再多一次对话也读不过来。
AGENT_MAX_IMAGE_ATTACHMENTS = 6

# 自建部署的 Caddy 开着 encode gzip，会把 SSE 攒在缓冲区里等压缩，
# 逐字流式就变成一次性吐完。no-transform 让代理不要动响应体；
# X-Accel-Buffering 是给 nginx 一类反代看的，Caddy 无视它也无害。
_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


class RecommendationCandidateRequest(BaseModel):
    mode: str = Field(pattern="^(buyer_to_target|target_to_buyer)$")
    buyer_intent_id: UUID | None = None
    seller_target_id: UUID | None = None
    # A one-off request is deliberately not persisted as a fake buyer intent or
    # seller target.  The text is kept only in the recommendation session
    # snapshot and drives a read-only temporary-filter session.
    temporary_input: str | None = Field(default=None, max_length=AGENT_INPUT_MAX_CHARS)
    limit: int = Field(default=20, ge=1, le=50)
    create_session: bool = True
    enable_rerank: bool = True
    user_message: str | None = None
    # Continue an existing session (multi-round chat): append the user message
    # and a new candidate round instead of creating a new session.
    session_id: UUID | None = None
    # Deterministic condition-panel actions (chip removal / clear-all); applied
    # without the LLM parser: [{"op": "remove_field", "field": ...},
    # {"op": "remove_preference", "value": ...}, {"op": "clear_all"}]
    condition_actions: list[dict[str, Any]] | None = None

    @model_validator(mode="after")
    def validate_anchor(self) -> "RecommendationCandidateRequest":
        has_temporary_input = bool((self.temporary_input or "").strip())
        if has_temporary_input and (self.buyer_intent_id is not None or self.seller_target_id is not None):
            raise ValueError("temporary_input cannot be combined with an existing recommendation anchor.")
        if has_temporary_input and (self.user_message or "").strip():
            raise ValueError("temporary_input is the initial request; send follow-up requirements in user_message.")
        # A continuation obtains its anchor from the persisted session.  The
        # endpoint then verifies that the supplied anchor still matches it.
        if self.session_id is not None:
            return self
        if self.mode == "buyer_to_target" and self.buyer_intent_id is None and not has_temporary_input:
            raise ValueError("buyer_intent_id is required for buyer_to_target.")
        if self.mode == "target_to_buyer" and self.seller_target_id is None and not has_temporary_input:
            raise ValueError("seller_target_id is required for target_to_buyer.")
        return self


TEMPORARY_FILTER_METADATA_KEY = "temporary_filter"


def _is_temporary_filter_session(session: dict[str, Any]) -> bool:
    return bool((session.get("metadata_json") or {}).get(TEMPORARY_FILTER_METADATA_KEY))


def _build_temporary_anchor(mode: str, temporary_input: str) -> dict[str, Any]:
    """Build an in-memory scoring anchor for a one-off filter.

    The object intentionally has no id.  That is the guardrail which prevents
    a temporary result from becoming a buyer-target relation by accident.
    """
    if mode == "buyer_to_target":
        return {
            "id": None,
            "buyer_party_id": None,
            "buyer_name": None,
            "intent_name": "临时买家需求",
            "raw_requirement_text": temporary_input,
            "intent_summary": temporary_input,
            "industries_json": [],
            "excluded_industries_json": [],
        }
    return {
        "id": None,
        "target_name": "临时标的画像",
        "business_summary": temporary_input,
        "transaction_summary": temporary_input,
        "risk_summary": None,
        "gap_summary": None,
        "industry_pairs_json": [],
    }


def _temporary_anchor_from_session(session: dict[str, Any]) -> dict[str, Any]:
    snapshot = session.get("initial_condition_snapshot_json")
    if isinstance(snapshot, dict) and snapshot:
        return dict(snapshot)
    # Sessions are only created through the candidate endpoint, but keep a
    # defensive fallback so an old manually-created anonymous session returns
    # a useful validation error rather than operating on an empty dict.
    raw_input = str(session.get("anonymous_input_snapshot") or "").strip()
    if not raw_input:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Temporary recommendation session has no input.")
    return _build_temporary_anchor(str(session["mode"]), raw_input)


class RecommendationCandidateOut(BaseModel):
    rank: int
    mode: str
    seller_target_id: UUID | None
    seller_target_name: str | None
    buyer_intent_id: UUID | None
    buyer_intent_name: str | None
    buyer_party_id: UUID | None
    buyer_name: str | None
    score: float
    recommendation_level: str
    match_summary: str
    gap_summary: str | None
    risk_summary: str | None
    evidence_json: dict[str, Any]
    match_state: str | None = None
    known_count: int = 0
    missing_dimensions: list[str] = Field(default_factory=list)
    best_scenario_id: str | None = None
    best_scenario_label: str | None = None
    matched_scenarios: list[str] = Field(default_factory=list)
    matched_scenario_labels: list[str] = Field(default_factory=list)
    deep_eval: dict[str, Any] | None = None
    selected: bool = False
    selected_item_id: UUID | None = None
    selected_at: str | None = None
    primary_entity_type: str | None = None
    primary_entity_id: UUID | None = None
    counterpart_entity_type: str | None = None
    counterpart_entity_id: UUID | None = None
    display_title: str | None = None
    display_subtitle: str | None = None
    display_meta: list[str] = Field(default_factory=list)
    display_badges: list[str] = Field(default_factory=list)
    score_breakdown: dict[str, Any] = Field(default_factory=dict)
    card_json: dict[str, Any] = Field(default_factory=dict)
    relation_id: UUID | None = None
    relation_status: str | None = None
    deep_progress_elsewhere: bool = False
    seller_target_has_other_deep_progress: bool = False
    buyer_intent_has_other_deep_progress: bool = False
    seller_target_owner_user_id: UUID | None = None
    seller_target_owner_name: str | None = None
    seller_target_owned_by_current_user: bool = False
    seller_target_operation_allowed: bool = False
    buyer_intent_owner_user_id: UUID | None = None
    buyer_intent_owner_name: str | None = None
    buyer_intent_owned_by_current_user: bool = False
    buyer_intent_operation_allowed: bool = False


class RecommendationCandidateResponse(BaseModel):
    session_id: UUID | None
    mode: str
    candidates: list[RecommendationCandidateOut]
    debug: dict[str, Any]


class RecommendationSessionCreate(BaseModel):
    mode: str = Field(pattern="^(buyer_to_target|target_to_buyer)$")
    buyer_intent_id: UUID | None = None
    buyer_party_id: UUID | None = None
    seller_target_id: UUID | None = None
    anonymous_input_snapshot: str | None = None
    initial_condition_snapshot_json: dict[str, Any] = Field(default_factory=dict)
    latest_condition_snapshot_json: dict[str, Any] = Field(default_factory=dict)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class RecommendationSessionOut(BaseModel):
    id: UUID
    mode: str
    buyer_intent_id: UUID | None
    buyer_party_id: UUID | None
    seller_target_id: UUID | None
    status: str
    selected_count: int
    report_count: int
    anonymous_input_snapshot: str | None
    initial_condition_snapshot_json: dict[str, Any]
    latest_condition_snapshot_json: dict[str, Any]
    condition_overrides_json: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    metadata_json: dict[str, Any]


class RecommendationSelectedItemCreate(BaseModel):
    mode: str = Field(pattern="^(buyer_to_target|target_to_buyer)$")
    seller_target_id: UUID | None = None
    buyer_intent_id: UUID | None = None
    buyer_party_id: UUID | None = None
    rank_at_selection: int | None = None
    recommendation_level: str | None = Field(default=None, pattern="^(strong|recommended|possible|weak)$")
    match_summary: str | None = None
    risk_summary: str | None = None
    gap_summary: str | None = None
    reason_snapshot: str | None = None
    evidence_snapshot_json: dict[str, Any] = Field(default_factory=dict)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class RecommendationSelectedItemOut(BaseModel):
    id: UUID
    session_id: UUID
    mode: str
    seller_target_id: UUID | None
    seller_target_name: str | None = None
    buyer_intent_id: UUID | None
    buyer_intent_name: str | None = None
    buyer_party_id: UUID | None
    buyer_name: str | None = None
    rank_at_selection: int | None
    recommendation_level: str | None
    match_summary: str | None
    risk_summary: str | None
    gap_summary: str | None
    reason_snapshot: str | None
    evidence_snapshot_json: dict[str, Any]
    selected_at: str
    canceled_at: str | None
    metadata_json: dict[str, Any]


class RecommendationMessageCreate(BaseModel):
    role: str = Field(default="user", pattern="^(user|assistant|system|tool)$")
    content: str
    content_type: str = Field(default="text", pattern="^(text|json|markdown)$")
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class RecommendationMessageOut(BaseModel):
    id: UUID
    session_id: UUID
    role: str
    content: str
    content_type: str
    metadata_json: dict[str, Any]
    created_at: str


class RecommendationReportCreate(BaseModel):
    report_type: Literal[
        "buyer_facing_target_report",
        "seller_facing_buyer_report",
    ] | None = None
    selected_item_ids: list[UUID] | None = None
    title: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class RecommendationReportOut(BaseModel):
    id: UUID
    session_id: UUID
    report_type: str
    selected_item_ids_json: list[Any]
    title: str | None
    markdown_content: str | None
    file_path: str | None
    file_format: str | None
    status: str
    generated_by_model: str | None
    prompt_version: str | None
    created_at: str
    metadata_json: dict[str, Any]


class RecommendationReportJobOut(BaseModel):
    report: RecommendationReportOut
    job_id: UUID
    job_status: str
    queue_name: str


class RecommendationSessionBundleOut(BaseModel):
    session: RecommendationSessionOut
    messages: list[RecommendationMessageOut]
    initial_candidates: list[RecommendationCandidateOut] = Field(default_factory=list)
    reranked_candidates: list[RecommendationCandidateOut] = Field(default_factory=list)
    latest_candidates: list[RecommendationCandidateOut] = Field(default_factory=list)
    candidate_source: str = "none"
    rerank_status: dict[str, Any] = Field(default_factory=dict)
    selected_items: list[RecommendationSelectedItemOut]
    reports: list[RecommendationReportOut]
    debug: dict[str, Any]


class RecommendationRerankJobCreate(BaseModel):
    candidates: list[dict[str, Any]] | None = None
    reason: str | None = Field(default=None, max_length=300)


class RecommendationRerankJobOut(BaseModel):
    job_id: UUID
    job_status: str
    queue_name: str
    candidate_count: int
    source: str


class RecommendationSessionSummaryOut(BaseModel):
    session: dict[str, Any]
    display: dict[str, Any]
    candidate_counts: dict[str, int]
    latest_candidates_preview: list[RecommendationCandidateOut] = Field(default_factory=list)
    candidate_source: str
    rerank_status: dict[str, Any]
    report_status: dict[str, Any]
    selected_status: dict[str, Any]
    agent_status: dict[str, Any] = Field(default_factory=dict)
    activity: dict[str, Any]
    debug_ref: dict[str, Any]


class RecommendationPageOut(BaseModel):
    recent_sessions: list[RecommendationSessionSummaryOut]
    running_sessions: list[RecommendationSessionSummaryOut]
    overview: dict[str, Any]
    quick_actions: list[dict[str, Any]]
    polling_hint: dict[str, Any]


class RecommendationSessionStatusOut(BaseModel):
    session: dict[str, Any]
    display: dict[str, Any]
    candidate_counts: dict[str, int]
    latest_candidates_preview: list[RecommendationCandidateOut] = Field(default_factory=list)
    candidate_source: str
    rerank_status: dict[str, Any]
    report_status: dict[str, Any]
    selected_status: dict[str, Any]
    agent_status: dict[str, Any] = Field(default_factory=dict)
    activity: dict[str, Any]
    debug_ref: dict[str, Any]


class RecommendationSessionPageStateOut(BaseModel):
    summary: RecommendationSessionSummaryOut
    bundle: RecommendationSessionBundleOut
    polling_hint: dict[str, Any]


@router.post("/candidates", response_model=RecommendationCandidateResponse)
def generate_recommendation_candidates(
    payload: RecommendationCandidateRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    existing_session = None
    temporary_input = (payload.temporary_input or "").strip()
    is_temporary_filter = bool(temporary_input)
    if payload.session_id is not None:
        ensure_recommendation_session_visible(db, current_user, payload.session_id)
        existing_session = _get_recommendation_session_or_404(db, payload.session_id)
        if existing_session["mode"] != payload.mode:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Session mode does not match the request mode.",
            )
        is_temporary_filter = _is_temporary_filter_session(existing_session)
        if temporary_input:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A temporary session already has its initial request; use user_message to refine it.",
            )

    if is_temporary_filter:
        if payload.buyer_intent_id is not None or payload.seller_target_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Temporary filtering cannot be combined with an existing recommendation anchor.",
            )
        anchor = (
            _temporary_anchor_from_session(existing_session)
            if existing_session is not None
            else _build_temporary_anchor(payload.mode, temporary_input)
        )
        session_anchor = {
            "buyer_intent_id": None,
            "buyer_party_id": None,
            "seller_target_id": None,
        }
    elif payload.mode == "buyer_to_target":
        if payload.buyer_intent_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Buyer intent anchor is required for this session.")
        ensure_entity_writable(db, current_user, entity_type="buyer_intent", entity_id=payload.buyer_intent_id)
        anchor = _get_buyer_intent_anchor(db, payload.buyer_intent_id)
        session_anchor = {
            "buyer_intent_id": payload.buyer_intent_id,
            "buyer_party_id": anchor.get("buyer_party_id"),
            "seller_target_id": None,
        }
    else:
        if payload.seller_target_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Seller target anchor is required for this session.")
        ensure_entity_writable(db, current_user, entity_type="seller_target", entity_id=payload.seller_target_id)
        anchor = _get_seller_target_anchor(db, payload.seller_target_id)
        session_anchor = {
            "buyer_intent_id": None,
            "buyer_party_id": None,
            "seller_target_id": payload.seller_target_id,
        }

    overrides: dict[str, Any] = {}
    if existing_session is not None:
        session_anchor_matches = (
            str(existing_session.get("buyer_intent_id") or "") == str(payload.buyer_intent_id or "")
            and str(existing_session.get("seller_target_id") or "") == str(payload.seller_target_id or "")
        )
        if not session_anchor_matches:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Session anchor does not match the requested intent/target.",
            )
        overrides = existing_session.get("condition_overrides_json") or {}

    # Condition-panel actions bypass the LLM parser entirely.
    panel_summary = None
    if payload.condition_actions and existing_session is not None:
        overrides, panel_summary = apply_condition_actions(overrides, payload.condition_actions)

    # Chat message -> structured extraction; routing is derived in code.
    parse_result = None
    user_message = (payload.user_message or "").strip()
    parser_input = user_message or temporary_input
    if parser_input:
        parse_result = parse_recommendation_message(
            db,
            mode=payload.mode,
            user_message=parser_input,
            current_conditions=conditions_snapshot(anchor, overrides) if payload.mode == "buyer_to_target" else {},
        )
        if payload.mode == "target_to_buyer" and parse_result["condition_ops"]:
            # v1 only supports structured overrides on the buyer_to_target flow;
            # keep the intent as a semantic preference so deep eval still sees it.
            described = describe_condition_ops(parse_result["condition_ops"])
            if described and described not in parse_result["semantic_preferences"]:
                parse_result["semantic_preferences"].append(described)
            parse_result["condition_ops"] = []
        overrides = merge_condition_overrides(overrides, parse_result)

    route = derive_route(parse_result)
    if panel_summary is not None:
        route = "refilter"  # panel actions always re-run the filter
    if existing_session is None:
        route = "refilter"  # first round always generates candidates

    effective_anchor = (
        apply_overrides_to_anchor(anchor, overrides) if payload.mode == "buyer_to_target" else anchor
    )
    semantic_preferences = list(overrides.get("semantic_preferences") or [])
    extra_query_lines = [line for line in [*semantic_preferences, parser_input or None] if line]

    disabled_scenarios = set(overrides.get("disabled_scenarios") or [])

    def run_filter() -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
        result = (
            _candidate_targets_for_intent(
                db,
                effective_anchor,
                payload.limit,
                disabled_scenarios,
                semantic_query_lines=extra_query_lines,
            )
            if payload.mode == "buyer_to_target"
            else _candidate_intents_for_target(
                db,
                effective_anchor,
                payload.limit,
                semantic_query_lines=extra_query_lines,
            )
        )
        return result["candidates"], result["funnel"], result.get("scenarios") or []

    candidates: list[dict[str, Any]] = []
    funnel: dict[str, Any] | None = None
    scenarios: list[dict[str, Any]] = []
    new_round = route in {"refilter", "re_evaluate"}
    if route == "refilter":
        candidates, funnel, scenarios = run_filter()
    elif route == "re_evaluate" and existing_session is not None:
        messages = _list_recommendation_messages(db, session_id=payload.session_id, limit=500, offset=0)
        candidates = _extract_recommendation_candidate_sets(messages)["initial_candidates"]
        if not candidates:
            candidates, funnel, scenarios = run_filter()
    elif existing_session is not None:
        # display / question / noop keep the current round; return it for context.
        messages = _list_recommendation_messages(db, session_id=payload.session_id, limit=500, offset=0)
        sets = _extract_recommendation_candidate_sets(messages)
        candidates = sets["reranked_candidates"] or sets["initial_candidates"]
    candidates = _enrich_candidates_for_frontend(candidates)
    candidates = _annotate_candidate_ownership(
        db,
        {"candidates": candidates},
        mode=payload.mode,
        current_user=current_user,
    )["candidates"]

    rerank_planned = new_round and payload.enable_rerank and len(candidates) > 1
    conversation = _build_conversation_payload(
        route=route,
        parse_result=parse_result,
        overrides=overrides,
        anchor=anchor,
        mode=payload.mode,
        candidate_count=len(candidates),
        rerank_requested=rerank_planned,
        panel_summary=panel_summary,
        funnel=funnel,
    )

    session_id = None
    rerank_job_id = None
    message_metadata = {"message_type": "initial_candidates"}
    if parse_result is not None:
        message_metadata["conversation"] = {
            "route": route,
            "parsed_ops": parse_result["condition_ops"],
            "semantic_preferences": parse_result["semantic_preferences"],
            "parser_status": parse_result["parser_status"],
        }

    if existing_session is not None:
        session_id = payload.session_id
        if user_message:
            _insert_recommendation_message(
                db,
                session_id=session_id,
                role="user",
                content_type="text",
                content=user_message,
                metadata_json=message_metadata.get("conversation") or {},
                created_by=current_user.user_id,
            )
        if new_round:
            _insert_recommendation_message(
                db,
                session_id=session_id,
                role="tool",
                content_type="json",
                content={
                    "message_type": "initial_candidates",
                    "mode": payload.mode,
                    "candidate_count": len(candidates),
                    "candidates": candidates,
                    "funnel": funnel,
                    "scenarios": scenarios,
                },
                metadata_json=message_metadata,
                created_by=current_user.user_id,
            )
            if payload.enable_rerank and len(candidates) > 1:
                rerank_job_id = _enqueue_recommendation_rerank_job(
                    db,
                    session_id=session_id,
                    mode=payload.mode,
                    anchor=effective_anchor,
                    candidates=candidates,
                    idempotency_suffix=uuid4().hex[:12],
                    metadata_json={"source": "recommendation_candidate_api_round"},
                    extra_query_lines=extra_query_lines,
                )
        if parse_result is not None or panel_summary is not None:
            # Persist the reply so restoring the session replays the whole chat.
            _insert_recommendation_message(
                db,
                session_id=session_id,
                role="assistant",
                content_type="text",
                content=conversation["system_reply"],
                metadata_json={"message_type": "system_reply", "route": route},
                created_by=current_user.user_id,
            )
        persist_session_overrides(db, session_id, overrides)
        _touch_recommendation_session(db, session_id)
        db.commit()
    elif payload.create_session:
        session_id = _create_recommendation_session(
            db,
            mode=payload.mode,
            user_message=parser_input,
            initial_snapshot=anchor,
            candidates=candidates,
            created_by=current_user.user_id,
            is_temporary_filter=is_temporary_filter,
            **session_anchor,
        )
        _insert_recommendation_message(
            db,
            session_id=session_id,
            role="tool",
            content_type="json",
            content={
                "message_type": "initial_candidates",
                "mode": payload.mode,
                "candidate_count": len(candidates),
                "candidates": candidates,
                "funnel": funnel,
                "scenarios": scenarios,
            },
            metadata_json=message_metadata,
            created_by=current_user.user_id,
        )
        if payload.enable_rerank and len(candidates) > 1:
            rerank_job_id = _enqueue_recommendation_rerank_job(
                db,
                session_id=session_id,
                mode=payload.mode,
                anchor=effective_anchor,
                candidates=candidates,
                extra_query_lines=extra_query_lines,
            )
        if parse_result is not None:
            _insert_recommendation_message(
                db,
                session_id=session_id,
                role="assistant",
                content_type="text",
                content=conversation["system_reply"],
                metadata_json={"message_type": "system_reply", "route": route},
                created_by=current_user.user_id,
            )
        if overrides != {} and any(overrides.get(key) for key in ("fields", "removed_fields", "extra_excluded_industries", "semantic_preferences")):
            persist_session_overrides(db, session_id, overrides)
        db.commit()

    return {
        "session_id": session_id,
        "mode": payload.mode,
        "candidates": candidates,
        "conversation": conversation,
        "funnel": funnel,
        "scenarios": scenarios,
        "debug": {
            "engine": "rule_v3_deep_eval" if rerank_job_id else "rule_v3",
            "rerank": bool(rerank_job_id),
            "rerank_job_id": str(rerank_job_id) if rerank_job_id else None,
            "route": route,
            "embedding_similarity": False,
            "funnel": funnel,
            "notes": [
                "Full-library scan with three-state screening; conflicts drop out, missing data never does.",
                "LLM deep eval runs asynchronously over the head of the optimistic ranking.",
            ],
        },
    }


def _describe_funnel(funnel: dict[str, int] | None, candidate_count: int) -> str:
    """Never let the deep-eval budget truncate silently: say what was left out."""
    if not funnel:
        return f"筛出 {candidate_count} 个候选。"
    eligible = funnel.get("eligible_count", candidate_count)
    deep_eval = funnel.get("deep_eval_count", candidate_count)
    text_value = f"全库扫描 {funnel.get('scan_count', 0)} 个，符合基础条件 {eligible} 个。"
    if eligible > deep_eval:
        text_value += f"本轮仅对前 {deep_eval} 个做 AI 深度评估，建议补充结构化条件以缩小范围。"
    return text_value


def _build_conversation_payload(
    *,
    route: str,
    parse_result: dict[str, Any] | None,
    overrides: dict[str, Any],
    anchor: dict[str, Any],
    mode: str,
    candidate_count: int,
    rerank_requested: bool,
    panel_summary: str | None = None,
    funnel: dict[str, int] | None = None,
) -> dict[str, Any]:
    parsed_ops = parse_result["condition_ops"] if parse_result else []
    new_preferences = parse_result["semantic_preferences"] if parse_result else []
    display_ops = parse_result["display_ops"] if parse_result else []

    if route == "refilter":
        parts = []
        if panel_summary:
            parts.append(f"已{panel_summary}。")
        if parsed_ops:
            parts.append(f"已更新条件：{describe_condition_ops(parsed_ops)}。")
        if new_preferences:
            parts.append(f"已记录偏好：{'；'.join(new_preferences)}。")
        parts.append(_describe_funnel(funnel, candidate_count))
        if rerank_requested:
            parts.append("AI 深度评估进行中，完成后自动重排并标注评级。")
        system_reply = "".join(parts)
    elif route == "re_evaluate":
        system_reply = (
            f"已记录偏好：{'；'.join(new_preferences) or '（无新增）'}。候选保持不变，"
            + ("AI 正按新偏好重新评级。" if rerank_requested else "候选不足，未触发重新评级。")
        )
    elif route == "display":
        system_reply = "已按要求调整当前展示。"
    elif route == "question":
        system_reply = "候选对比问答暂未上线：请结合卡片上的评级、AI 理由与详情链接查看；也可以继续补充筛选条件。"
    else:
        system_reply = "这句话里没有识别出可执行的筛选条件，已原样记录；可以说明行业、地区、利润等具体要求。"

    return {
        "route": route,
        "parsed_ops": parsed_ops,
        "new_semantic_preferences": new_preferences,
        "display_ops": display_ops,
        "question": parse_result.get("question") if parse_result else None,
        "parser_status": parse_result.get("parser_status") if parse_result else None,
        "applied_conditions": conditions_snapshot(anchor, overrides) if mode == "buyer_to_target" else {
            "semantic_preferences": list(overrides.get("semantic_preferences") or []),
        },
        "system_reply": system_reply,
    }


@router.post("/sessions", response_model=RecommendationSessionOut, status_code=status.HTTP_201_CREATED)
def create_recommendation_session(
    payload: RecommendationSessionCreate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _ensure_recommendation_anchor_writable(db, current_user, payload)
    row = db.execute(
        _session_returning_statement(
            """
            insert into recommendation_session (
              team_id, workspace_id, mode, buyer_intent_id, buyer_party_id,
              seller_target_id, anonymous_input_snapshot,
              initial_condition_snapshot_json, latest_condition_snapshot_json,
              created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, :mode, :buyer_intent_id, :buyer_party_id,
              :seller_target_id, :anonymous_input_snapshot,
              :initial_condition_snapshot_json, :latest_condition_snapshot_json,
              :created_by, :metadata_json
            )
            """
        ).bindparams(
            bindparam("initial_condition_snapshot_json", type_=JSONB),
            bindparam("latest_condition_snapshot_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "mode": payload.mode,
            "buyer_intent_id": payload.buyer_intent_id,
            "buyer_party_id": payload.buyer_party_id,
            "seller_target_id": payload.seller_target_id,
            "anonymous_input_snapshot": payload.anonymous_input_snapshot,
            "initial_condition_snapshot_json": payload.initial_condition_snapshot_json,
            "latest_condition_snapshot_json": payload.latest_condition_snapshot_json,
            "created_by": current_user.user_id,
            "metadata_json": payload.metadata_json,
        },
    ).mappings().one()
    db.commit()
    return dict(row)


@router.get("/sessions", response_model=list[RecommendationSessionOut])
def list_recommendation_sessions(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    mode: str | None = None,
    buyer_intent_id: UUID | None = None,
    seller_target_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    where = ["team_id = :team_id", "workspace_id = :workspace_id"]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
        "offset": offset,
    }
    if mode:
        where.append("mode = :mode")
        params["mode"] = mode
    if buyer_intent_id:
        where.append("buyer_intent_id = :buyer_intent_id")
        params["buyer_intent_id"] = buyer_intent_id
    if seller_target_id:
        where.append("seller_target_id = :seller_target_id")
        params["seller_target_id"] = seller_target_id
    if owner_scope_required(current_user):
        where.append(recommendation_session_visible_sql("recommendation_session"))
        params["scope_user_id"] = current_user.user_id

    rows = db.execute(
        text(
            f"""
            select {_session_select_columns()}
            from recommendation_session
            where {' and '.join(where)}
            order by updated_at desc, created_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


@router.get("/sessions/recent", response_model=list[RecommendationSessionSummaryOut])
def list_recent_recommendation_session_summaries(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    mode: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern="^(all|running|failed|generated|selected|idle)$",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=500),
    preview_limit: int = Query(default=3, ge=0, le=20),
) -> list[dict[str, Any]]:
    scan_limit = min(200, max(limit + offset, limit * 4))
    rows = _list_recommendation_session_overview_rows(
        db,
        current_user=current_user,
        mode=mode,
        limit=scan_limit,
        offset=0,
        q=q,
    )
    summaries = [
        _build_recommendation_session_summary(db, session=row, preview_limit=preview_limit) for row in rows
    ]
    filtered = _filter_recommendation_session_summaries(summaries, status_filter)
    return filtered[offset : offset + limit]


@router.get("/page", response_model=RecommendationPageOut)
def get_recommendation_page(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    mode: str | None = None,
    limit: int = Query(default=12, ge=1, le=50),
) -> dict[str, Any]:
    recent_rows = _list_recommendation_session_overview_rows(
        db,
        current_user=current_user,
        mode=mode,
        limit=limit,
        offset=0,
    )
    recent_summaries = [
        _build_recommendation_session_summary(db, session=row, preview_limit=5) for row in recent_rows
    ]

    recent_ids = {str(summary["session"]["id"]) for summary in recent_summaries}
    running_summaries = [
        summary for summary in recent_summaries if _recommendation_session_is_processing(summary)
    ]
    for session_id in _list_running_recommendation_session_ids(db, current_user=current_user, limit=20):
        if str(session_id) in recent_ids:
            continue
        row = _get_recommendation_session_overview_or_404(db, session_id)
        ensure_recommendation_session_visible(db, current_user, session_id)
        if mode and row.get("mode") != mode:
            continue
        running_summaries.append(_build_recommendation_session_summary(db, session=row, preview_limit=5))

    overview = _recommendation_page_overview(recent_summaries, running_summaries)
    return {
        "recent_sessions": recent_summaries,
        "running_sessions": running_summaries,
        "overview": overview,
        "quick_actions": _recommendation_quick_actions(overview),
        "polling_hint": {
            "enabled": overview["running_session_count"] > 0,
            "interval_ms": 3000,
            "endpoint_template": "/api/v1/recommendations/sessions/{session_id}/page-state",
            "status_endpoint_template": "/api/v1/recommendations/sessions/{session_id}/status",
            "bundle_endpoint_template": "/api/v1/recommendations/sessions/{session_id}/bundle",
        },
    }


@router.get("/sessions/{session_id}", response_model=RecommendationSessionOut)
def get_recommendation_session(
    session_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_recommendation_session_visible(db, current_user, session_id)
    return _get_recommendation_session_or_404(db, session_id)


@router.get("/sessions/{session_id}/status", response_model=RecommendationSessionStatusOut)
def get_recommendation_session_status(
    session_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    preview_limit: int = Query(default=8, ge=0, le=50),
) -> dict[str, Any]:
    ensure_recommendation_session_visible(db, current_user, session_id)
    session = _get_recommendation_session_overview_or_404(db, session_id)
    return _build_recommendation_session_summary(db, session=session, preview_limit=preview_limit)


@router.get("/sessions/{session_id}/bundle", response_model=RecommendationSessionBundleOut)
def get_recommendation_session_bundle(
    session_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    include_canceled: bool = Query(default=True),
) -> dict[str, Any]:
    ensure_recommendation_session_visible(db, current_user, session_id)
    return _build_recommendation_session_bundle(
        db,
        session_id=session_id,
        include_canceled=include_canceled,
        current_user=current_user,
    )


@router.get("/sessions/{session_id}/page-state", response_model=RecommendationSessionPageStateOut)
def get_recommendation_session_page_state(
    session_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    include_canceled: bool = Query(default=True),
    preview_limit: int = Query(default=8, ge=0, le=50),
) -> dict[str, Any]:
    ensure_recommendation_session_visible(db, current_user, session_id)
    session = _get_recommendation_session_overview_or_404(db, session_id)
    summary = _build_recommendation_session_summary(db, session=session, preview_limit=preview_limit)
    bundle = _build_recommendation_session_bundle(
        db,
        session_id=session_id,
        include_canceled=include_canceled,
        current_user=current_user,
    )
    return {
        "summary": summary,
        "bundle": bundle,
        "polling_hint": _recommendation_session_polling_hint(summary, session_id=session_id),
    }


class RecommendationAgentTurnRequest(BaseModel):
    mode: str = Field(pattern="^(buyer_to_target)$")
    session_id: UUID | None = None
    # 一段需求原文，或后续对话里的补充。上传的需求文件由前端取正文后走同一个字段。
    user_message: str = Field(min_length=1, max_length=AGENT_INPUT_MAX_CHARS)
    # 图片没有正文可以先取出来给用户看，所以只传 id，由 worker 交给多模态模型直读。
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=AGENT_MAX_IMAGE_ATTACHMENTS)


class RecommendationAgentTurnOut(BaseModel):
    session_id: UUID
    turn_id: str
    job_id: UUID
    queue_name: str


@router.post(
    "/agent-turn",
    response_model=RecommendationAgentTurnOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_recommendation_agent_turn(
    payload: RecommendationAgentTurnRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Start one agent turn. Returns immediately; progress arrives by polling.

    A session created here has no anchor entity by design — the whole point of
    the page is that the consultant does not have to create a buyer intent
    first. The temporary-filter flag rides along so the existing guards keep
    relations from ever being created out of one.
    """
    user_message = payload.user_message.strip()
    if not user_message:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_message is required.")

    if payload.session_id is not None:
        ensure_recommendation_session_visible(db, current_user, payload.session_id)
        session = _get_recommendation_session_or_404(db, payload.session_id)
        if session["mode"] != payload.mode:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Session mode does not match the request mode.",
            )
        session_id = payload.session_id
    else:
        session_id = _create_recommendation_session(
            db,
            mode=payload.mode,
            buyer_intent_id=None,
            buyer_party_id=None,
            seller_target_id=None,
            user_message=None,
            # 开场那句话也落进 anonymous_input_snapshot：会话搜索匹配的就是这一列。
            # 走 input_snapshot_only 而不是 user_message —— 后者会顺手再插一条
            # 消息，而这一轮的用户消息由下面带着 turn_id 自己写。
            input_snapshot_only=user_message,
            initial_snapshot={"agent_session": True, "first_message": user_message},
            candidates=[],
            created_by=current_user.user_id,
            is_temporary_filter=True,
        )

    # turn_id 先生成：用户消息也带上它，这一轮的问题和它的回答才有明确归属，
    # 「中止的轮次不进上下文」也才有得判断。
    turn_id = uuid4().hex
    history_context = agent_history_context(db, session_id)
    _insert_recommendation_message(
        db,
        session_id=session_id,
        role="user",
        content_type="text",
        content=user_message,
        metadata_json={"message_type": "agent_user_message", "turn_id": turn_id},
        created_by=current_user.user_id,
    )
    job_id = _enqueue_recommendation_agent_job(
        db,
        session_id=session_id,
        mode=payload.mode,
        turn_id=turn_id,
        user_message=user_message,
        history_context=history_context,
        attachment_ids=[str(value) for value in payload.attachment_ids],
        created_by=current_user.user_id,
    )
    _touch_recommendation_session(db, session_id)
    db.commit()
    return {
        "session_id": session_id,
        "turn_id": turn_id,
        "job_id": job_id,
        "queue_name": "llm",
    }


JOB_STATUS_MESSAGES = {
    "stale_running_job": "这一轮跑得太久被系统回收了。可以重试，或把需求说得更具体一些。",
}
DEFAULT_TURN_FAILURE_MESSAGE = "这一轮没能跑完。"


@router.get("/sessions/{session_id}/turns/{turn_id}/status")
def get_recommendation_agent_turn_status(
    session_id: UUID,
    turn_id: str,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Whether this turn is still working, and if not, why it stopped.

    Polling the message table alone cannot tell "thinking" from "dead": a job
    that fails writes no message, so the page would spin until its own timeout.
    Scoped by session visibility rather than admin, because the person who has
    to read this is the consultant whose recommendation just failed.
    """
    ensure_recommendation_session_visible(db, current_user, session_id)
    _get_recommendation_session_or_404(db, session_id)

    job = find_agent_turn_job(db, session_id, turn_id)
    job_status = str((job or {}).get("status") or "missing")
    failed = job_status in {"failed", "cancelled"}
    error_code = str((job or {}).get("error_code") or "") or None
    return {
        "session_id": str(session_id),
        "turn_id": turn_id,
        "job_status": job_status,
        "failed": failed,
        "aborted": agent_turn_aborted(db, session_id, turn_id),
        "error_code": error_code,
        "error_message": (
            JOB_STATUS_MESSAGES.get(error_code or "", DEFAULT_TURN_FAILURE_MESSAGE)
            if failed
            else None
        ),
        # 原始错误只给管理员：顾问看到的是上面那句人话。
        "error_detail": str((job or {}).get("error_message") or "") or None
        if failed and current_user.is_admin
        else None,
    }


@router.post(
    "/sessions/{session_id}/turns/{turn_id}/abort",
    status_code=status.HTTP_202_ACCEPTED,
)
def abort_recommendation_agent_turn(
    session_id: UUID,
    turn_id: str,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Stop one agent turn wherever it happens to be.

    The marker is written here, immediately, rather than by whichever process
    is running — the tab may be closing, and a stop the database never heard
    about would come back as context on the next turn.
    """
    ensure_recommendation_session_visible(db, current_user, session_id)
    _get_recommendation_session_or_404(db, session_id)
    if not agent_turn_aborted(db, session_id, turn_id):
        insert_agent_aborted_message(
            db,
            session_id=session_id,
            turn_id=turn_id,
            created_by=current_user.user_id,
        )
        _touch_recommendation_session(db, session_id)
        db.commit()
    return {"session_id": str(session_id), "turn_id": turn_id, "aborted": True}


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/sessions/{session_id}/turns/{turn_id}/answer-stream")
def stream_recommendation_answer(
    session_id: UUID,
    turn_id: str,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream the final write-up for one agent turn.

    This is the only streamed call in the system, and it is streamed here in
    the API rather than in the worker because there is no worker→browser
    channel (the queue is a Postgres table; there is no Redis). Everything the
    generator needs is read *before* the response is returned: the request
    session closes as soon as this function returns, so the generator opens its
    own session for the final write.
    """
    ensure_recommendation_session_visible(db, current_user, session_id)
    _get_recommendation_session_or_404(db, session_id)

    if agent_turn_aborted(db, session_id, turn_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This turn was stopped.",
        )

    existing = find_agent_turn_answer(db, session_id, turn_id)
    if existing is not None:
        replay = existing
        return StreamingResponse(
            iter([
                _sse("delta", {"text": replay["markdown"]}),
                _sse(
                    "done",
                    {
                        "markdown": replay["markdown"],
                        "message_id": str(replay["id"]),
                        "duration_ms": int(replay.get("duration_ms") or 0),
                        "replayed": True,
                    },
                ),
            ]),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    brief = find_agent_turn_brief(db, session_id, turn_id)
    if brief is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This turn has no writer brief yet; the agent may still be running.",
        )

    node_name = recommendation_answer_writer_node_by_mode().get(str(brief.get("mode") or ""))
    node_config = None
    if node_name:
        try:
            node_config = _get_default_node_config(db, node_name)
        except Exception:
            node_config = None

    link_map = target_link_map(brief)

    def turn_aborted_now() -> bool:
        # The request-scoped session is already closed once the generator runs.
        # A fresh read is required so a stop from this or another tab becomes
        # visible while the Writer stream is in flight.
        with session_scope() as check_db:
            return agent_turn_aborted(check_db, session_id, turn_id)

    def aborted_event() -> str:
        return _sse("aborted", {"turn_id": turn_id, "message": "This turn was stopped."})

    def persist(markdown: str, *, mode: str, duration_ms: int) -> str | None:
        # 独立 session：请求的那个已经随函数返回关掉了。
        with session_scope() as write_db:
            message_id = insert_agent_answer_message(
                write_db,
                session_id=session_id,
                turn_id=turn_id,
                markdown=markdown,
                model_name=(node_config or {}).get("model_name"),
                generation_mode=mode,
                duration_ms=duration_ms,
            )
            if message_id is not None:
                _touch_recommendation_session(write_db, session_id)
        return str(message_id) if message_id is not None else None

    def generate():
        writer_started = time.perf_counter()

        def writer_duration_ms() -> int:
            # Measures the whole Writer SSE stage through the final chunk (or
            # rule fallback), not merely time-to-first-token.
            return max(0, int((time.perf_counter() - writer_started) * 1000))

        if turn_aborted_now():
            yield aborted_event()
            return
        if node_config is None:
            markdown = backfill_target_links(fallback_answer_markdown(brief), link_map)
            if turn_aborted_now():
                yield aborted_event()
                return
            yield _sse("delta", {"text": markdown})
            duration_ms = writer_duration_ms()
            message_id = persist(markdown, mode="fallback", duration_ms=duration_ms)
            if message_id is None:
                yield aborted_event()
                return
            yield _sse(
                "done",
                {"markdown": markdown, "message_id": message_id, "duration_ms": duration_ms},
            )
            return

        chunks: list[str] = []
        try:
            for delta in stream_openai_compatible_chat(
                base_url=node_config["base_url"],
                api_key_secret_ref=node_config["api_key_secret_ref"],
                api_key_encrypted=node_config.get("api_key_encrypted"),
                model_name=node_config["model_name"],
                messages=_render_prompt_messages(node_config, build_answer_prompt_variables(brief)),
                temperature=node_config["temperature"],
                top_p=node_config["top_p"],
                max_tokens=node_config["max_tokens"],
                timeout_seconds=node_config["timeout_seconds"] or 180,
            ):
                if turn_aborted_now():
                    yield aborted_event()
                    return
                chunks.append(delta)
                yield _sse("delta", {"text": delta})
        except Exception as exc:  # noqa: BLE001 - 生成失败要给出可用兜底，不是空页面
            if turn_aborted_now():
                yield aborted_event()
                return
            markdown = backfill_target_links(fallback_answer_markdown(brief), link_map)
            yield _sse("error", {"message": str(exc)})
            yield _sse("delta", {"text": markdown})
            duration_ms = writer_duration_ms()
            message_id = persist(markdown, mode="fallback", duration_ms=duration_ms)
            if message_id is None:
                yield aborted_event()
                return
            yield _sse(
                "done",
                {"markdown": markdown, "message_id": message_id, "duration_ms": duration_ms},
            )
            return

        # 回填放在落库这一步：流式增量里做替换要处理跨 chunk 的半个名字，
        # 而前端在 done 事件里拿到的就是最终带链接的正文。
        markdown = sanitize_writer_output(
            "".join(chunks),
            forbidden_ids=list(link_map.values()),
            forbidden_phrases=[str(value) for value in brief.get("follow_up_suggestions") or []],
        )
        if not markdown:
            markdown = fallback_answer_markdown(brief)
            generation_mode = "fallback"
        else:
            generation_mode = "llm"
        markdown = backfill_target_links(markdown, link_map)
        if turn_aborted_now():
            yield aborted_event()
            return
        duration_ms = writer_duration_ms()
        message_id = persist(markdown, mode=generation_mode, duration_ms=duration_ms)
        if message_id is None:
            yield aborted_event()
            return
        yield _sse(
            "done",
            {"markdown": markdown, "message_id": message_id, "duration_ms": duration_ms},
        )

    return StreamingResponse(generate(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post(
    "/sessions/{session_id}/rerank-jobs",
    response_model=RecommendationRerankJobOut,
    status_code=status.HTTP_201_CREATED,
)
def create_recommendation_rerank_job(
    session_id: UUID,
    payload: RecommendationRerankJobCreate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_recommendation_session_visible(db, current_user, session_id)
    session = _get_recommendation_session_or_404(db, session_id)
    if session["mode"] not in {"buyer_to_target", "target_to_buyer"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported recommendation mode.")

    anchor = _get_rerank_anchor_for_session(db, session)
    messages = _list_recommendation_messages(db, session_id=session_id, limit=500, offset=0)
    candidate_sets = _extract_recommendation_candidate_sets(messages)
    candidates = _normalize_candidates(payload.candidates or candidate_sets["initial_candidates"])
    source = "request" if payload.candidates is not None else "initial_candidates"
    if len(candidates) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least two candidates are required to rerank a recommendation session.",
        )

    job_id = _enqueue_recommendation_rerank_job(
        db,
        session_id=session_id,
        mode=str(session["mode"]),
        anchor=anchor,
        candidates=candidates,
        idempotency_suffix=str(uuid4()),
        metadata_json={
            "source": "recommendation_rerank_job_api",
            "rerank_reason": payload.reason,
            "candidate_source": source,
        },
    )
    db.commit()
    return {
        "job_id": job_id,
        "job_status": "queued",
        "queue_name": "llm",
        "candidate_count": len(candidates),
        "source": source,
    }


@router.get("/sessions/{session_id}/messages", response_model=list[RecommendationMessageOut])
def list_recommendation_messages(
    session_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    ensure_recommendation_session_visible(db, current_user, session_id)
    _get_recommendation_session_or_404(db, session_id)
    return _list_recommendation_messages(db, session_id=session_id, limit=limit, offset=offset)


@router.post(
    "/sessions/{session_id}/messages",
    response_model=RecommendationMessageOut,
    status_code=status.HTTP_201_CREATED,
)
def create_recommendation_message(
    session_id: UUID,
    payload: RecommendationMessageCreate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_recommendation_session_visible(db, current_user, session_id)
    _get_recommendation_session_or_404(db, session_id)
    row = db.execute(
        _message_returning_statement(
            """
            insert into recommendation_message (
              team_id, workspace_id, session_id, role, content,
              content_type, metadata_json, created_by
            )
            values (
              :team_id, :workspace_id, :session_id, :role, :content,
              :content_type, :metadata_json, :created_by
            )
            """
        ).bindparams(bindparam("metadata_json", type_=JSONB)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "session_id": session_id,
            "role": payload.role,
            "content": payload.content,
            "content_type": payload.content_type,
            "metadata_json": payload.metadata_json,
            "created_by": current_user.user_id,
        },
    ).mappings().one()
    _touch_recommendation_session(db, session_id)
    db.commit()
    return dict(row)


@router.post(
    "/sessions/{session_id}/selected-items",
    response_model=RecommendationSelectedItemOut,
    status_code=status.HTTP_201_CREATED,
)
def create_selected_item(
    session_id: UUID,
    payload: RecommendationSelectedItemCreate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_recommendation_session_visible(db, current_user, session_id)
    session = _get_recommendation_session_or_404(db, session_id)
    _ensure_session_is_not_temporary_filter(session)
    _ensure_selected_item_matches_session(session, payload)
    _ensure_selected_item_allowed_from_session_candidates(db, current_user, session_id, payload)
    existing = _get_active_selected_item_for_pair(
        db,
        session_id=session_id,
        buyer_intent_id=payload.buyer_intent_id,
        seller_target_id=payload.seller_target_id,
    )
    if existing is not None:
        return existing

    row = db.execute(
        _selected_item_returning_statement(
            """
            insert into recommendation_selected_item (
              team_id, workspace_id, session_id, mode, seller_target_id,
              buyer_intent_id, buyer_party_id, rank_at_selection,
              recommendation_level, match_summary, risk_summary, gap_summary,
              reason_snapshot, evidence_snapshot_json, selected_by, metadata_json
            )
            values (
              :team_id, :workspace_id, :session_id, :mode, :seller_target_id,
              :buyer_intent_id, :buyer_party_id, :rank_at_selection,
              :recommendation_level, :match_summary, :risk_summary, :gap_summary,
              :reason_snapshot, :evidence_snapshot_json, :selected_by, :metadata_json
            )
            """
        ).bindparams(
            bindparam("evidence_snapshot_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "session_id": session_id,
            "mode": payload.mode,
            "seller_target_id": payload.seller_target_id,
            "buyer_intent_id": payload.buyer_intent_id,
            "buyer_party_id": payload.buyer_party_id,
            "rank_at_selection": payload.rank_at_selection,
            "recommendation_level": payload.recommendation_level,
            "match_summary": payload.match_summary,
            "risk_summary": payload.risk_summary,
            "gap_summary": payload.gap_summary,
            "reason_snapshot": payload.reason_snapshot,
            "evidence_snapshot_json": payload.evidence_snapshot_json,
            "selected_by": current_user.user_id,
            "metadata_json": payload.metadata_json,
        },
    ).mappings().one()
    selected_item = dict(row)
    _refresh_session_selected_count(db, session_id)
    db.commit()
    return selected_item


@router.get("/selected-items", response_model=list[RecommendationSelectedItemOut])
def list_all_selected_items(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    session_id: UUID | None = None,
    buyer_intent_id: UUID | None = None,
    seller_target_id: UUID | None = None,
    relation_id: UUID | None = None,
    include_canceled: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    where = ["ri.team_id = :team_id", "ri.workspace_id = :workspace_id"]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
        "offset": offset,
    }
    if session_id:
        where.append("ri.session_id = :session_id")
        params["session_id"] = session_id
    if buyer_intent_id:
        where.append("ri.buyer_intent_id = :buyer_intent_id")
        params["buyer_intent_id"] = buyer_intent_id
    if seller_target_id:
        where.append("ri.seller_target_id = :seller_target_id")
        params["seller_target_id"] = seller_target_id
    if relation_id:
        where.append("ri.metadata_json ->> 'relation_id' = :relation_id")
        params["relation_id"] = str(relation_id)
    if not include_canceled:
        where.append("ri.canceled_at is null")
    if owner_scope_required(current_user):
        where.append(
            f"""
            exists (
              select 1
              from recommendation_session scope_rs
              where scope_rs.id = ri.session_id
                and {recommendation_session_visible_sql("scope_rs")}
            )
            """
        )
        params["scope_user_id"] = current_user.user_id

    rows = db.execute(
        text(
            f"""
            select {_selected_item_select_columns()}
            from recommendation_selected_item ri
            left join seller_target st on st.id = ri.seller_target_id
            left join buyer_intent bi on bi.id = ri.buyer_intent_id
            left join buyer_party bp on bp.id = ri.buyer_party_id
            where {' and '.join(where)}
            order by ri.selected_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


@router.get("/sessions/{session_id}/selected-items", response_model=list[RecommendationSelectedItemOut])
def list_selected_items(
    session_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    include_canceled: bool = Query(default=False),
) -> list[dict[str, Any]]:
    ensure_recommendation_session_visible(db, current_user, session_id)
    _get_recommendation_session_or_404(db, session_id)
    return _list_selected_items(
        db,
        session_id=session_id,
        include_canceled=include_canceled,
        limit=500,
        offset=0,
    )


@router.post(
    "/sessions/{session_id}/reports",
    response_model=RecommendationReportOut,
    status_code=status.HTTP_201_CREATED,
)
def create_recommendation_report(
    session_id: UUID,
    payload: RecommendationReportCreate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_recommendation_session_visible(db, current_user, session_id)
    session = _get_recommendation_session_or_404(db, session_id)
    _ensure_session_is_not_temporary_filter(session)
    selected_items = _list_selected_items_for_report(
        db,
        session_id=session_id,
        selected_item_ids=payload.selected_item_ids,
    )
    try:
        ensure_report_item_count(selected_items)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    report_type = payload.report_type or default_report_type(session["mode"])
    if not report_type_matches_mode(report_type, session["mode"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Report type does not match the recommendation session mode.",
        )
    title = (payload.title or "").strip() or default_report_title(
        session,
        selected_items=selected_items,
        report_type=report_type,
    )
    report_context = build_recommendation_report_context(
        db,
        report={"id": "", "report_type": report_type, "title": title},
        session=session,
        selected_items=selected_items,
    )
    markdown_content = build_fallback_report_markdown(report_context, title=title)
    selected_item_ids_json = [str(item["id"]) for item in selected_items]
    row = db.execute(
        _report_returning_statement(
            """
            insert into recommendation_report (
              team_id, workspace_id, session_id, report_type, selected_item_ids_json,
              title, markdown_content, file_format, status,
              generated_by_model, prompt_version, created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, :session_id, :report_type, :selected_item_ids_json,
              :title, :markdown_content, 'markdown', 'generated',
              :generated_by_model, :prompt_version, :created_by, :metadata_json
            )
            """
        ).bindparams(
            bindparam("selected_item_ids_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "session_id": session_id,
            "report_type": report_type,
            "selected_item_ids_json": selected_item_ids_json,
            "title": title,
            "markdown_content": markdown_content,
            "generated_by_model": "rule_template_v0",
            "prompt_version": None,
            "created_by": current_user.user_id,
            "metadata_json": {
                **payload.metadata_json,
                "source": "recommendation_report_api",
                "selected_item_count": len(selected_items),
                "generation_mode": "fallback",
                "report_context_version": report_context["schema_version"],
            },
        },
    ).mappings().one()
    report = dict(row)
    _insert_recommendation_message(
        db,
        session_id=session_id,
        role="assistant",
        content_type="markdown",
        content=markdown_content,
        metadata_json={"report_id": str(report["id"]), "message_type": "recommendation_report"},
        created_by=current_user.user_id,
    )
    _refresh_session_report_count(db, session_id)
    db.commit()
    return report


@router.post(
    "/sessions/{session_id}/reports/jobs",
    response_model=RecommendationReportJobOut,
    status_code=status.HTTP_201_CREATED,
)
def create_recommendation_report_job(
    session_id: UUID,
    payload: RecommendationReportCreate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_recommendation_session_visible(db, current_user, session_id)
    session = _get_recommendation_session_or_404(db, session_id)
    _ensure_session_is_not_temporary_filter(session)
    selected_items = _list_selected_items_for_report(
        db,
        session_id=session_id,
        selected_item_ids=payload.selected_item_ids,
    )
    try:
        ensure_report_item_count(selected_items)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    report_type = payload.report_type or default_report_type(session["mode"])
    if not report_type_matches_mode(report_type, session["mode"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Report type does not match the recommendation session mode.",
        )
    title = (payload.title or "").strip() or default_report_title(
        session,
        selected_items=selected_items,
        report_type=report_type,
    )
    report_context = build_recommendation_report_context(
        db,
        report={"id": "", "report_type": report_type, "title": title},
        session=session,
        selected_items=selected_items,
    )
    fallback_markdown = build_fallback_report_markdown(report_context, title=title)
    selected_item_ids_json = [str(item["id"]) for item in selected_items]
    report_row = db.execute(
        _report_returning_statement(
            """
            insert into recommendation_report (
              team_id, workspace_id, session_id, report_type, selected_item_ids_json,
              title, markdown_content, file_format, status,
              generated_by_model, prompt_version, created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, :session_id, :report_type, :selected_item_ids_json,
              :title, :markdown_content, 'markdown', 'generating',
              'rule_template_v0', null, :created_by, :metadata_json
            )
            """
        ).bindparams(
            bindparam("selected_item_ids_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "session_id": session_id,
            "report_type": report_type,
            "selected_item_ids_json": selected_item_ids_json,
            "title": title,
            "markdown_content": fallback_markdown,
            "created_by": current_user.user_id,
            "metadata_json": {
                **payload.metadata_json,
                "source": "recommendation_report_job_api",
                "selected_item_count": len(selected_items),
                "generation_mode": "queued",
                "fallback_ready": True,
                "report_context_version": report_context["schema_version"],
            },
        },
    ).mappings().one()
    report = dict(report_row)
    job_id = _enqueue_recommendation_report_job(
        db,
        report_id=report["id"],
        session_id=session_id,
        selected_item_ids=selected_item_ids_json,
    )
    _refresh_session_report_count(db, session_id)
    db.commit()
    return {
        "report": report,
        "job_id": job_id,
        "job_status": "queued",
        "queue_name": "llm",
    }


@router.get("/sessions/{session_id}/reports", response_model=list[RecommendationReportOut])
def list_recommendation_reports(
    session_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    ensure_recommendation_session_visible(db, current_user, session_id)
    _get_recommendation_session_or_404(db, session_id)
    return _list_recommendation_reports(db, session_id=session_id, limit=limit, offset=offset)


@router.get("/reports/{report_id}", response_model=RecommendationReportOut)
def get_recommendation_report(
    report_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _ensure_recommendation_report_visible(db, current_user, report_id)
    row = db.execute(
        text(
            f"""
            select {_report_select_columns()}
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation report not found.")
    return dict(row)


@router.get("/reports/{report_id}/docx")
def download_recommendation_report_docx(
    report_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> Response:
    _ensure_recommendation_report_visible(db, current_user, report_id)
    row = db.execute(
        text(
            """
            select title, markdown_content
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation report not found.",
        )
    markdown_content = str(row.get("markdown_content") or "").strip()
    if not markdown_content:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Recommendation report content is not ready.",
        )

    title = str(row.get("title") or "推荐报告")
    content = render_report_docx(markdown_content, title=title)
    filename = safe_docx_filename(title)
    return Response(
        content=content,
        media_type=DOCX_MEDIA_TYPE,
        headers={
            "Content-Disposition": (
                'attachment; filename="recommendation-report.docx"; '
                f"filename*=UTF-8''{quote(filename, safe='')}"
            ),
            "Content-Length": str(len(content)),
        },
    )


@router.post("/selected-items/{selected_item_id}/cancel", response_model=RecommendationSelectedItemOut)
def cancel_selected_item(
    selected_item_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    current = _get_selected_item_or_404(db, selected_item_id)
    ensure_recommendation_session_visible(db, current_user, current["session_id"])
    if owner_scope_required(current_user) and current.get("selected_by") != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only remove recommendation items that you selected.",
        )
    if current["canceled_at"] is not None:
        return current
    row = db.execute(
        _selected_item_returning_statement(
            """
            update recommendation_selected_item
            set canceled_at = now(),
                canceled_by = :canceled_by
            where id = :selected_item_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "selected_item_id": selected_item_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "canceled_by": current_user.user_id,
        },
    ).mappings().one()
    _refresh_session_selected_count(db, row["session_id"])
    db.commit()
    return dict(row)


# Region groups let phrases like 长三角 in region_scope_summary match concrete
# provinces. Province names are stored without 省/市 suffixes.

# Score caps: hard mismatches and exclusion hits sink candidates instead of
# deleting them (business rule: never hide an opportunity, but label it).


def _ensure_recommendation_anchor_writable(
    db: Session,
    current_user: CurrentUser,
    payload: RecommendationSessionCreate,
) -> None:
    if payload.buyer_intent_id:
        ensure_entity_writable(db, current_user, entity_type="buyer_intent", entity_id=payload.buyer_intent_id)
    if payload.buyer_party_id:
        ensure_entity_writable(db, current_user, entity_type="buyer_party", entity_id=payload.buyer_party_id)
    if payload.seller_target_id:
        ensure_entity_writable(db, current_user, entity_type="seller_target", entity_id=payload.seller_target_id)
    if payload.mode == "buyer_to_target" and not (payload.buyer_intent_id or payload.buyer_party_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Buyer anchor is required.")
    if payload.mode == "target_to_buyer" and not payload.seller_target_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Seller target anchor is required.")


def _ensure_session_is_not_temporary_filter(session: dict[str, Any]) -> None:
    if _is_temporary_filter_session(session):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Temporary recommendation results are read-only. Select an existing buyer intent or seller target before adding candidates or starting progress.",
        )


def _ensure_selected_item_matches_session(
    session: dict[str, Any],
    payload: RecommendationSelectedItemCreate,
) -> None:
    if payload.mode != session["mode"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected item mode does not match session.")
    if session["mode"] == "buyer_to_target":
        if not payload.seller_target_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="seller_target_id is required.")
        if session.get("buyer_intent_id") and payload.buyer_intent_id != session["buyer_intent_id"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected buyer intent does not match session anchor.",
            )
    if session["mode"] == "target_to_buyer":
        if not payload.buyer_intent_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="buyer_intent_id is required.")
        if session.get("seller_target_id") and payload.seller_target_id != session["seller_target_id"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected seller target does not match session anchor.",
            )


def _ensure_selected_item_allowed_from_session_candidates(
    db: Session,
    current_user: CurrentUser,
    session_id: UUID,
    payload: RecommendationSelectedItemCreate,
) -> None:
    if not owner_scope_required(current_user):
        return
    requested_key = _candidate_pair_key(payload.model_dump())
    messages = _list_recommendation_messages(db, session_id=session_id, limit=500, offset=0)
    candidate_sets = _extract_recommendation_candidate_sets(messages)
    allowed_keys = {
        _candidate_pair_key(candidate)
        for candidate in [
            *candidate_sets["initial_candidates"],
            *candidate_sets["reranked_candidates"],
        ]
    }
    if requested_key not in allowed_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Selected item must come from this recommendation session's generated candidates.",
        )
    if payload.mode == "buyer_to_target" and payload.seller_target_id:
        ensure_entity_writable(
            db,
            current_user,
            entity_type="seller_target",
            entity_id=payload.seller_target_id,
        )
    if payload.mode == "target_to_buyer" and payload.buyer_intent_id:
        ensure_entity_writable(
            db,
            current_user,
            entity_type="buyer_intent",
            entity_id=payload.buyer_intent_id,
        )


