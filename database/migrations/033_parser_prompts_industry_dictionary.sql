-- Match-MA parser prompts with closed industry dictionary
-- Purpose: buyer_intent_parser v0.5.0 adds multi-value industries_json and
-- excluded_industries_json chosen from the closed L1 industry list, and
-- seller_target_parser v0.6.0 adds normalized industry_l1. The L1 list is
-- injected at render time via the industry_l1_list template variable.

begin;

update prompt_template
set is_default = false,
    updated_at = now()
where team_id = '00000000-0000-0000-0000-000000000001'
  and workspace_id = '00000000-0000-0000-0000-000000000101'
  and node_name = 'buyer_intent_parser'
  and version <> 'v0.5.0';

insert into prompt_template (
  id, team_id, workspace_id, node_name, version, name, description,
  system_prompt, user_prompt_template, output_schema_json,
  few_shot_examples_json, template_engine, variables_json,
  is_active, is_default, created_by, metadata_json
)
values (
  '00000000-0000-0000-0000-000000004226',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  'buyer_intent_parser',
  'v0.5.0',
  'Buyer intent parser with closed industry dictionary',
  'Parse buyer requirements into canonical buyer_intent fields with multi-value industries from the closed L1 dictionary, plus buyer party enrichment.',
  'You parse buyer acquisition requirements for Match-MA, an internal M&A matching platform. Output only one JSON object, no Markdown. Top level must contain a fields object and may also include an optional buyer_party object describing the acquirer. Use canonical field names only. Do not invent facts. If uncertain, preserve the evidence in summaries rather than forcing a structured value.',
  'Raw buyer requirement:
{{ raw_requirement_text }}

Existing buyer profile/context JSON:
{{ buyer_profile_json }}

Closed level-1 industry categories (items of industries_json and excluded_industries_json MUST come from this list):
{{ industry_l1_list }}

Return JSON in this shape:
{
  "fields": {
    "intent_name": "...",
    "raw_requirement_text": "...",
    "intent_summary": "...",
    "industry_primary": "...",
    "industry_secondary": "...",
    "industries_json": ["制造与工业", "能源"],
    "excluded_industries_json": ["房地产与建筑", "风电"],
    "region_scope_summary": "...",
    "region_constraints_json": [{"constraint_type":"hard","province":"浙江省","city":null,"raw_text":"浙江省内"}],
    "min_revenue_yuan": 100000000,
    "min_net_profit_yuan": 20000000,
    "min_total_profit_yuan": null,
    "max_pe": 13,
    "max_valuation_yuan": null,
    "min_market_cap_yuan": 500000000,
    "max_market_cap_yuan": 3000000000,
    "market_cap_range_summary": "市值5-30亿",
    "requires_control": "unknown",
    "requires_consolidation": "yes",
    "accepts_minority_investment": "unknown",
    "desired_equity_ratio_min": null,
    "desired_equity_ratio_max": null,
    "equity_ratio_summary": "可并表即可",
    "equity_requirement_type": "consolidation_required",
    "acceptable_control_paths_json": [],
    "preferred_listed_status": "unlisted",
    "listing_board_requirement_summary": "北交所或创业板",
    "financing_stage_requirement_summary": "pre-IPO",
    "transaction_type": null,
    "transaction_types_json": ["control", "minority"],
    "premium_tolerance_summary": "可接受合理溢价，需视估值确认",
    "max_premium_rate": 20,
    "max_debt_ratio": 65,
    "debt_ratio_requirement_summary": "资产负债率不高于65 percent",
    "major_risk_tolerance_summary": "不接受重大诉讼、冻结、执行、违规违法",
    "buyer_industry_advantage_summary": "收购方所在地有医药产业资源",
    "negative_summary": "...",
    "priority_summary": "...",
    "preference_summary": "...",
    "unknown_summary": "...",
    "parsed_requirement_json": {"notes":["..."]}
  },
  "buyer_party": {
    "buyer_type": "industrial_buyer | listed_company | state_owned_platform | pe_fund | financial_investor | government_platform | other",
    "group_name": "...",
    "listed_status": "listed | preparing_listing | pre_ipo | unlisted | unknown",
    "region_province": "浙江省",
    "region_city": "杭州市",
    "main_business": "...",
    "capital_strength_summary": "...",
    "profile_summary": "..."
  }
}

Rules:
1. Normalize money amounts to CNY yuan numbers.
2. Normalize percentages to numeric percentage values, e.g. use 51 for 51 percent.
3. For requires_control, requires_consolidation, accepts_minority_investment use exactly one of: yes, no, likely, unknown.
4. For preferred_listed_status use one of: listed, preparing_listing, pre_ipo, unlisted, any, unknown. Use preparing_listing for broad "准备上市/拟上市" requirements; use financing_stage_requirement_summary for details such as pre-IPO, A轮, B轮, 已递表, 辅导备案.
5. Keep listing board details in listing_board_requirement_summary, e.g. 主板, 创业板, 科创板, 北交所, 港股, 美股.
6. Keep market cap, premium, debt ratio, major risk tolerance, buyer regional/industry advantage, and transaction type requirements when evidence exists.
7. transaction_types_json should be a JSON array of concise strings when multiple transaction methods are acceptable; keep transaction_type for one short legacy label if there is a single clear type.
8. Convert region phrases such as 长三角 into provinces/cities when obvious; otherwise preserve the raw text in region_scope_summary and parsed_requirement_json.
9. Put hard constraints and preferences into summaries/JSON; do not create buyer_intent_constraint rows in this version.
10. Omit fields only when there is no evidence.
11. industries_json lists ALL industry tracks the buyer wants, ordered by priority with the primary track first. Every item MUST be exactly one value copied from the closed level-1 list above; never invent new category names. A requirement with multiple tracks stays ONE intent with multiple industries_json items; do not drop secondary tracks. Keep the descriptive Chinese industry wording in industry_primary and industry_secondary as before.
12. excluded_industries_json lists industries or tracks the buyer explicitly refuses (e.g. 不投风电, 不碰房地产和建筑施工). Prefer values from the closed level-1 list; when the exclusion is narrower than a level-1 category, use a short Chinese term such as 风电 or 房地产开发. Keep the human-readable exclusion evidence in negative_summary as before.
13. For buyer_party.buyer_type use exactly one of: industrial_buyer, listed_company, state_owned_platform, pe_fund, financial_investor, government_platform, other. Map strategic/private/corporate buyers to industrial_buyer; listed acquirers to listed_company; state-owned acquirers to state_owned_platform.
14. Only populate buyer_party when the material describes the ACQUIRER (the buyer) itself — its type, group, listing status, headquarters province/city, main business, or capital strength. Never place target/seller attributes in buyer_party. Use Chinese for region and main business. Do not output or overwrite manual buyer notes. Omit buyer_party entirely when there is no clear buyer self-description.',
  '{
    "type": "object",
    "required": ["fields"],
    "properties": {
      "fields": {
        "type": "object",
        "properties": {
          "intent_name": {"type": ["string", "null"]},
          "raw_requirement_text": {"type": ["string", "null"]},
          "intent_summary": {"type": ["string", "null"]},
          "industry_primary": {"type": ["string", "null"]},
          "industry_secondary": {"type": ["string", "null"]},
          "industries_json": {"type": ["array", "null"]},
          "excluded_industries_json": {"type": ["array", "null"]},
          "region_scope_summary": {"type": ["string", "null"]},
          "region_constraints_json": {"type": ["array", "object", "null"]},
          "min_revenue_yuan": {"type": ["number", "null"]},
          "min_net_profit_yuan": {"type": ["number", "null"]},
          "min_total_profit_yuan": {"type": ["number", "null"]},
          "max_pe": {"type": ["number", "null"]},
          "max_valuation_yuan": {"type": ["number", "null"]},
          "min_market_cap_yuan": {"type": ["number", "null"]},
          "max_market_cap_yuan": {"type": ["number", "null"]},
          "market_cap_range_summary": {"type": ["string", "null"]},
          "requires_control": {"type": ["string", "null"]},
          "requires_consolidation": {"type": ["string", "null"]},
          "accepts_minority_investment": {"type": ["string", "null"]},
          "desired_equity_ratio_min": {"type": ["number", "null"]},
          "desired_equity_ratio_max": {"type": ["number", "null"]},
          "equity_ratio_summary": {"type": ["string", "null"]},
          "equity_requirement_type": {"type": ["string", "null"]},
          "acceptable_control_paths_json": {"type": ["array", "object", "null"]},
          "preferred_listed_status": {"type": ["string", "null"]},
          "listing_board_requirement_summary": {"type": ["string", "null"]},
          "financing_stage_requirement_summary": {"type": ["string", "null"]},
          "transaction_type": {"type": ["string", "null"]},
          "transaction_types_json": {"type": ["array", "object", "null"]},
          "premium_tolerance_summary": {"type": ["string", "null"]},
          "max_premium_rate": {"type": ["number", "null"]},
          "max_debt_ratio": {"type": ["number", "null"]},
          "debt_ratio_requirement_summary": {"type": ["string", "null"]},
          "major_risk_tolerance_summary": {"type": ["string", "null"]},
          "buyer_industry_advantage_summary": {"type": ["string", "null"]},
          "negative_summary": {"type": ["string", "null"]},
          "priority_summary": {"type": ["string", "null"]},
          "preference_summary": {"type": ["string", "null"]},
          "unknown_summary": {"type": ["string", "null"]},
          "parsed_requirement_json": {"type": ["object", "null"]}
        }
      },
      "buyer_party": {
        "type": ["object", "null"],
        "properties": {
          "buyer_type": {"type": ["string", "null"]},
          "group_name": {"type": ["string", "null"]},
          "listed_status": {"type": ["string", "null"]},
          "region_province": {"type": ["string", "null"]},
          "region_city": {"type": ["string", "null"]},
          "main_business": {"type": ["string", "null"]},
          "capital_strength_summary": {"type": ["string", "null"]},
          "profile_summary": {"type": ["string", "null"]}
        }
      }
    }
  }'::jsonb,
  '[]'::jsonb,
  'jinja',
  '["raw_requirement_text", "buyer_profile_json", "industry_l1_list"]'::jsonb,
  true,
  true,
  '00000000-0000-0000-0000-000000000201',
  '{"source":"migration_033_parser_prompts_industry_dictionary"}'::jsonb
)
on conflict (team_id, workspace_id, node_name, version) do update set
  name = excluded.name,
  description = excluded.description,
  system_prompt = excluded.system_prompt,
  user_prompt_template = excluded.user_prompt_template,
  output_schema_json = excluded.output_schema_json,
  few_shot_examples_json = excluded.few_shot_examples_json,
  template_engine = excluded.template_engine,
  variables_json = excluded.variables_json,
  is_active = excluded.is_active,
  is_default = true,
  metadata_json = excluded.metadata_json,
  updated_at = now();

