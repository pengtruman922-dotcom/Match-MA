from backend.app.ai.prompting import extract_template_variables
from backend.app.api.routes.model_config import PromptRenderPreviewIn, render_prompt_preview


def test_extract_template_variables_unique_in_order() -> None:
    variables = extract_template_variables(
        "System uses {{ industry_l1_list }}.",
        "Text: {{ raw_text }}\nDict again: {{ industry_l1_list }}\nContext: {{context_json}}",
    )

    assert variables == ["industry_l1_list", "raw_text", "context_json"]


def test_render_preview_resolves_industry_dictionary_and_samples(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.api.routes.model_config.industry_l1_prompt_list",
        lambda _db: "制造与工业、能源、医药健康",
    )
    result = render_prompt_preview(
        PromptRenderPreviewIn(
            system_prompt="行业清单：{{ industry_l1_list }}",
            user_prompt_template="原文：{{ raw_text }}",
        ),
        db=None,
    )

    assert result["variables"] == ["industry_l1_list", "raw_text"]
    assert result["rendered_system_prompt"] == "行业清单：制造与工业、能源、医药健康"
    assert result["rendered_user_prompt"] == "原文：【示例数据: raw_text】"
    assert result["resolved_variables"]["industry_l1_list"] == "制造与工业、能源、医药健康"


def test_render_preview_survives_dictionary_failure(monkeypatch) -> None:
    def boom(_db):
        raise RuntimeError("db down")

    monkeypatch.setattr("backend.app.api.routes.model_config.industry_l1_prompt_list", boom)
    result = render_prompt_preview(
        PromptRenderPreviewIn(user_prompt_template="{{ industry_l1_list }}"),
        db=None,
    )

    assert "行业字典读取失败" in result["rendered_user_prompt"]
