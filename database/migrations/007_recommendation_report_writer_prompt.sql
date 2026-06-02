update prompt_template
set is_default = false,
    updated_at = now()
where team_id = '00000000-0000-0000-0000-000000000001'
  and workspace_id = '00000000-0000-0000-0000-000000000101'
  and node_name = 'recommendation_report_writer'
  and version <> 'v0.1.0';

insert into prompt_template (
  id, team_id, workspace_id, node_name, version, name, description,
  system_prompt, user_prompt_template, output_schema_json,
  few_shot_examples_json, template_engine, variables_json,
  is_active, is_default, created_by, metadata_json
)
values (
  '00000000-0000-0000-0000-000000004205',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  'recommendation_report_writer',
  'v0.1.0',
  'Recommendation report writer baseline',
  'Draft a readable recommendation report from selected recommendation items.',
  'You write concise Chinese Markdown reports for Match-MA, an internal M&A matching platform. Use only the provided context. Do not invent financial figures, entity names, deal status, or risks. If information is missing, state that it needs review. Output Markdown only, no JSON, no code fence.',
  'Context JSON: {{ context_json }}

Write a recommendation report with these sections:
# Title
## Executive summary
## Recommended list
## Match rationale
## Gaps and risks
## Suggested next steps

Rules:
1. Keep the report business-readable and concise.
2. Separate confirmed facts from system inference.
3. Mention each selected item and its buyer, intent, target, recommendation level, match summary, gaps, and risk summary when available.
4. If there are multiple selected items, rank them in the same order as context.selected_items.
5. Do not include source code, raw JSON, or debug logs.',
  '{}'::jsonb,
  '[]'::jsonb,
  'jinja',
  '["context_json"]'::jsonb,
  true,
  true,
  '00000000-0000-0000-0000-000000000201',
  '{"source":"migration_007_recommendation_report_writer_prompt"}'::jsonb
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
