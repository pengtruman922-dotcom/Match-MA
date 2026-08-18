"""Writer v0.2.0 publication and answer-brief-v2 boundaries."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _prompt_module():
    path = ROOT / "scripts" / "publish_recommendation_writer_v020_prompt.py"
    spec = importlib.util.spec_from_file_location("publish_recommendation_writer_v020_prompt", path)
    loaded = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(loaded)
    return loaded


def test_writer_v020_variables_match_node_spec_and_render() -> None:
    from backend.app.ai.prompting import extract_template_variables, render_template
    from backend.app.registry.nodes import node_by_name

    prompt = _prompt_module()
    spec = node_by_name(prompt.NODE_NAME)
    assert spec is not None
    assert prompt.VERSION == "v0.2.0"
    assert set(extract_template_variables(prompt.SYSTEM_PROMPT, prompt.USER_PROMPT_TEMPLATE)) == set(
        spec.prompt_variables
    ) == {"answer_brief_json"}
    value = json.dumps({"brief_version": 2, "candidate_pool_count": 30}, ensure_ascii=False)
    rendered = render_template(prompt.SYSTEM_PROMPT, {"answer_brief_json": value}) + render_template(
        prompt.USER_PROMPT_TEMPLATE, {"answer_brief_json": value}
    )
    assert "{{ answer_brief_json }}" not in rendered
    assert value in rendered


def test_writer_v020_spells_out_the_final_contract() -> None:
    prompt = _prompt_module()
    body = prompt.SYSTEM_PROMPT + prompt.USER_PROMPT_TEMPLATE

    for phrase in (
        "只读代码提供的 answer brief v2",
        "本轮汇总了 N 家去重候选",
        "绝不能把某次 `screening_runs[].matched_count`",
        "strength=required",
        "仅供参考、需核实",
        "原始数字只能引用候选的 `facts`",
        "不展示内部深评等级、分数",
        "不输出 id、URL、Markdown 链接",
        "不要引用、复述或改写到正文结尾",
        "正与其他买家深入推进",
        "不为凑字数灌水",
    ):
        assert phrase in body


def test_writer_v020_rejects_same_version_content_drift() -> None:
    prompt = _prompt_module()
    row = prompt._payload()
    row["system_prompt"] = "冲突正文"

    try:
        prompt.ensure_existing_version_compatible([row])
    except prompt.PromptVersionConflict:
        pass
    else:
        raise AssertionError("same-version drift must fail")


def test_writer_v020_conflict_exits_nonzero(monkeypatch) -> None:
    prompt = _prompt_module()

    class FakeApi:
        @staticmethod
        def _resolve_token(_base):
            return "token"

        @staticmethod
        def _request_json(*_args, **_kwargs):
            row = prompt._payload()
            row["user_prompt_template"] = "冲突正文"
            return [row]

    monkeypatch.setattr(prompt, "_api_client", lambda: FakeApi)
    monkeypatch.setattr(sys, "argv", ["publish_recommendation_writer_v020_prompt.py", "--dry-run"])

    assert prompt.main() == 2


def test_new_brief_and_fallback_have_no_total_eligible_reader() -> None:
    answer_source = (ROOT / "backend/app/services/recommendation_answer.py").read_text(encoding="utf-8")
    brief_source = (ROOT / "backend/app/jobs/handlers/recommendation.py").read_text(encoding="utf-8")
    brief_function = brief_source.split("def _build_answer_brief(", 1)[1].split(
        "\ndef _get_deep_eval_node_config", 1
    )[0]

    assert "total_eligible" not in answer_source
    assert "total_eligible" not in brief_function
