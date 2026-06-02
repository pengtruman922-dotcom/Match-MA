from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


class RecommendationCandidateRequest(BaseModel):
    mode: str = Field(pattern="^(buyer_to_target|target_to_buyer)$")
    buyer_intent_id: UUID | None = None
    seller_target_id: UUID | None = None
    limit: int = Field(default=20, ge=1, le=50)
    create_session: bool = True
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


class RecommendationSessionBundleOut(BaseModel):
    session: RecommendationSessionOut
    messages: list[RecommendationMessageOut]
    selected_items: list[RecommendationSelectedItemOut]
    reports: list[RecommendationReportOut]
    debug: dict[str, Any]


@router.post("/candidates", response_model=RecommendationCandidateResponse)
def generate_recommendation_candidates(
    payload: RecommendationCandidateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if payload.mode == "buyer_to_target":
        anchor = _get_buyer_intent_anchor(db, payload.buyer_intent_id)
        candidates = _candidate_targets_for_intent(db, anchor, payload.limit)
        session_anchor = {
            "buyer_intent_id": payload.buyer_intent_id,
            "buyer_party_id": anchor.get("buyer_party_id"),
            "seller_target_id": None,
        }
    else:
        anchor = _get_seller_target_anchor(db, payload.seller_target_id)
        candidates = _candidate_intents_for_target(db, anchor, payload.limit)
        session_anchor = {
            "buyer_intent_id": None,
            "buyer_party_id": None,
            "seller_target_id": payload.seller_target_id,
        }

    session_id = None
    if payload.create_session:
        session_id = _create_recommendation_session(
            db,
            mode=payload.mode,
            user_message=payload.user_message,
            initial_snapshot=anchor,
            candidates=candidates,
            **session_anchor,
        )
        _insert_recommendation_message(
            db,
            session_id=session_id,
            role="tool",
            content_type="json",
            content={
                "mode": payload.mode,
                "candidate_count": len(candidates),
                "candidates": candidates,
            },
        )
        db.commit()

    embedding_used = _candidates_have_embedding(candidates)
    return {
        "session_id": session_id,
        "mode": payload.mode,
        "candidates": candidates,
        "debug": {
            "engine": "rule_sql_embedding_v0.2" if embedding_used else "rule_sql_v0.1",
            "llm_rerank": False,
            "embedding_similarity": embedding_used,
            "notes": [
                "本版使用结构化规则召回；当双方 search_doc 都已有 embedding 时，叠加向量相似度加权排序。",
            ],
        },
    }


@router.post("/sessions", response_model=RecommendationSessionOut, status_code=status.HTTP_201_CREATED)
def create_recommendation_session(
    payload: RecommendationSessionCreate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": payload.metadata_json,
        },
    ).mappings().one()
    db.commit()
    return dict(row)


