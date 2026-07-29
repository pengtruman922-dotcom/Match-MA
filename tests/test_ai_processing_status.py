"""The single AI-processing state shown in the target list (施工单 0727 · T2).

One column answers one question: "我刚才发起的那个操作跑完没有". It merges two
asynchronous pipelines — 解析 (``information_status``) and 调研
(``last_research_at`` / ``research_last_outcome``).

The decision table lives in Python and is returned by the API.  The frontend
module is intentionally a renderer only, which prevents list/detail drift.
"""

import inspect
from pathlib import Path
from uuid import UUID

import pytest

from backend.app.services.seller_target_status import (
    AIProcessingBusyError,
    AI_PROCESSING_COMPLETED,
    AI_PROCESSING_NEVER,
    AI_PROCESSING_PARSE_FAILED,
    AI_PROCESSING_PARSING,
    AI_PROCESSING_RESEARCH_MAPPING,
    AI_PROCESSING_RESEARCH_FAILED,
    AI_PROCESSING_RESEARCH_QUEUED,
    AI_PROCESSING_RESEARCHING,
    ai_processing_state,
    acquire_ai_processing,
)
from backend.app.api.routes.research import _enqueue_seller_research_job
from backend.app.api.routes.seller_targets import parse_seller_target

REPO = Path(__file__).resolve().parents[1]
FRONTEND_MODULE = REPO / "frontend/src/features/targets/aiProcessing.ts"


def _target(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "information_status": "normal",
        "last_parse_at": None,
        "last_research_at": None,
        "research_last_outcome": None,
    }
    base.update(overrides)
    return base


CASES: tuple[tuple[str, dict[str, object], str], ...] = (
    (
        "parsing_wins",
        {"information_status": "parsing"},
        AI_PROCESSING_PARSING,
    ),
    (
        "researching_wins_over_completed_research",
        {
            "information_status": "researching",
            "last_research_at": "2026-07-26T10:00:00+00:00",
            "research_last_outcome": "found",
        },
        AI_PROCESSING_RESEARCHING,
    ),
    (
        "queued_research_is_not_running",
        {
            "information_status": "researching",
            "research_job_type": "seller_target_research",
            "research_job_status": "queued",
        },
        AI_PROCESSING_RESEARCH_QUEUED,
    ),
    (
        "running_research_uses_running_phase",
        {
            "information_status": "researching",
            "research_job_type": "seller_target_research",
            "research_job_status": "running",
        },
        AI_PROCESSING_RESEARCHING,
    ),
    (
        "mapper_phase_is_visible",
        {
            "information_status": "researching",
            "research_job_type": "seller_target_research_map",
            "research_job_status": "queued",
        },
        AI_PROCESSING_RESEARCH_MAPPING,
    ),
    (
        "parse_failed",
        {"information_status": "parse_failed"},
        AI_PROCESSING_PARSE_FAILED,
    ),
    (
        "parse_failure_outranks_earlier_successful_research",
        {
            "information_status": "parse_failed",
            "last_parse_at": "2026-07-27T10:00:00+00:00",
            "last_research_at": "2026-07-26T10:00:00+00:00",
            "research_last_outcome": "found",
        },
        AI_PROCESSING_PARSE_FAILED,
    ),
    (
        "later_research_success_clears_older_parse_failure_badge",
        {
            "information_status": "parse_failed",
            "last_parse_at": "2026-07-26T10:00:00+00:00",
            "last_research_at": "2026-07-27T10:00:00+00:00",
            "research_last_outcome": "found",
        },
        AI_PROCESSING_COMPLETED,
    ),
    (
        "later_parse_success_clears_older_research_failure_badge",
        {
            "information_status": "normal",
            "last_parse_at": "2026-07-27T10:00:00+00:00",
            "last_research_at": "2026-07-26T10:00:00+00:00",
            "research_last_outcome": "failed",
        },
        AI_PROCESSING_COMPLETED,
    ),
    (
        "research_failed",
        {
            "information_status": "normal",
            "last_research_at": "2026-07-27T09:00:00+00:00",
            "research_last_outcome": "failed",
        },
        AI_PROCESSING_RESEARCH_FAILED,
    ),
    (
        "no_public_information_is_completed_not_failed",
        {
            "information_status": "normal",
            "last_research_at": "2026-07-27T09:00:00+00:00",
            "research_last_outcome": "no_public_information",
        },
        AI_PROCESSING_COMPLETED,
    ),
    (
        "parsed_without_research_is_completed",
        {"information_status": "normal"},
        AI_PROCESSING_COMPLETED,
    ),
    (
        "never_processed",
        {"information_status": "insufficient"},
        AI_PROCESSING_NEVER,
    ),
    (
        "research_only_target_is_completed",
        {
            "information_status": "insufficient",
            "last_research_at": "2026-07-27T09:00:00+00:00",
            "research_last_outcome": "found",
        },
        AI_PROCESSING_COMPLETED,
    ),
    (
        "retired_pending_review_reads_as_completed",
        {"information_status": "pending_review"},
        AI_PROCESSING_COMPLETED,
    ),
)


