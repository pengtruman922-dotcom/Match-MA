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

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

DEEP_EVAL_CANDIDATE_LIMIT = 20


class RecommendationCandidateRequest(BaseModel):
    mode: str = Field(pattern="^(buyer_to_target|target_to_buyer)$")
    buyer_intent_id: UUID | None = None
    seller_target_id: UUID | None = None
    limit: int = Field(default=20, ge=1, le=50)
    create_session: bool = True
    enable_rerank: bool = True
    user_message: str | None = None

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
    if payload.create_session:
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


def _build_recommendation_session_bundle(
    db: Session,
    *,
    session_id: UUID,
    include_canceled: bool,
) -> dict[str, Any]:
    session = _get_recommendation_session_or_404(db, session_id)
    messages = _list_recommendation_messages(db, session_id=session_id, limit=500, offset=0)
    selected_items = _list_selected_items(
        db,
        session_id=session_id,
        include_canceled=include_canceled,
        limit=500,
        offset=0,
    )
    reports = _list_recommendation_reports(db, session_id=session_id, limit=100, offset=0)
    candidate_sets = _extract_recommendation_candidate_sets(messages)
    initial_candidates = _enrich_candidates_with_selection(
        candidate_sets["initial_candidates"],
        selected_items,
    )
    reranked_candidates = _enrich_candidates_with_selection(
        candidate_sets["reranked_candidates"],
        selected_items,
    )
    latest_candidates = reranked_candidates or initial_candidates
    candidate_source = "reranked_candidates" if reranked_candidates else (
        "initial_candidates" if initial_candidates else "none"
    )
    rerank_job = _get_latest_recommendation_rerank_job(db, session_id=session_id)
    rerank_status = _build_recommendation_rerank_status(
        rerank_job=rerank_job,
        reranked_candidates=reranked_candidates,
        candidate_sets=candidate_sets,
    )
    return {
        "session": session,
        "messages": messages,
        "initial_candidates": initial_candidates,
        "reranked_candidates": reranked_candidates,
        "latest_candidates": latest_candidates,
        "candidate_source": candidate_source,
        "rerank_status": rerank_status,
        "selected_items": selected_items,
        "reports": reports,
        "debug": {
            "selected_count": len([item for item in selected_items if item.get("canceled_at") is None]),
            "canceled_selected_count": len([item for item in selected_items if item.get("canceled_at") is not None]),
            "message_count": len(messages),
            "report_count": len(reports),
            "initial_candidate_count": len(initial_candidates),
            "reranked_candidate_count": len(reranked_candidates),
            "latest_candidate_count": len(latest_candidates),
            "candidate_source": candidate_source,
            "engine_hint": "rule_sql_python_deep_eval_v1",
        },
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


def _list_recommendation_session_overview_rows(
    db: Session,
    *,
    current_user: CurrentUser,
    mode: str | None,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where = ["rs.team_id = :team_id", "rs.workspace_id = :workspace_id", "rs.status <> 'archived'"]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
        "offset": offset,
    }
    if mode:
        where.append("rs.mode = :mode")
        params["mode"] = mode
    if owner_scope_required(current_user):
        where.append(recommendation_session_visible_sql("rs"))
        params["scope_user_id"] = current_user.user_id

    rows = db.execute(
        text(
            f"""
            select {_session_overview_select_columns()}
            from recommendation_session rs
            left join buyer_intent bi on bi.id = rs.buyer_intent_id
            left join buyer_party bp on bp.id = coalesce(rs.buyer_party_id, bi.buyer_party_id)
            left join seller_target st on st.id = rs.seller_target_id
            where {' and '.join(where)}
            order by rs.updated_at desc, rs.created_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


def _get_recommendation_session_overview_or_404(db: Session, session_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            f"""
            select {_session_overview_select_columns()}
            from recommendation_session rs
            left join buyer_intent bi on bi.id = rs.buyer_intent_id
            left join buyer_party bp on bp.id = coalesce(rs.buyer_party_id, bi.buyer_party_id)
            left join seller_target st on st.id = rs.seller_target_id
            where rs.id = :session_id
              and rs.team_id = :team_id
              and rs.workspace_id = :workspace_id
            """
        ),
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation session not found.")
    return dict(row)


def _list_running_recommendation_session_ids(
    db: Session,
    *,
    current_user: CurrentUser,
    limit: int,
) -> list[UUID]:
    scope_join = ""
    scope_where = ""
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
    }
    if owner_scope_required(current_user):
        scope_join = """
            join recommendation_session rs
              on rs.id = running_jobs.session_id
             and rs.team_id = :team_id
             and rs.workspace_id = :workspace_id
        """
        scope_where = f"and {recommendation_session_visible_sql('rs')}"
        params["scope_user_id"] = current_user.user_id
    rows = db.execute(
        text(
            f"""
            with running_jobs as (
              select
                case
                  when job.job_type in ('recommendation_deep_eval', 'recommendation_rerank')
                    and job.entity_type = 'recommendation_session'
                    then job.entity_id
                  when job.payload_json ? 'session_id'
                    and job.payload_json ->> 'session_id'
                      ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                    then nullif(job.payload_json ->> 'session_id', '')::uuid
                  else null
                end as session_id
              from background_job job
              where job.team_id = :team_id
                and job.workspace_id = :workspace_id
                and job.job_type in ('recommendation_deep_eval', 'recommendation_rerank', 'recommendation_report_generate')
                and job.status in ('queued', 'running', 'retry_waiting')
            )
            select distinct session_id
            from running_jobs
            {scope_join}
            where session_id is not null
            {scope_where}
            order by session_id
            limit :limit
            """
        ),
        params,
    ).mappings().all()
    return [row["session_id"] for row in rows if row.get("session_id") is not None]


def _build_recommendation_session_summary(
    db: Session,
    *,
    session: dict[str, Any],
    preview_limit: int,
) -> dict[str, Any]:
    session_id = session["id"]
    messages = _list_recommendation_messages(db, session_id=session_id, limit=500, offset=0)
    selected_items = _list_selected_items(
        db,
        session_id=session_id,
        include_canceled=True,
        limit=500,
        offset=0,
    )
    reports = _list_recommendation_reports(db, session_id=session_id, limit=50, offset=0)
    candidate_sets = _extract_recommendation_candidate_sets(messages)
    initial_candidates = _enrich_candidates_with_selection(
        candidate_sets["initial_candidates"],
        selected_items,
    )
    reranked_candidates = _enrich_candidates_with_selection(
        candidate_sets["reranked_candidates"],
        selected_items,
    )
    latest_candidates = reranked_candidates or initial_candidates
    candidate_source = "reranked_candidates" if reranked_candidates else (
        "initial_candidates" if initial_candidates else "none"
    )
    rerank_job = _get_latest_recommendation_rerank_job(db, session_id=session_id)
    rerank_status = _build_recommendation_rerank_status(
        rerank_job=rerank_job,
        reranked_candidates=reranked_candidates,
        candidate_sets=candidate_sets,
    )
    report_jobs = _get_recommendation_report_jobs(db, session_id=session_id)
    report_status = _build_recommendation_report_status(reports=reports, jobs=report_jobs)
    selected_status = _build_recommendation_selected_status(selected_items)
    activity = _build_recommendation_activity(
        session=session,
        messages=messages,
        reports=reports,
        rerank_status=rerank_status,
        report_status=report_status,
    )
    return {
        "session": session,
        "display": _recommendation_session_display(session),
        "candidate_counts": {
            "initial": len(initial_candidates),
            "reranked": len(reranked_candidates),
            "latest": len(latest_candidates),
        },
        "latest_candidates_preview": latest_candidates[:preview_limit],
        "candidate_source": candidate_source,
        "rerank_status": rerank_status,
        "report_status": report_status,
        "selected_status": selected_status,
        "activity": activity,
        "debug_ref": {
            "entity_type": "recommendation_session",
            "entity_id": str(session_id),
            "route": f"/debug/entities/recommendation_session/{session_id}",
        },
    }


def _recommendation_session_display(session: dict[str, Any]) -> dict[str, Any]:
    mode = session.get("mode")
    if mode == "buyer_to_target":
        title = session.get("buyer_intent_name") or session.get("buyer_name") or "买家找标的"
        subtitle = session.get("buyer_name")
        anchor = {"entity_type": "buyer_intent", "entity_id": _string_or_none(session.get("buyer_intent_id"))}
        primary_action = "recommend_targets"
    else:
        title = session.get("seller_target_name") or "标的找买家"
        subtitle = "推荐买家意向"
        anchor = {"entity_type": "seller_target", "entity_id": _string_or_none(session.get("seller_target_id"))}
        primary_action = "recommend_buyers"
    return {
        "title": title,
        "subtitle": subtitle,
        "mode_label": "买家找标的" if mode == "buyer_to_target" else "标的找买家",
        "anchor": anchor,
        "primary_action": primary_action,
        "route": f"/recommendations/sessions/{session['id']}",
    }


def _recommendation_session_is_processing(summary: dict[str, Any]) -> bool:
    return (
        summary["rerank_status"].get("status") in {"queued", "running", "retry_waiting"}
        or summary["report_status"].get("status") in {"queued", "running", "retry_waiting", "generating"}
    )


def _filter_recommendation_session_summaries(
    summaries: list[dict[str, Any]],
    status_filter: str | None,
) -> list[dict[str, Any]]:
    if not status_filter or status_filter == "all":
        return summaries
    if status_filter == "running":
        return [summary for summary in summaries if _recommendation_session_is_processing(summary)]
    if status_filter == "failed":
        return [
            summary
            for summary in summaries
            if summary["rerank_status"].get("status") == "failed"
            or summary["report_status"].get("status") == "failed"
        ]
    if status_filter == "generated":
        return [summary for summary in summaries if summary["report_status"].get("status") == "generated"]
    if status_filter == "selected":
        return [
            summary
            for summary in summaries
            if int(summary["selected_status"].get("active_count") or 0) > 0
        ]
    if status_filter == "idle":
        return [
            summary
            for summary in summaries
            if not _recommendation_session_is_processing(summary)
            and summary["rerank_status"].get("status") != "failed"
            and summary["report_status"].get("status") != "failed"
        ]
    return summaries


def _recommendation_session_polling_hint(
    summary: dict[str, Any],
    *,
    session_id: UUID,
) -> dict[str, Any]:
    enabled = _recommendation_session_is_processing(summary)
    watched_jobs = []
    rerank_job_id = summary["rerank_status"].get("job_id")
    if rerank_job_id and summary["rerank_status"].get("status") in {"queued", "running", "retry_waiting"}:
        watched_jobs.append(
            {
                "job_type": "recommendation_deep_eval",
                "job_id": rerank_job_id,
                "queue_name": summary["rerank_status"].get("queue_name"),
                "status": summary["rerank_status"].get("status"),
            }
        )
    latest_report_job = summary["report_status"].get("latest_job")
    if latest_report_job and latest_report_job.get("status") in {"queued", "running", "retry_waiting"}:
        watched_jobs.append(
            {
                "job_type": latest_report_job.get("job_type"),
                "job_id": latest_report_job.get("id"),
                "queue_name": latest_report_job.get("queue_name"),
                "status": latest_report_job.get("status"),
            }
        )
    return {
        "enabled": enabled,
        "interval_ms": 3000 if enabled else None,
        "endpoint": f"/api/v1/recommendations/sessions/{session_id}/page-state",
        "status_endpoint": f"/api/v1/recommendations/sessions/{session_id}/status",
        "bundle_endpoint": f"/api/v1/recommendations/sessions/{session_id}/bundle",
        "watched_jobs": watched_jobs,
        "reason": "rerank_or_report_running" if enabled else "terminal_or_not_requested",
    }


def _recommendation_page_overview(
    recent_summaries: list[dict[str, Any]],
    running_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    failed_count = 0
    generated_report_count = 0
    selected_count = 0
    for summary in recent_summaries:
        if summary["rerank_status"].get("status") == "failed" or summary["report_status"].get("status") == "failed":
            failed_count += 1
        generated_report_count += int(summary["report_status"].get("generated_count") or 0)
        selected_count += int(summary["selected_status"].get("active_count") or 0)
    return {
        "recent_session_count": len(recent_summaries),
        "running_session_count": len(running_summaries),
        "failed_session_count": failed_count,
        "generated_report_count": generated_report_count,
        "active_selected_item_count": selected_count,
    }


def _recommendation_quick_actions(overview: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "key": "start_buyer_to_target",
            "label": "按买家找标的",
            "action": "open_buyer_selector",
            "route": None,
            "badge_count": None,
        },
        {
            "key": "start_target_to_buyer",
            "label": "按标的找买家",
            "action": "open_target_selector",
            "route": None,
            "badge_count": None,
        },
        {
            "key": "review_running",
            "label": "查看生成中",
            "action": "filter_running_sessions",
            "route": "/recommendations?status=running",
            "badge_count": overview.get("running_session_count"),
        },
    ]


def _build_recommendation_report_status(
    *,
    reports: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_report = reports[0] if reports else None
    latest_job = jobs[0] if jobs else None
    status_counts = _count_by_key(reports, "status")
    job_status = latest_job.get("status") if latest_job else None
    report_status = latest_report.get("status") if latest_report else None
    running_statuses = {"queued", "running", "retry_waiting"}
    if job_status in running_statuses or report_status == "generating":
        aggregate_status = "generating"
    elif job_status == "failed" or report_status == "failed":
        aggregate_status = "failed"
    elif status_counts.get("generated", 0) > 0:
        aggregate_status = "generated"
    else:
        aggregate_status = "not_requested"
    return {
        "requested": bool(reports or jobs),
        "status": aggregate_status,
        "latest_report": _compact_recommendation_report(latest_report) if latest_report else None,
        "latest_job": _compact_background_job(latest_job) if latest_job else None,
        "total_count": len(reports),
        "generated_count": int(status_counts.get("generated", 0)),
        "generating_count": int(status_counts.get("generating", 0)),
        "failed_count": int(status_counts.get("failed", 0)),
        "archived_count": int(status_counts.get("archived", 0)),
    }


def _build_recommendation_selected_status(selected_items: list[dict[str, Any]]) -> dict[str, Any]:
    active_items = [item for item in selected_items if item.get("canceled_at") is None]
    return {
        "active_count": len(active_items),
        "canceled_count": len(selected_items) - len(active_items),
        "latest_selected_at": active_items[0].get("selected_at") if active_items else None,
        "latest_item": _compact_selected_item(active_items[0]) if active_items else None,
    }


def _build_recommendation_activity(
    *,
    session: dict[str, Any],
    messages: list[dict[str, Any]],
    reports: list[dict[str, Any]],
    rerank_status: dict[str, Any],
    report_status: dict[str, Any],
) -> dict[str, Any]:
    timestamps = [
        session.get("updated_at"),
        messages[-1].get("created_at") if messages else None,
        reports[0].get("created_at") if reports else None,
        rerank_status.get("finished_at") or rerank_status.get("started_at") or rerank_status.get("created_at"),
        (report_status.get("latest_job") or {}).get("finished_at")
        or (report_status.get("latest_job") or {}).get("started_at")
        or (report_status.get("latest_job") or {}).get("created_at"),
    ]
    latest_activity_at = max([value for value in timestamps if value] or [None])
    return {
        "latest_activity_at": latest_activity_at,
        "message_count": len(messages),
        "report_count": len(reports),
        "last_message": _compact_recommendation_message(messages[-1]) if messages else None,
    }


def _get_recommendation_report_jobs(db: Session, *, session_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, job_type, status, priority, queue_name, entity_type, entity_id,
              result_json, error_code, error_message, attempt_count, max_attempts,
              started_at::text as started_at, finished_at::text as finished_at,
              created_at::text as created_at, updated_at::text as updated_at, metadata_json
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and job_type = 'recommendation_report_generate'
              and (
                payload_json ->> 'session_id' = :session_id_text
                or entity_id in (
                  select id
                  from recommendation_report
                  where session_id = :session_id
                    and team_id = :team_id
                    and workspace_id = :workspace_id
                )
              )
            order by created_at desc
            limit 50
            """
        ),
        {
            "session_id": session_id,
            "session_id_text": str(session_id),
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _compact_recommendation_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": report.get("id"),
        "session_id": report.get("session_id"),
        "report_type": report.get("report_type"),
        "title": report.get("title"),
        "status": report.get("status"),
        "generated_by_model": report.get("generated_by_model"),
        "prompt_version": report.get("prompt_version"),
        "created_at": report.get("created_at"),
        "metadata_json": report.get("metadata_json"),
    }


def _compact_background_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job.get("id"),
        "job_type": job.get("job_type"),
        "status": job.get("status"),
        "queue_name": job.get("queue_name"),
        "entity_type": job.get("entity_type"),
        "entity_id": job.get("entity_id"),
        "error_code": job.get("error_code"),
        "error_message": job.get("error_message"),
        "attempt_count": job.get("attempt_count"),
        "max_attempts": job.get("max_attempts"),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "updated_at": job.get("updated_at"),
    }


def _compact_selected_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "seller_target_id": item.get("seller_target_id"),
        "seller_target_name": item.get("seller_target_name"),
        "buyer_intent_id": item.get("buyer_intent_id"),
        "buyer_intent_name": item.get("buyer_intent_name"),
        "buyer_party_id": item.get("buyer_party_id"),
        "buyer_name": item.get("buyer_name"),
        "recommendation_level": item.get("recommendation_level"),
        "selected_at": item.get("selected_at"),
    }


