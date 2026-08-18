"""4D v0.2.1 only tightens the follow-up chip voice."""

from __future__ import annotations

import importlib.util
import pathlib


def _prompt_module():
    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "publish_recommendation_agent_v021_prompt.py"
    spec = importlib.util.spec_from_file_location("publish_recommendation_agent_v021_prompt", path)
    loaded = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(loaded)
    return loaded


def test_v021_keeps_the_two_node_variables_and_user_voice_examples() -> None:
    prompt = _prompt_module()

    assert prompt.VERSION == "v0.2.1"
    assert set(prompt.EXPECTED_VARIABLES) == {"recommendation_context_json", "history_context"}
    for phrase in (
        "用户下一句要说的话本身",
        "只看能控股的",
        "净利放宽到 500 万",
        "只要江苏的",
        "详细说说 XX",
        "排除掉要对赌的",
    ):
        assert phrase in prompt.USER_PROMPT_TEMPLATE


def test_v021_same_version_conflict_is_rejected() -> None:
    prompt = _prompt_module()

    try:
        prompt.ensure_existing_version_compatible([{
            "version": prompt.VERSION,
            "system_prompt": "conflicting text",
            "user_prompt_template": prompt.USER_PROMPT_TEMPLATE,
            "output_schema_json": prompt.OUTPUT_SCHEMA,
            "variables_json": list(prompt.EXPECTED_VARIABLES),
        }])
    except prompt.PromptVersionConflict:
        return
    raise AssertionError("same-version Prompt drift must be rejected")
