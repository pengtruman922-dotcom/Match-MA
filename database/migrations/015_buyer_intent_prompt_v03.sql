-- Match-MA buyer intent parser prompt v0.3
-- Purpose: capture split listing requirements and core structured buyer filters.

begin;

update prompt_template
set is_default = false,
    updated_at = now()
where team_id = '00000000-0000-0000-0000-000000000001'
  and workspace_id = '00000000-0000-0000-0000-000000000101'
  and node_name = 'buyer_intent_parser'
  and version <> 'v0.3.0';

insert into prompt_template (
  id, team_id, workspace_id, node_name, version, name, description,
  system_prompt, user_prompt_template, output_schema_json,
  few_shot_examples_json, template_engine, variables_json,
  is_active, is_default, created_by, metadata_json
)
values (
  '00000000-0000-0000-0000-000000004215',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  'buyer_intent_parser',
  'v0.3.0',
  'Buyer intent parser expanded requirement fields',
  'Parse buyer requirements into expanded canonical buyer_intent fields.',
  'You parse buyer acquisition requirements for Match-MA, an internal M&A matching platform. Output only one JSON object, no Markdown. Top level must contain a fields object. Use canonical buyer_intent field names only. Do not invent facts. If uncertain, preserve the evidence in summaries rather than forcing a structured value.',
  'Raw buyer requirement:
{{ raw_requirement_text }}

Existing buyer profile/context JSON:
{{ buyer_profile_json }}

Return JSON in this shape:
{
  "fields": {
    "intent_name": "...",
    "raw_requirement_text": "...",
    "intent_summary": "...",
    "industry_primary": "...",
    "industry_secondary": "...",
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
10. Omit fields only when there is no evidence.',
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
      }
    }
  }'::jsonb,
  '[]'::jsonb,
  'jinja',
  '["raw_requirement_text", "buyer_profile_json"]'::jsonb,
  true,
  true,
  '00000000-0000-0000-0000-000000000201',
  '{"source":"migration_015_buyer_intent_prompt_v03"}'::jsonb
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