def _compact_recommendation_message(message: dict[str, Any]) -> dict[str, Any]:
    content = str(message.get("content") or "")
    return {
        "id": message.get("id"),
        "role": message.get("role"),
        "content_type": message.get("content_type"),
        "content_preview": content[:160],
        "metadata_json": message.get("metadata_json"),
        "created_at": message.get("created_at"),
    }


def _count_by_key(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _string_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


def _list_recommendation_messages(
    db: Session,
    *,
    session_id: UUID,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            select {_message_select_columns()}
            from recommendation_message
            where session_id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            order by created_at asc
            limit :limit offset :offset
            """
        ),
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "limit": limit,
            "offset": offset,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _list_selected_items(
    db: Session,
    *,
    session_id: UUID,
    include_canceled: bool,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where = ["ri.session_id = :session_id", "ri.team_id = :team_id", "ri.workspace_id = :workspace_id"]
    if not include_canceled:
        where.append("ri.canceled_at is null")
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
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "limit": limit,
            "offset": offset,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _list_recommendation_reports(
    db: Session,
    *,
    session_id: UUID,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            select {_report_select_columns()}
            from recommendation_report
            where session_id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            order by created_at desc
            limit :limit offset :offset
            """
        ),
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "limit": limit,
            "offset": offset,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _extract_recommendation_candidate_sets(
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    initial_candidates: list[dict[str, Any]] = []
    reranked_candidates: list[dict[str, Any]] = []
    initial_message_id: str | None = None
    reranked_message_id: str | None = None
    reranked_at: str | None = None

    for message in messages:
        if message.get("content_type") != "json":
            continue

        content = _json_loads(message.get("content") or "{}")
        metadata = message.get("metadata_json") if isinstance(message.get("metadata_json"), dict) else {}
        message_type = str(
            metadata.get("message_type")
            or content.get("message_type")
            or _infer_recommendation_candidate_message_type(content)
            or ""
        )
        candidates = content.get("candidates")
        if not isinstance(candidates, list):
            continue

        if message_type == "reranked_candidates":
            reranked_candidates = _normalize_candidates(candidates)
            reranked_message_id = str(message["id"])
            reranked_at = message.get("created_at")
        elif message_type == "initial_candidates":
            initial_candidates = _normalize_candidates(candidates)
            initial_message_id = str(message["id"])

    return {
        "initial_candidates": initial_candidates,
        "reranked_candidates": reranked_candidates,
        "initial_message_id": initial_message_id,
        "reranked_message_id": reranked_message_id,
        "reranked_at": reranked_at,
    }


def _infer_recommendation_candidate_message_type(content: dict[str, Any]) -> str | None:
    candidates = content.get("candidates")
    if not isinstance(candidates, list):
        return None
    if not candidates:
        return "initial_candidates"

    has_rerank_score = any(
        isinstance(candidate, dict)
        and isinstance(candidate.get("evidence_json"), dict)
        and isinstance(candidate["evidence_json"].get("score"), dict)
        and candidate["evidence_json"]["score"].get("rerank_score") is not None
        for candidate in candidates
    )
    return "reranked_candidates" if has_rerank_score else "initial_candidates"


def _normalize_candidates(candidates: list[Any]) -> list[dict[str, Any]]:
    normalized_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        if isinstance(candidate, dict):
            normalized_candidates.append(dict(candidate))
    return normalized_candidates


def _enrich_candidates_with_selection(
    candidates: list[dict[str, Any]],
    selected_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected_by_pair = {
        _candidate_pair_key(selected_item): selected_item
        for selected_item in selected_items
        if selected_item.get("canceled_at") is None
    }
    enriched: list[dict[str, Any]] = []
    for candidate in candidates:
        item = dict(candidate)
        selected_item = selected_by_pair.get(_candidate_pair_key(item))
        if selected_item is not None:
            item["selected"] = True
            item["selected_item_id"] = selected_item.get("id")
            item["selected_at"] = selected_item.get("selected_at")
        else:
            item["selected"] = False
            item["selected_item_id"] = None
            item["selected_at"] = None
        enriched.append(_with_frontend_candidate_fields(item))
    return enriched


def _enrich_candidates_for_frontend(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_with_frontend_candidate_fields(candidate) for candidate in candidates]


def _with_frontend_candidate_fields(candidate: dict[str, Any]) -> dict[str, Any]:
    item = dict(candidate)
    mode = str(item.get("mode") or "")
    if mode == "buyer_to_target":
        primary_entity_type = "seller_target"
        primary_entity_id = item.get("seller_target_id")
        counterpart_entity_type = "buyer_intent"
        counterpart_entity_id = item.get("buyer_intent_id")
        title = item.get("seller_target_name")
        subtitle = _join_display_parts([item.get("buyer_intent_name"), item.get("buyer_name")])
        action_label = "add_target_to_recommendation"
    else:
        primary_entity_type = "buyer_intent"
        primary_entity_id = item.get("buyer_intent_id")
        counterpart_entity_type = "seller_target"
        counterpart_entity_id = item.get("seller_target_id")
        title = item.get("buyer_intent_name") or item.get("buyer_name")
        subtitle = _join_display_parts([item.get("buyer_name"), item.get("seller_target_name")])
        action_label = "add_buyer_to_recommendation"

    score_breakdown = _candidate_score_breakdown(item)
    display_meta = _candidate_display_meta(item, score_breakdown)
    display_badges = _candidate_display_badges(item, score_breakdown)
    item.update(
        {
            "primary_entity_type": primary_entity_type,
            "primary_entity_id": primary_entity_id,
            "counterpart_entity_type": counterpart_entity_type,
            "counterpart_entity_id": counterpart_entity_id,
            "display_title": title,
            "display_subtitle": subtitle,
            "display_meta": display_meta,
            "display_badges": display_badges,
            "score_breakdown": score_breakdown,
            "card_json": {
                "title": title,
                "subtitle": subtitle,
                "meta": display_meta,
                "badges": display_badges,
                "score": item.get("score"),
                "recommendation_level": item.get("recommendation_level"),
                "selected": bool(item.get("selected")),
                "action_label": action_label,
                "primary_entity_type": primary_entity_type,
                "primary_entity_id": str(primary_entity_id) if primary_entity_id else None,
                "counterpart_entity_type": counterpart_entity_type,
                "counterpart_entity_id": str(counterpart_entity_id) if counterpart_entity_id else None,
            },
        }
    )
    return item


def _candidate_score_breakdown(candidate: dict[str, Any]) -> dict[str, Any]:
    evidence_json = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
    score_json = evidence_json.get("score") if isinstance(evidence_json.get("score"), dict) else {}
    return {
        "rule_score": score_json.get("rule_score"),
        "rerank_score": score_json.get("rerank_score"),
        "rerank_boost": score_json.get("rerank_boost"),
        "rerank_model": score_json.get("rerank_model"),
        "hard_mismatches": score_json.get("hard_mismatches") or [],
        "excluded_hit": score_json.get("excluded_hit"),
        "deep_eval_grade": score_json.get("deep_eval_grade"),
        "deep_eval_model": score_json.get("deep_eval_model"),
        "final_score": score_json.get("final_score") or candidate.get("score"),
    }


def _candidate_display_meta(candidate: dict[str, Any], score_breakdown: dict[str, Any]) -> list[str]:
    meta = [
        f"score {candidate.get('score')}",
        f"level {candidate.get('recommendation_level')}",
    ]
    if score_breakdown.get("rerank_score") is not None:
        meta.append(f"rerank {float(score_breakdown['rerank_score']):.2f}")
    return [item for item in meta if item and not item.endswith("None")]


def _candidate_display_badges(candidate: dict[str, Any], score_breakdown: dict[str, Any]) -> list[str]:
    badges = [str(candidate.get("recommendation_level") or "unrated")]
    if score_breakdown.get("deep_eval_grade"):
        badges.append(f"深评{score_breakdown['deep_eval_grade']}档")
    if score_breakdown.get("excluded_hit"):
        badges.append("命中排除项")
    elif score_breakdown.get("hard_mismatches"):
        badges.append("硬性条件不符")
    if score_breakdown.get("rerank_score") is not None:
        badges.append("reranked")
    if candidate.get("selected"):
        badges.append("selected")
    return badges


def _join_display_parts(parts: list[Any]) -> str | None:
    values = [str(part) for part in parts if part]
    return " / ".join(values) if values else None


def _candidate_pair_key(item: dict[str, Any]) -> tuple[str | None, str | None]:
    seller_target_id = item.get("seller_target_id")
    buyer_intent_id = item.get("buyer_intent_id")
    return (
        str(seller_target_id) if seller_target_id else None,
        str(buyer_intent_id) if buyer_intent_id else None,
    )


def _get_latest_recommendation_rerank_job(
    db: Session,
    *,
    session_id: UUID,
) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select
              id, status, queue_name, error_code, error_message,
              attempt_count, max_attempts, run_after::text as run_after,
              started_at::text as started_at, finished_at::text as finished_at,
              created_at::text as created_at, updated_at::text as updated_at,
              result_json, metadata_json
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and job_type in ('recommendation_deep_eval', 'recommendation_rerank')
              and entity_type = 'recommendation_session'
              and entity_id = :session_id
            order by created_at desc
            limit 1
            """
        ),
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


def _build_recommendation_rerank_status(
    *,
    rerank_job: dict[str, Any] | None,
    reranked_candidates: list[dict[str, Any]],
    candidate_sets: dict[str, Any],
) -> dict[str, Any]:
    if rerank_job is None:
        return {
            "requested": False,
            "status": "not_requested",
            "job_id": None,
            "queue_name": None,
            "candidate_count": 0,
            "reranked_at": None,
            "error_code": None,
            "error_message": None,
        }

    return {
        "requested": True,
        "status": rerank_job.get("status"),
        "job_id": str(rerank_job["id"]),
        "queue_name": rerank_job.get("queue_name"),
        "candidate_count": len(reranked_candidates),
        "message_id": candidate_sets.get("reranked_message_id"),
        "reranked_at": candidate_sets.get("reranked_at") or rerank_job.get("finished_at"),
        "created_at": rerank_job.get("created_at"),
        "started_at": rerank_job.get("started_at"),
        "finished_at": rerank_job.get("finished_at"),
        "attempt_count": rerank_job.get("attempt_count"),
        "max_attempts": rerank_job.get("max_attempts"),
        "error_code": rerank_job.get("error_code"),
        "error_message": rerank_job.get("error_message"),
    }


def _get_rerank_anchor_for_session(db: Session, session: dict[str, Any]) -> dict[str, Any]:
    if session["mode"] == "buyer_to_target":
        buyer_intent_id = _optional_uuid(session.get("buyer_intent_id"))
        if buyer_intent_id is not None:
            return _get_buyer_intent_anchor(db, buyer_intent_id)
    if session["mode"] == "target_to_buyer":
        seller_target_id = _optional_uuid(session.get("seller_target_id"))
        if seller_target_id is not None:
            return _get_seller_target_anchor(db, seller_target_id)

    snapshot = session.get("latest_condition_snapshot_json")
    if isinstance(snapshot, dict) and snapshot:
        return snapshot
    snapshot = session.get("initial_condition_snapshot_json")
    if isinstance(snapshot, dict) and snapshot:
        return snapshot
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Recommendation session has no rerank anchor.")


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


def _get_active_selected_item_for_pair(
    db: Session,
    *,
    session_id: UUID,
    buyer_intent_id: UUID | None,
    seller_target_id: UUID | None,
) -> dict[str, Any] | None:
    if buyer_intent_id is None or seller_target_id is None:
        return None
    row = db.execute(
        text(
            f"""
            select {_selected_item_select_columns()}
            from recommendation_selected_item ri
            left join seller_target st on st.id = ri.seller_target_id
            left join buyer_intent bi on bi.id = ri.buyer_intent_id
            left join buyer_party bp on bp.id = ri.buyer_party_id
            where ri.session_id = :session_id
              and ri.buyer_intent_id = :buyer_intent_id
              and ri.seller_target_id = :seller_target_id
              and ri.team_id = :team_id
              and ri.workspace_id = :workspace_id
              and ri.canceled_at is null
            order by ri.selected_at desc
            limit 1
            """
        ),
        {
            "session_id": session_id,
            "buyer_intent_id": buyer_intent_id,
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _list_selected_items_for_report(
    db: Session,
    *,
    session_id: UUID,
    selected_item_ids: list[UUID] | None,
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
    statement = text(
        f"""
        select {_selected_item_select_columns()}
        from recommendation_selected_item ri
        left join seller_target st on st.id = ri.seller_target_id
        left join buyer_intent bi on bi.id = ri.buyer_intent_id
        left join buyer_party bp on bp.id = ri.buyer_party_id
        where {' and '.join(where)}
        order by ri.rank_at_selection nulls last, ri.selected_at asc
        """
    )
    if selected_item_ids is not None:
        if not selected_item_ids:
            return []
        where.append("ri.id in :selected_item_ids")
        params["selected_item_ids"] = tuple(selected_item_ids)
        statement = text(
            f"""
            select {_selected_item_select_columns()}
            from recommendation_selected_item ri
            left join seller_target st on st.id = ri.seller_target_id
            left join buyer_intent bi on bi.id = ri.buyer_intent_id
            left join buyer_party bp on bp.id = ri.buyer_party_id
            where {' and '.join(where)}
            order by ri.rank_at_selection nulls last, ri.selected_at asc
            """
        ).bindparams(bindparam("selected_item_ids", expanding=True))

    rows = db.execute(statement, params).mappings().all()
    return [dict(row) for row in rows]


def _default_report_type(mode: str) -> str:
    if mode == "buyer_to_target":
        return "buyer_facing_target_report"
    return "internal_buyer_list"


def _default_report_title(
    session: dict[str, Any],
    selected_items: list[dict[str, Any]],
    report_type: str,
) -> str:
    if report_type == "buyer_facing_target_report":
        anchor = selected_items[0].get("buyer_intent_name") or "买家意向"
        return f"{anchor} - 推荐标的清单"
    anchor = selected_items[0].get("seller_target_name") or "标的项目"
    return f"{anchor} - 推荐买家意向清单"


def _build_recommendation_report_markdown(
    *,
    session: dict[str, Any],
    selected_items: list[dict[str, Any]],
    report_type: str,
    title: str,
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
        target_name = item.get("seller_target_name") or "未绑定标的"
        intent_name = item.get("buyer_intent_name") or "未绑定意向"
        buyer_name = item.get("buyer_name") or "未绑定买家"
        level = item.get("recommendation_level") or "未评级"
        lines.extend(
            [
                f"### {index}. {target_name} / {intent_name}",
                "",
                f"- 买家：{buyer_name}",
                f"- 推荐等级：{level}",
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
            "- 复核通过后，可在买家-标的关系中继续记录推荐、反馈、尽调和终止等进展。",
        ]
    )
    return "\n".join(lines)


def _candidate_targets_for_intent(
    db: Session,
    intent: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              st.id as seller_target_id,
              st.target_name as seller_target_name,
              st.industry_l1,
              st.industry_primary,
              st.industry_secondary,
              st.headquarter_province,
              st.headquarter_city,
              st.current_revenue_yuan,
              st.current_net_profit_yuan,
              st.pe_ratio,
              st.valuation_yuan,
              st.asking_price_yuan,
              st.market_cap_yuan,
              st.current_debt_ratio,
              st.cash_flow_status,
              st.can_control,
              st.can_consolidate,
              st.transfer_ratio_max,
              st.listed_status,
              st.risk_summary,
              st.gap_summary,
              st.business_summary,
              exists(
                select 1
                from buyer_intent_target_exclusion x
                where x.buyer_intent_id = :buyer_intent_id
                  and x.seller_target_id = st.id
                  and x.active = true
                  and x.canceled_at is null
              ) as is_excluded
            from seller_target st
            where st.team_id = :team_id
              and st.workspace_id = :workspace_id
              and st.deleted_at is null
              and st.recommendation_status = 'recommendable'
              and st.lifecycle_status = 'active'
            order by
              case
                when st.industry_l1 is not null and st.industry_l1 in :intent_industries then 0
                when st.industry_primary is not null and st.industry_primary = :industry_primary then 0
                else 1
              end,
              st.current_net_profit_yuan desc nulls last,
              st.updated_at desc
            limit :candidate_pool_limit
            """
        ).bindparams(bindparam("intent_industries", expanding=True)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "buyer_intent_id": intent["id"],
            "industry_primary": intent.get("industry_primary"),
            "intent_industries": _intent_industry_list(intent) or ["__none__"],
            "candidate_pool_limit": max(limit * 10, 200),
        },
    ).mappings().all()

    candidates: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if item.pop("is_excluded"):
            continue
        rule_score, evidence, gaps, meta = _score_target_against_intent(item, intent)
        score = _apply_score_caps(rule_score, gaps, meta)
        if score < 10 and not meta.get("excluded_hit"):
            continue
        candidates.append(
            {
                "rank": 0,
                "mode": "buyer_to_target",
                "seller_target_id": item["seller_target_id"],
                "seller_target_name": item["seller_target_name"],
                "buyer_intent_id": intent["id"],
                "buyer_intent_name": intent["intent_name"],
                "buyer_party_id": intent.get("buyer_party_id"),
                "buyer_name": intent.get("buyer_name"),
                "score": score,
                "recommendation_level": _recommendation_level(score),
                "match_summary": _summary_text(evidence, fallback="具备初步匹配基础"),
                "gap_summary": _summary_text(gaps) if gaps else None,
                "risk_summary": item.get("risk_summary") or item.get("gap_summary"),
                "evidence_json": {
                    "matches": evidence,
                    "gaps": gaps,
                    "score": {
                        "rule_score": rule_score,
                        "final_score": score,
                        "hard_mismatches": meta.get("hard_mismatches") or [],
                        "excluded_hit": meta.get("excluded_hit"),
                        "score_engine": meta.get("score_engine"),
                    },
                },
            }
        )

    candidates.sort(key=lambda candidate: candidate["score"], reverse=True)
    for index, candidate in enumerate(candidates[:limit], start=1):
        candidate["rank"] = index
    return candidates[:limit]


def _candidate_intents_for_target(
    db: Session,
    target: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              bi.id as buyer_intent_id,
              bi.intent_name as buyer_intent_name,
              bi.buyer_party_id,
              bp.buyer_name,
              bi.industry_primary,
              bi.industry_secondary,
              bi.industries_json,
              bi.excluded_industries_json,
              bi.region_scope_summary,
              bi.min_revenue_yuan,
              bi.min_net_profit_yuan,
              bi.max_pe,
              bi.max_ps,
              bi.min_net_margin,
              bi.min_gross_margin,
              bi.min_valuation_yuan,
              bi.max_valuation_yuan,
              bi.min_market_cap_yuan,
              bi.max_market_cap_yuan,
              bi.max_debt_ratio,
              bi.requires_control,
              bi.requires_consolidation,
              bi.accepts_minority_investment,
              bi.desired_equity_ratio_min,
              bi.preferred_listed_status,
              bi.major_risk_tolerance_summary,
              bi.negative_summary,
              bi.preference_summary,
              exists(
                select 1
                from buyer_intent_target_exclusion x
                where x.buyer_intent_id = bi.id
                  and x.seller_target_id = :seller_target_id
                  and x.active = true
                  and x.canceled_at is null
              ) as is_excluded
            from buyer_intent bi
            left join buyer_party bp on bp.id = bi.buyer_party_id
            where bi.team_id = :team_id
              and bi.workspace_id = :workspace_id
              and bi.deleted_at is null
              and bi.status = 'active'
            order by
              case
                when :target_industry_l1 is not null and bi.industries_json ? :target_industry_l1 then 0
                when bi.industry_primary is not null and bi.industry_primary = :industry_primary then 0
                else 1
              end,
              bi.updated_at desc
            limit :candidate_pool_limit
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "seller_target_id": target["id"],
            "industry_primary": target.get("industry_primary"),
            "target_industry_l1": target.get("industry_l1"),
            "candidate_pool_limit": max(limit * 10, 200),
        },
    ).mappings().all()

    candidates: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if item.pop("is_excluded"):
            continue
        rule_score, evidence, gaps, meta = _score_target_against_intent(target, item)
        score = _apply_score_caps(rule_score, gaps, meta)
        if score < 10 and not meta.get("excluded_hit"):
            continue
        candidates.append(
            {
                "rank": 0,
                "mode": "target_to_buyer",
                "seller_target_id": target["id"],
                "seller_target_name": target["target_name"],
                "buyer_intent_id": item["buyer_intent_id"],
                "buyer_intent_name": item["buyer_intent_name"],
                "buyer_party_id": item.get("buyer_party_id"),
                "buyer_name": item.get("buyer_name"),
                "score": score,
                "recommendation_level": _recommendation_level(score),
                "match_summary": _summary_text(evidence, fallback="具备初步匹配基础"),
                "gap_summary": _summary_text(gaps) if gaps else None,
                "risk_summary": target.get("risk_summary") or target.get("gap_summary"),
                "evidence_json": {
                    "matches": evidence,
                    "gaps": gaps,
                    "score": {
                        "rule_score": rule_score,
                        "final_score": score,
                        "hard_mismatches": meta.get("hard_mismatches") or [],
                        "excluded_hit": meta.get("excluded_hit"),
                        "score_engine": meta.get("score_engine"),
                    },
                },
            }
        )

    candidates.sort(key=lambda candidate: candidate["score"], reverse=True)
    for index, candidate in enumerate(candidates[:limit], start=1):
        candidate["rank"] = index
    return candidates[:limit]


