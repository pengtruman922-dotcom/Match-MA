from pathlib import Path


def test_default_llm_seed_uses_qwen36_plus() -> None:
    sql = Path("database/migrations/012_default_llm_qwen36_plus.sql").read_text(encoding="utf-8")

    assert "model_name = 'qwen3.6-plus'" in sql
    assert "business_update_extractor" in sql
    assert "supports_multimodal_input" in sql


def test_meta_ai_infra_status_checks_qwen36_plus() -> None:
    source = Path("backend/app/api/routes/meta.py").read_text(encoding="utf-8")

    assert "model_name = 'qwen3.6-plus'" in source
    assert "model_name = 'qwen3.6-flash'" not in source
