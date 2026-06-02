-- Match-MA seller target parser node and prompt v0.1
-- Purpose: parse natural-language seller target descriptions into seller_target fields.

begin;

insert into model_node_config (
  id, team_id, workspace_id, node_name, node_type, provider_config_id,
  model_name, temperature, top_p, max_tokens, timeout_seconds,
  response_format, output_mode, embedding_dimension,
  is_active, is_default, created_by, metadata_json
)
values (
  '00000000-0000-0000-0000-000000004107',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  'seller_target_parser',
  'llm',
  '00000000-0000-0000-0000-000000004001',
  'qwen3.6-flash',
  0.100,
  0.900,
  4096,
  90,
  'json_object',
  'json',
  null,
  true,
  true,
  '00000000-0000-0000-0000-000000000201',
  '{"purpose":"Parse seller target descriptions into structured seller_target fields.","has_prompt":true,"queue_name":"llm"}'::jsonb
)
on conflict (team_id, workspace_id, node_name) where is_default = true do update set
  node_type = excluded.node_type,
  provider_config_id = excluded.provider_config_id,
  model_name = excluded.model_name,
  temperature = excluded.temperature,
  top_p = excluded.top_p,
  max_tokens = excluded.max_tokens,
  timeout_seconds = excluded.timeout_seconds,
  response_format = excluded.response_format,
  output_mode = excluded.output_mode,
  embedding_dimension = excluded.embedding_dimension,
  is_active = excluded.is_active,
  metadata_json = excluded.metadata_json,
  updated_at = now();

update prompt_template
set is_default = false,
    updated_at = now()
where team_id = '00000000-0000-0000-0000-000000000001'
  and workspace_id = '00000000-0000-0000-0000-000000000101'
  and node_name = 'seller_target_parser'
  and version <> 'v0.1.0';

insert into prompt_template (
  id, team_id, workspace_id, node_name, version, name, description,
  system_prompt, user_prompt_template, output_schema_json,
  few_shot_examples_json, template_engine, variables_json,
  is_active, is_default, created_by, metadata_json
)
values (
  '00000000-0000-0000-0000-000000004208',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  'seller_target_parser',
  'v0.1.0',
  'Seller target parser structured fields baseline',
  'Parse natural-language seller target descriptions into canonical seller_target fields.',
  'You parse seller target descriptions for Match-MA, an internal M&A matching platform. Output only one JSON object, no Markdown. Top level must contain a fields object. Use canonical seller_target field names only. Do not invent facts. If uncertain, write summaries into risk_summary, gap_summary, or business_summary instead of forcing a field.',
  'Raw seller target text:
{{ raw_target_text }}

Existing seller target context JSON:
{{ target_context_json }}

Return JSON in this shape:
{
  "fields": {
    "target_name": "...",
    "target_type": "company",
    "industry_primary": "healthcare",
    "industry_secondary": "medical_device",
    "headquarter_province": "Zhejiang Province",
    "headquarter_city": "Hangzhou City",
    "listed_status": "unlisted",
    "current_revenue_yuan": null,
    "current_net_profit_yuan": 25000000,
    "current_total_profit_yuan": null,
    "valuation_yuan": 320000000,
    "asking_price_yuan": null,
    "pe_ratio": 12.8,
    "is_for_sale": "yes",
    "can_control": "unknown",
    "can_consolidate": "unknown",
    "accepts_minority_investment": "unknown",
    "transfer_ratio_min": null,
    "transfer_ratio_max": null,
    "transfer_ratio_text": "control stake negotiable",
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
4. For listed_status use one of: listed, unlisted, pre_ipo, unknown.
5. For transfer_flexibility_type use one of: control_available, consolidation_available, minority_available, full_sale_available, flexible, specific_range, unknown.
6. Store actual target location fields such as headquarter_province/headquarter_city; do not judge whether it matches a buyer preference.
7. Omit fields when there is no evidence.',
  '{
    "type": "object",
    "required": ["fields"],
    "properties": {
      "fields": {
        "type": "object",
        "properties": {
          "target_name": {"type": ["string", "null"]},
          "target_type": {"type": ["string", "null"]},
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
          "asking_price_yuan": {"type": ["number", "null"]},
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
  '{"source":"migration_010_seller_target_parser_prompt_v01"}'::jsonb
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