# Region groups let phrases like 长三角 in region_scope_summary match concrete
# provinces. Province names are stored without 省/市 suffixes.
REGION_GROUPS: dict[str, tuple[str, ...]] = {
    "长三角": ("上海", "江苏", "浙江", "安徽"),
    "珠三角": ("广东",),
    "大湾区": ("广东", "香港", "澳门"),
    "京津冀": ("北京", "天津", "河北"),
    "成渝": ("四川", "重庆"),
    "东北": ("辽宁", "吉林", "黑龙江"),
    "长江中游": ("湖北", "湖南", "江西"),
    "华东": ("上海", "江苏", "浙江", "安徽", "福建", "江西", "山东"),
    "华南": ("广东", "广西", "海南"),
    "华北": ("北京", "天津", "河北", "山西", "内蒙古"),
    "华中": ("湖北", "湖南", "河南", "江西"),
    "西北": ("陕西", "甘肃", "青海", "宁夏", "新疆"),
    "西南": ("四川", "重庆", "云南", "贵州", "西藏"),
}

# Score caps: hard mismatches and exclusion hits sink candidates instead of
# deleting them (business rule: never hide an opportunity, but label it).
HARD_MISMATCH_CAP_BASE = 45.0
EXCLUDED_HIT_CAP = 15.0
UNKNOWN_DIMENSION_CREDIT = 0.3


