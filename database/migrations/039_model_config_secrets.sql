-- Treat provider rows as callable model configurations and support encrypted keys.

begin;

alter table model_provider_config
  add column if not exists model_name text,
  add column if not exists secret_mode text not null default 'env',
  add column if not exists api_key_encrypted text;

update model_provider_config provider
set model_name = coalesce(
      nullif(provider.model_name, ''),
      (
        select node.model_name
        from model_node_config node
        where node.provider_config_id = provider.id
        order by
          case when node.node_type in ('llm', 'parser', 'research') then 0 else 1 end,
          node.is_active desc, node.is_default desc, node.updated_at desc
        limit 1
      ),
      provider.provider_name
    ),
    secret_mode = case
      when provider.api_key_encrypted is not null then 'direct'
      else 'env'
    end;

alter table model_provider_config
  alter column model_name set not null;

alter table model_provider_config
  drop constraint if exists chk_model_provider_secret_mode;

alter table model_provider_config
  add constraint chk_model_provider_secret_mode check (secret_mode in ('env', 'direct'));

-- Chat providers apply their own output ceiling when max_tokens is omitted.
update model_node_config
set max_tokens = null,
    updated_at = now()
where node_type in ('llm', 'parser', 'research')
  and max_tokens is not null;

update model_provider_config provider
set is_active = false,
    is_default = false,
    updated_at = now(),
    metadata_json = coalesce(metadata_json, '{}'::jsonb)
      || '{"retired_reason":"generic_rerank_path_disabled"}'::jsonb
where (
    provider.model_name = 'qwen3-rerank'
    or provider.provider_name = 'aliyun_dashscope_rerank'
  )
  and not exists (
    select 1 from model_node_config node
    where node.provider_config_id = provider.id and node.is_active = true
  );

commit;
