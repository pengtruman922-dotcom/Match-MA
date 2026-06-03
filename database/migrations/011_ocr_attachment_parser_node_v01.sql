-- Match-MA OCR attachment parser node v0.1
-- Purpose: register the OCR worker node used by attachment_ocr_parse jobs.

begin;

insert into model_node_config (
  id, team_id, workspace_id, node_name, node_type, provider_config_id,
  model_name, temperature, top_p, max_tokens, timeout_seconds,
  response_format, output_mode, embedding_dimension,
  is_active, is_default, created_by, metadata_json
)
values (
  '00000000-0000-0000-0000-000000004108',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  'ocr_attachment_parser',
  'ocr',
  '00000000-0000-0000-0000-000000004001',
  'ocr-skeleton-v0',
  null,
  null,
  null,
  120,
  null,
  'mixed',
  null,
  true,
  true,
  '00000000-0000-0000-0000-000000000201',
  '{"purpose":"Parse uploaded attachments via OCR or document extraction.","has_prompt":false,"queue_name":"ocr","execution_mode":"skeleton"}'::jsonb
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

commit;
