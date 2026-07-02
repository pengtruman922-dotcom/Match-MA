-- Match-MA buyer intent parser timeout tuning
-- Purpose: qwen3.6-plus can exceed 90 seconds on longer natural-language
-- buyer requirements, so keep the parser aligned with other long-running LLM
-- extraction nodes.

begin;

update model_node_config
set timeout_seconds = greatest(coalesce(timeout_seconds, 90), 300),
    metadata_json = coalesce(metadata_json, '{}'::jsonb) || jsonb_build_object(
      'timeout_tuning_reason', 'qwen3.6-plus buyer intent parsing can exceed 90 seconds on long natural-language requirements',
      'timeout_tuning_source', 'migration_024_buyer_intent_parser_timeout'
    ),
    updated_at = now()
where team_id = '00000000-0000-0000-0000-000000000001'
  and workspace_id = '00000000-0000-0000-0000-000000000101'
  and node_name = 'buyer_intent_parser';

commit;