@pytest.mark.parametrize(
    ("name", "overrides", "expected"),
    CASES,
    ids=[case[0] for case in CASES],
)
def test_ai_processing_state(name: str, overrides: dict[str, object], expected: str) -> None:
    assert ai_processing_state(_target(**overrides)) == expected


def test_frontend_renders_server_state_without_reimplementing_decision_table() -> None:
    source = FRONTEND_MODULE.read_text(encoding="utf-8")
    for state in (
        AI_PROCESSING_PARSING,
        AI_PROCESSING_RESEARCH_QUEUED,
        AI_PROCESSING_RESEARCHING,
        AI_PROCESSING_RESEARCH_MAPPING,
        AI_PROCESSING_PARSE_FAILED,
        AI_PROCESSING_RESEARCH_FAILED,
        AI_PROCESSING_COMPLETED,
        AI_PROCESSING_NEVER,
    ):
        assert f"'{state}'" in source, f"前端缺少 AI 处理状态 {state}"
    assert "return target.ai_processing_state" in source
    assert "target.information_status" not in source


def test_research_enqueue_marks_target_researching() -> None:
    """调研入队必须置位，否则列表上完全看不出调研跑没跑。"""
    source = (REPO / "backend/app/api/routes/research.py").read_text(encoding="utf-8")
    assert "researching" in source, "调研入队未写 information_status='researching'"


def test_research_outcome_releases_researching() -> None:
    source = (REPO / "backend/app/jobs/handlers/research.py").read_text(encoding="utf-8")
    assert "_mark_research_outcome" in source
    assert "researching" in source, "调研收尾未把 researching 释放回 normal"


def test_research_stays_busy_until_mapper_finishes() -> None:
    research_source = (REPO / "backend/app/jobs/handlers/research.py").read_text(encoding="utf-8")
    mapper_branch = research_source.split("if _research_mapper_available(db):", 1)[1].split(
        "# 未配置映射节点时", 1
    )[0]
    dispatch_source = (REPO / "backend/app/jobs/handlers/dispatch.py").read_text(encoding="utf-8")
    route_source = (REPO / "backend/app/api/routes/research.py").read_text(encoding="utf-8")

    assert "_mark_research_outcome" not in mapper_branch
    assert "seller_target_research_map" in dispatch_source
    assert '_mark_research_outcome(db, job.entity_id, "failed")' in dispatch_source
    assert "job_type in ('seller_target_research', 'seller_target_research_map')" in route_source


def test_batch_research_dialog_shows_all_groups_without_outcome_details() -> None:
    source = (REPO / "frontend/src/features/targets/BatchResearchDialog.tsx").read_text(encoding="utf-8")

    for label in ("即将调研", "正在调研", "天内已经调研过"):
        assert label in source
    assert "OUTCOME_LABELS" not in source
    assert "research_last_outcome === 'failed'" in source
    assert "new Set(ready.map((item) => item.id))" in source
    assert "checked={selectedIds.has(item.id)}" in source


def test_target_api_reads_the_active_research_job_phase() -> None:
    source = (REPO / "backend/app/api/routes/seller_targets.py").read_text(encoding="utf-8")

    assert "ACTIVE_RESEARCH_JOB_LATERAL_SQL" in source
    assert "active_research_job.job_type as research_job_type" in source
    assert "active_research_job.status as research_job_status" in source


def test_business_update_no_longer_parks_targets_in_pending_review() -> None:
    source = (REPO / "backend/app/jobs/handlers/business_update.py").read_text(encoding="utf-8")
    assert "has_pending_bound_action" not in source
    assert "pending_review=" not in source


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value


class _AcquireDB:
    def __init__(self, values: list[object]) -> None:
        self.values = values
        self.calls = 0

    def execute(self, *_args: object, **_kwargs: object) -> _ScalarResult:
        value = self.values[self.calls]
        self.calls += 1
        return _ScalarResult(value)


def test_ai_processing_acquire_is_atomic_and_reports_busy_state() -> None:
    db = _AcquireDB([None, "researching"])
    with pytest.raises(AIProcessingBusyError, match="调研"):
        acquire_ai_processing(
            db,  # type: ignore[arg-type]
            seller_target_id=UUID("00000000-0000-0000-0000-000000000001"),
            desired_status="parsing",
            actor_user_id=UUID("00000000-0000-0000-0000-000000000002"),
        )
    assert db.calls == 2


def test_api_reserves_ai_state_before_inserting_job() -> None:
    for function in (_enqueue_seller_research_job, parse_seller_target):
        source = inspect.getsource(function)
        assert source.index("acquire_ai_processing(") < source.index("insert into background_job")


def test_parse_success_and_failure_paths_record_terminal_time() -> None:
    parse_source = (REPO / "backend/app/jobs/handlers/seller_target_parse.py").read_text(
        encoding="utf-8"
    )
    apply_source = (REPO / "backend/app/services/extracted_action_apply.py").read_text(
        encoding="utf-8"
    )
    route_source = (REPO / "backend/app/api/routes/seller_targets.py").read_text(
        encoding="utf-8"
    )
    assert "mark_parse_completed(" in parse_source
    assert parse_source.count("last_parse_at = now()") >= 2
    assert "mark_parse_completed(" in apply_source
    assert "last_parse_at::text as last_parse_at" in route_source
