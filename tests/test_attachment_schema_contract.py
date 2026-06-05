from pathlib import Path


def test_attachment_worker_updates_do_not_reference_missing_updated_at() -> None:
    source = Path("backend/app/jobs/handlers.py").read_text(encoding="utf-8")
    marker = "def _patch_attachment_metadata"
    function_source = source[source.index(marker): source.index("def _enqueue_doc2x_poll_job")]

    assert "updated_at = now()" not in function_source