@router.get("/sessions", response_model=list[RecommendationSessionOut])
def list_recommendation_sessions(
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


@router.get("/sessions/{session_id}", response_model=RecommendationSessionOut)
def get_recommendation_session(session_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _get_recommendation_session_or_404(db, session_id)


@router.get("/sessions/{session_id}/bundle", response_model=RecommendationSessionBundleOut)
def get_recommendation_session_bundle(
    session_id: UUID,
    db: Session = Depends(get_db),
    include_canceled: bool = Query(default=True),
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
    return {
        "session": session,
        "messages": messages,
        "selected_items": selected_items,
        "reports": reports,
        "debug": {
            "selected_count": len([item for item in selected_items if item.get("canceled_at") is None]),
            "canceled_selected_count": len([item for item in selected_items if item.get("canceled_at") is not None]),
            "message_count": len(messages),
            "report_count": len(reports),
            "engine_hint": "rule_sql_embedding_v0.2",
        },
    }


@router.get("/sessions/{session_id}/messages", response_model=list[RecommendationMessageOut])
def list_recommendation_messages(
    session_id: UUID,
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
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
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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
            "created_by": DEFAULT_ADMIN_USER_ID,
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
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _get_recommendation_session_or_404(db, session_id)
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
            "selected_by": DEFAULT_ADMIN_USER_ID,
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
    db: Session = Depends(get_db),
    include_canceled: bool = Query(default=False),
) -> list[dict[str, Any]]:
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
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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
            "created_by": DEFAULT_ADMIN_USER_ID,
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
    )
    _refresh_session_report_count(db, session_id)
    db.commit()
    return report


@router.get("/sessions/{session_id}/reports", response_model=list[RecommendationReportOut])
def list_recommendation_reports(
    session_id: UUID,
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    _get_recommendation_session_or_404(db, session_id)
    return _list_recommendation_reports(db, session_id=session_id, limit=limit, offset=offset)


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


@router.get("/reports/{report_id}", response_model=RecommendationReportOut)
def get_recommendation_report(report_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
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
def cancel_selected_item(selected_item_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    current = _get_selected_item_or_404(db, selected_item_id)
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
            "canceled_by": DEFAULT_ADMIN_USER_ID,
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
              st.industry_primary,
              st.industry_secondary,
              st.headquarter_province,
              st.headquarter_city,
              st.current_net_profit_yuan,
              st.pe_ratio,
              st.valuation_yuan,
              st.can_control,
              st.can_consolidate,
              st.listed_status,
              st.risk_summary,
              st.gap_summary,
              st.business_summary,
              case
                when std.embedding is not null and bid.embedding is not null
                then 1 - (std.embedding <=> bid.embedding)
                else null
              end as embedding_similarity,
              exists(
                select 1
                from buyer_intent_target_exclusion x
                where x.buyer_intent_id = :buyer_intent_id
                  and x.seller_target_id = st.id
                  and x.active = true
                  and x.canceled_at is null
              ) as is_excluded
            from seller_target st
            left join seller_target_search_doc std
              on std.seller_target_id = st.id
             and std.doc_type = 'profile'
            left join buyer_intent_search_doc bid
              on bid.buyer_intent_id = :buyer_intent_id
            where st.team_id = :team_id
              and st.workspace_id = :workspace_id
              and st.deleted_at is null
              and st.recommendation_status = 'recommendable'
            order by
              case when st.industry_primary = :industry_primary then 0 else 1 end,
              st.current_net_profit_yuan desc nulls last,
              st.updated_at desc
            limit :candidate_pool_limit
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "buyer_intent_id": intent["id"],
            "industry_primary": intent.get("industry_primary"),
            "candidate_pool_limit": max(limit * 5, 50),
        },
    ).mappings().all()

    candidates: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if item.pop("is_excluded"):
            continue
        rule_score, evidence, gaps = _score_target_against_intent(item, intent)
        embedding_similarity = _optional_float(item.get("embedding_similarity"))
        score, embedding_boost = _apply_embedding_score(rule_score, evidence, embedding_similarity)
        if score < 10:
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
                        "embedding_similarity": embedding_similarity,
                        "embedding_boost": embedding_boost,
                        "final_score": score,
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
              bi.region_scope_summary,
              bi.min_net_profit_yuan,
              bi.max_pe,
              bi.max_valuation_yuan,
              bi.requires_control,
              bi.requires_consolidation,
              bi.accepts_minority_investment,
              bi.preferred_listed_status,
              bi.negative_summary,
              bi.preference_summary,
              case
                when bid.embedding is not null and std.embedding is not null
                then 1 - (bid.embedding <=> std.embedding)
                else null
              end as embedding_similarity,
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
            left join buyer_intent_search_doc bid
              on bid.buyer_intent_id = bi.id
            left join seller_target_search_doc std
              on std.seller_target_id = :seller_target_id
             and std.doc_type = 'profile'
            where bi.team_id = :team_id
              and bi.workspace_id = :workspace_id
              and bi.deleted_at is null
              and bi.status = 'active'
            order by
              case when bi.industry_primary = :industry_primary then 0 else 1 end,
              bi.updated_at desc
            limit :candidate_pool_limit
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "seller_target_id": target["id"],
            "industry_primary": target.get("industry_primary"),
            "candidate_pool_limit": max(limit * 5, 50),
        },
    ).mappings().all()

    candidates: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if item.pop("is_excluded"):
            continue
        rule_score, evidence, gaps = _score_target_against_intent(target, item)
        embedding_similarity = _optional_float(item.get("embedding_similarity"))
        score, embedding_boost = _apply_embedding_score(rule_score, evidence, embedding_similarity)
        if score < 10:
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
                        "embedding_similarity": embedding_similarity,
                        "embedding_boost": embedding_boost,
                        "final_score": score,
                    },
                },
            }
        )

    candidates.sort(key=lambda candidate: candidate["score"], reverse=True)
    for index, candidate in enumerate(candidates[:limit], start=1):
        candidate["rank"] = index
    return candidates[:limit]


