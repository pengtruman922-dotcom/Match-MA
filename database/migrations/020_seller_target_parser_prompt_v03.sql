-- Match-MA seller target parser prompt v0.3
-- Purpose: parse target subject, price/valuation time labels, and Chinese industry/region values.

begin;

update prompt_template
set is_default = false,
    updated_at = now()
where team_id = '00000000-0000-0000-0000-000000000001'
  and workspace_id = '00000000-0000-0000-0000-000000000101'
  and node_name = 'seller_target_parser'
  and version <> 'v0.3.0';

insert into prompt_template (
  id, team_id, workspace_id, node_name, version, name, description,
  system_prompt, user_prompt_template, output_schema_json,
  few_shot_examples_json, template_engine, variables_json,
  is_active, is_default, created_by, metadata_json
)
values (
  '00000000-0000-0000-0000-000000004220',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  'seller_target_parser',
  'v0.3.0',
  'Seller target parser Chinese industry and region values',
  'Parse seller target descriptions into canonical seller_target fields with Chinese industry and region values.',
  'You parse seller target descriptions for Match-MA, an internal M&A matching platform. Output only one JSON object, no Markdown. Top level must contain a fields object. Use canonical seller_target field names only. Do not invent facts. Output industry and region values in Chinese. If formal attachments or official documents provide a more complete target name, target subject, or industry classification than user-entered text, prefer the formal evidence. If uncertain, write summaries into risk_summary, gap_summary, or business_summary instead of forcing a field.',
  'Raw seller target text:
{{ raw_target_text }}

Existing seller target context JSON:
{{ target_context_json }}

Return JSON in this shape:
{
  "fields": {
    "target_name": "...",
    "target_type": "company",
    "target_subject_name": "...",
    "industry_primary": "制造业",
    "industry_secondary": "精密模具",
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
    "business_summary": "...",
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
8. Output industry_primary, industry_secondary, registered_province, registered_city, headquarter_province, headquarter_city, raw_region_text, and region_granularity values in Chinese when evidence exists. Use Chinese administrative names such as 浙江省、杭州市; do not output English translated labels such as Zhejiang Province, Hangzhou City, healthcare, manufacturing, or medical_device.
9. Omit fields when there is no evidence.',
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
  '["raw_target_text", "target_context_json"]'::jsonb,
  true,
  true,
  '00000000-0000-0000-0000-000000000201',
  '{"source":"migration_020_seller_target_parser_prompt_v03"}'::jsonb
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
