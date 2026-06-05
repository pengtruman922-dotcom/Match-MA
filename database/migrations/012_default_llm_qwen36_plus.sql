-- Match-MA default LLM model upgrade v0.1
-- Purpose: switch default text/multimodal LLM nodes from qwen3.6-flash to qwen3.6-plus.

begin;

update model_node_config
set model_name = 'qwen3.6-plus',
    timeout_seconds = case
      when node_name = 'business_update_extractor' then greatest(coalesce(timeout_seconds, 90), 120)
      else timeout_seconds
    end,
    max_tokens = case
      when node_name = 'business_update_extractor' then greatest(coalesce(max_tokens, 4096), 8192)
      else max_tokens
    end,
    metadata_json = coalesce(metadata_json, '{}'::jsonb) || jsonb_build_object(
      'model_upgrade_source', 'migration_012_default_llm_qwen36_plus',
      'previous_default_model', 'qwen3.6-flash',
      'supports_multimodal_input', node_name = 'business_update_extractor'
    ),
    updated_at = now()
where team_id = '00000000-0000-0000-0000-000000000001'
  and workspace_id = '00000000-0000-0000-0000-000000000101'
  and node_type = 'llm'
  and is_default = true
  and node_name in (
    'business_update_extractor',
    'buyer_intent_parser',
    'seller_target_parser',
    'recommendation_report_writer'
  );

commit;
