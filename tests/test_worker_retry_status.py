from uuid import UUID

from backend.app.jobs.queue import JobClaim
from backend.app.worker import _mark_related_business_update_failed_if_final


class _MappingResult:
    def __init__(self, row: dict | None = None) -> None:
        self.row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row


class _FakeDb:
    def __init__(self, job_status: str) -> None:
        self.job_status = job_status
        self.execute_calls = []

    def execute(self, statement, params=None):
        self.execute_calls.append((str(statement), params or {}))
        if len(self.execute_calls) == 1:
            return _MappingResult({"status": self.job_status})
        return _MappingResult()


JOB_ID = UUID("00000000-0000-0000-0000-000000000001")
BUSINESS_UPDATE_ID = UUID("00000000-0000-0000-0000-000000000002")


def _business_update_job() -> JobClaim:
    return JobClaim(
        id=JOB_ID,
        job_type="business_update_extract_actions",
        queue_name="llm",
        entity_type="business_update",
        entity_id=BUSINESS_UPDATE_ID,
        correlation_id=None,
        payload_json={},
        attempt_count=1,
        max_attempts=3,
    )


def test_retry_waiting_business_update_job_does_not_mark_update_failed() -> None:
    db = _FakeDb("retry_waiting")

    _mark_related_business_update_failed_if_final(db, _business_update_job(), "timeout")

    assert len(db.execute_calls) == 1


def test_final_failed_business_update_job_marks_update_failed() -> None:
    db = _FakeDb("failed")

    _mark_related_business_update_failed_if_final(db, _business_update_job(), "timeout")

    assert len(db.execute_calls) == 2
    update_sql, params = db.execute_calls[1]
    assert "set processing_status = 'failed'" in update_sql
    assert params["metadata_patch"]["last_processing_result"] == "failed"
