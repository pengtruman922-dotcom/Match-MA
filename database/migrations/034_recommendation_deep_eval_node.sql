-- Match-MA recommendation deep-eval node and prompt v0.1
-- Purpose: replace the generic rerank model with an LLM deep evaluation that
-- grades every candidate (A/B/C) with a reason, risks, and info gaps. The
-- rerank job/message plumbing is reused; only the engine changes. The rerank
-- handler falls back to the legacy rerank model when this node is absent.

begin;

insert into model_node_config (
  id, team_id, workspace_id, node_name, node_type, provider_config_id,
  model_name, temperature, top_p, max_tokens, timeout_seconds,
  response_format, output_mode, embedding_dimension,
  is_active, is_default, created_by, metadata_json
)
values (
  '00000000-0000-0000-0000-000000004109',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  'recommendation_deep_eval',
  'llm',
  '00000000-0000-0000-0000-000000004001',
  'qwen3.6-plus',
  0.200,
  0.900,
  8192,
  180,
  'json_object',
  'json',
  null,
  true,
  true,
  '00000000-0000-0000-0000-000000000201',
  '{"purpose":"Deep-evaluate recommendation candidates with grades and reasons.","has_prompt":true,"queue_name":"rerank"}'::jsonb
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
  and node_name = 'recommendation_deep_eval'
  and version <> 'v0.1.0';

insert into prompt_template (
  id, team_id, workspace_id, node_name, version, name, description,
  system_prompt, user_prompt_template, output_schema_json,
  few_shot_examples_json, template_engine, variables_json,
  is_active, is_default, created_by, metadata_json
)
values (
  '00000000-0000-0000-0000-000000004228',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  'recommendation_deep_eval',
  'v0.1.0',
  'Recommendation deep evaluation',
  'Grade recommendation candidates (A/B/C) against the anchor with concise Chinese reasons, risks, and info gaps.',
  'You are an M&A matchmaking analyst for Match-MA, an internal M&A matching platform. You evaluate how well each candidate fits the anchor (a buyer intent or a seller target). Output only one JSON object, no Markdown. Be strict about hard constraints (financial thresholds, budget vs price, exclusions, equity/control requirements) and thoughtful about soft fit (industry track, region, business synergy, buyer capital strength).',
  'Mode: {{ mode }}
(buyer_to_target means the anchor is a buyer intent and candidates are seller targets; target_to_buyer means the anchor is a seller target and candidates are buyer intents.)

Anchor profile:
{{ anchor_context }}

Candidates (JSON array; each item has index, name, rule_score, recommendation_level, matches, gaps, profile):
{{ candidates_json }}

Return JSON in this shape:
{
  "results": [
    {"index": 0, "grade": "A", "reason": "一句话推荐理由", "risks": "主要风险或不确定点", "info_gaps": "需要补充的关键信息"}
  ]
}

Rules:
1. Grade every candidate exactly once: A = 高度契合、建议优先推进; B = 基本契合、值得跟进; C = 契合度低或存在硬伤，仅作备选.
2. Weigh hard constraints first: financial thresholds, budget versus price/valuation, PE cap, equity/control requirements, and exclusions. Then weigh soft fit: industry tracks beyond the primary one, region, listed status, business synergy, and buyer capital strength found in the free-text profiles.
3. A candidate whose gaps mention 命中排除项 or an unmet hard threshold must NOT be graded A; name the blocker in reason.
4. reason, risks, and info_gaps must each be one concise Chinese sentence; do not repeat the candidate name inside them; use 暂无 when there is nothing to say.
5. Order results from most recommended to least recommended. Cover every candidate index exactly once.',
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
            "grade": {"type": "string"},
            "reason": {"type": ["string", "null"]},
            "risks": {"type": ["string", "null"]},
            "info_gaps": {"type": ["string", "null"]}
          }
        }
      }
    }
  }'::jsonb,
  '[]'::jsonb,
  'jinja',
  '["mode", "anchor_context", "candidates_json"]'::jsonb,
  true,
  true,
  '00000000-0000-0000-0000-000000000201',
  '{"source":"migration_034_recommendation_deep_eval_node"}'::jsonb
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
