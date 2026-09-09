from backend.app.ai.prompting import RETIRED_TEMPLATE_VARIABLES, extract_template_variables, render_template
from backend.app.api.routes.model_config import PromptRenderPreviewIn, render_prompt_preview


def test_extract_template_variables_unique_in_order() -> None:
    variables = extract_template_variables(
        "System uses {{ province_list }}.",
        "Text: {{ raw_text }}\nList again: {{ province_list }}\nContext: {{context_json}}",
    )

    assert variables == ["province_list", "raw_text", "context_json"]


def test_render_preview_resolves_runtime_lists_and_samples(monkeypatch) -> None:
    """运行时由 handler 注入的清单，预览也必须给真值。

    编辑者写「从清单里逐字挑」时看到的若是占位符，根本判断不了清单里有没有那个词。
    行业字典的两个变量 0908 随字典一起下线，现在只剩省份清单与可筛字段清单。
    """
    monkeypatch.setattr(
        "backend.app.api.routes.model_config.screening_fields_prompt_json",
        lambda: '[{"field": "min_revenue_yuan"}]',
    )
    result = render_prompt_preview(
        PromptRenderPreviewIn(
            system_prompt="可筛字段：{{ screening_fields_json }}",
            user_prompt_template="省份：{{ province_list }}\n原文：{{ raw_text }}",
        ),
        db=None,
    )

    assert result["variables"] == ["screening_fields_json", "province_list", "raw_text"]
    assert result["rendered_system_prompt"] == '可筛字段：[{"field": "min_revenue_yuan"}]'
    assert "广东省" in result["resolved_variables"]["province_list"]
    assert result["rendered_user_prompt"].endswith("原文：【示例数据: raw_text】")
    assert "示例数据" not in result["rendered_system_prompt"]


def test_render_preview_survives_list_loader_failure(monkeypatch) -> None:
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr("backend.app.api.routes.model_config.screening_fields_prompt_json", boom)
    result = render_prompt_preview(
        PromptRenderPreviewIn(user_prompt_template="{{ screening_fields_json }}"),
        db=None,
    )

    assert "screening_fields_json 字典读取失败" in result["rendered_user_prompt"]


def test_retired_dictionary_variables_render_as_empty_lists_not_null() -> None:
    """行业字典下线后，线上可能还跑着引用 industry_l1_list 的旧版本 prompt。

    render_template 对未绑定变量渲染成字面量 "null" —— 模型会收到「闭集：null」。
    过渡期 handler 把这两个名字传成空串，旧版本渲染出来是空清单。
    """
    template = "闭集：{{ industry_l1_list }}|{{ industry_l2_list }}|"
    assert render_template(template, {}) == "闭集：null|null|"
    assert render_template(template, dict(RETIRED_TEMPLATE_VARIABLES)) == "闭集：||"
