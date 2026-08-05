"""A prompt whose variables never render is indistinguishable from a working one.

The renderer only understands `{{ name }}`. Anything else is passed through, so
a prompt written with single braces saves cleanly, renders cleanly, and hands
the model the literal string `{answer_brief_json}` — the model then replies
asking where the data went, and no log anywhere says why. These are the two
shapes of that mistake.
"""

import pytest
from fastapi import HTTPException

from backend.app.api.routes.model_config import _validate_prompt_variables
from backend.app.registry.nodes import NODES

AGENT_NODE = "recommendation_agent_to_target"
WRITER_NODE = "recommendation_answer_writer_to_target"


def test_single_braces_are_rejected_with_the_offending_name() -> None:
    with pytest.raises(HTTPException) as excinfo:
        _validate_prompt_variables(WRITER_NODE, "写成一段话。", "素材：{answer_brief_json}")

    assert excinfo.value.status_code == 400
    assert "answer_brief_json" in excinfo.value.detail
    assert "{{ name }}" in excinfo.value.detail


def test_double_braces_pass() -> None:
    _validate_prompt_variables(WRITER_NODE, "写成一段话。", "素材：{{ answer_brief_json }}")


def test_a_prompt_that_uses_no_variable_at_all_is_rejected() -> None:
    with pytest.raises(HTTPException) as excinfo:
        _validate_prompt_variables(WRITER_NODE, "你是一个撰稿助手。", "请写一段话。")

    assert excinfo.value.status_code == 400
    assert "answer_brief_json" in excinfo.value.detail


def test_using_some_but_not_all_variables_is_allowed() -> None:
    """有的变量本来就是可选的（历史为空、字典没启用），不该因此写不了提示词。"""
    _validate_prompt_variables(AGENT_NODE, "", "{{ recommendation_context_json }}")


def test_the_variable_may_live_in_the_system_prompt() -> None:
    _validate_prompt_variables(AGENT_NODE, "背景：{{ recommendation_context_json }}", "开始。")


def test_json_examples_in_a_prompt_are_not_mistaken_for_variables() -> None:
    """提示词里经常有 JSON 示例，{"understanding": ...} 不能被当成变量误报。"""
    _validate_prompt_variables(
        AGENT_NODE,
        '输出形如 {"understanding": "…", "recommended": []}',
        "{{ recommendation_context_json }}",
    )


def test_nodes_without_declared_variables_are_left_alone() -> None:
    without = next((spec for spec in NODES if not spec.prompt_variables), None)
    if without is None:
        pytest.skip("每个节点都声明了变量")
    _validate_prompt_variables(without.node_name, "随便写", "随便写")