def _strip_region_suffix(value: Any) -> str:
    text_value = str(value or "").strip()
    for suffix in ("维吾尔自治区", "壮族自治区", "回族自治区", "自治区", "特别行政区", "省", "市"):
        if text_value.endswith(suffix):
            return text_value[: -len(suffix)]
    return text_value


def _region_scope_matches(region_scope: str, province: Any, city: Any) -> bool:
    for part in (province, city):
        part_text = str(part or "").strip()
        if not part_text:
            continue
        if part_text in region_scope or _strip_region_suffix(part_text) in region_scope:
            return True
    province_short = _strip_region_suffix(province)
    if not province_short:
        return False
    for group_name, provinces in REGION_GROUPS.items():
        if group_name in region_scope and province_short in provinces:
            return True
    return False


def _intent_industry_list(intent: dict[str, Any]) -> list[str]:
    values = intent.get("industries_json")
    if isinstance(values, list):
        return [str(item).strip() for item in values if item is not None and str(item).strip()]
    return []


def _excluded_industry_hit(target: dict[str, Any], intent: dict[str, Any]) -> str | None:
    values = intent.get("excluded_industries_json")
    if not isinstance(values, list):
        return None
    industry_l1 = str(target.get("industry_l1") or "")
    descriptive = "／".join(
        str(target.get(key) or "")
        for key in ("industry_primary", "industry_secondary", "business_summary")
    )
    for value in values:
        term = str(value or "").strip()
        if not term:
            continue
        if term == industry_l1:
            return term
        if term in descriptive:
            return term
        industry_primary = str(target.get("industry_primary") or "")
        if industry_primary and industry_primary in term:
            return term
    return None