update prompt_template
set is_default = false,
    updated_at = now()
where team_id = '00000000-0000-0000-0000-000000000001'
  and workspace_id = '00000000-0000-0000-0000-000000000101'
  and node_name = 'seller_target_parser'
  and version <> 'v0.6.0';

insert into prompt_template (
  id, team_id, workspace_id, node_name, version, name, description,
  system_prompt, user_prompt_template, output_schema_json,
  few_shot_examples_json, template_engine, variables_json,
  is_active, is_default, created_by, metadata_json
)
values (
  '00000000-0000-0000-0000-000000004227',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  'seller_target_parser',
  'v0.6.0',
  'Seller target parser with closed industry dictionary',
  'Parse seller target descriptions into canonical seller_target fields including normalized industry_l1 from the closed L1 dictionary.',
  'You parse seller target descriptions for Match-MA, an internal M&A matching platform. Output only one JSON object, no Markdown. Top level must contain a fields object. Use canonical seller_target field names only. Do not invent facts. Output all user-facing natural-language values in Chinese. Keep JSON field names and controlled enum codes in canonical English. If formal attachments or official documents provide a more complete target name, target subject, or industry classification than user-entered text, prefer the formal evidence. If uncertain, write summaries into risk_summary, gap_summary, or business_summary instead of forcing a field.',
  'Raw seller target text:
{{ raw_target_text }}

Existing seller target context JSON:
{{ target_context_json }}

Closed level-1 industry categories (industry_l1 MUST be exactly one value from this list):
{{ industry_l1_list }}

Return JSON in this shape:
{
  "fields": {
    "target_name": "...",
    "target_type": "company",
    "target_subject_name": "...",
    "industry_l1": "制造与工业",
    "industry_primary": "精密模具",
    "industry_secondary": "医疗器械注塑模具",
    "headquarter_province": "浙江省",
    "headquarter_city": "杭州市",
    "listed_status": "unlisted",
    "current_revenue_yuan": null,
    "current_net_profit_yuan": 25000000,
    "current_total_profit_yuan": null,
    "financial_period_label": "2025年一季度",
    "valuation_yuan": 320000000,
    "valuation_date": "2025年一季度",
    "asking_price_yuan": null,
    "asking_price_date": null,
    "pe_ratio": 12.8,
    "is_for_sale": "yes",
    "can_control": "unknown",
    "can_consolidate": "unknown",
    "accepts_minority_investment": "unknown",
    "transfer_ratio_min": null,
    "transfer_ratio_max": null,
    "transfer_ratio_text": "控股权可谈",
    "transfer_flexibility_type": "flexible",
    "business_summary": "专注精密注塑模具设计与制造，主要服务医疗器械客户，年净利润约2500万元。",
    "transaction_summary": "...",
    "risk_summary": "...",
    "gap_summary": "...",
    "information_status": "normal"
  }
}

Rules:
1. Normalize money amounts to CNY yuan numbers.
2. Normalize percentages to numeric percentage values, e.g. use 51 for 51 percent.
3. For is_for_sale, can_control, can_consolidate, accepts_minority_investment use exactly one of: yes, no, likely, unknown.
4. For listed_status use one of: listed, unlisted, pre_ipo, unknown. Use pre_ipo only when the material explicitly says preparing IPO/pre-IPO.
5. target_subject_name is the company/entity that owns the target. If the target is a whole company, target_subject_name can equal target_name. If the target is a project, asset package, or business unit, use the owning company when known.
6. valuation_date and asking_price_date are short source time labels such as 2024, 2025 Q1, 2025-05, or the document date. Do not invent a time label.
7. Store actual target location fields such as headquarter_province/headquarter_city; do not judge whether it matches a buyer preference.
8. Output industry_primary, industry_secondary, registered_province, registered_city, headquarter_province, headquarter_city, and raw_region_text values in Chinese when evidence exists. Use Chinese administrative names such as 浙江省、杭州市; do not output English translated labels such as Zhejiang Province, Hangzhou City, healthcare, manufacturing, or medical_device.
9. Output user-facing text fields in Chinese, including financial_period_label, valuation_date, asking_price_date, transfer_ratio_text, consolidation_path_summary, management_team_summary, business_summary, transaction_summary, risk_summary, and gap_summary. Keep controlled enum values such as target_type, listed_status, can_control, transfer_flexibility_type, information_status, and recommendation_status in canonical English codes.
10. Omit fields when there is no evidence.
11. business_summary must be a rewritten profile of one or two sentences within 80 Chinese characters on a single line: main business, core products or customers, and one scale highlight. Never copy or paste raw input text into business_summary. Do not include deal, price, valuation, or risk content in business_summary; deal terms belong to transaction_summary and risks belong to risk_summary.
12. Follow-up or progress dynamics such as 推给某买家, 已发资料, 等待反馈, 暂缓 are not target facts; never write them into business_summary or transaction_summary. If the existing business_summary in context already covers the business and the material adds no new business facts, omit business_summary.
13. industry_l1 MUST be exactly one value copied from the closed level-1 list above; choose the category closest to the main business and never invent new category names. Keep the finer descriptive Chinese industry wording in industry_primary and industry_secondary.',
  '{
    "type": "object",
    "required": ["fields"],
    "properties": {
      "fields": {
        "type": "object",
        "properties": {
          "target_name": {"type": ["string", "null"]},
          "target_type": {"type": ["string", "null"]},
          "target_subject_name": {"type": ["string", "null"]},
          "industry_l1": {"type": ["string", "null"]},
          "industry_primary": {"type": ["string", "null"]},
          "industry_secondary": {"type": ["string", "null"]},
          "registered_province": {"type": ["string", "null"]},
          "registered_city": {"type": ["string", "null"]},
          "headquarter_province": {"type": ["string", "null"]},
          "headquarter_city": {"type": ["string", "null"]},
          "raw_region_text": {"type": ["string", "null"]},
          "region_granularity": {"type": ["string", "null"]},
          "listed_status": {"type": ["string", "null"]},
          "market_cap_yuan": {"type": ["number", "null"]},
          "current_revenue_yuan": {"type": ["number", "null"]},
          "current_net_profit_yuan": {"type": ["number", "null"]},
          "current_total_profit_yuan": {"type": ["number", "null"]},
          "current_assets_yuan": {"type": ["number", "null"]},
          "current_debt_ratio": {"type": ["number", "null"]},
          "current_operating_cash_flow_yuan": {"type": ["number", "null"]},
          "financial_period_label": {"type": ["string", "null"]},
          "profitability_status": {"type": ["string", "null"]},
          "cash_flow_status": {"type": ["string", "null"]},
          "operation_stability_status": {"type": ["string", "null"]},
          "valuation_yuan": {"type": ["number", "null"]},
          "valuation_date": {"type": ["string", "null"]},
          "asking_price_yuan": {"type": ["number", "null"]},
          "asking_price_date": {"type": ["string", "null"]},
          "pe_ratio": {"type": ["number", "null"]},
          "pe_source_type": {"type": ["string", "null"]},
          "premium_rate": {"type": ["number", "null"]},
          "is_for_sale": {"type": ["string", "null"]},
          "can_control": {"type": ["string", "null"]},
          "can_consolidate": {"type": ["string", "null"]},
          "accepts_minority_investment": {"type": ["string", "null"]},
          "transfer_ratio_min": {"type": ["number", "null"]},
          "transfer_ratio_max": {"type": ["number", "null"]},
          "transfer_ratio_text": {"type": ["string", "null"]},
          "transfer_flexibility_type": {"type": ["string", "null"]},
          "consolidation_path_summary": {"type": ["string", "null"]},
          "accepts_relocation": {"type": ["string", "null"]},
          "accepts_return_investment": {"type": ["string", "null"]},
          "management_team_summary": {"type": ["string", "null"]},
          "management_retention_possible": {"type": ["string", "null"]},
          "earnout_dependency_status": {"type": ["string", "null"]},
          "business_summary": {"type": ["string", "null"]},
          "transaction_summary": {"type": ["string", "null"]},
          "risk_summary": {"type": ["string", "null"]},
          "gap_summary": {"type": ["string", "null"]},
          "information_status": {"type": ["string", "null"]}
        }
      }
    }
  }'::jsonb,
  '[]'::jsonb,
  'jinja',
  '["raw_target_text", "target_context_json", "industry_l1_list"]'::jsonb,
  true,
  true,
  '00000000-0000-0000-0000-000000000201',
  '{"source":"migration_033_parser_prompts_industry_dictionary"}'::jsonb
)
on conflict (team_id, workspace_id, node_name, version) do update set
  name = excluded.name,
  description = excluded.description,
  system_prompt = excluded.system_prompt,
  user_prompt_template = excluded.user_prompt_template,
  output_schema_json = excluded.output_schema_json,
  few_shot_examples_json = excluded.few_shot_examples_json,
  template_engine = excluded.template_engine,
  variables_json = excluded.variables_json,
  is_active = excluded.is_active,
  is_default = true,
  metadata_json = excluded.metadata_json,
  updated_at = now();

commit;
