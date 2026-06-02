insert into model_provider_config (
  id, team_id, workspace_id, provider_name, provider_type,
  base_url, api_key_secret_ref, auth_type, is_active, is_default, created_by, metadata_json
)
values (
  '00000000-0000-0000-0000-000000004002',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  'aliyun_dashscope_rerank',
  'custom',
  'https://dashscope.aliyuncs.com/compatible-api/v1',
  'ALIYUN_API_KEY',
  'bearer',
  true,
  false,
  '00000000-0000-0000-0000-000000000201',
  '{"purpose":"Aliyun DashScope qwen3-rerank endpoint for rerank nodes."}'::jsonb
)
on conflict (team_id, workspace_id, provider_name) do update set
  provider_type = excluded.provider_type,
  base_url = excluded.base_url,
  api_key_secret_ref = excluded.api_key_secret_ref,
  auth_type = excluded.auth_type,
  is_active = excluded.is_active,
  metadata_json = excluded.metadata_json,
  updated_at = now();

update model_node_config
set provider_config_id = '00000000-0000-0000-0000-000000004002',
    model_name = 'qwen3-rerank',
    temperature = null,
    top_p = null,
    max_tokens = null,
    timeout_seconds = 90,
    response_format = null,
    output_mode = 'json',
    metadata_json = metadata_json || '{"purpose":"Rerank recommendation candidates with qwen3-rerank.","has_prompt":false,"queue_name":"rerank"}'::jsonb,
    updated_at = now()
where team_id = '00000000-0000-0000-0000-000000000001'
  and workspace_id = '00000000-0000-0000-0000-000000000101'
  and node_name = 'recommendation_reranker'
  and is_default = true;