def _score_target_against_intent(
    target: dict[str, Any],
    intent: dict[str, Any],
) -> tuple[float, list[str], list[str], dict[str, Any]]:
    """Three-state normalized scoring.

    Each dimension the buyer actually asked for contributes weight to the
    denominator; targets earn full weight on match, a small credit when the
    target-side information is missing, and zero on mismatch. Hard mismatches
    and exclusion hits are reported in meta so callers can sink the candidate.
    """
    evidence: list[str] = []
    gaps: list[str] = []
    hard_mismatches: list[str] = []
    earned = 0.0
    possible = 0.0

    def add_dimension(
        weight: float,
        state: str,
        *,
        match_text: str | None = None,
        gap_text: str | None = None,
        hard: bool = False,
        earned_override: float | None = None,
    ) -> None:
        nonlocal earned, possible
        possible += weight
        if state == "match":
            earned += weight if earned_override is None else earned_override
            if match_text:
                evidence.append(match_text)
        elif state == "mismatch":
            if gap_text:
                gaps.append(gap_text)
            if hard and gap_text:
                hard_mismatches.append(gap_text)
        else:
            earned += weight * UNKNOWN_DIMENSION_CREDIT
            if gap_text:
                gaps.append(gap_text)

    # 行业（多值，任一命中；主赛道全分，其余 85%）
    intent_industries = _intent_industry_list(intent)
    target_l1 = str(target.get("industry_l1") or "").strip()
    if intent_industries:
        if not target_l1:
            add_dimension(30, "unknown", gap_text="标的行业待归类")
        elif target_l1 in intent_industries:
            is_primary_track = target_l1 == intent_industries[0]
            add_dimension(
                30,
                "match",
                match_text=f"行业命中：{target_l1}" + ("（主赛道）" if is_primary_track else ""),
                earned_override=30.0 if is_primary_track else 25.5,
            )
        else:
            add_dimension(30, "mismatch", gap_text="行业不在买家关注赛道", hard=True)
    elif intent.get("industry_primary"):
        # 旧数据兜底：字符串相等，不命中只降分不沉底
        if target.get("industry_primary") == intent.get("industry_primary"):
            add_dimension(30, "match", match_text=f"一级行业匹配：{intent['industry_primary']}")
        else:
            add_dimension(30, "mismatch", gap_text="一级行业不完全匹配")

    # 区域（含区域组展开；偏好性，不沉底）
    region_scope = str(intent.get("region_scope_summary") or "").strip()
    if region_scope:
        province = target.get("headquarter_province")
        city = target.get("headquarter_city")
        if not province and not city:
            add_dimension(12, "unknown", gap_text="标的区域缺失")
        elif _region_scope_matches(region_scope, province, city):
            target_region = "".join(str(item) for item in [province, city] if item)
            add_dimension(12, "match", match_text=f"区域匹配：{target_region}")
        else:
            add_dimension(12, "mismatch", gap_text="区域不符合买家范围，需人工复核")

    # 财务门槛：净利润 + 营收。两个门槛都提出时按“任一达标”弱化处理（买家常用或条件）
    min_profit = _optional_decimal(intent.get("min_net_profit_yuan"))
    target_profit = _optional_decimal(target.get("current_net_profit_yuan"))
    min_revenue = _optional_decimal(intent.get("min_revenue_yuan"))
    target_revenue = _optional_decimal(target.get("current_revenue_yuan"))
    profit_ok = target_profit is not None and min_profit is not None and target_profit >= min_profit
    revenue_ok = target_revenue is not None and min_revenue is not None and target_revenue >= min_revenue
    both_thresholds = min_profit is not None and min_revenue is not None
    if min_profit is not None:
        if target_profit is None:
            add_dimension(16, "unknown", gap_text="标的净利润缺失")
        elif profit_ok:
            add_dimension(16, "match", match_text="净利润达到门槛")
        else:
            softened = both_thresholds and revenue_ok
            add_dimension(16, "mismatch", gap_text="净利润低于买家门槛", hard=not softened)
    if min_revenue is not None:
        if target_revenue is None:
            add_dimension(12, "unknown", gap_text="标的营收缺失")
        elif revenue_ok:
            add_dimension(12, "match", match_text="营收达到门槛")
        else:
            softened = both_thresholds and profit_ok
            add_dimension(12, "mismatch", gap_text="营收低于买家门槛", hard=not softened)

    # 价格（预算 vs 报价/估值：付不起是硬约束）
    min_valuation = _optional_decimal(intent.get("min_valuation_yuan"))
    max_valuation = _optional_decimal(intent.get("max_valuation_yuan"))
    if min_valuation is not None or max_valuation is not None:
        target_price = (
            _optional_decimal(target.get("asking_price_yuan"))
            or _optional_decimal(target.get("valuation_yuan"))
            or _optional_decimal(target.get("market_cap_yuan"))
        )
        if target_price is None:
            add_dimension(14, "unknown", gap_text="标的报价与估值缺失")
        elif max_valuation is not None and target_price > max_valuation:
            add_dimension(14, "mismatch", gap_text="报价/估值超出买家预算", hard=True)
        elif min_valuation is not None and target_price < min_valuation:
            add_dimension(14, "mismatch", gap_text="报价/估值低于买家偏好区间")
        else:
            add_dimension(14, "match", match_text="报价/估值处于买家要求范围")

    # PE 上限
    max_pe = _optional_decimal(intent.get("max_pe"))
    if max_pe is not None:
        target_pe = _optional_decimal(target.get("pe_ratio"))
        if target_pe is None:
            add_dimension(10, "unknown", gap_text="标的 PE 缺失")
        elif target_pe <= max_pe:
            add_dimension(10, "match", match_text="PE 未超过上限")
        else:
            add_dimension(10, "mismatch", gap_text="PE 超过买家上限", hard=True)

    # 市值区间（上市标的体量偏好，不沉底）
    min_market_cap = _optional_decimal(intent.get("min_market_cap_yuan"))
    max_market_cap = _optional_decimal(intent.get("max_market_cap_yuan"))
    if min_market_cap is not None or max_market_cap is not None:
        target_market_cap = _optional_decimal(target.get("market_cap_yuan")) or _optional_decimal(
            target.get("valuation_yuan")
        )
        if target_market_cap is None:
            add_dimension(6, "unknown", gap_text="标的市值缺失")
        elif min_market_cap is not None and target_market_cap < min_market_cap:
            add_dimension(6, "mismatch", gap_text="市值低于买家下限")
        elif max_market_cap is not None and target_market_cap > max_market_cap:
            add_dimension(6, "mismatch", gap_text="市值超过买家上限")
        else:
            add_dimension(6, "match", match_text="市值处于买家要求范围")

    # 股比/控股/并表：取买家提出的最强要求；标的明确说“不行”才算硬不符
    requires_control = _yes_like(intent.get("requires_control"))
    requires_consolidation = _yes_like(intent.get("requires_consolidation"))
    desired_min_ratio = _optional_decimal(intent.get("desired_equity_ratio_min"))
    if requires_control or requires_consolidation:
        requirement_label = "控股" if requires_control else "并表"
        capability = target.get("can_control") if requires_control else target.get("can_consolidate")
        if _yes_like(capability):
            add_dimension(12, "match", match_text=f"满足{requirement_label}要求")
        elif str(capability or "").lower() == "no":
            add_dimension(12, "mismatch", gap_text=f"标的明确不可{requirement_label}", hard=True)
        else:
            add_dimension(12, "unknown", gap_text=f"{requirement_label}能力待确认")
    elif desired_min_ratio is not None:
        transfer_max = _optional_decimal(target.get("transfer_ratio_max"))
        if transfer_max is None:
            add_dimension(12, "unknown", gap_text="标的可转让股比未知")
        elif transfer_max >= desired_min_ratio:
            add_dimension(12, "match", match_text="可转让股比满足买家要求")
        else:
            add_dimension(12, "mismatch", gap_text="可转让股比低于买家要求", hard=True)

    # 上市状态偏好（不沉底）
    preferred_listed_status = intent.get("preferred_listed_status")
    if preferred_listed_status and preferred_listed_status not in {"any", "unknown"}:
        target_listed_status = target.get("listed_status")
        if preferred_listed_status == target_listed_status or (
            preferred_listed_status == "preparing_listing" and target_listed_status == "pre_ipo"
        ):
            add_dimension(8, "match", match_text="上市状态符合偏好")
        elif target_listed_status and target_listed_status != "unknown":
            add_dimension(8, "mismatch", gap_text="上市状态不符合偏好")
        else:
            add_dimension(8, "unknown", gap_text="标的上市状态缺失")

    # 负债率上限（弱信号）
    max_debt_ratio = _optional_decimal(intent.get("max_debt_ratio"))
    if max_debt_ratio is not None:
        target_debt_ratio = _optional_decimal(target.get("current_debt_ratio"))
        if target_debt_ratio is None:
            add_dimension(4, "unknown", gap_text="标的负债率缺失")
        elif target_debt_ratio <= max_debt_ratio:
            add_dimension(4, "match", match_text="负债率未超过买家上限")
        else:
            add_dimension(4, "mismatch", gap_text="负债率超过买家上限")

    if possible > 0:
        score = 100.0 * earned / possible
    else:
        # 买家没有任何结构化要求：给中性分，排序交给语义层
        score = 40.0

    # 加分项（不参与归一化）：二级行业一致、现金流状态
    if intent.get("industry_secondary") and target.get("industry_secondary") == intent.get("industry_secondary"):
        score += 4
        evidence.append(f"二级行业一致：{intent['industry_secondary']}")
    cash_flow_status = str(target.get("cash_flow_status") or "")
    if cash_flow_status == "stable_positive":
        score += 3
        evidence.append("现金流稳定为正")
    elif cash_flow_status == "positive":
        score += 1.5
        evidence.append("现金流为正")

    # 风险提示：买家有风险容忍要求且标的存在风险记录时提示人工核对（不改分）
    if intent.get("major_risk_tolerance_summary") and target.get("risk_summary"):
        gaps.append("买家有风险容忍要求且标的存在风险记录，需人工核对")

    meta = {
        "hard_mismatches": hard_mismatches,
        "excluded_hit": _excluded_industry_hit(target, intent),
        "score_engine": "rule_v2",
    }
    return min(round(score, 2), 100.0), evidence, gaps, meta


