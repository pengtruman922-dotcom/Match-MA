-- Retire recommendation embedding and generic rerank nodes from the active path.

begin;

update model_node_config
set is_active = false,
    is_default = false,
    updated_at = now(),
    metadata_json = metadata_json || '{"retired_reason":"recommendation_v3_sql_rules_deep_eval"}'::jsonb
where node_name in (
  'embedding_seller_doc',
  'embedding_buyer_intent',
  'recommendation_reranker'
);

commit;
