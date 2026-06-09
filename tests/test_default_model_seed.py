from pathlib import Path


def test_default_llm_seed_uses_qwen36_plus() -> None:
    sql = Path("database/migrations/012_default_llm_qwen36_plus.sql").read_text(encoding="utf-8")

    assert "model_name = 'qwen3.6-plus'" in sql
    assert "business_update_extractor" in sql
    assert "supports_multimodal_input" in sql


def test_business_update_extractor_timeout_seed_allows_long_attachment_jobs() -> None:
    sql = Path("database/migrations/013_business_update_extractor_timeout.sql").read_text(encoding="utf-8")

    assert "business_update_extractor" in sql
    assert "greatest(coalesce(timeout_seconds, 90), 300)" in sql
    assert "qwen3.6-plus attachment-backed business updates" in sql


def test_buyer_intent_prompt_seed_includes_expanded_requirement_fields() -> None:
    sql = Path("database/migrations/015_buyer_intent_prompt_v03.sql").read_text(encoding="utf-8")

    assert "buyer_intent_parser" in sql
    assert "listing_board_requirement_summary" in sql
    assert "financing_stage_requirement_summary" in sql
    assert "min_market_cap_yuan" in sql
    assert "max_debt_ratio" in sql
    assert "major_risk_tolerance_summary" in sql


def test_business_update_prompt_seed_allows_expanded_buyer_intent_fields() -> None:
    sql = Path("database/migrations/016_business_update_extractor_prompt_v04.sql").read_text(encoding="utf-8")

    assert "business_update_extractor" in sql
    assert "buyer_intent_update" in sql
    assert "transaction_types_json" in sql
    assert "buyer_industry_advantage_summary" in sql


def test_seller_target_prompt_seed_includes_subject_and_price_dates() -> None:
    sql = Path("database/migrations/018_seller_target_parser_prompt_v02.sql").read_text(encoding="utf-8")

    assert "seller_target_parser" in sql
    assert "target_subject_name" in sql
    assert "asking_price_date" in sql
    assert "valuation_date" in sql


def test_business_update_prompt_seed_allows_seller_subject_and_price_dates() -> None:
    sql = Path("database/migrations/019_business_update_extractor_prompt_v05.sql").read_text(encoding="utf-8")

    assert "business_update_extractor" in sql
    assert "target_subject_name" in sql
    assert "asking_price_date" in sql
    assert "valuation_date" in sql


def test_seller_target_prompt_seed_requires_chinese_industry_and_region_values() -> None:
    sql = Path("database/migrations/020_seller_target_parser_prompt_v03.sql").read_text(encoding="utf-8")

    assert "seller_target_parser" in sql
    assert "v0.3.0" in sql
    assert "Output industry and region values in Chinese" in sql
    assert "浙江省" in sql
    assert "杭州市" in sql
    assert "do not output English translated labels" in sql


def test_business_update_prompt_seed_requires_chinese_industry_and_region_values() -> None:
    sql = Path("database/migrations/021_business_update_extractor_prompt_v06.sql").read_text(encoding="utf-8")

    assert "business_update_extractor" in sql
    assert "v0.6.0" in sql
    assert "Output industry and region values in Chinese" in sql
    assert "region_scope_summary" in sql
    assert "浙江省、杭州市、江苏省、上海市" in sql
    assert "do not output English translated labels" in sql


def test_meta_ai_infra_status_checks_qwen36_plus() -> None:
    source = Path("backend/app/api/routes/meta.py").read_text(encoding="utf-8")

    assert "model_name = 'qwen3.6-plus'" in source
    assert "model_name = 'qwen3.6-flash'" not in source