def _apply_score_caps(score: float, gaps: list[str], meta: dict[str, Any]) -> float:
    """Sink hard-mismatch and excluded candidates without removing them."""
    capped = score
    hard_count = len(meta.get("hard_mismatches") or [])
    if hard_count:
        capped = min(capped, max(HARD_MISMATCH_CAP_BASE - 5.0 * (hard_count - 1), 20.0))
    excluded_hit = meta.get("excluded_hit")
    if excluded_hit:
        capped = min(capped, EXCLUDED_HIT_CAP)
        gaps.insert(0, f"命中排除项：{excluded_hit}")
    return round(capped, 2)


def _get_buyer_intent_anchor(db: Session, buyer_intent_id: UUID | None) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              bi.id, bi.buyer_party_id, bp.buyer_name,
              bi.intent_name, bi.industry_primary, bi.industry_secondary,
              bi.industries_json, bi.excluded_industries_json, bi.industry_focus_tags_json,
              bi.region_scope_summary, bi.min_revenue_yuan, bi.min_net_profit_yuan, bi.max_pe,
              bi.max_ps, bi.min_net_margin, bi.min_gross_margin,
              bi.min_valuation_yuan, bi.max_valuation_yuan,
              bi.min_market_cap_yuan, bi.max_market_cap_yuan,
              bi.max_debt_ratio, bi.requires_control, bi.requires_consolidation,
              bi.accepts_minority_investment, bi.desired_equity_ratio_min,
              bi.preferred_listed_status, bi.major_risk_tolerance_summary,
              bi.negative_summary, bi.preference_summary
            from buyer_intent bi
            left join buyer_party bp on bp.id = bi.buyer_party_id
            where bi.id = :buyer_intent_id
              and bi.team_id = :team_id
              and bi.workspace_id = :workspace_id
              and bi.deleted_at is null
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Buyer intent not found.")
    return dict(row)


