-- Specialized seller/buyer update parsers and buyer intent parser v0.6.

begin;

insert into model_node_config (
  id, team_id, workspace_id, node_name, node_type, provider_config_id,
  model_name, temperature, top_p, max_tokens, timeout_seconds,
  response_format, output_mode, embedding_dimension,
  is_active, is_default, created_by, metadata_json
)
select
  v.id, n.team_id, n.workspace_id, v.node_name, 'llm', n.provider_config_id,
  n.model_name, n.temperature, n.top_p, n.max_tokens, n.timeout_seconds,
  n.response_format, n.output_mode, n.embedding_dimension,
  true, true, n.created_by, jsonb_build_object('source', 'migration_036_specialized_update_parsers')
from model_node_config n
cross join (
  values
    ('00000000-0000-0000-0000-000000004235'::uuid, 'seller_target_update_parser'),
    ('00000000-0000-0000-0000-000000004236'::uuid, 'buyer_intent_update_parser')
) as v(id, node_name)
where n.node_name = 'business_update_extractor'
  and n.is_default = true
on conflict (team_id, workspace_id, node_name) where is_default = true do update set
  provider_config_id = excluded.provider_config_id,
  model_name = excluded.model_name,
  temperature = excluded.temperature,
  top_p = excluded.top_p,
  max_tokens = excluded.max_tokens,
  timeout_seconds = excluded.timeout_seconds,
  response_format = excluded.response_format,
  output_mode = excluded.output_mode,
  is_active = true,
  updated_at = now(),
  metadata_json = excluded.metadata_json;

insert into prompt_template (
  id, team_id, workspace_id, node_name, version, name, description,
  system_prompt, user_prompt_template, output_schema_json,
  few_shot_examples_json, template_engine, variables_json,
  is_active, is_default, created_by, metadata_json
)
values
(
  '00000000-0000-0000-0000-000000004237',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  'seller_target_update_parser', 'v0.1.0',
  'Seller target update parser',
  'Extract seller target field changes and target follow-up notes only.',
  'You parse updates for one known seller target. Output one JSON object with an actions array and no Markdown. Never create buyer-intent actions. Do not invent facts or UUIDs.',
  'Context JSON: {{ context_json }}

Raw input: {{ raw_text }}

Return actions using only:
1. seller_fact_update targeting seller_target for actual target facts.
2. target_follow_up targeting seller_target for dated seller-side progress notes.
3. unresolved_item when the content cannot be safely classified.

For target_follow_up use proposed_changes_json keys occurred_on, content, buyer_names. For seller_fact_update use canonical seller_target fields from context. Output Chinese text. Omit null fields and do not echo the full input.',
  '{"type":"object","required":["actions"],"properties":{"actions":{"type":"array"}}}'::jsonb,
  '[]'::jsonb, 'jinja', '["context_json","raw_text"]'::jsonb,
  true, true, '00000000-0000-0000-0000-000000000201',
  '{"source":"migration_036_specialized_update_parsers"}'::jsonb
),
(
  '00000000-0000-0000-0000-000000004238',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  'buyer_intent_update_parser', 'v0.1.0',
  'Buyer intent update and follow-up parser',
  'Extract buyer-intent field changes and intent-scoped follow-up records only.',
  'You parse updates for one known buyer acquisition intent. Output one JSON object with an actions array and no Markdown. Never create seller facts, target follow-ups, buyer-party changes, relations, or target links. Do not invent facts or UUIDs.',
  'Context JSON: {{ context_json }}

Raw input: {{ raw_text }}

Return actions using only:
1. buyer_intent_update targeting buyer_intent when acquisition requirements changed.
2. buyer_intent_follow_up targeting buyer_intent for calls, meetings, recommendations, feedback, progress, or next steps.
3. unresolved_item only when neither applies.

buyer_intent_follow_up proposed_changes_json may use occurred_at, contact_name, content, next_step, next_follow_up_at. A follow-up is valid even when it has no structured buyer-intent field changes. Preserve mentioned target names only inside content; never link or update seller targets.

buyer_intent_update may use canonical intent fields including industries_json, excluded_industries_json, industry_focus_tags_json, min/max valuation, PE, PS, margins, listing preference, financing stage, transaction methods, risk tolerance, exclusions, preferences and unknowns. industries_json must use exact values from context_json.industry_l1_list; preserve detailed tracks in industry_focus_tags_json. Estimation/valuation is not market capitalization. Output Chinese text, omit null fields, and do not echo the full input.',
  '{"type":"object","required":["actions"],"properties":{"actions":{"type":"array"}}}'::jsonb,
  '[]'::jsonb, 'jinja', '["context_json","raw_text"]'::jsonb,
  true, true, '00000000-0000-0000-0000-000000000201',
  '{"source":"migration_036_specialized_update_parsers"}'::jsonb
)
on conflict (team_id, workspace_id, node_name, version) do update set
  system_prompt = excluded.system_prompt,
  user_prompt_template = excluded.user_prompt_template,
  output_schema_json = excluded.output_schema_json,
  variables_json = excluded.variables_json,
  is_active = true,
  is_default = true,
  updated_at = now(),
  metadata_json = excluded.metadata_json;

