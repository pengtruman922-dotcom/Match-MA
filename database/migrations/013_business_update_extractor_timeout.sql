-- Match-MA business update extractor timeout tuning v0.1
-- Purpose: allow qwen3.6-plus enough time for longer attachment-backed extraction jobs.

begin;

update model_node_config
set timeout_seconds = greatest(coalesce(timeout_seconds, 90), 300),
    metadata_json = coalesce(metadata_json, '{}'::jsonb) || jsonb_build_object(
      'timeout_tuning_source', 'migration_013_business_update_extractor_timeout',
      'timeout_tuning_reason', 'qwen3.6-plus attachment-backed business updates can exceed 120 seconds'
    ),
    updated_at = now()
where team_id = '00000000-0000-0000-0000-000000000001'
  and workspace_id = '00000000-0000-0000-0000-000000000101'
  and node_name = 'business_update_extractor'
  and node_type = 'llm'
  and is_default = true;

commit;