def _get_seller_target_anchor(db: Session, seller_target_id: UUID | None) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, target_name, industry_l1, industry_primary, industry_secondary,
              headquarter_province, headquarter_city,
              current_revenue_yuan, current_net_profit_yuan,
              pe_ratio, valuation_yuan, asking_price_yuan, market_cap_yuan, current_debt_ratio,
              cash_flow_status, can_control, can_consolidate, transfer_ratio_max,
              listed_status, risk_summary, gap_summary, business_summary
            from seller_target
            where id = :seller_target_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seller target not found.")
    return dict(row)


def _create_recommendation_session(
    db: Session,
    *,
    mode: str,
    buyer_intent_id: UUID | None,
    buyer_party_id: UUID | None,
    seller_target_id: UUID | None,
    user_message: str | None,
    initial_snapshot: dict[str, Any],
    candidates: list[dict[str, Any]],
    created_by: UUID,
) -> UUID:
    row = db.execute(
        text(
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
            returning id
            """
        ).bindparams(
            bindparam("initial_condition_snapshot_json", type_=JSONB),
            bindparam("latest_condition_snapshot_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "mode": mode,
            "buyer_intent_id": buyer_intent_id,
            "buyer_party_id": buyer_party_id,
            "seller_target_id": seller_target_id,
            "anonymous_input_snapshot": user_message,
            "initial_condition_snapshot_json": _json_safe(initial_snapshot),
            "latest_condition_snapshot_json": _json_safe(initial_snapshot),
            "created_by": created_by,
            "metadata_json": {
                "source": "recommendation_candidate_api",
                "candidate_count": len(candidates),
            },
        },
    ).mappings().one()
    if user_message:
        _insert_recommendation_message(
            db,
            session_id=row["id"],
            role="user",
            content_type="text",
            content=user_message,
            created_by=created_by,
        )
    return row["id"]


def _insert_recommendation_message(
    db: Session,
    *,
    session_id: UUID,
    role: str,
    content_type: str,
    content: str | dict[str, Any],
    metadata_json: dict[str, Any] | None = None,
    created_by: UUID = DEFAULT_ADMIN_USER_ID,
) -> None:
    db.execute(
        text(
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
            "role": role,
            "content": content if isinstance(content, str) else _json_dumps(content),
            "content_type": content_type,
            "metadata_json": metadata_json or {},
            "created_by": created_by,
        },
    )


def _get_recommendation_session_or_404(db: Session, session_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            f"""
            select {_session_select_columns()}
            from recommendation_session
            where id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {"session_id": session_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation session not found.")
    return dict(row)


def _get_selected_item_or_404(db: Session, selected_item_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            f"""
            select {_selected_item_select_columns()}
            from recommendation_selected_item ri
            left join seller_target st on st.id = ri.seller_target_id
            left join buyer_intent bi on bi.id = ri.buyer_intent_id
            left join buyer_party bp on bp.id = ri.buyer_party_id
            where ri.id = :selected_item_id
              and ri.team_id = :team_id
              and ri.workspace_id = :workspace_id
            """
        ),
        {
            "selected_item_id": selected_item_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Selected item not found.")
    return dict(row)


def _sync_selected_item_to_relation(db: Session, selected_item: dict[str, Any]) -> UUID | None:
    buyer_intent_id = selected_item.get("buyer_intent_id")
    seller_target_id = selected_item.get("seller_target_id")
    if not buyer_intent_id or not seller_target_id:
        return None

    buyer_party_id = selected_item.get("buyer_party_id") or _get_buyer_party_id_for_intent(db, buyer_intent_id)
    relation = _get_or_create_recommendation_relation(
        db,
        buyer_intent_id=buyer_intent_id,
        seller_target_id=seller_target_id,
        buyer_party_id=buyer_party_id,
        session_id=selected_item["session_id"],
    )
    content = _summary_text(
        [
            selected_item.get("match_summary") or "",
            selected_item.get("gap_summary") or "",
            selected_item.get("risk_summary") or "",
        ]
    )
    _insert_recommendation_relation_event(
        db,
        relation_id=relation["id"],
        buyer_intent_id=buyer_intent_id,
        buyer_party_id=buyer_party_id,
        seller_target_id=seller_target_id,
        event_type="recommended",
        title="加入推荐列表",
        content=content or "用户将该候选加入推荐列表。",
        source_id=selected_item["id"],
        metadata_json={
            "recommendation_session_id": str(selected_item["session_id"]),
            "rank_at_selection": selected_item.get("rank_at_selection"),
            "recommendation_level": selected_item.get("recommendation_level"),
            "evidence_snapshot_json": selected_item.get("evidence_snapshot_json") or {},
        },
    )
    db.execute(
        text(
            """
            update buyer_seller_relation
            set first_recommended_at = coalesce(first_recommended_at, now()),
                last_event_at = now(),
                last_event_summary = :last_event_summary,
                updated_at = now(),
                updated_by = :updated_by,
                metadata_json = metadata_json || :metadata_patch
            where id = :relation_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "relation_id": relation["id"],
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "last_event_summary": content or "加入推荐列表",
            "updated_by": DEFAULT_ADMIN_USER_ID,
            "metadata_patch": {"last_recommendation_selected_item_id": str(selected_item["id"])},
        },
    )
    return relation["id"]


def _insert_selected_item_cancel_event(db: Session, selected_item: dict[str, Any]) -> None:
    relation_id = _optional_uuid_from_mapping(selected_item.get("metadata_json"), "relation_id")
    buyer_intent_id = selected_item.get("buyer_intent_id")
    seller_target_id = selected_item.get("seller_target_id")
    if relation_id is None and buyer_intent_id and seller_target_id:
        relation = _get_existing_recommendation_relation(db, buyer_intent_id, seller_target_id)
        relation_id = relation["id"] if relation else None
    if relation_id is None or not buyer_intent_id or not seller_target_id:
        return

    buyer_party_id = selected_item.get("buyer_party_id") or _get_buyer_party_id_for_intent(db, buyer_intent_id)
    _insert_recommendation_relation_event(
        db,
        relation_id=relation_id,
        buyer_intent_id=buyer_intent_id,
        buyer_party_id=buyer_party_id,
        seller_target_id=seller_target_id,
        event_type="internal_note",
        title="取消推荐列表项",
        content="用户从推荐列表中取消了该候选。",
        source_id=selected_item["id"],
        metadata_json={"recommendation_session_id": str(selected_item["session_id"])},
    )
    db.execute(
        text(
            """
            update buyer_seller_relation
            set last_event_at = now(),
                last_event_summary = '取消推荐列表项',
                updated_at = now(),
                updated_by = :updated_by
            where id = :relation_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "relation_id": relation_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "updated_by": DEFAULT_ADMIN_USER_ID,
        },
    )


def _get_or_create_recommendation_relation(
    db: Session,
    *,
    buyer_intent_id: UUID,
    seller_target_id: UUID,
    buyer_party_id: UUID | None,
    session_id: UUID,
) -> dict[str, Any]:
    existing = _get_existing_recommendation_relation(db, buyer_intent_id, seller_target_id)
    if existing:
        return existing

    row = db.execute(
        text(
            """
            insert into buyer_seller_relation (
              team_id, workspace_id, buyer_intent_id, buyer_party_id,
              seller_target_id, status, first_recommended_at,
              created_from_session_id, created_by, updated_by, metadata_json
            )
            values (
              :team_id, :workspace_id, :buyer_intent_id, :buyer_party_id,
              :seller_target_id, 'recommended', now(),
              :session_id, :created_by, :updated_by, :metadata_json
            )
            returning id, status
            """
        ).bindparams(bindparam("metadata_json", type_=JSONB)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "buyer_intent_id": buyer_intent_id,
            "buyer_party_id": buyer_party_id,
            "seller_target_id": seller_target_id,
            "session_id": session_id,
            "created_by": DEFAULT_ADMIN_USER_ID,
            "updated_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {"source": "recommendation_selected_item"},
        },
    ).mappings().one()
    return dict(row)


def _get_existing_recommendation_relation(
    db: Session,
    buyer_intent_id: UUID,
    seller_target_id: UUID,
) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select id, status
            from buyer_seller_relation
            where team_id = :team_id
              and workspace_id = :workspace_id
              and buyer_intent_id = :buyer_intent_id
              and seller_target_id = :seller_target_id
              and deleted_at is null
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "buyer_intent_id": buyer_intent_id,
            "seller_target_id": seller_target_id,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _insert_recommendation_relation_event(
    db: Session,
    *,
    relation_id: UUID,
    buyer_intent_id: UUID,
    buyer_party_id: UUID | None,
    seller_target_id: UUID,
    event_type: str,
    title: str,
    content: str,
    source_id: UUID,
    metadata_json: dict[str, Any],
) -> None:
    db.execute(
        text(
            """
            insert into relation_event (
              team_id, workspace_id, relation_id, buyer_intent_id, buyer_party_id,
              seller_target_id, event_type, event_time, title, content,
              source_type, source_id, metadata_json, created_by
            )
            values (
              :team_id, :workspace_id, :relation_id, :buyer_intent_id, :buyer_party_id,
              :seller_target_id, :event_type, now(), :title, :content,
              'recommendation_selected_item', :source_id, :metadata_json, :created_by
            )
            """
        ).bindparams(bindparam("metadata_json", type_=JSONB)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "relation_id": relation_id,
            "buyer_intent_id": buyer_intent_id,
            "buyer_party_id": buyer_party_id,
            "seller_target_id": seller_target_id,
            "event_type": event_type,
            "title": title,
            "content": content,
            "source_id": source_id,
            "metadata_json": metadata_json,
            "created_by": DEFAULT_ADMIN_USER_ID,
        },
    )


def _get_buyer_party_id_for_intent(db: Session, buyer_intent_id: UUID) -> UUID | None:
    row = db.execute(
        text(
            """
            select buyer_party_id
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
    return row["buyer_party_id"] if row else None


def _optional_uuid_from_mapping(value: Any, key: str) -> UUID | None:
    if not isinstance(value, dict) or not value.get(key):
        return None
    return _optional_uuid(value[key])


def _optional_uuid(value: Any) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _refresh_session_selected_count(db: Session, session_id: UUID) -> None:
    db.execute(
        text(
            """
            update recommendation_session
            set selected_count = (
                  select count(*)
                  from recommendation_selected_item
                  where session_id = :session_id
                    and canceled_at is null
                ),
                updated_at = now()
            where id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {"session_id": session_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    )


def _enqueue_recommendation_report_job(
    db: Session,
    *,
    report_id: UUID,
    session_id: UUID,
    selected_item_ids: list[str],
) -> UUID:
    row = db.execute(
        text(
            """
            insert into background_job (
              team_id, workspace_id, job_type, priority, queue_name,
              entity_type, entity_id, idempotency_key, payload_json,
              max_attempts, created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, 'recommendation_report_generate', 120, 'llm',
              'recommendation_report', :report_id, :idempotency_key, :payload_json,
              1, :created_by, :metadata_json
            )
            returning id
            """
        ).bindparams(
            bindparam("payload_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "report_id": report_id,
            "idempotency_key": f"recommendation_report_generate:{report_id}",
            "payload_json": {
                "report_id": str(report_id),
                "session_id": str(session_id),
                "selected_item_ids": selected_item_ids,
            },
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {"source": "recommendation_report_job_api"},
        },
    ).mappings().one()
    return row["id"]


def _enqueue_recommendation_rerank_job(
    db: Session,
    *,
    session_id: UUID,
    mode: str,
    anchor: dict[str, Any],
    candidates: list[dict[str, Any]],
    idempotency_suffix: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> UUID:
    deep_eval_candidates = candidates[:DEEP_EVAL_CANDIDATE_LIMIT]
    payload = _json_loads(
        _json_dumps(
            {
                "session_id": session_id,
                "mode": mode,
                "query": _build_rerank_query(mode=mode, anchor=anchor),
                "anchor": anchor,
                "candidates": deep_eval_candidates,
            }
        )
    )
    row = db.execute(
        text(
            """
            insert into background_job (
              team_id, workspace_id, job_type, priority, queue_name,
              entity_type, entity_id, idempotency_key, payload_json,
              max_attempts, created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, 'recommendation_deep_eval', 110, 'llm',
              'recommendation_session', :session_id, :idempotency_key, :payload_json,
              2, :created_by, :metadata_json
            )
            returning id
            """
        ).bindparams(
            bindparam("payload_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "session_id": session_id,
            "idempotency_key": (
                f"recommendation_deep_eval:{session_id}:{idempotency_suffix}"
                if idempotency_suffix
                else f"recommendation_deep_eval:{session_id}"
            ),
            "payload_json": payload,
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": metadata_json or {"source": "recommendation_candidate_api"},
        },
    ).mappings().one()
    return row["id"]


def _build_rerank_query(*, mode: str, anchor: dict[str, Any]) -> str:
    if mode == "buyer_to_target":
        parts = [
            anchor.get("intent_name"),
            anchor.get("industry_primary"),
            anchor.get("industry_secondary"),
            anchor.get("region_scope_summary"),
            anchor.get("preference_summary"),
            anchor.get("negative_summary"),
        ]
    else:
        parts = [
            anchor.get("target_name"),
            anchor.get("industry_primary"),
            anchor.get("industry_secondary"),
            anchor.get("headquarter_province"),
            anchor.get("headquarter_city"),
            anchor.get("business_summary"),
            anchor.get("risk_summary"),
        ]
    return "\n".join(str(part) for part in parts if part)


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


def _ensure_recommendation_report_visible(db: Session, current_user: CurrentUser, report_id: UUID) -> None:
    if not owner_scope_required(current_user):
        return
    row = db.execute(
        text(
            f"""
            select 1
            from recommendation_report rr
            where rr.id = :report_id
              and rr.team_id = :team_id
              and rr.workspace_id = :workspace_id
              and {recommendation_report_visible_sql("rr")}
            """
        ),
        {
            "report_id": report_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "scope_user_id": current_user.user_id,
        },
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation report not found.")


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


def _refresh_session_report_count(db: Session, session_id: UUID) -> None:
    db.execute(
        text(
            """
            update recommendation_session
            set report_count = (
                  select count(*)
                  from recommendation_report
                  where session_id = :session_id
                    and status <> 'archived'
                ),
                updated_at = now()
            where id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {"session_id": session_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    )


def _touch_recommendation_session(db: Session, session_id: UUID) -> None:
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


def _session_select_columns() -> str:
    return """
      id, mode, buyer_intent_id, buyer_party_id, seller_target_id, status,
      selected_count, report_count, anonymous_input_snapshot,
      initial_condition_snapshot_json, latest_condition_snapshot_json,
      created_at::text as created_at, updated_at::text as updated_at, metadata_json
    """


def _session_overview_select_columns() -> str:
    return """
      rs.id, rs.mode, rs.buyer_intent_id, rs.buyer_party_id, rs.seller_target_id, rs.status,
      rs.selected_count, rs.report_count, rs.anonymous_input_snapshot,
      rs.initial_condition_snapshot_json, rs.latest_condition_snapshot_json,
      rs.created_at::text as created_at, rs.updated_at::text as updated_at, rs.metadata_json,
      bi.intent_name as buyer_intent_name,
      bp.buyer_name,
      st.target_name as seller_target_name
    """


def _session_returning_statement(prefix_sql: str):
    return text(f"{prefix_sql} returning {_session_select_columns()}")


def _message_select_columns() -> str:
    return """
      id, session_id, role, content, content_type,
      metadata_json, created_at::text as created_at
    """


def _message_returning_statement(prefix_sql: str):
    return text(f"{prefix_sql} returning {_message_select_columns()}")


def _selected_item_select_columns() -> str:
    return """
      ri.id, ri.session_id, ri.mode,
      ri.seller_target_id, st.target_name as seller_target_name,
      ri.buyer_intent_id, bi.intent_name as buyer_intent_name,
      ri.buyer_party_id, bp.buyer_name,
      ri.rank_at_selection, ri.recommendation_level, ri.match_summary,
      ri.risk_summary, ri.gap_summary, ri.reason_snapshot,
      ri.evidence_snapshot_json, ri.selected_at::text as selected_at,
      ri.canceled_at::text as canceled_at, ri.metadata_json
    """


def _selected_item_returning_statement(prefix_sql: str):
    return text(
        f"""
        with changed as (
          {prefix_sql}
          returning *
        )
        select
          changed.id, changed.session_id, changed.mode,
          changed.seller_target_id, st.target_name as seller_target_name,
          changed.buyer_intent_id, bi.intent_name as buyer_intent_name,
          changed.buyer_party_id, bp.buyer_name,
          changed.rank_at_selection, changed.recommendation_level,
          changed.match_summary, changed.risk_summary, changed.gap_summary,
          changed.reason_snapshot, changed.evidence_snapshot_json,
          changed.selected_at::text as selected_at,
          changed.canceled_at::text as canceled_at, changed.metadata_json
        from changed
        left join seller_target st on st.id = changed.seller_target_id
        left join buyer_intent bi on bi.id = changed.buyer_intent_id
        left join buyer_party bp on bp.id = changed.buyer_party_id
        """
    )


def _report_select_columns() -> str:
    return """
      id, session_id, report_type, selected_item_ids_json, title,
      markdown_content, file_path, file_format, status,
      generated_by_model, prompt_version,
      created_at::text as created_at, metadata_json
    """


def _report_returning_statement(prefix_sql: str):
    return text(f"{prefix_sql} returning {_report_select_columns()}")


def _recommendation_level(score: float) -> str:
    if score >= 80:
        return "strong"
    if score >= 60:
        return "recommended"
    if score >= 35:
        return "possible"
    return "weak"


def _summary_text(items: list[str], *, fallback: str | None = None) -> str | None:
    if items:
        return "；".join(items[:4])
    return fallback


def _yes_like(value: Any) -> bool:
    return str(value or "").lower() in {"yes", "likely", "true", "1"}


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, UUID):
            result[key] = str(item)
        elif isinstance(item, Decimal):
            result[key] = float(item)
        else:
            result[key] = item
    return result


def _json_dumps(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


def _json_loads(value: str) -> dict[str, Any]:
    import json

    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
