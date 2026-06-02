-- Match-MA buyer intent parser prompt v0.2
-- Purpose: turn buyer_intent_parser into a structured JSON field extractor.

begin;

update prompt_template
set is_default = false,
    updated_at = now()
where team_id = '00000000-0000-0000-0000-000000000001'
  and workspace_id = '00000000-0000-0000-0000-000000000101'
  and node_name = 'buyer_intent_parser'
  and version <> 'v0.2.0';

insert into prompt_template (
  id, team_id, workspace_id, node_name, version, name, description,
  system_prompt, user_prompt_template, output_schema_json,
  few_shot_examples_json, template_engine, variables_json,
  is_active, is_default, created_by, metadata_json
)
values (
  '00000000-0000-0000-0000-000000004207',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  'buyer_intent_parser',
  'v0.2.0',
  'Buyer intent parser structured fields baseline',
  'Parse natural-language buyer requirements into canonical buyer_intent fields.',
  'You parse buyer acquisition requirements for Match-MA, an internal M&A matching platform. Output only one JSON object, no Markdown. Top level must contain a fields object. Use canonical field names only. Do not invent facts. If uncertain, write summaries into unknown_summary or parsed_requirement_json instead of forcing a field.',
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
    "requires_control": "unknown",
    "requires_consolidation": "yes",
    "accepts_minority_investment": "unknown",
    "desired_equity_ratio_min": null,
    "desired_equity_ratio_max": null,
    "equity_ratio_summary": "可并表即可",
    "equity_requirement_type": "consolidation_required",
    "acceptable_control_paths_json": [],
    "preferred_listed_status": "unlisted",
    "transaction_type": null,
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
4. For preferred_listed_status use one of: listed, unlisted, pre_ipo, any, unknown.
5. For equity_requirement_type use one of: control_required, consolidation_required, minority_acceptable, minority_only, flexible, specific_range, unknown.
6. Convert region phrases such as 长三角 into provinces/cities when obvious; otherwise preserve the raw text in region_scope_summary and parsed_requirement_json.
7. Put hard constraints and preferences into summaries/JSON; do not create buyer_intent_constraint rows in this version.
8. Omit fields only when there is no evidence.',
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
          "requires_control": {"type": ["string", "null"]},
          "requires_consolidation": {"type": ["string", "null"]},
          "accepts_minority_investment": {"type": ["string", "null"]},
          "desired_equity_ratio_min": {"type": ["number", "null"]},
          "desired_equity_ratio_max": {"type": ["number", "null"]},
          "equity_ratio_summary": {"type": ["string", "null"]},
          "equity_requirement_type": {"type": ["string", "null"]},
          "acceptable_control_paths_json": {"type": ["array", "object", "null"]},
          "preferred_listed_status": {"type": ["string", "null"]},
          "transaction_type": {"type": ["string", "null"]},
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
  '{"source":"migration_009_buyer_intent_parser_prompt_v02"}'::jsonb
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