def _score_target_against_intent(
    target: dict[str, Any],
    intent: dict[str, Any],
) -> tuple[float, list[str], list[str]]:
    score = 0.0
    evidence: list[str] = []
    gaps: list[str] = []

    if intent.get("industry_primary") and target.get("industry_primary") == intent.get("industry_primary"):
        score += 30
        evidence.append(f"一级行业匹配：{intent['industry_primary']}")
    elif intent.get("industry_primary"):
        gaps.append("一级行业不完全匹配")
    else:
        score += 8

    if intent.get("industry_secondary") and target.get("industry_secondary") == intent.get("industry_secondary"):
        score += 12
        evidence.append(f"二级行业匹配：{intent['industry_secondary']}")

    region_scope = intent.get("region_scope_summary") or ""
    target_region = "".join(str(item) for item in [target.get("headquarter_province"), target.get("headquarter_city")] if item)
    if region_scope and target_region and any(part and part in region_scope for part in [target.get("headquarter_province"), target.get("headquarter_city")]):
        score += 15
        evidence.append(f"区域匹配：{target_region}")
    elif region_scope:
        gaps.append("区域需要人工复核")

    min_profit = _optional_decimal(intent.get("min_net_profit_yuan"))
    target_profit = _optional_decimal(target.get("current_net_profit_yuan"))
    if min_profit is not None and target_profit is not None:
        if target_profit >= min_profit:
            score += 18
            evidence.append("净利润达到门槛")
        else:
            gaps.append("净利润低于买家门槛")
    elif min_profit is None:
        score += 6
    else:
        gaps.append("标的净利润缺失")

    max_pe = _optional_decimal(intent.get("max_pe"))
    target_pe = _optional_decimal(target.get("pe_ratio"))
    if max_pe is not None and target_pe is not None:
        if target_pe <= max_pe:
            score += 12
            evidence.append("PE 未超过上限")
        else:
            gaps.append("PE 超过买家上限")
    elif max_pe is None:
        score += 4
    else:
        gaps.append("标的 PE 缺失")

    if _yes_like(intent.get("requires_consolidation")):
        if _yes_like(target.get("can_consolidate")):
            score += 12
            evidence.append("满足并表要求")
        else:
            gaps.append("并表能力待确认")
    if _yes_like(intent.get("requires_control")):
        if _yes_like(target.get("can_control")):
            score += 10
            evidence.append("满足控股要求")
        else:
            gaps.append("控股能力待确认")

    max_valuation = _optional_decimal(intent.get("max_valuation_yuan"))
    target_valuation = _optional_decimal(target.get("valuation_yuan"))
    if max_valuation is not None and target_valuation is not None:
        if target_valuation <= max_valuation:
            score += 6
            evidence.append("估值未超过上限")
        else:
            gaps.append("估值超过买家上限")

    return min(score, 100.0), evidence, gaps


def _get_buyer_intent_anchor(db: Session, buyer_intent_id: UUID | None) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              bi.id, bi.buyer_party_id, bp.buyer_name,
              bi.intent_name, bi.industry_primary, bi.industry_secondary,
              bi.region_scope_summary, bi.min_net_profit_yuan, bi.max_pe,
              bi.max_valuation_yuan, bi.requires_control, bi.requires_consolidation,
              bi.accepts_minority_investment, bi.preferred_listed_status,
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
              id, target_name, industry_primary, industry_secondary,
              headquarter_province, headquarter_city, current_net_profit_yuan,
              pe_ratio, valuation_yuan, can_control, can_consolidate,
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
            "created_by": DEFAULT_ADMIN_USER_ID,
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
            "created_by": DEFAULT_ADMIN_USER_ID,
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
    try:
        return UUID(str(value[key]))
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


def _apply_embedding_score(
    rule_score: float,
    evidence: list[str],
    embedding_similarity: float | None,
) -> tuple[float, float | None]:
    if embedding_similarity is None:
        return min(rule_score, 100.0), None

    normalized_similarity = max(0.0, min(float(embedding_similarity), 1.0))
    boost = round(normalized_similarity * 10, 2)
    evidence.append(f"语义相似度：{normalized_similarity:.2f}")
    return min(rule_score + boost, 100.0), boost


def _candidates_have_embedding(candidates: list[dict[str, Any]]) -> bool:
    for candidate in candidates:
        score_json = candidate.get("evidence_json", {}).get("score", {})
        if score_json.get("embedding_similarity") is not None:
            return True
    return False


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
