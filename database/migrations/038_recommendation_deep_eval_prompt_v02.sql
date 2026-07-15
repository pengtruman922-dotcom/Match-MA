-- Recommendation deep-eval prompt v0.2: score only buyer-intent requirements.

begin;

update model_node_config
set metadata_json = coalesce(metadata_json, '{}'::jsonb)
      || '{"queue_name":"llm","recommendation_engine":"sql_python_llm_deep_eval"}'::jsonb,
    updated_at = now()
where node_name = 'recommendation_deep_eval'
  and is_default = true;

update prompt_template
set is_default = false, updated_at = now()
where node_name = 'recommendation_deep_eval'
  and version <> 'v0.2.0';

insert into prompt_template (
  id, team_id, workspace_id, node_name, version, name, description,
  system_prompt, user_prompt_template, output_schema_json,
  few_shot_examples_json, template_engine, variables_json,
  is_active, is_default, created_by, metadata_json
)
values (
  '00000000-0000-0000-0000-000000004240',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  'recommendation_deep_eval', 'v0.2.0',
  'Recommendation deep evaluation from intent requirements',
  'Grade candidates using seller-target facts and buyer-intent requirements only.',
  'You are an M&A matchmaking analyst for Match-MA. Evaluate candidates using seller-target facts and buyer-intent requirements only. Buyer-party profile attributes such as capital strength, company scale, location, main business, group background, or listed status must not affect the grade unless the buyer intent itself states the same item as an acquisition requirement. Output one JSON object and no Markdown.',
  'Mode: {{ mode }}

Anchor profile:
{{ anchor_context }}

Candidates:
{{ candidates_json }}

Return:
{
  "results": [
    {"index": 0, "grade": "A", "reason": "一句话推荐理由", "risks": "主要风险或不确定点", "info_gaps": "需要补充的信息"}
  ]
}

Rules:
1. Grade every candidate exactly once. A means highly suitable, B means worth following, and C means weak fit or a hard mismatch.
2. Apply explicit exclusions and hard thresholds first, including industry, financial, budget, valuation, PE or PS, equity, control, consolidation, listing, region, and risk requirements.
3. Evaluate multiple industries and listing preferences as alternatives unless the intent explicitly says all conditions must hold together.
4. Never infer a buyer requirement from buyer-party profile data. Buyer identity is display context only.
5. A candidate with an exclusion hit or unmet hard threshold cannot receive A.
6. Use only supplied evidence. Put missing target facts in info_gaps instead of inventing them.
7. Keep reason, risks, and info_gaps concise Chinese sentences and use 暂无 when empty.
8. Return every candidate index exactly once, ordered from most to least recommended.',
  '{
    "type": "object",
    "required": ["results"],
    "properties": {
      "results": {
        "type": "array",
        "items": {
          "type": "object",
          "required": ["index", "grade"],
          "properties": {
            "index": {"type": "integer"},
            "grade": {"type": "string", "enum": ["A", "B", "C"]},
            "reason": {"type": ["string", "null"]},
            "risks": {"type": ["string", "null"]},
            "info_gaps": {"type": ["string", "null"]}
          }
        }
      }
    }
  }'::jsonb,
  '[]'::jsonb, 'jinja',
  '["mode","anchor_context","candidates_json"]'::jsonb,
  true, true, '00000000-0000-0000-0000-000000000201',
  '{"source":"migration_038_recommendation_deep_eval_prompt_v02"}'::jsonb
)
on conflict (team_id, workspace_id, node_name, version) do update set
  name = excluded.name,
  description = excluded.description,
  system_prompt = excluded.system_prompt,
  user_prompt_template = excluded.user_prompt_template,
  output_schema_json = excluded.output_schema_json,
  variables_json = excluded.variables_json,
  is_active = true,
  is_default = true,
  updated_at = now(),
  metadata_json = excluded.metadata_json;

commit;