update prompt_template
set is_default = false, updated_at = now()
where node_name = 'buyer_intent_parser' and version <> 'v0.6.0';

insert into prompt_template (
  id, team_id, workspace_id, node_name, version, name, description,
  system_prompt, user_prompt_template, output_schema_json,
  few_shot_examples_json, template_engine, variables_json,
  is_active, is_default, created_by, metadata_json
)
values (
  '00000000-0000-0000-0000-000000004239',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  'buyer_intent_parser', 'v0.6.0',
  'Buyer intent parser with semantic field separation',
  'Parse one buyer requirement into canonical fields without modifying the buyer party.',
  'You parse one buyer acquisition requirement. Output one JSON object with a fields object and no Markdown. Do not output buyer_party. Do not invent facts. Use Chinese for user-facing text and exact canonical enum values where required.',
  'Raw buyer requirement:
{{ raw_requirement_text }}

Existing intent context JSON:
{{ buyer_profile_json }}

Closed level-1 industries:
{{ industry_l1_list }}

Return only supported fields that have evidence. Do not output null fields and do not repeat raw_requirement_text.

Industry rules:
- industries_json contains every applicable level-1 industry, each copied exactly from the closed list.
- industry_focus_tags_json preserves all specific Chinese tracks such as 新式茶饮、宠物医疗、垂类电商SaaS.
- industry_primary and industry_secondary remain concise descriptive Chinese labels, not level-1 replacements.

Financial rules:
- min_valuation_yuan and max_valuation_yuan are valuation bounds.
- min_market_cap_yuan and max_market_cap_yuan are only for explicit market-cap evidence. Never copy valuation into market-cap fields.
- max_pe and max_ps are different multiples.
- min_net_margin and min_gross_margin are numeric percentage values.
- money values are CNY yuan numbers.

Capital-market rules:
- preferred_listed_status is one of listed, unlisted, preparing_listing, pre_ipo, any, unknown only when explicitly supported.
- A/B round and similar financing details belong in financing_stage_requirement_summary, not listing status.
- words such as 优先、一般、可放宽 describe preferences; preserve them in priority_summary or preference_summary rather than turning them into hard facts.

Use the remaining existing canonical buyer_intent fields for revenue, profit, region, equity, transaction, premium, debt, risk, exclusion, preference and unknown summaries.',
  '{"type":"object","required":["fields"],"properties":{"fields":{"type":"object"}}}'::jsonb,
  '[]'::jsonb, 'jinja',
  '["raw_requirement_text","buyer_profile_json","industry_l1_list"]'::jsonb,
  true, true, '00000000-0000-0000-0000-000000000201',
  '{"source":"migration_036_specialized_update_parsers"}'::jsonb
)
on conflict (team_id, workspace_id, node_name, version) do update set
  system_prompt = excluded.system_prompt,
  user_prompt_template = excluded.user_prompt_template,
  output_schema_json = excluded.output_schema_json,
  variables_json = excluded.variables_json,
  is_active = true,
  is_default = true,
  updated_at = now(),
  metadata_json = excluded.metadata_json;

commit;
