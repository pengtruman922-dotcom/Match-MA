-- Match-MA real business update extractor prompt v0.1
-- Purpose: replace placeholder prompt with a usable JSON extraction prompt.

begin;

update prompt_template
set is_default = false,
    updated_at = now()
where team_id = '00000000-0000-0000-0000-000000000001'
  and workspace_id = '00000000-0000-0000-0000-000000000101'
  and node_name = 'business_update_extractor'
  and version <> 'v0.2.0';

insert into prompt_template (
  id, team_id, workspace_id, node_name, version, name, description,
  system_prompt, user_prompt_template, output_schema_json,
  few_shot_examples_json, template_engine, variables_json,
  is_active, is_default, created_by, metadata_json
)
values (
  '00000000-0000-0000-0000-000000004203',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  'business_update_extractor',
  'v0.2.0',
  'Business update extractor real LLM baseline',
  'Extract pending-review actions from business update text.',
  'You extract structured actions for Match-MA, an internal M&A matching platform. Output only one JSON object, no Markdown. Top level must contain actions array. Allowed action_type values: seller_fact_update, seller_event, buyer_seller_relation_update, buyer_intent_target_exclusion, buyer_intent_update, buyer_level_blacklist_suggestion, internal_note, unresolved_item. Use null target_entity_id when uncertain. Never invent UUIDs. This version creates pending-review actions only.',
  'Context JSON: {{ context_json }}

Raw input: {{ raw_text }}

Return JSON in this shape:
{
  "actions": [
    {
      "action_type": "seller_event",
      "target_entity_type": "seller_target",
      "target_entity_id": null,
      "proposed_changes_json": {"event_summary": "..."},
      "raw_evidence_text": "original evidence span",
      "confidence": 0.80,
      "reason": "why this action was extracted"
    }
  ]
}

Rules:
1. Use seller_fact_update for current seller target fact changes. proposed_changes_json may include finance, deal, summary, risk, or status fields.
2. Use buyer_intent_update for buyer requirement changes. target_entity_type is buyer_intent.
3. Use buyer_seller_relation_update for recommendation, in-talk, due diligence, terminated, or buyer feedback progress. If clearly not interested, also create buyer_intent_target_exclusion.
4. Use seller_event or internal_note for process notes that should not update the current snapshot.
5. Use unresolved_item when confidence is low, classification is unclear, or key target objects are missing.
6. Normalize money amounts to CNY yuan numbers. Normalize percentages to numeric percentage values, e.g. use 51 for a 51 percent share.
7. If the input contains multiple independent matters, return multiple actions.',
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
  '{"source":"migration_005_real_business_update_extractor_prompt"}'::jsonb
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
