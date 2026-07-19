from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser
from backend.app.api.routes.utils import (
    ensure_entity_writable,
    ensure_recommendation_session_visible,
    owner_scope_required,
    recommendation_report_visible_sql,
    recommendation_session_visible_sql,
)
from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db
from backend.app.services.recommendation_flow import (  # noqa: F401 - re-exported for compatibility
    DEEP_EVAL_CANDIDATE_LIMIT,
    EXCLUDED_HIT_CAP,
    HARD_MISMATCH_CAP_BASE,
    REGION_GROUPS,
    UNKNOWN_DIMENSION_CREDIT,
    _apply_score_caps,
    _build_recommendation_activity,
    _build_recommendation_report_markdown,
    _build_recommendation_report_status,
    _build_recommendation_rerank_status,
    _build_recommendation_selected_status,
    _build_recommendation_session_bundle,
    _build_recommendation_session_summary,
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
    _create_recommendation_session,
    _default_report_title,
    _default_report_type,
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
    _get_existing_recommendation_relation,
    _get_latest_recommendation_rerank_job,
    _get_or_create_recommendation_relation,
    _get_recommendation_report_jobs,
    _get_recommendation_session_or_404,
    _get_recommendation_session_overview_or_404,
    _get_rerank_anchor_for_session,
    _get_selected_item_or_404,
    _get_seller_target_anchor,
    _infer_recommendation_candidate_message_type,
    _insert_recommendation_message,
    _insert_recommendation_relation_event,
    _insert_selected_item_cancel_event,
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
    _sync_selected_item_to_relation,
    _touch_recommendation_session,
    _with_frontend_candidate_fields,
    _yes_like,
)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


