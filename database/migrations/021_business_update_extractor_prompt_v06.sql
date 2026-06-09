-- Match-MA business update extractor prompt v0.6
-- Purpose: require Chinese industry and region values in business update actions.

begin;

update prompt_template
set is_default = false,
    updated_at = now()
where team_id = '00000000-0000-0000-0000-000000000001'
  and workspace_id = '00000000-0000-0000-0000-000000000101'
  and node_name = 'business_update_extractor'
  and version <> 'v0.6.0';

insert into prompt_template (
  id, team_id, workspace_id, node_name, version, name, description,
  system_prompt, user_prompt_template, output_schema_json,
  few_shot_examples_json, template_engine, variables_json,
  is_active, is_default, created_by, metadata_json
)
values (
  '00000000-0000-0000-0000-000000004221',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  'business_update_extractor',
  'v0.6.0',
  'Business update extractor Chinese industry and region values',
  'Extract pending-review actions while keeping industry and region field values in Chinese.',
  'You extract structured actions for Match-MA, an internal M&A matching platform. Output only one JSON object, no Markdown. Top level must contain actions array. Allowed action_type values: seller_fact_update, seller_event, buyer_seller_relation_update, buyer_intent_target_exclusion, buyer_intent_update, buyer_level_blacklist_suggestion, internal_note, unresolved_item. Use null target_entity_id when uncertain. Output industry and region values in Chinese. Never invent UUIDs. proposed_changes_json must use canonical database field names only when a canonical field exists. This version creates pending-review actions only.',
  'Context JSON: {{ context_json }}

Raw input: {{ raw_text }}

Return JSON in this shape:
{
  "actions": [
    {
      "action_type": "seller_fact_update",
      "target_entity_type": "seller_target",
      "target_entity_id": null,
      "proposed_changes_json": {"target_subject_name": "..."},
      "raw_evidence_text": "original evidence span",
      "confidence": 0.80,
      "reason": "why this action was extracted"
    }
  ]
}

Rules:
1. Use seller_fact_update for current seller target fact changes. target_entity_type must be seller_target.
2. seller_fact_update proposed_changes_json may ONLY use these canonical fields when applicable: target_name, target_subject_name, industry_primary, industry_secondary, headquarter_province, headquarter_city, listed_status, current_revenue_yuan, current_net_profit_yuan, current_total_profit_yuan, financial_period_label, valuation_yuan, valuation_date, asking_price_yuan, asking_price_date, pe_ratio, is_for_sale, can_control, can_consolidate, accepts_minority_investment, transfer_ratio_min, transfer_ratio_max, transfer_ratio_text, transfer_flexibility_type, business_summary, transaction_summary, risk_summary, gap_summary, information_status, recommendation_status.
3. Map common expressions: target subject, owning company, project company, owner company -> target_subject_name; profit or net profit -> current_net_profit_yuan; revenue -> current_revenue_yuan; valuation -> valuation_yuan; valuation time/date -> valuation_date; asking price or quote -> asking_price_yuan; asking price time/date or quote time -> asking_price_date; PE -> pe_ratio; province/city/location -> headquarter_province/headquarter_city; can be controlled -> can_control; can be consolidated -> can_consolidate.
4. Use buyer_intent_update for buyer requirement changes. target_entity_type must be buyer_intent. proposed_changes_json may use: raw_requirement_text, intent_summary, industry_primary, industry_secondary, region_scope_summary, min_revenue_yuan, min_net_profit_yuan, min_total_profit_yuan, max_pe, max_valuation_yuan, min_market_cap_yuan, max_market_cap_yuan, market_cap_range_summary, requires_control, requires_consolidation, accepts_minority_investment, desired_equity_ratio_min, desired_equity_ratio_max, equity_ratio_summary, equity_requirement_type, preferred_listed_status, listing_board_requirement_summary, financing_stage_requirement_summary, transaction_type, transaction_types_json, premium_tolerance_summary, max_premium_rate, max_debt_ratio, debt_ratio_requirement_summary, major_risk_tolerance_summary, buyer_industry_advantage_summary, negative_summary, priority_summary, preference_summary, unknown_summary, status, pause_reason.
5. Split listing requirements: preferred_listed_status is listed, preparing_listing, pre_ipo, unlisted, any, or unknown; listing_board_requirement_summary stores 主板/创业板/科创板/北交所/港股/美股; financing_stage_requirement_summary stores pre-IPO/A轮/辅导备案/已递表等阶段.
6. transaction_types_json should be a JSON array when multiple deal methods are mentioned; keep transaction_type only for one short legacy label if clearly single.
7. Use buyer_seller_relation_update for recommendation, in-talk, due diligence, terminated, or buyer feedback progress. target_entity_type must be buyer_seller_relation. proposed_changes_json may use: status, status_reason, first_recommended_at, last_contact_at, last_event_at, last_event_summary, event_type, event_title, event_content, next_step, buyer_name, seller_target_name.
8. If clearly not interested, create buyer_intent_target_exclusion in addition to relation update. If an item cannot be mapped safely, create unresolved_item.
9. Normalize money amounts to CNY yuan numbers. Normalize percentages to numeric percentage values, e.g. use 51 for a 51 percent share. For yes/no/likely/unknown fields use exactly one of: yes, no, likely, unknown.
10. If user-entered text and attachment evidence conflict on formal target_name, target_subject_name, or standardized industry, prefer the formal attachment evidence and explain briefly in reason.
11. For seller_fact_update and buyer_intent_update, output industry_primary, industry_secondary, headquarter_province, headquarter_city, region_scope_summary, and buyer_industry_advantage_summary values in Chinese when evidence exists. Use Chinese administrative names such as 浙江省、杭州市、江苏省、上海市; do not output English translated labels such as Zhejiang Province, Hangzhou City, healthcare, manufacturing, or medical_device.
12. If the input contains multiple independent matters, return multiple actions.',
  '{
    "type": "object",
    "required": ["actions"],
    "properties": {
      "actions": {
        "type": "array",
        "items": {
          "type": "object",
          "required": ["action_type", "proposed_changes_json"],
          "properties": {
            "action_type": {"type": "string"},
            "target_entity_type": {"type": ["string", "null"]},
            "target_entity_id": {"type": ["string", "null"]},
            "proposed_changes_json": {"type": "object"},
            "raw_evidence_text": {"type": ["string", "null"]},
            "confidence": {"type": ["number", "null"]},
            "reason": {"type": ["string", "null"]}
          }
        }
      }
    }
  }'::jsonb,
  '[]'::jsonb,
  'jinja',
  '["context_json", "raw_text"]'::jsonb,
  true,
  true,
  '00000000-0000-0000-0000-000000000201',
  '{"source":"migration_021_business_update_extractor_prompt_v06"}'::jsonb
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
