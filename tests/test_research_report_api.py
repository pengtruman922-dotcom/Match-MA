from uuid import UUID
from pathlib import Path

from backend.app.api.routes.research import _research_report_output


def test_report_returns_mapper_input_without_rewriting_it() -> None:
    raw = '{"profile_sections":[],"coverage":{"no_public_information":["identity"]}}'
    row = {
        "id": UUID("00000000-0000-0000-0000-000000000001"),
        "seller_target_id": UUID("00000000-0000-0000-0000-000000000002"),
        "status": "succeeded",
        "result_json": {"report_text": "stale fallback"},
        "created_at": "2026-07-29T10:00:00+00:00",
        "finished_at": "2026-07-29T10:10:00+00:00",
        "raw_output_text": raw,
        "parsed_output_json": {"profile_sections": [], "coverage": {"no_public_information": ["identity"]}},
        "prompt_version": "0.4.0",
        "mapper_status": "succeeded",
        "trace_metadata_json": {
            "searched_queries": ["测试公司"],
            "search_observations": [{"query": "测试公司", "returned_count": 0, "matched_result_count": 0}],
            "internal_debug_value": "must not leak",
        },
    }

    output = _research_report_output(row)

    assert output["raw_output_text"] == raw
    assert output["agent_output_json"] == row["parsed_output_json"]
    assert output["execution_trace"]["searched_queries"] == ["测试公司"]
    assert "internal_debug_value" not in output["execution_trace"]


def test_report_falls_back_to_job_result_for_historical_runs() -> None:
    row = {
        "id": UUID("00000000-0000-0000-0000-000000000001"),
        "seller_target_id": UUID("00000000-0000-0000-0000-000000000002"),
        "status": "succeeded",
        "result_json": {"report_text": "历史原始输出", "agent_output_json": {"ok": True}},
        "created_at": "2026-07-29T10:00:00+00:00",
        "finished_at": None,
        "raw_output_text": None,
        "parsed_output_json": None,
        "prompt_version": None,
        "mapper_status": None,
        "trace_metadata_json": {},
    }

    output = _research_report_output(row)

    assert output["raw_output_text"] == "历史原始输出"
    assert output["agent_output_json"] == {"ok": True}


def test_frontend_labels_mapper_input_as_raw_output_and_does_not_rewrite_it() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "frontend/src/features/targets/ResearchReportDrawer.tsx"
    ).read_text(encoding="utf-8")

    assert "Agent 原始输出" in source
    assert "仅做 JSON 缩进，不增删或改写内容" in source
    assert "readableAgentOutput" not in source