class RecommendationCandidateRequest(BaseModel):
    mode: str = Field(pattern="^(buyer_to_target|target_to_buyer)$")
    buyer_intent_id: UUID | None = None
    seller_target_id: UUID | None = None
    limit: int = Field(default=20, ge=1, le=50)
    create_session: bool = True
    enable_rerank: bool = True
    user_message: str | None = None
    # Continue an existing session (multi-round chat): append the user message
    # and a new candidate round instead of creating a new session.
    session_id: UUID | None = None

    @model_validator(mode="after")
    def validate_anchor(self) -> "RecommendationCandidateRequest":
        if self.mode == "buyer_to_target" and self.buyer_intent_id is None:
            raise ValueError("buyer_intent_id is required for buyer_to_target.")
        if self.mode == "target_to_buyer" and self.seller_target_id is None:
            raise ValueError("seller_target_id is required for target_to_buyer.")
        return self


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
    report_type: str | None = Field(default=None, pattern="^(buyer_facing_target_report|internal_buyer_list)$")
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
    if payload.mode == "buyer_to_target":
        ensure_entity_writable(db, current_user, entity_type="buyer_intent", entity_id=payload.buyer_intent_id)
        anchor = _get_buyer_intent_anchor(db, payload.buyer_intent_id)
        candidates = _candidate_targets_for_intent(db, anchor, payload.limit)
        session_anchor = {
            "buyer_intent_id": payload.buyer_intent_id,
            "buyer_party_id": anchor.get("buyer_party_id"),
            "seller_target_id": None,
        }
    else:
        ensure_entity_writable(db, current_user, entity_type="seller_target", entity_id=payload.seller_target_id)
        anchor = _get_seller_target_anchor(db, payload.seller_target_id)
        candidates = _candidate_intents_for_target(db, anchor, payload.limit)
        session_anchor = {
            "buyer_intent_id": None,
            "buyer_party_id": None,
            "seller_target_id": payload.seller_target_id,
        }
    candidates = _enrich_candidates_for_frontend(candidates)

    session_id = None
    rerank_job_id = None
    if payload.session_id is not None:
        existing_session = _get_recommendation_session_or_404(db, payload.session_id)
        if existing_session["mode"] != payload.mode:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Session mode does not match the request mode.",
            )
        session_anchor_matches = (
            str(existing_session.get("buyer_intent_id") or "") == str(payload.buyer_intent_id or "")
            and str(existing_session.get("seller_target_id") or "") == str(payload.seller_target_id or "")
        )
        if not session_anchor_matches:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Session anchor does not match the requested intent/target.",
            )
        session_id = payload.session_id
        if payload.user_message:
            _insert_recommendation_message(
                db,
                session_id=session_id,
                role="user",
                content_type="text",
                content=payload.user_message,
                created_by=current_user.user_id,
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
            },
            metadata_json={"message_type": "initial_candidates"},
            created_by=current_user.user_id,
        )
        if payload.enable_rerank and len(candidates) > 1:
            rerank_job_id = _enqueue_recommendation_rerank_job(
                db,
                session_id=session_id,
                mode=payload.mode,
                anchor=anchor,
                candidates=candidates,
                idempotency_suffix=uuid4().hex[:12],
                metadata_json={"source": "recommendation_candidate_api_round"},
            )
        _touch_recommendation_session(db, session_id)
        db.commit()
    elif payload.create_session:
        session_id = _create_recommendation_session(
            db,
            mode=payload.mode,
            user_message=payload.user_message,
            initial_snapshot=anchor,
            candidates=candidates,
            created_by=current_user.user_id,
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
            },
            metadata_json={"message_type": "initial_candidates"},
            created_by=current_user.user_id,
        )
        if payload.enable_rerank and len(candidates) > 1:
            rerank_job_id = _enqueue_recommendation_rerank_job(
                db,
                session_id=session_id,
                mode=payload.mode,
                anchor=anchor,
                candidates=candidates,
            )
        db.commit()

    return {
        "session_id": session_id,
        "mode": payload.mode,
        "candidates": candidates,
        "debug": {
            "engine": "rule_v2_deep_eval" if rerank_job_id else "rule_v2",
            "rerank": bool(rerank_job_id),
            "rerank_job_id": str(rerank_job_id) if rerank_job_id else None,
            "embedding_similarity": False,
            "notes": [
                "Returns SQL/Python rule ranking first; LLM deep eval runs asynchronously for the top candidates.",
            ],
        },
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
    )
    return {
        "summary": summary,
        "bundle": bundle,
        "polling_hint": _recommendation_session_polling_hint(summary, session_id=session_id),
    }


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
    relation_id = _sync_selected_item_to_relation(db, selected_item)
    if relation_id:
        metadata_patch = {"relation_id": str(relation_id)}
        db.execute(
            text(
                """
                update recommendation_selected_item
                set metadata_json = metadata_json || :metadata_patch
                where id = :selected_item_id
                  and team_id = :team_id
                  and workspace_id = :workspace_id
                """
            ).bindparams(bindparam("metadata_patch", type_=JSONB)),
            {
                "selected_item_id": selected_item["id"],
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "metadata_patch": metadata_patch,
            },
        )
        selected_item["metadata_json"] = {**selected_item["metadata_json"], **metadata_patch}
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
    selected_items = _list_selected_items_for_report(
        db,
        session_id=session_id,
        selected_item_ids=payload.selected_item_ids,
    )
    if not selected_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one active selected item is required to generate a recommendation report.",
        )

    report_type = payload.report_type or _default_report_type(session["mode"])
    title = payload.title or _default_report_title(session, selected_items, report_type)
    markdown_content = _build_recommendation_report_markdown(
        session=session,
        selected_items=selected_items,
        report_type=report_type,
        title=title,
    )
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
    selected_items = _list_selected_items_for_report(
        db,
        session_id=session_id,
        selected_item_ids=payload.selected_item_ids,
    )
    if not selected_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one active selected item is required to generate a recommendation report.",
        )

    report_type = payload.report_type or _default_report_type(session["mode"])
    title = payload.title or _default_report_title(session, selected_items, report_type)
    fallback_markdown = _build_recommendation_report_markdown(
        session=session,
        selected_items=selected_items,
        report_type=report_type,
        title=title,
    )
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


@router.post("/selected-items/{selected_item_id}/cancel", response_model=RecommendationSelectedItemOut)
def cancel_selected_item(
    selected_item_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    current = _get_selected_item_or_404(db, selected_item_id)
    ensure_recommendation_session_visible(db, current_user, current["session_id"])
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
    _insert_selected_item_cancel_event(db, dict(row))
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


