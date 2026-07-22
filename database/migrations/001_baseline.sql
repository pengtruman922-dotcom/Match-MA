-- Match-MA baseline schema
-- Generated 2026-07-22 from the production schema after migration 048
-- (charter docs/系统总纲.md §6.3). Replaces migrations 001-048. The alembic
-- revision keeps the pre-squash id 20260722_0048 so the production database
-- needs no stamping -- only fresh databases execute this file.
-- Seeds at the bottom: default team/workspace/users, the industry dictionary
-- and the current default prompt versions exported from production.

create table action_application_log (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  extracted_action_id uuid,
  business_update_id uuid,
  entity_type text not null,
  entity_id uuid not null,
  field_path text not null,
  old_value_json jsonb,
  new_value_json jsonb,
  source_type text,
  source_id uuid,
  evidence_id uuid,
  applied_by uuid,
  applied_at timestamp with time zone not null default now(),
  edited_before_apply boolean not null default false,
  can_rollback boolean not null default true,
  rollback_at timestamp with time zone,
  metadata_json jsonb not null default '{}'::jsonb,
  constraint action_application_log_pkey PRIMARY KEY (id)
);

create table ai_trace (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  trace_type text not null,
  node_name text not null,
  job_id uuid,
  correlation_id uuid,
  entity_type text,
  entity_id uuid,
  provider_config_id uuid,
  node_config_id uuid,
  prompt_template_id uuid,
  provider_name text,
  model_name text,
  prompt_version text,
  status text not null default 'started'::text,
  input_json jsonb not null default '{}'::jsonb,
  prompt_messages_json jsonb not null default '[]'::jsonb,
  raw_output_text text,
  parsed_output_json jsonb,
  output_schema_json jsonb,
  schema_validation_json jsonb not null default '{}'::jsonb,
  retrieval_input_json jsonb not null default '{}'::jsonb,
  retrieval_output_json jsonb not null default '{}'::jsonb,
  tool_calls_json jsonb not null default '[]'::jsonb,
  error_code text,
  error_message text,
  error_detail_json jsonb not null default '{}'::jsonb,
  latency_ms integer,
  prompt_tokens integer,
  completion_tokens integer,
  total_tokens integer,
  cost_json jsonb not null default '{}'::jsonb,
  started_at timestamp with time zone not null default now(),
  finished_at timestamp with time zone,
  created_by uuid,
  metadata_json jsonb not null default '{}'::jsonb,
  constraint ai_trace_pkey PRIMARY KEY (id),
  constraint chk_ai_trace_status CHECK ((status = ANY (ARRAY['started'::text, 'succeeded'::text, 'failed'::text, 'skipped'::text]))),
  constraint chk_ai_trace_type CHECK ((trace_type = ANY (ARRAY['llm'::text, 'embedding'::text, 'ocr'::text, 'parser'::text, 'retrieval'::text, 'rerank'::text, 'research'::text, 'system'::text])))
);

create table app_user (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  default_workspace_id uuid,
  name text not null,
  email text,
  role text not null default 'consultant'::text,
  status text not null default 'active'::text,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  username text,
  password_hash text,
  constraint app_user_pkey PRIMARY KEY (id),
  constraint app_user_role_check CHECK ((role = ANY (ARRAY['consultant'::text, 'manager'::text, 'admin'::text, 'developer'::text]))),
  constraint app_user_status_check CHECK ((status = ANY (ARRAY['active'::text, 'disabled'::text])))
);

create table attachment (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  visibility text not null default 'workspace'::text,
  file_name text not null,
  file_type text,
  mime_type text,
  file_size bigint,
  storage_path text not null,
  uploaded_by uuid,
  uploaded_at timestamp with time zone not null default now(),
  parse_status text not null default 'pending'::text,
  metadata_json jsonb not null default '{}'::jsonb,
  deleted_at timestamp with time zone,
  deleted_by uuid,
  constraint attachment_parse_status_check CHECK ((parse_status = ANY (ARRAY['pending'::text, 'parsing'::text, 'parsed'::text, 'failed'::text, 'skipped'::text]))),
  constraint attachment_pkey PRIMARY KEY (id),
  constraint attachment_visibility_check CHECK ((visibility = ANY (ARRAY['workspace'::text, 'team'::text, 'private'::text])))
);

create table attachment_link (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  attachment_id uuid not null,
  entity_type text not null,
  entity_id uuid not null,
  link_type text,
  created_at timestamp with time zone not null default now(),
  created_by uuid,
  constraint attachment_link_pkey PRIMARY KEY (id)
);

create table background_job (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  job_type text not null,
  status text not null default 'queued'::text,
  priority integer not null default 100,
  queue_name text not null default 'default'::text,
  entity_type text,
  entity_id uuid,
  idempotency_key text,
  payload_json jsonb not null default '{}'::jsonb,
  result_json jsonb not null default '{}'::jsonb,
  error_code text,
  error_message text,
  error_detail_json jsonb not null default '{}'::jsonb,
  attempt_count integer not null default 0,
  max_attempts integer not null default 3,
  run_after timestamp with time zone not null default now(),
  locked_by text,
  locked_at timestamp with time zone,
  started_at timestamp with time zone,
  finished_at timestamp with time zone,
  parent_job_id uuid,
  correlation_id uuid,
  created_by uuid,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  metadata_json jsonb not null default '{}'::jsonb,
  constraint background_job_pkey PRIMARY KEY (id),
  constraint chk_background_job_status CHECK ((status = ANY (ARRAY['queued'::text, 'running'::text, 'succeeded'::text, 'failed'::text, 'cancelled'::text, 'retry_waiting'::text])))
);

create table business_update (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  raw_text text,
  input_type text not null default 'text'::text,
  processing_status text not null default 'pending'::text,
  bound_seller_target_ids_json jsonb not null default '[]'::jsonb,
  bound_buyer_party_ids_json jsonb not null default '[]'::jsonb,
  bound_buyer_intent_ids_json jsonb not null default '[]'::jsonb,
  bound_recommendation_session_id uuid,
  created_by uuid,
  created_at timestamp with time zone not null default now(),
  metadata_json jsonb not null default '{}'::jsonb,
  constraint business_update_input_type_check CHECK ((input_type = ANY (ARRAY['text'::text, 'screenshot'::text, 'attachment'::text, 'mixed'::text]))),
  constraint business_update_pkey PRIMARY KEY (id),
  constraint business_update_processing_status_check CHECK ((processing_status = ANY (ARRAY['pending'::text, 'processing'::text, 'parsed'::text, 'partially_applied'::text, 'applied'::text, 'failed'::text])))
);

create table buyer_intent (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  buyer_party_id uuid,
  owner_user_id uuid,
  intent_name text not null,
  status text not null default 'active'::text,
  pause_reason text,
  contact_name text,
  contact_info_json jsonb not null default '{}'::jsonb,
  raw_requirement_text text,
  intent_summary text,
  parsed_requirement_json jsonb not null default '{}'::jsonb,
  industry_primary text,
  industry_secondary text,
  region_scope_summary text,
  region_constraints_json jsonb not null default '[]'::jsonb,
  min_revenue_yuan numeric(20,2),
  min_net_profit_yuan numeric(20,2),
  min_total_profit_yuan numeric(20,2),
  max_pe numeric(10,4),
  max_valuation_yuan numeric(20,2),
  market_cap_range_summary text,
  requires_control text not null default 'unknown'::text,
  requires_consolidation text not null default 'unknown'::text,
  accepts_minority_investment text not null default 'unknown'::text,
  desired_equity_ratio_min numeric(10,4),
  desired_equity_ratio_max numeric(10,4),
  equity_ratio_summary text,
  equity_requirement_type text,
  acceptable_control_paths_json jsonb not null default '[]'::jsonb,
  preferred_listed_status text,
  transaction_type text,
  negative_summary text,
  priority_summary text,
  preference_summary text,
  unknown_summary text,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamp with time zone not null default now(),
  created_by uuid,
  updated_at timestamp with time zone not null default now(),
  updated_by uuid,
  deleted_at timestamp with time zone,
  deleted_by uuid,
  min_market_cap_yuan numeric(20,2),
  max_market_cap_yuan numeric(20,2),
  listing_board_requirement_summary text,
  financing_stage_requirement_summary text,
  premium_tolerance_summary text,
  max_premium_rate numeric(10,4),
  max_debt_ratio numeric(10,4),
  debt_ratio_requirement_summary text,
  major_risk_tolerance_summary text,
  buyer_industry_advantage_summary text,
  transaction_types_json jsonb not null default '[]'::jsonb,
  industries_json jsonb not null default '[]'::jsonb,
  excluded_industries_json jsonb not null default '[]'::jsonb,
  min_valuation_yuan numeric(20,2),
  max_ps numeric(10,4),
  min_net_margin numeric(10,4),
  min_gross_margin numeric(10,4),
  industry_focus_tags_json jsonb not null default '[]'::jsonb,
  industry_l2_json jsonb not null default '[]'::jsonb,
  acceptable_cash_flow_status_json jsonb not null default '[]'::jsonb,
  acceptable_profitability_status_json jsonb not null default '[]'::jsonb,
  requires_relocation text not null default 'unknown'::text,
  relocation_target_regions_json jsonb not null default '[]'::jsonb,
  requires_return_investment text not null default 'unknown'::text,
  return_investment_multiple numeric(10,4),
  requires_team_retention text not null default 'unknown'::text,
  earnout_requirement text not null default 'unknown'::text,
  listing_market_region text,
  budget_min_yuan numeric(20,2),
  budget_max_yuan numeric(20,2),
  constraint buyer_intent_accepts_minority_investment_check CHECK ((accepts_minority_investment = ANY (ARRAY['yes'::text, 'no'::text, 'unknown'::text, 'likely'::text]))),
  constraint buyer_intent_check CHECK (((desired_equity_ratio_min IS NULL) OR (desired_equity_ratio_max IS NULL) OR (desired_equity_ratio_min <= desired_equity_ratio_max))),
  constraint buyer_intent_desired_equity_ratio_max_check CHECK (((desired_equity_ratio_max IS NULL) OR (desired_equity_ratio_max <= (100)::numeric))),
  constraint buyer_intent_desired_equity_ratio_min_check CHECK (((desired_equity_ratio_min IS NULL) OR (desired_equity_ratio_min >= (0)::numeric))),
  constraint buyer_intent_equity_requirement_type_check CHECK ((equity_requirement_type = ANY (ARRAY['control_required'::text, 'consolidation_required'::text, 'minority_acceptable'::text, 'minority_only'::text, 'flexible'::text, 'specific_range'::text, 'unknown'::text]))),
  constraint buyer_intent_market_cap_range_check CHECK (((min_market_cap_yuan IS NULL) OR (max_market_cap_yuan IS NULL) OR (min_market_cap_yuan <= max_market_cap_yuan))),
  constraint buyer_intent_pkey PRIMARY KEY (id),
  constraint buyer_intent_preferred_listed_status_check CHECK ((preferred_listed_status = ANY (ARRAY['listed'::text, 'preparing_listing'::text, 'pre_ipo'::text, 'unlisted'::text, 'any'::text, 'unknown'::text]))),
  constraint buyer_intent_requires_consolidation_check CHECK ((requires_consolidation = ANY (ARRAY['yes'::text, 'no'::text, 'unknown'::text, 'likely'::text]))),
  constraint buyer_intent_requires_control_check CHECK ((requires_control = ANY (ARRAY['yes'::text, 'no'::text, 'unknown'::text, 'likely'::text]))),
  constraint buyer_intent_status_check CHECK ((status = ANY (ARRAY['active'::text, 'paused'::text, 'closed'::text]))),
  constraint chk_buyer_intent_listing_market_region CHECK (((listing_market_region IS NULL) OR (listing_market_region = ANY (ARRAY['domestic'::text, 'overseas'::text, 'unknown'::text])))),
  constraint chk_buyer_intent_requirement_strength CHECK (((requires_relocation = ANY (ARRAY['required'::text, 'preferred'::text, 'not_required'::text, 'unknown'::text])) AND (requires_return_investment = ANY (ARRAY['required'::text, 'preferred'::text, 'not_required'::text, 'unknown'::text])) AND (requires_team_retention = ANY (ARRAY['required'::text, 'preferred'::text, 'not_required'::text, 'unknown'::text])) AND (earnout_requirement = ANY (ARRAY['required'::text, 'preferred'::text, 'not_required'::text, 'unknown'::text]))))
);

create table buyer_intent_follow_up (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  buyer_intent_id uuid not null,
  occurred_at timestamp with time zone not null default now(),
  contact_name text,
  content text not null,
  next_step text,
  next_follow_up_at timestamp with time zone,
  business_update_id uuid,
  extracted_action_id uuid,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamp with time zone not null default now(),
  created_by uuid,
  deleted_at timestamp with time zone,
  deleted_by uuid,
  constraint buyer_intent_follow_up_pkey PRIMARY KEY (id)
);

create table buyer_intent_scenario (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  buyer_intent_id uuid not null,
  label text not null,
  sort_order integer not null default 0,
  active boolean not null default true,
  fields_json jsonb not null default '{}'::jsonb,
  source text not null default 'parser'::text,
  created_at timestamp with time zone not null default now(),
  created_by uuid,
  updated_at timestamp with time zone not null default now(),
  updated_by uuid,
  deleted_at timestamp with time zone,
  constraint buyer_intent_scenario_pkey PRIMARY KEY (id),
  constraint buyer_intent_scenario_source_check CHECK ((source = ANY (ARRAY['parser'::text, 'manual'::text, 'chat'::text])))
);

create table buyer_intent_search_doc (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  buyer_intent_id uuid not null,
  title text,
  requirement_summary text,
  constraint_text text,
  preference_text text,
  negative_text text,
  history_text text,
  full_text text,
  embedding vector(1024),
  embedding_model text default 'text-embedding-v4'::text,
  embedding_dim integer default 1024,
  source_version integer not null default 1,
  updated_at timestamp with time zone not null default now(),
  constraint buyer_intent_search_doc_buyer_intent_id_key UNIQUE (buyer_intent_id),
  constraint buyer_intent_search_doc_pkey PRIMARY KEY (id)
);

create table buyer_intent_target_exclusion (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  buyer_intent_id uuid not null,
  buyer_party_id uuid,
  seller_target_id uuid not null,
  reason text,
  source_relation_id uuid,
  source_update_id uuid,
  source_event_id uuid,
  active boolean not null default true,
  created_by uuid,
  created_at timestamp with time zone not null default now(),
  canceled_by uuid,
  canceled_at timestamp with time zone,
  constraint buyer_intent_target_exclusion_pkey PRIMARY KEY (id)
);

create table buyer_party (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  buyer_name text not null,
  legal_name text,
  aliases_json jsonb not null default '[]'::jsonb,
  buyer_type text,
  group_name text,
  listed_status text not null default 'unknown'::text,
  region_country text default '中国'::text,
  region_province text,
  region_city text,
  main_business text,
  capital_strength_summary text,
  profile_summary text,
  long_term_preference_json jsonb not null default '{}'::jsonb,
  owner_user_id uuid,
  status text not null default 'active'::text,
  merged_into_id uuid,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamp with time zone not null default now(),
  created_by uuid,
  updated_at timestamp with time zone not null default now(),
  updated_by uuid,
  deleted_at timestamp with time zone,
  deleted_by uuid,
  notes text,
  constraint buyer_party_buyer_type_check CHECK ((buyer_type = ANY (ARRAY['industrial_buyer'::text, 'listed_company'::text, 'state_owned_platform'::text, 'pe_fund'::text, 'financial_investor'::text, 'government_platform'::text, 'other'::text]))),
  constraint buyer_party_listed_status_check CHECK ((listed_status = ANY (ARRAY['listed'::text, 'unlisted'::text, 'pre_ipo'::text, 'unknown'::text]))),
  constraint buyer_party_pkey PRIMARY KEY (id),
  constraint buyer_party_status_check CHECK ((status = ANY (ARRAY['active'::text, 'archived'::text, 'merged'::text])))
);

create table buyer_seller_relation (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  buyer_intent_id uuid not null,
  buyer_party_id uuid,
  seller_target_id uuid not null,
  status text not null default 'recommended'::text,
  status_reason text,
  owner_user_id uuid,
  first_recommended_at timestamp with time zone,
  last_contact_at timestamp with time zone,
  last_event_at timestamp with time zone,
  last_event_summary text,
  created_from_session_id uuid,
  created_from_report_id uuid,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamp with time zone not null default now(),
  created_by uuid,
  updated_at timestamp with time zone not null default now(),
  updated_by uuid,
  deleted_at timestamp with time zone,
  deleted_by uuid,
  constraint buyer_seller_relation_pkey PRIMARY KEY (id),
  constraint buyer_seller_relation_status_check CHECK ((status = ANY (ARRAY['recommended'::text, 'interested'::text, 'in_discussion'::text, 'due_diligence'::text, 'agreement'::text, 'deal_closed'::text, 'not_interested'::text, 'paused'::text, 'lost'::text])))
);

create table entity_profile_section (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  entity_type text not null,
  entity_id uuid not null,
  section_code text not null,
  info_status text not null default 'filled'::text,
  content_text text,
  source_type text,
  source_url text,
  source_title text,
  source_excerpt text,
  as_of_date date,
  confidence numeric(5,4),
  review_status text not null default 'accepted'::text,
  created_at timestamp with time zone not null default now(),
  created_by uuid,
  updated_at timestamp with time zone not null default now(),
  updated_by uuid,
  deleted_at timestamp with time zone,
  constraint entity_profile_section_entity_type_check CHECK ((entity_type = ANY (ARRAY['seller_target'::text, 'buyer_intent'::text]))),
  constraint entity_profile_section_info_status_check CHECK ((info_status = ANY (ARRAY['filled'::text, 'not_found'::text, 'not_applicable'::text]))),
  constraint entity_profile_section_pkey PRIMARY KEY (id),
  constraint entity_profile_section_review_status_check CHECK ((review_status = ANY (ARRAY['pending_review'::text, 'accepted'::text, 'rejected'::text, 'auto_accepted'::text, 'ignored'::text]))),
  constraint entity_profile_section_section_code_check CHECK ((section_code = ANY (ARRAY['business_product'::text, 'chain_position'::text, 'tech_team'::text, 'ops_quality'::text, 'deal_terms'::text, 'sell_intent_risk'::text])))
);

create table evidence_span (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  source_type text not null,
  source_id uuid,
  attachment_id uuid,
  parsed_document_id uuid,
  page_no integer,
  slide_no integer,
  sheet_name text,
  cell_range text,
  text_excerpt text,
  char_start integer,
  char_end integer,
  created_at timestamp with time zone not null default now(),
  constraint evidence_span_pkey PRIMARY KEY (id)
);

create table extracted_action (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  business_update_id uuid not null,
  action_type text not null,
  target_entity_type text,
  target_entity_id uuid,
  proposed_changes_json jsonb not null default '{}'::jsonb,
  raw_evidence_text text,
  evidence_id uuid,
  confidence numeric(5,4),
  review_status text not null default 'pending_review'::text,
  reviewed_by uuid,
  reviewed_at timestamp with time zone,
  applied_at timestamp with time zone,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamp with time zone not null default now(),
  constraint chk_extracted_action_type CHECK ((action_type = ANY (ARRAY['seller_fact_update'::text, 'seller_event'::text, 'target_follow_up'::text, 'buyer_intent_follow_up'::text, 'buyer_seller_relation_update'::text, 'buyer_intent_target_exclusion'::text, 'buyer_intent_update'::text, 'buyer_level_blacklist_suggestion'::text, 'internal_note'::text, 'unresolved_item'::text]))),
  constraint extracted_action_pkey PRIMARY KEY (id),
  constraint extracted_action_review_status_check CHECK ((review_status = ANY (ARRAY['pending_review'::text, 'accepted'::text, 'rejected'::text, 'auto_accepted'::text, 'ignored'::text])))
);

create table field_value_source (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  entity_type text not null,
  entity_id uuid not null,
  field_path text not null,
  value_snapshot_json jsonb not null default '{}'::jsonb,
  source_type text,
  source_id uuid,
  evidence_id uuid,
  source_label text,
  confidence numeric(5,4),
  review_status text not null default 'pending_review'::text,
  created_at timestamp with time zone not null default now(),
  created_by uuid,
  constraint field_value_source_pkey PRIMARY KEY (id),
  constraint field_value_source_review_status_check CHECK ((review_status = ANY (ARRAY['pending_review'::text, 'accepted'::text, 'rejected'::text, 'auto_accepted'::text, 'ignored'::text])))
);

create table industry_taxonomy (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  term text not null,
  level text not null,
  l1_name text not null,
  active boolean not null default true,
  sort_order integer not null default 0,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  parent_id uuid,
  canonical_term_id uuid,
  constraint industry_taxonomy_level_check CHECK ((level = ANY (ARRAY['l1'::text, 'l2'::text, 'alias'::text]))),
  constraint industry_taxonomy_pkey PRIMARY KEY (id)
);

create table model_node_config (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  node_name text not null,
  node_type text not null,
  provider_config_id uuid not null,
  model_name text not null,
  temperature numeric(4,3),
  top_p numeric(4,3),
  max_tokens integer,
  timeout_seconds integer not null default 60,
  response_format text,
  output_mode text not null default 'text'::text,
  embedding_dimension integer,
  is_active boolean not null default true,
  is_default boolean not null default false,
  created_by uuid,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  metadata_json jsonb not null default '{}'::jsonb,
  constraint chk_model_node_output_mode CHECK ((output_mode = ANY (ARRAY['text'::text, 'json'::text, 'embedding'::text, 'file'::text, 'mixed'::text]))),
  constraint chk_model_node_type CHECK ((node_type = ANY (ARRAY['llm'::text, 'embedding'::text, 'ocr'::text, 'rerank'::text, 'research'::text, 'parser'::text]))),
  constraint model_node_config_pkey PRIMARY KEY (id)
);

create table model_provider_config (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  provider_name text not null,
  provider_type text not null,
  base_url text,
  api_key_secret_ref text,
  auth_type text not null default 'bearer'::text,
  extra_headers_json jsonb not null default '{}'::jsonb,
  extra_config_json jsonb not null default '{}'::jsonb,
  is_active boolean not null default true,
  is_default boolean not null default false,
  created_by uuid,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  metadata_json jsonb not null default '{}'::jsonb,
  model_name text not null,
  secret_mode text not null default 'env'::text,
  api_key_encrypted text,
  constraint chk_model_provider_auth_type CHECK ((auth_type = ANY (ARRAY['none'::text, 'bearer'::text, 'api_key_header'::text, 'custom'::text]))),
  constraint chk_model_provider_secret_mode CHECK ((secret_mode = ANY (ARRAY['env'::text, 'direct'::text]))),
  constraint chk_model_provider_type CHECK ((provider_type = ANY (ARRAY['openai_compatible'::text, 'dashscope'::text, 'deepseek'::text, 'azure_openai'::text, 'ocr'::text, 'embedding'::text, 'search'::text, 'custom'::text]))),
  constraint model_provider_config_pkey PRIMARY KEY (id)
);

create table parsed_document (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  attachment_id uuid not null,
  parser_name text,
  parser_version text,
  parse_status text not null default 'pending'::text,
  text_path text,
  markdown_path text,
  manifest_path text,
  page_count integer,
  token_count integer,
  error_message text,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint parsed_document_parse_status_check CHECK ((parse_status = ANY (ARRAY['pending'::text, 'parsing'::text, 'parsed'::text, 'failed'::text, 'skipped'::text]))),
  constraint parsed_document_pkey PRIMARY KEY (id)
);

create table prompt_template (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  node_name text not null,
  version text not null,
  name text,
  description text,
  system_prompt text,
  user_prompt_template text,
  output_schema_json jsonb not null default '{}'::jsonb,
  few_shot_examples_json jsonb not null default '[]'::jsonb,
  template_engine text not null default 'jinja'::text,
  variables_json jsonb not null default '[]'::jsonb,
  is_active boolean not null default true,
  is_default boolean not null default false,
  created_by uuid,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  metadata_json jsonb not null default '{}'::jsonb,
  constraint chk_prompt_template_engine CHECK ((template_engine = ANY (ARRAY['jinja'::text, 'plain'::text, 'custom'::text]))),
  constraint prompt_template_pkey PRIMARY KEY (id),
  constraint uq_prompt_template_version UNIQUE (team_id, workspace_id, node_name, version)
);

create table recommendation_message (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  session_id uuid not null,
  role text not null,
  content text not null,
  content_type text not null default 'text'::text,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamp with time zone not null default now(),
  created_by uuid,
  constraint recommendation_message_content_type_check CHECK ((content_type = ANY (ARRAY['text'::text, 'json'::text, 'markdown'::text]))),
  constraint recommendation_message_pkey PRIMARY KEY (id),
  constraint recommendation_message_role_check CHECK ((role = ANY (ARRAY['user'::text, 'assistant'::text, 'system'::text, 'tool'::text])))
);

create table recommendation_report (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  session_id uuid not null,
  report_type text not null,
  selected_item_ids_json jsonb not null default '[]'::jsonb,
  title text,
  markdown_content text,
  file_path text,
  file_format text,
  status text not null default 'generated'::text,
  generated_by_model text,
  prompt_version text,
  created_by uuid,
  created_at timestamp with time zone not null default now(),
  metadata_json jsonb not null default '{}'::jsonb,
  constraint recommendation_report_file_format_check CHECK ((file_format = ANY (ARRAY['markdown'::text, 'docx'::text, 'pdf'::text]))),
  constraint recommendation_report_pkey PRIMARY KEY (id),
  constraint recommendation_report_report_type_check CHECK ((report_type = ANY (ARRAY['buyer_facing_target_report'::text, 'internal_buyer_list'::text]))),
  constraint recommendation_report_status_check CHECK ((status = ANY (ARRAY['generating'::text, 'generated'::text, 'failed'::text, 'archived'::text])))
);

create table recommendation_selected_item (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  session_id uuid not null,
  mode text not null,
  seller_target_id uuid,
  buyer_intent_id uuid,
  buyer_party_id uuid,
  selected_from_message_id uuid,
  rank_at_selection integer,
  recommendation_level text,
  match_summary text,
  risk_summary text,
  gap_summary text,
  reason_snapshot text,
  evidence_snapshot_json jsonb not null default '{}'::jsonb,
  selected_by uuid,
  selected_at timestamp with time zone not null default now(),
  canceled_by uuid,
  canceled_at timestamp with time zone,
  metadata_json jsonb not null default '{}'::jsonb,
  constraint recommendation_selected_item_mode_check CHECK ((mode = ANY (ARRAY['buyer_to_target'::text, 'target_to_buyer'::text]))),
  constraint recommendation_selected_item_pkey PRIMARY KEY (id),
  constraint recommendation_selected_item_recommendation_level_check CHECK ((recommendation_level = ANY (ARRAY['strong'::text, 'recommended'::text, 'possible'::text, 'weak'::text])))
);

create table recommendation_session (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  mode text not null,
  buyer_intent_id uuid,
  buyer_party_id uuid,
  seller_target_id uuid,
  anonymous_input_snapshot text,
  initial_condition_snapshot_json jsonb not null default '{}'::jsonb,
  latest_condition_snapshot_json jsonb not null default '{}'::jsonb,
  status text not null default 'active'::text,
  selected_count integer not null default 0,
  report_count integer not null default 0,
  created_by uuid,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  archived_at timestamp with time zone,
  metadata_json jsonb not null default '{}'::jsonb,
  condition_overrides_json jsonb not null default '{}'::jsonb,
  constraint recommendation_session_mode_check CHECK ((mode = ANY (ARRAY['buyer_to_target'::text, 'target_to_buyer'::text]))),
  constraint recommendation_session_pkey PRIMARY KEY (id),
  constraint recommendation_session_status_check CHECK ((status = ANY (ARRAY['active'::text, 'archived'::text, 'completed'::text])))
);

create table relation_event (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  relation_id uuid not null,
  buyer_intent_id uuid not null,
  buyer_party_id uuid,
  seller_target_id uuid not null,
  event_type text not null,
  event_time timestamp with time zone not null default now(),
  title text,
  content text,
  next_step text,
  source_type text,
  source_id uuid,
  evidence_id uuid,
  metadata_json jsonb not null default '{}'::jsonb,
  created_by uuid,
  created_at timestamp with time zone not null default now(),
  constraint relation_event_event_type_check CHECK ((event_type = ANY (ARRAY['recommended'::text, 'buyer_interested'::text, 'buyer_not_interested'::text, 'meeting'::text, 'call'::text, 'material_sent'::text, 'due_diligence_started'::text, 'agreement_discussion'::text, 'deal_closed'::text, 'paused'::text, 'internal_note'::text, 'other'::text]))),
  constraint relation_event_pkey PRIMARY KEY (id)
);

create table research_proposal (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  entity_type text not null,
  entity_id uuid not null,
  job_id uuid,
  proposal_kind text not null,
  section_code text,
  field_path text,
  proposed_value_json jsonb not null default '{}'::jsonb,
  current_value_json jsonb not null default '{}'::jsonb,
  conflict_kind text not null default 'supplement'::text,
  period_label text,
  as_of_date date,
  source_type text,
  source_url text,
  source_title text,
  source_excerpt text,
  anchor_matches_json jsonb not null default '[]'::jsonb,
  confidence numeric(5,4),
  review_status text not null default 'pending_review'::text,
  reviewed_by uuid,
  reviewed_at timestamp with time zone,
  created_at timestamp with time zone not null default now(),
  created_by uuid,
  updated_at timestamp with time zone not null default now(),
  deleted_at timestamp with time zone,
  constraint research_proposal_conflict_kind_check CHECK ((conflict_kind = ANY (ARRAY['consistent'::text, 'supplement'::text, 'temporal_update'::text, 'same_period_conflict'::text]))),
  constraint research_proposal_entity_type_check CHECK ((entity_type = ANY (ARRAY['seller_target'::text, 'buyer_intent'::text]))),
  constraint research_proposal_pkey PRIMARY KEY (id),
  constraint research_proposal_proposal_kind_check CHECK ((proposal_kind = ANY (ARRAY['profile_section'::text, 'structured_fact'::text]))),
  constraint research_proposal_review_status_check CHECK ((review_status = ANY (ARRAY['pending_review'::text, 'accepted'::text, 'rejected'::text, 'auto_accepted'::text, 'ignored'::text])))
);

create table seller_target (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  target_name text not null,
  target_type text not null default 'company'::text,
  owner_user_id uuid,
  recommendation_status text not null default 'recommendable'::text,
  information_status text not null default 'insufficient'::text,
  industry_primary text,
  industry_secondary text,
  registered_province text,
  registered_city text,
  headquarter_province text,
  headquarter_city text,
  raw_region_text text,
  region_granularity text,
  listed_status text not null default 'unknown'::text,
  market_cap_yuan numeric(20,2),
  current_revenue_yuan numeric(20,2),
  current_net_profit_yuan numeric(20,2),
  current_total_profit_yuan numeric(20,2),
  current_assets_yuan numeric(20,2),
  current_debt_ratio numeric(10,4),
  current_operating_cash_flow_yuan numeric(20,2),
  financial_period_label text,
  profitability_status text,
  cash_flow_status text,
  operation_stability_status text,
  valuation_yuan numeric(20,2),
  asking_price_yuan numeric(20,2),
  pe_ratio numeric(10,4),
  pe_source_type text,
  premium_rate numeric(10,4),
  is_for_sale text not null default 'unknown'::text,
  can_control text not null default 'unknown'::text,
  can_consolidate text not null default 'unknown'::text,
  accepts_minority_investment text not null default 'unknown'::text,
  transfer_ratio_min numeric(10,4),
  transfer_ratio_max numeric(10,4),
  transfer_ratio_text text,
  transfer_flexibility_type text,
  consolidation_path_summary text,
  accepts_relocation text not null default 'unknown'::text,
  accepts_return_investment text not null default 'unknown'::text,
  management_team_summary text,
  management_retention_possible text not null default 'unknown'::text,
  earnout_dependency_status text,
  business_summary text,
  transaction_summary text,
  risk_summary text,
  gap_summary text,
  last_research_at timestamp with time zone,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamp with time zone not null default now(),
  created_by uuid,
  updated_at timestamp with time zone not null default now(),
  updated_by uuid,
  deleted_at timestamp with time zone,
  deleted_by uuid,
  target_subject_name text,
  valuation_date text,
  asking_price_date text,
  lifecycle_status text not null default 'active'::text,
  industry_l1 text,
  industry_l2 text,
  listing_market_region text,
  research_last_outcome text,
  constraint chk_seller_target_listing_market_region CHECK (((listing_market_region IS NULL) OR (listing_market_region = ANY (ARRAY['domestic'::text, 'overseas'::text, 'unknown'::text])))),
  constraint chk_seller_target_research_outcome CHECK (((research_last_outcome IS NULL) OR (research_last_outcome = ANY (ARRAY['found'::text, 'no_public_information'::text, 'failed'::text])))),
  constraint seller_target_accepts_minority_investment_check CHECK ((accepts_minority_investment = ANY (ARRAY['yes'::text, 'no'::text, 'unknown'::text, 'likely'::text]))),
  constraint seller_target_accepts_relocation_check CHECK ((accepts_relocation = ANY (ARRAY['yes'::text, 'no'::text, 'unknown'::text, 'likely'::text]))),
  constraint seller_target_accepts_return_investment_check CHECK ((accepts_return_investment = ANY (ARRAY['yes'::text, 'no'::text, 'unknown'::text, 'likely'::text]))),
  constraint seller_target_can_consolidate_check CHECK ((can_consolidate = ANY (ARRAY['yes'::text, 'no'::text, 'unknown'::text, 'likely'::text]))),
  constraint seller_target_can_control_check CHECK ((can_control = ANY (ARRAY['yes'::text, 'no'::text, 'unknown'::text, 'likely'::text]))),
  constraint seller_target_cash_flow_status_check CHECK ((cash_flow_status = ANY (ARRAY['stable_positive'::text, 'positive'::text, 'negative'::text, 'unstable'::text, 'unknown'::text]))),
  constraint seller_target_check CHECK (((transfer_ratio_min IS NULL) OR (transfer_ratio_max IS NULL) OR (transfer_ratio_min <= transfer_ratio_max))),
  constraint seller_target_earnout_dependency_status_check CHECK ((earnout_dependency_status = ANY (ARRAY['none'::text, 'low'::text, 'medium'::text, 'high'::text, 'unknown'::text]))),
  constraint seller_target_information_status_check CHECK ((information_status = ANY (ARRAY['normal'::text, 'insufficient'::text, 'pending_review'::text, 'parsing'::text, 'researching'::text, 'parse_failed'::text]))),
  constraint seller_target_is_for_sale_check CHECK ((is_for_sale = ANY (ARRAY['yes'::text, 'no'::text, 'unknown'::text, 'likely'::text]))),
  constraint seller_target_lifecycle_status_check CHECK ((lifecycle_status = ANY (ARRAY['active'::text, 'sold'::text, 'off_market'::text]))),
  constraint seller_target_listed_status_check CHECK ((listed_status = ANY (ARRAY['listed'::text, 'unlisted'::text, 'pre_ipo'::text, 'unknown'::text]))),
  constraint seller_target_management_retention_possible_check CHECK ((management_retention_possible = ANY (ARRAY['yes'::text, 'no'::text, 'unknown'::text, 'likely'::text]))),
  constraint seller_target_operation_stability_status_check CHECK ((operation_stability_status = ANY (ARRAY['stable'::text, 'unstable'::text, 'unknown'::text, 'needs_review'::text]))),
  constraint seller_target_pe_source_type_check CHECK ((pe_source_type = ANY (ARRAY['user_input'::text, 'document'::text, 'calculated'::text, 'research'::text, 'unknown'::text]))),
  constraint seller_target_pkey PRIMARY KEY (id),
  constraint seller_target_profitability_status_check CHECK ((profitability_status = ANY (ARRAY['profitable'::text, 'loss_making'::text, 'break_even'::text, 'unknown'::text]))),
  constraint seller_target_recommendation_status_check CHECK ((recommendation_status = ANY (ARRAY['recommendable'::text, 'not_recommendable'::text]))),
  constraint seller_target_region_granularity_check CHECK ((region_granularity = ANY (ARRAY['country'::text, 'province'::text, 'city'::text, 'district'::text, 'region_group'::text, 'unknown'::text]))),
  constraint seller_target_target_type_check CHECK ((target_type = ANY (ARRAY['company'::text, 'equity_package'::text, 'business_unit'::text, 'asset_package'::text, 'project'::text, 'other'::text]))),
  constraint seller_target_transfer_flexibility_type_check CHECK ((transfer_flexibility_type = ANY (ARRAY['control_available'::text, 'consolidation_available'::text, 'minority_available'::text, 'full_sale_available'::text, 'flexible'::text, 'specific_range'::text, 'unknown'::text]))),
  constraint seller_target_transfer_ratio_max_check CHECK (((transfer_ratio_max IS NULL) OR (transfer_ratio_max <= (100)::numeric))),
  constraint seller_target_transfer_ratio_min_check CHECK (((transfer_ratio_min IS NULL) OR (transfer_ratio_min >= (0)::numeric)))
);

create table seller_target_search_doc (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  seller_target_id uuid not null,
  doc_type text not null default 'profile'::text,
  title text,
  structured_summary text,
  tag_text text,
  business_text text,
  financial_text text,
  transaction_text text,
  risk_text text,
  gap_text text,
  full_text text,
  embedding vector(1024),
  embedding_model text default 'text-embedding-v4'::text,
  embedding_dim integer default 1024,
  source_version integer not null default 1,
  updated_at timestamp with time zone not null default now(),
  constraint seller_target_search_doc_doc_type_check CHECK ((doc_type = ANY (ARRAY['profile'::text, 'business'::text, 'transaction'::text, 'risk'::text, 'attachment_summary'::text, 'research_summary'::text]))),
  constraint seller_target_search_doc_pkey PRIMARY KEY (id),
  constraint seller_target_search_doc_seller_target_id_doc_type_key UNIQUE (seller_target_id, doc_type)
);

create table target_follow_up (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  seller_target_id uuid not null,
  occurred_on date not null default CURRENT_DATE,
  content text not null,
  related_buyer_party_ids_json jsonb not null default '[]'::jsonb,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamp with time zone not null default now(),
  created_by uuid,
  deleted_at timestamp with time zone,
  deleted_by uuid,
  constraint target_follow_up_pkey PRIMARY KEY (id)
);

create table team (
  id uuid not null default gen_random_uuid(),
  name text not null,
  status text not null default 'active'::text,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint team_pkey PRIMARY KEY (id),
  constraint team_status_check CHECK ((status = ANY (ARRAY['active'::text, 'archived'::text])))
);

create table workspace (
  id uuid not null default gen_random_uuid(),
  team_id uuid not null,
  name text not null,
  workspace_type text not null default 'department'::text,
  status text not null default 'active'::text,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  constraint workspace_pkey PRIMARY KEY (id),
  constraint workspace_status_check CHECK ((status = ANY (ARRAY['active'::text, 'archived'::text]))),
  constraint workspace_workspace_type_check CHECK ((workspace_type = ANY (ARRAY['department'::text, 'project'::text, 'data_space'::text, 'special_task'::text, 'other'::text])))
);

-- Foreign keys, applied after every table exists
alter table action_application_log add constraint action_application_log_applied_by_fkey FOREIGN KEY (applied_by) REFERENCES app_user(id);
alter table action_application_log add constraint action_application_log_business_update_id_fkey FOREIGN KEY (business_update_id) REFERENCES business_update(id);
alter table action_application_log add constraint action_application_log_evidence_id_fkey FOREIGN KEY (evidence_id) REFERENCES evidence_span(id);
alter table action_application_log add constraint action_application_log_extracted_action_id_fkey FOREIGN KEY (extracted_action_id) REFERENCES extracted_action(id);
alter table action_application_log add constraint action_application_log_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table action_application_log add constraint action_application_log_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table ai_trace add constraint ai_trace_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table ai_trace add constraint ai_trace_job_id_fkey FOREIGN KEY (job_id) REFERENCES background_job(id);
alter table ai_trace add constraint ai_trace_node_config_id_fkey FOREIGN KEY (node_config_id) REFERENCES model_node_config(id);
alter table ai_trace add constraint ai_trace_prompt_template_id_fkey FOREIGN KEY (prompt_template_id) REFERENCES prompt_template(id);
alter table ai_trace add constraint ai_trace_provider_config_id_fkey FOREIGN KEY (provider_config_id) REFERENCES model_provider_config(id);
alter table ai_trace add constraint ai_trace_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table ai_trace add constraint ai_trace_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table app_user add constraint app_user_default_workspace_id_fkey FOREIGN KEY (default_workspace_id) REFERENCES workspace(id);
alter table app_user add constraint app_user_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table attachment add constraint attachment_deleted_by_fkey FOREIGN KEY (deleted_by) REFERENCES app_user(id);
alter table attachment add constraint attachment_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table attachment add constraint attachment_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES app_user(id);
alter table attachment add constraint attachment_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table attachment_link add constraint attachment_link_attachment_id_fkey FOREIGN KEY (attachment_id) REFERENCES attachment(id);
alter table attachment_link add constraint attachment_link_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table attachment_link add constraint attachment_link_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table attachment_link add constraint attachment_link_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table background_job add constraint background_job_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table background_job add constraint background_job_parent_job_id_fkey FOREIGN KEY (parent_job_id) REFERENCES background_job(id);
alter table background_job add constraint background_job_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table background_job add constraint background_job_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table business_update add constraint business_update_bound_recommendation_session_id_fkey FOREIGN KEY (bound_recommendation_session_id) REFERENCES recommendation_session(id);
alter table business_update add constraint business_update_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table business_update add constraint business_update_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table business_update add constraint business_update_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table buyer_intent add constraint buyer_intent_buyer_party_id_fkey FOREIGN KEY (buyer_party_id) REFERENCES buyer_party(id);
alter table buyer_intent add constraint buyer_intent_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table buyer_intent add constraint buyer_intent_deleted_by_fkey FOREIGN KEY (deleted_by) REFERENCES app_user(id);
alter table buyer_intent add constraint buyer_intent_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES app_user(id);
alter table buyer_intent add constraint buyer_intent_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table buyer_intent add constraint buyer_intent_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES app_user(id);
alter table buyer_intent add constraint buyer_intent_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table buyer_intent_follow_up add constraint buyer_intent_follow_up_business_update_id_fkey FOREIGN KEY (business_update_id) REFERENCES business_update(id);
alter table buyer_intent_follow_up add constraint buyer_intent_follow_up_buyer_intent_id_fkey FOREIGN KEY (buyer_intent_id) REFERENCES buyer_intent(id);
alter table buyer_intent_follow_up add constraint buyer_intent_follow_up_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table buyer_intent_follow_up add constraint buyer_intent_follow_up_deleted_by_fkey FOREIGN KEY (deleted_by) REFERENCES app_user(id);
alter table buyer_intent_follow_up add constraint buyer_intent_follow_up_extracted_action_id_fkey FOREIGN KEY (extracted_action_id) REFERENCES extracted_action(id);
alter table buyer_intent_follow_up add constraint buyer_intent_follow_up_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table buyer_intent_follow_up add constraint buyer_intent_follow_up_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table buyer_intent_scenario add constraint buyer_intent_scenario_buyer_intent_id_fkey FOREIGN KEY (buyer_intent_id) REFERENCES buyer_intent(id);
alter table buyer_intent_scenario add constraint buyer_intent_scenario_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table buyer_intent_scenario add constraint buyer_intent_scenario_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table buyer_intent_scenario add constraint buyer_intent_scenario_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES app_user(id);
alter table buyer_intent_scenario add constraint buyer_intent_scenario_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table buyer_intent_search_doc add constraint buyer_intent_search_doc_buyer_intent_id_fkey FOREIGN KEY (buyer_intent_id) REFERENCES buyer_intent(id);
alter table buyer_intent_search_doc add constraint buyer_intent_search_doc_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table buyer_intent_search_doc add constraint buyer_intent_search_doc_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table buyer_intent_target_exclusion add constraint buyer_intent_target_exclusion_buyer_intent_id_fkey FOREIGN KEY (buyer_intent_id) REFERENCES buyer_intent(id);
alter table buyer_intent_target_exclusion add constraint buyer_intent_target_exclusion_buyer_party_id_fkey FOREIGN KEY (buyer_party_id) REFERENCES buyer_party(id);
alter table buyer_intent_target_exclusion add constraint buyer_intent_target_exclusion_canceled_by_fkey FOREIGN KEY (canceled_by) REFERENCES app_user(id);
alter table buyer_intent_target_exclusion add constraint buyer_intent_target_exclusion_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table buyer_intent_target_exclusion add constraint buyer_intent_target_exclusion_seller_target_id_fkey FOREIGN KEY (seller_target_id) REFERENCES seller_target(id);
alter table buyer_intent_target_exclusion add constraint buyer_intent_target_exclusion_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table buyer_intent_target_exclusion add constraint buyer_intent_target_exclusion_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table buyer_party add constraint buyer_party_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table buyer_party add constraint buyer_party_deleted_by_fkey FOREIGN KEY (deleted_by) REFERENCES app_user(id);
alter table buyer_party add constraint buyer_party_merged_into_id_fkey FOREIGN KEY (merged_into_id) REFERENCES buyer_party(id);
alter table buyer_party add constraint buyer_party_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES app_user(id);
alter table buyer_party add constraint buyer_party_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table buyer_party add constraint buyer_party_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES app_user(id);
alter table buyer_party add constraint buyer_party_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table buyer_seller_relation add constraint buyer_seller_relation_buyer_intent_id_fkey FOREIGN KEY (buyer_intent_id) REFERENCES buyer_intent(id);
alter table buyer_seller_relation add constraint buyer_seller_relation_buyer_party_id_fkey FOREIGN KEY (buyer_party_id) REFERENCES buyer_party(id);
alter table buyer_seller_relation add constraint buyer_seller_relation_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table buyer_seller_relation add constraint buyer_seller_relation_deleted_by_fkey FOREIGN KEY (deleted_by) REFERENCES app_user(id);
alter table buyer_seller_relation add constraint buyer_seller_relation_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES app_user(id);
alter table buyer_seller_relation add constraint buyer_seller_relation_seller_target_id_fkey FOREIGN KEY (seller_target_id) REFERENCES seller_target(id);
alter table buyer_seller_relation add constraint buyer_seller_relation_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table buyer_seller_relation add constraint buyer_seller_relation_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES app_user(id);
alter table buyer_seller_relation add constraint buyer_seller_relation_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table entity_profile_section add constraint entity_profile_section_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table entity_profile_section add constraint entity_profile_section_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table entity_profile_section add constraint entity_profile_section_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES app_user(id);
alter table entity_profile_section add constraint entity_profile_section_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table evidence_span add constraint evidence_span_attachment_id_fkey FOREIGN KEY (attachment_id) REFERENCES attachment(id);
alter table evidence_span add constraint evidence_span_parsed_document_id_fkey FOREIGN KEY (parsed_document_id) REFERENCES parsed_document(id);
alter table evidence_span add constraint evidence_span_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table evidence_span add constraint evidence_span_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table extracted_action add constraint extracted_action_business_update_id_fkey FOREIGN KEY (business_update_id) REFERENCES business_update(id);
alter table extracted_action add constraint extracted_action_evidence_id_fkey FOREIGN KEY (evidence_id) REFERENCES evidence_span(id);
alter table extracted_action add constraint extracted_action_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES app_user(id);
alter table extracted_action add constraint extracted_action_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table extracted_action add constraint extracted_action_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table field_value_source add constraint field_value_source_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table field_value_source add constraint field_value_source_evidence_id_fkey FOREIGN KEY (evidence_id) REFERENCES evidence_span(id);
alter table field_value_source add constraint field_value_source_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table field_value_source add constraint field_value_source_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table industry_taxonomy add constraint industry_taxonomy_canonical_term_id_fkey FOREIGN KEY (canonical_term_id) REFERENCES industry_taxonomy(id);
alter table industry_taxonomy add constraint industry_taxonomy_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES industry_taxonomy(id);
alter table industry_taxonomy add constraint industry_taxonomy_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table industry_taxonomy add constraint industry_taxonomy_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table model_node_config add constraint model_node_config_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table model_node_config add constraint model_node_config_provider_config_id_fkey FOREIGN KEY (provider_config_id) REFERENCES model_provider_config(id);
alter table model_node_config add constraint model_node_config_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table model_node_config add constraint model_node_config_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table model_provider_config add constraint model_provider_config_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table model_provider_config add constraint model_provider_config_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table model_provider_config add constraint model_provider_config_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table parsed_document add constraint parsed_document_attachment_id_fkey FOREIGN KEY (attachment_id) REFERENCES attachment(id);
alter table parsed_document add constraint parsed_document_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table parsed_document add constraint parsed_document_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table prompt_template add constraint prompt_template_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table prompt_template add constraint prompt_template_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table prompt_template add constraint prompt_template_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table recommendation_message add constraint recommendation_message_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table recommendation_message add constraint recommendation_message_session_id_fkey FOREIGN KEY (session_id) REFERENCES recommendation_session(id);
alter table recommendation_message add constraint recommendation_message_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table recommendation_message add constraint recommendation_message_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table recommendation_report add constraint recommendation_report_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table recommendation_report add constraint recommendation_report_session_id_fkey FOREIGN KEY (session_id) REFERENCES recommendation_session(id);
alter table recommendation_report add constraint recommendation_report_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table recommendation_report add constraint recommendation_report_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table recommendation_selected_item add constraint recommendation_selected_item_buyer_intent_id_fkey FOREIGN KEY (buyer_intent_id) REFERENCES buyer_intent(id);
alter table recommendation_selected_item add constraint recommendation_selected_item_buyer_party_id_fkey FOREIGN KEY (buyer_party_id) REFERENCES buyer_party(id);
alter table recommendation_selected_item add constraint recommendation_selected_item_canceled_by_fkey FOREIGN KEY (canceled_by) REFERENCES app_user(id);
alter table recommendation_selected_item add constraint recommendation_selected_item_selected_by_fkey FOREIGN KEY (selected_by) REFERENCES app_user(id);
alter table recommendation_selected_item add constraint recommendation_selected_item_selected_from_message_id_fkey FOREIGN KEY (selected_from_message_id) REFERENCES recommendation_message(id);
alter table recommendation_selected_item add constraint recommendation_selected_item_seller_target_id_fkey FOREIGN KEY (seller_target_id) REFERENCES seller_target(id);
alter table recommendation_selected_item add constraint recommendation_selected_item_session_id_fkey FOREIGN KEY (session_id) REFERENCES recommendation_session(id);
alter table recommendation_selected_item add constraint recommendation_selected_item_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table recommendation_selected_item add constraint recommendation_selected_item_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table recommendation_session add constraint recommendation_session_buyer_intent_id_fkey FOREIGN KEY (buyer_intent_id) REFERENCES buyer_intent(id);
alter table recommendation_session add constraint recommendation_session_buyer_party_id_fkey FOREIGN KEY (buyer_party_id) REFERENCES buyer_party(id);
alter table recommendation_session add constraint recommendation_session_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table recommendation_session add constraint recommendation_session_seller_target_id_fkey FOREIGN KEY (seller_target_id) REFERENCES seller_target(id);
alter table recommendation_session add constraint recommendation_session_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table recommendation_session add constraint recommendation_session_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table relation_event add constraint relation_event_buyer_intent_id_fkey FOREIGN KEY (buyer_intent_id) REFERENCES buyer_intent(id);
alter table relation_event add constraint relation_event_buyer_party_id_fkey FOREIGN KEY (buyer_party_id) REFERENCES buyer_party(id);
alter table relation_event add constraint relation_event_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table relation_event add constraint relation_event_relation_id_fkey FOREIGN KEY (relation_id) REFERENCES buyer_seller_relation(id);
alter table relation_event add constraint relation_event_seller_target_id_fkey FOREIGN KEY (seller_target_id) REFERENCES seller_target(id);
alter table relation_event add constraint relation_event_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table relation_event add constraint relation_event_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table research_proposal add constraint research_proposal_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table research_proposal add constraint research_proposal_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES app_user(id);
alter table research_proposal add constraint research_proposal_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table research_proposal add constraint research_proposal_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table seller_target add constraint seller_target_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table seller_target add constraint seller_target_deleted_by_fkey FOREIGN KEY (deleted_by) REFERENCES app_user(id);
alter table seller_target add constraint seller_target_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES app_user(id);
alter table seller_target add constraint seller_target_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table seller_target add constraint seller_target_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES app_user(id);
alter table seller_target add constraint seller_target_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table seller_target_search_doc add constraint seller_target_search_doc_seller_target_id_fkey FOREIGN KEY (seller_target_id) REFERENCES seller_target(id);
alter table seller_target_search_doc add constraint seller_target_search_doc_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table seller_target_search_doc add constraint seller_target_search_doc_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table target_follow_up add constraint target_follow_up_created_by_fkey FOREIGN KEY (created_by) REFERENCES app_user(id);
alter table target_follow_up add constraint target_follow_up_deleted_by_fkey FOREIGN KEY (deleted_by) REFERENCES app_user(id);
alter table target_follow_up add constraint target_follow_up_seller_target_id_fkey FOREIGN KEY (seller_target_id) REFERENCES seller_target(id);
alter table target_follow_up add constraint target_follow_up_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);
alter table target_follow_up add constraint target_follow_up_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspace(id);
alter table workspace add constraint workspace_team_id_fkey FOREIGN KEY (team_id) REFERENCES team(id);

-- Indexes not implied by primary key or unique constraints
CREATE INDEX idx_action_log_action ON public.action_application_log USING btree (extracted_action_id);
CREATE INDEX idx_action_log_entity ON public.action_application_log USING btree (entity_type, entity_id, applied_at DESC);
CREATE INDEX idx_action_log_update ON public.action_application_log USING btree (business_update_id);
CREATE INDEX idx_ai_trace_correlation ON public.ai_trace USING btree (correlation_id, started_at DESC);
CREATE INDEX idx_ai_trace_entity ON public.ai_trace USING btree (entity_type, entity_id, started_at DESC);
CREATE INDEX idx_ai_trace_job ON public.ai_trace USING btree (job_id, started_at DESC);
CREATE INDEX idx_ai_trace_node ON public.ai_trace USING btree (node_name, started_at DESC);
CREATE INDEX idx_ai_trace_scope ON public.ai_trace USING btree (team_id, workspace_id, started_at DESC);
CREATE INDEX idx_app_user_team ON public.app_user USING btree (team_id, status);
CREATE UNIQUE INDEX uq_app_user_username ON public.app_user USING btree (lower(username)) WHERE (username IS NOT NULL);
CREATE INDEX idx_attachment_scope ON public.attachment USING btree (team_id, workspace_id, parse_status) WHERE (deleted_at IS NULL);
CREATE INDEX idx_attachment_link_attachment ON public.attachment_link USING btree (attachment_id);
CREATE INDEX idx_attachment_link_entity ON public.attachment_link USING btree (entity_type, entity_id);
CREATE INDEX idx_background_job_correlation ON public.background_job USING btree (correlation_id);
CREATE INDEX idx_background_job_entity ON public.background_job USING btree (entity_type, entity_id, created_at DESC);
CREATE INDEX idx_background_job_fetch ON public.background_job USING btree (queue_name, status, run_after, priority, created_at);
CREATE INDEX idx_background_job_idempotency ON public.background_job USING btree (team_id, workspace_id, job_type, idempotency_key) WHERE (idempotency_key IS NOT NULL);
CREATE INDEX idx_background_job_scope ON public.background_job USING btree (team_id, workspace_id, status, created_at DESC);
CREATE INDEX idx_business_update_metadata ON public.business_update USING gin (metadata_json);
CREATE INDEX idx_business_update_scope ON public.business_update USING btree (team_id, workspace_id, processing_status, created_at DESC);
CREATE INDEX idx_buyer_intent_industry ON public.buyer_intent USING btree (team_id, industry_primary, industry_secondary) WHERE (deleted_at IS NULL);
CREATE INDEX idx_buyer_intent_owner ON public.buyer_intent USING btree (owner_user_id) WHERE (deleted_at IS NULL);
CREATE INDEX idx_buyer_intent_party ON public.buyer_intent USING btree (buyer_party_id) WHERE (deleted_at IS NULL);
CREATE INDEX idx_buyer_intent_scope ON public.buyer_intent USING btree (team_id, workspace_id, status) WHERE (deleted_at IS NULL);
CREATE INDEX idx_buyer_intent_text_trgm ON public.buyer_intent USING gin (intent_name gin_trgm_ops);
CREATE INDEX idx_buyer_intent_follow_up_intent ON public.buyer_intent_follow_up USING btree (buyer_intent_id, occurred_at DESC, created_at DESC) WHERE (deleted_at IS NULL);
CREATE UNIQUE INDEX uq_buyer_intent_follow_up_action ON public.buyer_intent_follow_up USING btree (extracted_action_id) WHERE ((extracted_action_id IS NOT NULL) AND (deleted_at IS NULL));
CREATE INDEX idx_buyer_intent_scenario_intent ON public.buyer_intent_scenario USING btree (team_id, buyer_intent_id, sort_order) WHERE ((deleted_at IS NULL) AND (active = true));
CREATE INDEX idx_buyer_search_embedding ON public.buyer_intent_search_doc USING ivfflat (embedding vector_cosine_ops) WITH (lists='100');
CREATE INDEX idx_buyer_search_full_text_trgm ON public.buyer_intent_search_doc USING gin (full_text gin_trgm_ops);
CREATE INDEX idx_buyer_search_intent ON public.buyer_intent_search_doc USING btree (buyer_intent_id);
CREATE INDEX idx_exclusion_target ON public.buyer_intent_target_exclusion USING btree (seller_target_id) WHERE ((active = true) AND (canceled_at IS NULL));
CREATE UNIQUE INDEX uniq_active_intent_target_exclusion ON public.buyer_intent_target_exclusion USING btree (team_id, buyer_intent_id, seller_target_id) WHERE ((active = true) AND (canceled_at IS NULL));
CREATE INDEX idx_buyer_party_legal_trgm ON public.buyer_party USING gin (legal_name gin_trgm_ops);
CREATE INDEX idx_buyer_party_name_trgm ON public.buyer_party USING gin (buyer_name gin_trgm_ops);
CREATE INDEX idx_buyer_party_scope ON public.buyer_party USING btree (team_id, workspace_id, status) WHERE (deleted_at IS NULL);
CREATE INDEX idx_relation_intent ON public.buyer_seller_relation USING btree (buyer_intent_id, status) WHERE (deleted_at IS NULL);
CREATE INDEX idx_relation_recent ON public.buyer_seller_relation USING btree (team_id, last_event_at DESC) WHERE (deleted_at IS NULL);
CREATE INDEX idx_relation_target ON public.buyer_seller_relation USING btree (seller_target_id, status) WHERE (deleted_at IS NULL);
CREATE UNIQUE INDEX uniq_buyer_seller_relation_active ON public.buyer_seller_relation USING btree (team_id, buyer_intent_id, seller_target_id) WHERE (deleted_at IS NULL);
CREATE INDEX idx_entity_profile_section_entity ON public.entity_profile_section USING btree (team_id, entity_type, entity_id, section_code) WHERE (deleted_at IS NULL);
CREATE INDEX idx_entity_profile_section_review ON public.entity_profile_section USING btree (team_id, review_status) WHERE ((deleted_at IS NULL) AND (review_status = 'pending_review'::text));
CREATE INDEX idx_evidence_attachment ON public.evidence_span USING btree (attachment_id);
CREATE INDEX idx_evidence_source ON public.evidence_span USING btree (source_type, source_id);
CREATE INDEX idx_extracted_action_review ON public.extracted_action USING btree (team_id, workspace_id, review_status);
CREATE INDEX idx_extracted_action_target ON public.extracted_action USING btree (target_entity_type, target_entity_id);
CREATE INDEX idx_extracted_action_update ON public.extracted_action USING btree (business_update_id);
CREATE INDEX idx_field_source_entity ON public.field_value_source USING btree (entity_type, entity_id, field_path);
CREATE INDEX idx_field_source_review ON public.field_value_source USING btree (team_id, review_status);
CREATE INDEX idx_industry_taxonomy_canonical ON public.industry_taxonomy USING btree (team_id, workspace_id, canonical_term_id) WHERE (level = 'alias'::text);
CREATE INDEX idx_industry_taxonomy_l1 ON public.industry_taxonomy USING btree (team_id, l1_name) WHERE (active = true);
CREATE INDEX idx_industry_taxonomy_parent ON public.industry_taxonomy USING btree (team_id, workspace_id, parent_id) WHERE (level = 'l2'::text);
CREATE UNIQUE INDEX uq_industry_taxonomy_term ON public.industry_taxonomy USING btree (team_id, workspace_id, lower(term));
CREATE INDEX idx_model_node_active ON public.model_node_config USING btree (team_id, workspace_id, node_name, is_active);
CREATE UNIQUE INDEX uq_model_node_default ON public.model_node_config USING btree (team_id, workspace_id, node_name) WHERE (is_default = true);
CREATE INDEX idx_model_provider_active ON public.model_provider_config USING btree (team_id, workspace_id, is_active);
CREATE UNIQUE INDEX uq_model_provider_name ON public.model_provider_config USING btree (team_id, workspace_id, provider_name);
CREATE INDEX idx_parsed_document_attachment ON public.parsed_document USING btree (attachment_id);
CREATE INDEX idx_prompt_template_active ON public.prompt_template USING btree (team_id, workspace_id, node_name, is_active);
CREATE UNIQUE INDEX uq_prompt_template_default ON public.prompt_template USING btree (team_id, workspace_id, node_name) WHERE (is_default = true);
CREATE INDEX idx_recommendation_message_metadata ON public.recommendation_message USING gin (metadata_json);
CREATE INDEX idx_recommendation_message_session ON public.recommendation_message USING btree (session_id, created_at);
CREATE INDEX idx_recommendation_report_session ON public.recommendation_report USING btree (session_id, created_at DESC);
CREATE INDEX idx_selected_item_intent ON public.recommendation_selected_item USING btree (buyer_intent_id) WHERE (canceled_at IS NULL);
CREATE INDEX idx_selected_item_session ON public.recommendation_selected_item USING btree (session_id, selected_at DESC);
CREATE INDEX idx_selected_item_target ON public.recommendation_selected_item USING btree (seller_target_id) WHERE (canceled_at IS NULL);
CREATE INDEX idx_recommendation_session_buyer ON public.recommendation_session USING btree (buyer_intent_id, created_at DESC);
CREATE INDEX idx_recommendation_session_scope ON public.recommendation_session USING btree (team_id, workspace_id, mode, status);
CREATE INDEX idx_recommendation_session_target ON public.recommendation_session USING btree (seller_target_id, created_at DESC);
CREATE INDEX idx_relation_event_intent ON public.relation_event USING btree (buyer_intent_id, event_time DESC);
CREATE INDEX idx_relation_event_relation ON public.relation_event USING btree (relation_id, event_time DESC);
CREATE INDEX idx_relation_event_target ON public.relation_event USING btree (seller_target_id, event_time DESC);
CREATE INDEX idx_research_proposal_entity ON public.research_proposal USING btree (team_id, entity_type, entity_id, review_status) WHERE (deleted_at IS NULL);
CREATE INDEX idx_research_proposal_pending ON public.research_proposal USING btree (team_id, created_at DESC) WHERE ((deleted_at IS NULL) AND (review_status = 'pending_review'::text));
CREATE INDEX idx_seller_target_deal ON public.seller_target USING btree (team_id, can_control, can_consolidate, is_for_sale) WHERE (deleted_at IS NULL);
CREATE INDEX idx_seller_target_finance ON public.seller_target USING btree (team_id, current_net_profit_yuan, pe_ratio, valuation_yuan) WHERE (deleted_at IS NULL);
CREATE INDEX idx_seller_target_industry ON public.seller_target USING btree (team_id, industry_primary, industry_secondary) WHERE (deleted_at IS NULL);
CREATE INDEX idx_seller_target_industry_l1 ON public.seller_target USING btree (team_id, industry_l1) WHERE (deleted_at IS NULL);
CREATE INDEX idx_seller_target_industry_l2 ON public.seller_target USING btree (team_id, industry_l2) WHERE (deleted_at IS NULL);
CREATE INDEX idx_seller_target_name_trgm ON public.seller_target USING gin (target_name gin_trgm_ops);
CREATE INDEX idx_seller_target_owner ON public.seller_target USING btree (owner_user_id) WHERE (deleted_at IS NULL);
CREATE INDEX idx_seller_target_region ON public.seller_target USING btree (team_id, headquarter_province, headquarter_city) WHERE (deleted_at IS NULL);
CREATE INDEX idx_seller_target_scope ON public.seller_target USING btree (team_id, workspace_id, recommendation_status, information_status) WHERE (deleted_at IS NULL);
CREATE INDEX idx_seller_search_embedding ON public.seller_target_search_doc USING ivfflat (embedding vector_cosine_ops) WITH (lists='100');
CREATE INDEX idx_seller_search_full_text_trgm ON public.seller_target_search_doc USING gin (full_text gin_trgm_ops);
CREATE INDEX idx_seller_search_target ON public.seller_target_search_doc USING btree (seller_target_id);
CREATE INDEX idx_target_follow_up_target ON public.target_follow_up USING btree (seller_target_id, occurred_on DESC, created_at DESC) WHERE (deleted_at IS NULL);
CREATE INDEX idx_workspace_team ON public.workspace USING btree (team_id, status);

-- Seed: default team, workspace and the two fixed users
insert into team (id, name, status)
values ('00000000-0000-0000-0000-000000000001', 'Match-MA 默认团队', 'active')
on conflict (id) do nothing;

insert into workspace (id, team_id, name, workspace_type, status)
values ('00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000001', '默认数据空间', 'data_space', 'active')
on conflict (id) do nothing;

insert into app_user (id, team_id, default_workspace_id, name, email, role, status)
values
  ('00000000-0000-0000-0000-000000000201', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '系统管理员', 'admin@match-ma.local', 'admin', 'active'),
  ('00000000-0000-0000-0000-000000000202', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '系统助手', null, 'developer', 'active')
on conflict (id) do nothing;

-- Seed: industry_taxonomy (171 rows exported from production)
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('e2cb008b-266d-4404-913f-542673838a69', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '交通与物流', 'l1', '交通与物流', true, 5, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', null, null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '信息技术与通信', 'l1', '信息技术与通信', true, 3, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', null, null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('7e6863b1-7764-4d1d-b471-8ef2888b80e6', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '其他', 'l1', '其他', true, 15, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', null, null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('75c8a36f-8bdd-4a40-8a5d-5223ab099934', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '军工', 'l1', '军工', true, 13, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', null, null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('425e9594-9f0c-4b1e-97f8-32e0bdec4c09', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '农林牧渔', 'l1', '农林牧渔', true, 12, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', null, null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '制造与工业', 'l1', '制造与工业', true, 7, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', null, null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('8647abac-20c5-41b0-8b24-4f12657b9fd9', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '医药与健康', 'l1', '医药与健康', true, 9, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', null, null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('e02a6e07-abb9-4e14-b550-eccefd7b23af', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '商务与专业服务', 'l1', '商务与专业服务', true, 14, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', null, null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('8e463190-5368-4068-bb97-6bba70f3cb4f', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '商贸与消费', 'l1', '商贸与消费', true, 8, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', null, null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('3a41e089-9a97-4bab-9916-c9cfd2d73c80', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '房地产与建筑', 'l1', '房地产与建筑', true, 4, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', null, null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('2176b781-5701-420d-abe8-d9f3a4bb720b', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '教育与科研', 'l1', '教育与科研', true, 10, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', null, null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('040e7a76-b8b2-4efe-8848-40eec02426c2', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '文化与传媒', 'l1', '文化与传媒', true, 6, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', null, null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('33fa6943-530a-46d1-b51b-50b5df564b90', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '环保与公用事业', 'l1', '环保与公用事业', true, 11, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', null, null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('564b82a3-346d-49cb-b578-682b9a9bd702', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '能源', 'l1', '能源', true, 1, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', null, null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('cb0af43c-6273-4454-baa5-5a9a83a00df7', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '金融', 'l1', '金融', true, 2, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', null, null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('936dfb07-644e-4218-9760-af59f0ab7853', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', 'PCB', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('f1d8ed19-3cca-4c06-bc84-de43ab0ffb89', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '云计算', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('5cf89929-5bcd-456c-942a-3b0b9773659b', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '互联网', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('f7f5d071-f755-485e-88e3-ab125378f00c', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '互联网服务', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('3868aeb5-6851-4c0b-8d9f-ec7cec2383e3', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '交易所', 'l2', '金融', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'cb0af43c-6273-4454-baa5-5a9a83a00df7', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('6c7b0334-f3e7-4859-bd75-6759764ced52', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '交通基础设施', 'l2', '交通与物流', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', 'e2cb008b-266d-4404-913f-542673838a69', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('ad17db2c-b577-4e7c-9831-4493e9baae4e', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '产业园区', 'l2', '房地产与建筑', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '3a41e089-9a97-4bab-9916-c9cfd2d73c80', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('468a1c67-1014-4a6d-9984-94e7a7eb4525', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '人力资源服务', 'l2', '教育与科研', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '2176b781-5701-420d-abe8-d9f3a4bb720b', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('6066d93c-efb4-4c10-a77c-ceccc9875d57', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '人工智能', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('c39aeaef-f9b7-4e9a-b032-c8f8aae52942', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '仓储', 'l2', '交通与物流', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'e2cb008b-266d-4404-913f-542673838a69', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('dfc2c056-afa6-46e6-87d5-d0ada1f2e8bb', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '休闲食品', 'l2', '商贸与消费', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8e463190-5368-4068-bb97-6bba70f3cb4f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('4b7f4089-833d-466f-bb4f-ec0ed69a710b', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '会展', 'l2', '文化与传媒', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '040e7a76-b8b2-4efe-8848-40eec02426c2', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('b26863da-1409-4264-a859-f1879c997e76', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '低空经济', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('c19b6e72-3906-403c-bdfb-4af30b287c86', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '体育', 'l2', '文化与传媒', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '040e7a76-b8b2-4efe-8848-40eec02426c2', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('e41c7429-1c8b-45cc-b2f3-1be421ab0066', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '体育演艺与内容制作', 'l2', '文化与传媒', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '040e7a76-b8b2-4efe-8848-40eec02426c2', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('5249e115-8539-4839-8f50-ef519bc03863', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '保险', 'l2', '金融', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'cb0af43c-6273-4454-baa5-5a9a83a00df7', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('a51fb7de-c554-46e3-8642-222b23983669', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '储能', 'l2', '能源', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '564b82a3-346d-49cb-b578-682b9a9bd702', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('e6608a25-9e40-41df-a25f-e3d5a563db21', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '光伏', 'l2', '能源', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '564b82a3-346d-49cb-b578-682b9a9bd702', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('d510d573-0ad8-41f6-bbc3-cb07f1a254bd', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '光电子', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('cba7700d-2814-4bb7-917a-195acc5db5f2', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '光通信', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('505fb3b4-f99d-438c-8ef5-832883db84ab', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '公路', 'l2', '交通与物流', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'e2cb008b-266d-4404-913f-542673838a69', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('fdce8dd1-7bc0-457e-8293-4ba6c49e61a6', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '农业', 'l2', '农林牧渔', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '425e9594-9f0c-4b1e-97f8-32e0bdec4c09', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('4ff749c0-29cf-46e2-92cc-e31e3d744c43', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '农产品加工', 'l2', '商贸与消费', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8e463190-5368-4068-bb97-6bba70f3cb4f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('feb3bd54-1dca-43a1-bd10-43a0457c9c83', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '农垦', 'l2', '农林牧渔', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '425e9594-9f0c-4b1e-97f8-32e0bdec4c09', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('6bab4030-70d1-48a1-a005-69d324dfbe39', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '出版', 'l2', '文化与传媒', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '040e7a76-b8b2-4efe-8848-40eec02426c2', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('4c6c0d26-8ff3-4542-98f4-0bb14d982138', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '出行服务', 'l2', '交通与物流', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'e2cb008b-266d-4404-913f-542673838a69', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('b21a0a09-daa1-4764-a043-d688b287a9a9', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '制药', 'l2', '医药与健康', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '8647abac-20c5-41b0-8b24-4f12657b9fd9', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('092d6a7b-6bca-4ac8-b088-c9479490936a', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '动力电池', 'l2', '能源', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '564b82a3-346d-49cb-b578-682b9a9bd702', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('0ed01f3a-981f-4a56-a9d2-f22af7206fdc', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '化工', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('e4f623a0-ab1a-4bbf-999c-a19e00905541', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '北斗', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('b4a553b7-6754-4dab-8ed8-d849482a580a', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '北斗与卫星应用', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('85300048-b228-4e5d-9025-c4821b246a54', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '医疗器械', 'l2', '医药与健康', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8647abac-20c5-41b0-8b24-4f12657b9fd9', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('ad888dad-0b0e-4789-9e1f-484252a39abd', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '医疗康养服务', 'l2', '医药与健康', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8647abac-20c5-41b0-8b24-4f12657b9fd9', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('86c7b65b-7a20-4bdc-acd9-cbf8898ec733', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '医疗研发外包', 'l2', '医药与健康', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8647abac-20c5-41b0-8b24-4f12657b9fd9', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('70a0900d-7bce-4396-b73e-1260d0caafc6', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '医美', 'l2', '医药与健康', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8647abac-20c5-41b0-8b24-4f12657b9fd9', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('e82e7466-acb0-4009-9ba3-41e9e9697df2', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '医药商业', 'l2', '医药与健康', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '8647abac-20c5-41b0-8b24-4f12657b9fd9', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('184b59bf-02ef-40eb-ad84-2023c8028c5e', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '医药流通', 'l2', '医药与健康', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8647abac-20c5-41b0-8b24-4f12657b9fd9', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('1a407a27-5e73-4cd3-93bd-e5e6760bf8fb', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '医院', 'l2', '医药与健康', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8647abac-20c5-41b0-8b24-4f12657b9fd9', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('76057842-7785-4718-a0b4-dad0ccb91b35', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '半导体', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('c72e86b1-1f0f-42d0-9762-f54cb2872e20', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '半导体与集成电路', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('08e611a7-9ef4-4bc0-840f-eccb69cee963', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '卫星应用', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('6e68c50f-557d-4cff-800c-f443711d0cc3', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '发电', 'l2', '能源', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '564b82a3-346d-49cb-b578-682b9a9bd702', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('3b63759c-de6f-465e-9879-8e6b68012120', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '咨询', 'l2', '商务与专业服务', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', 'e02a6e07-abb9-4e14-b550-eccefd7b23af', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('1db3ccb7-5a1f-45e8-b48a-98ac731bf2fe', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '咨询服务', 'l2', '商务与专业服务', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'e02a6e07-abb9-4e14-b550-eccefd7b23af', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('9f9aa32a-f46e-43cb-b7b3-2a00d853c7c8', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '售电', 'l2', '能源', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '564b82a3-346d-49cb-b578-682b9a9bd702', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('64cd37ca-d732-4dac-9c46-e004dde485f7', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '商务服务', 'l2', '商务与专业服务', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'e02a6e07-abb9-4e14-b550-eccefd7b23af', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('06214113-ce6a-4439-b234-88a942185cef', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '大数据', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('1435c4c6-4e0e-418d-b293-29694d6b754d', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '家居建材', 'l2', '房地产与建筑', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '3a41e089-9a97-4bab-9916-c9cfd2d73c80', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('45ac2e12-4b1d-4bae-8d67-5f29ee836be0', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '家电电器', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('8aa5738f-a4dd-40b2-92a1-c25479527b77', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '工业互联网', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('a9d500ed-7680-403c-af80-a6a0e5382104', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '广告传媒', 'l2', '文化与传媒', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '040e7a76-b8b2-4efe-8848-40eec02426c2', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('aca96f1d-cb9d-401c-8938-b57d0cb7a6e8', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '广电', 'l2', '文化与传媒', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '040e7a76-b8b2-4efe-8848-40eec02426c2', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('54c98e5c-fc58-4add-a890-96daa8614e5a', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '康养', 'l2', '医药与健康', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '8647abac-20c5-41b0-8b24-4f12657b9fd9', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('7c8d46a9-4145-4d02-a7b7-12a59ba27531', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '建材', 'l2', '房地产与建筑', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '3a41e089-9a97-4bab-9916-c9cfd2d73c80', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('d098dfce-f2b2-472f-849b-b80c7dc2fee7', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '建材家居', 'l2', '房地产与建筑', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '3a41e089-9a97-4bab-9916-c9cfd2d73c80', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('758e0742-71a1-4188-b2ed-f5d047fef420', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '建筑施工', 'l2', '房地产与建筑', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '3a41e089-9a97-4bab-9916-c9cfd2d73c80', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('1323a1fe-6057-498d-b626-de7658564e44', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '房地产', 'l2', '房地产与建筑', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '3a41e089-9a97-4bab-9916-c9cfd2d73c80', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('a3ca70e0-8ecb-4cfd-adf8-fbeb46d8ccf4', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '批发', 'l2', '商贸与消费', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8e463190-5368-4068-bb97-6bba70f3cb4f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('e30a39b9-b311-423e-b043-8dd0efb0f584', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '控股平台', 'l2', '金融', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'cb0af43c-6273-4454-baa5-5a9a83a00df7', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('653d12ff-6612-44ba-bc40-df2000b35de9', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '教育培训', 'l2', '教育与科研', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '2176b781-5701-420d-abe8-d9f3a4bb720b', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('a8477849-577a-4d88-92af-46bb5242fff5', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '教育机构', 'l2', '教育与科研', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '2176b781-5701-420d-abe8-d9f3a4bb720b', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('7156f0a9-0fa6-4849-b7e8-76f5992a5314', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '整车制造', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('41c93fd7-ead5-4cff-b793-16951fa01b10', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '文化旅游', 'l2', '文化与传媒', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '040e7a76-b8b2-4efe-8848-40eec02426c2', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('d73fb34c-f6ce-41fa-9156-8ebced7dc6e7', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '文旅', 'l2', '文化与传媒', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '040e7a76-b8b2-4efe-8848-40eec02426c2', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('1adf43ef-611f-495b-b288-297dbf4c66e1', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '新材料', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('42bca3e0-d8ce-4f24-90b4-1d61aa359878', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '新能源', 'l2', '能源', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '564b82a3-346d-49cb-b578-682b9a9bd702', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('ca8cf35d-cc0d-4ffe-8c4f-0f774033ca02', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '新能源制造', 'l2', '能源', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '564b82a3-346d-49cb-b578-682b9a9bd702', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('84e2979d-f088-4815-bba4-42da0e0db330', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '旅游', 'l2', '文化与传媒', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '040e7a76-b8b2-4efe-8848-40eec02426c2', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('cd6e5e91-2c51-468c-9627-63dc6d6d8c3d', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '无人机', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('78e078df-9780-4698-bc8e-0a14e5932ace', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '日化美妆', 'l2', '商贸与消费', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8e463190-5368-4068-bb97-6bba70f3cb4f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('46be7850-4bf1-43be-bbcc-9c8a1c10773d', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '智慧城市', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('1a93c2f7-3ddb-43df-a7df-a65c6647b397', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '有色金属', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('c7996e7a-2566-46ba-a21b-53b01c920055', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '有色金属压铸', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('b6653d40-1d54-4b4c-8dfd-5eacc924d44d', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '有色金属及矿业', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('fa847045-f4c9-4d86-a555-0e008f155044', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '服装鞋帽', 'l2', '商贸与消费', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8e463190-5368-4068-bb97-6bba70f3cb4f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('fcac6201-4506-454e-8fbc-540f860a9f6b', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '期货', 'l2', '金融', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'cb0af43c-6273-4454-baa5-5a9a83a00df7', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('ec21bb4b-0128-43e4-b161-b5dbc8e73a3b', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '机器人', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('b321bb14-32d2-4310-8144-0b3f16cda573', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '机场', 'l2', '交通与物流', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'e2cb008b-266d-4404-913f-542673838a69', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('b18507b2-a3cf-4dba-957b-cb577f235c9e', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '核电', 'l2', '能源', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '564b82a3-346d-49cb-b578-682b9a9bd702', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('1b26ceeb-b67a-4ed8-a03e-19299eee8f2d', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '检测服务', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('8357b3cc-fe11-479d-9c6d-f3c84393d4a9', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '橡胶塑料', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('45051304-3524-4124-a2d0-23a745ce67fd', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '氢能', 'l2', '能源', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '564b82a3-346d-49cb-b578-682b9a9bd702', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('cc46e223-1b98-4eb7-922f-b397636cba6d', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '水务', 'l2', '环保与公用事业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '33fa6943-530a-46d1-b51b-50b5df564b90', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('2d71e9db-362e-4f46-93b3-bb830739aa42', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '水运', 'l2', '交通与物流', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'e2cb008b-266d-4404-913f-542673838a69', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('acc97a51-db77-4812-a1bb-708fdb550410', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '汽车', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('1540ddc8-9bbe-408c-8164-2576080f6ade', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '汽车销售与服务', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('b17aaa8e-1fd9-4ada-8cc5-3d2a999fc04c', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '汽车零部件', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('b4fdf40d-492a-42bf-a547-b282df405c19', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '测量测绘', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('3a02c2bb-3e64-4cd2-944a-c7429afc4583', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '海洋装备', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('36993e56-a3a2-4646-8c47-a7de9001ee49', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '渔业', 'l2', '农林牧渔', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '425e9594-9f0c-4b1e-97f8-32e0bdec4c09', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('5293cf4f-92b7-4688-8263-8a42a59a1979', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '港口', 'l2', '交通与物流', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'e2cb008b-266d-4404-913f-542673838a69', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('b76538da-4eb6-4a81-abb3-a1b639c5f2ac', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '煤炭', 'l2', '能源', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '564b82a3-346d-49cb-b578-682b9a9bd702', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('8ccb7d5e-bf3e-4d15-a776-ca6db4aefc2e', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '燃气', 'l2', '环保与公用事业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '33fa6943-530a-46d1-b51b-50b5df564b90', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('47024210-e8a7-46fa-968c-c5b7a0aa26d2', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '物业管理', 'l2', '房地产与建筑', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '3a41e089-9a97-4bab-9916-c9cfd2d73c80', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('52aec859-b893-450b-a027-e67a924444a9', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '物流仓储', 'l2', '交通与物流', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', 'e2cb008b-266d-4404-913f-542673838a69', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('a1b590b5-9b92-43b6-b37d-13c71d139e91', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '物流运输', 'l2', '交通与物流', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'e2cb008b-266d-4404-913f-542673838a69', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('1edc541e-c987-4718-8624-93d5d1033914', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '珠宝奢侈品', 'l2', '商贸与消费', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8e463190-5368-4068-bb97-6bba70f3cb4f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('1b097aed-f079-4db9-84f8-23ad645d1b39', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '生态环保', 'l2', '环保与公用事业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '33fa6943-530a-46d1-b51b-50b5df564b90', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('ff2f5b58-b04c-4ca9-973b-d07f2142a0a9', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '生物制药', 'l2', '医药与健康', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '8647abac-20c5-41b0-8b24-4f12657b9fd9', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('1cc705cb-ecd8-464a-9ee4-d9655d899e5d', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '生物医药', 'l2', '医药与健康', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8647abac-20c5-41b0-8b24-4f12657b9fd9', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('965d3b7f-9582-4e82-b502-f3bc4d5d9832', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '生物技术', 'l2', '医药与健康', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '8647abac-20c5-41b0-8b24-4f12657b9fd9', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('311514ae-ee72-4976-b8ac-75177f14efb4', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '电力', 'l2', '能源', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '564b82a3-346d-49cb-b578-682b9a9bd702', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('24f32398-69e5-4e51-b0ee-b032f7f810ff', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '电力工程', 'l2', '能源', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '564b82a3-346d-49cb-b578-682b9a9bd702', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('abd5ee3c-672d-4946-95e8-1fbbbffb6f25', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '电商', 'l2', '商贸与消费', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '8e463190-5368-4068-bb97-6bba70f3cb4f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('16c13bb8-5e54-40b0-957d-4b712ae23bd5', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '电子', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('262840f6-4b4d-4c61-855a-feb2ec2623e8', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '电子元件', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('e34376b3-65ad-44f4-9bcb-c0a3b104e3d4', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '电池', 'l2', '能源', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '564b82a3-346d-49cb-b578-682b9a9bd702', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('e7e860a4-c529-4403-85be-f4121504e400', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '电线电缆', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('7626af88-d234-44e1-92b1-341e8ebc8040', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '电网', 'l2', '能源', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '564b82a3-346d-49cb-b578-682b9a9bd702', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('1e11cc81-b0a0-4685-b34a-1204c1977ed5', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '畜牧业', 'l2', '农林牧渔', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '425e9594-9f0c-4b1e-97f8-32e0bdec4c09', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('453b7f84-d424-41bc-9b98-342782bd755a', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '盐业', 'l2', '商贸与消费', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8e463190-5368-4068-bb97-6bba70f3cb4f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('d3d6e3f4-a15a-44d3-950c-722a2d4d8136', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '石油石化', 'l2', '能源', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '564b82a3-346d-49cb-b578-682b9a9bd702', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('9392d193-1f27-4634-a10d-458a996f9a51', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '矿业', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('b2c765ac-764f-4dc8-a8f8-5e6d2efe0587', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '科研院所', 'l2', '教育与科研', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '2176b781-5701-420d-abe8-d9f3a4bb720b', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('a73002b0-1c7f-4ed6-81b4-08eef17dccb0', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '算力与数据中心', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('b4cb8378-3bd3-4824-b239-5320d760b8d9', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '粮油食品', 'l2', '商贸与消费', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8e463190-5368-4068-bb97-6bba70f3cb4f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('8047af49-8943-4b78-a001-28671847a89e', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '精细化工', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('c648d5ad-6c2f-424f-b16b-39a1360a131b', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '纺织', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('da2a3ab2-0928-49b1-8921-0270fa8ff86b', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '纺织业', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('b900afd8-9fed-47d5-bc57-ab35767ec11f', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '综合能源服务', 'l2', '能源', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '564b82a3-346d-49cb-b578-682b9a9bd702', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('801743a4-34b0-42e2-90ad-02c73e86da98', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '网络安全', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('9c0f5dc4-b648-4d8e-b895-0607c820bf9c', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '职业教育', 'l2', '教育与科研', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '2176b781-5701-420d-abe8-d9f3a4bb720b', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('d3a2fc73-f3cd-423e-8489-2742ed74e829', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '航空航天', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('9cc3877c-1e6f-4a87-b419-29a1443fe576', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '航空运输', 'l2', '交通与物流', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'e2cb008b-266d-4404-913f-542673838a69', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('cf3cfec7-4ac8-432b-8406-9f914aee0f57', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '芯片', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('63af2031-9866-43fa-a220-6030c1ddbeb1', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '药品生产', 'l2', '医药与健康', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8647abac-20c5-41b0-8b24-4f12657b9fd9', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('bf460e7d-e9f0-4d46-b993-e01d3e9ebfa9', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '装备制造', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('2084ffb2-8bb8-46b0-a24c-cf97a56fa336', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '装饰装修', 'l2', '房地产与建筑', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '3a41e089-9a97-4bab-9916-c9cfd2d73c80', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('c7c81a1c-74a6-4b3a-9013-29332ace8449', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '设计监理与工程咨询', 'l2', '房地产与建筑', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '3a41e089-9a97-4bab-9916-c9cfd2d73c80', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('6f96a4a5-a9e6-467a-ba30-d22c9b3f9dc6', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '证券', 'l2', '金融', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'cb0af43c-6273-4454-baa5-5a9a83a00df7', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('c5b9aa22-cba2-481c-87b5-2f4e39121a77', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '贸易', 'l2', '商贸与消费', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8e463190-5368-4068-bb97-6bba70f3cb4f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('6fbb5469-9fa8-4211-a774-c3d733d677ed', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '资产管理', 'l2', '商务与专业服务', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'e02a6e07-abb9-4e14-b550-eccefd7b23af', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('b2aaf92a-8589-4229-bbc3-1ee6edc41393', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '跨境电商', 'l2', '商贸与消费', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8e463190-5368-4068-bb97-6bba70f3cb4f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('460a10c5-dd9c-4d0c-8469-d760a881b6e6', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '轨道交通', 'l2', '交通与物流', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'e2cb008b-266d-4404-913f-542673838a69', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('4bceb826-52cc-4b1b-a324-03d24a08c3ee', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '软件', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('e9f8db06-2b6d-42da-921f-e00eac241894', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '软件与信息化服务', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('af4b9a0c-e732-4476-aa6c-8634eb8786f5', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '运营商', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('9642c794-b425-423c-8ed7-ce0ccbc97244', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '通信', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('4e6aa2f5-d6ee-4890-bc1e-7ab9014e0c1e', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '通信设备', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('2c21acd0-6a03-451b-818b-988a74b2915e', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '酒店', 'l2', '文化与传媒', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '040e7a76-b8b2-4efe-8848-40eec02426c2', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('2ace82fc-da01-42f7-8541-3cbf5f376475', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '酒水饮料', 'l2', '商贸与消费', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8e463190-5368-4068-bb97-6bba70f3cb4f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('25498cce-bd42-4352-9995-801795996dd9', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '采掘与矿业', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('1b1f7377-41f0-410d-8a98-d21abb166454', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '采矿业', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('e9b05afc-a42f-400c-ade0-570d362d99c0', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '金融科技', 'l2', '金融', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'cb0af43c-6273-4454-baa5-5a9a83a00df7', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('5719fd0a-da38-4909-95ab-dcd44a46d83e', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '钢铁', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('3595c081-5167-418e-a3ea-bdde265c0902', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '铁路', 'l2', '交通与物流', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'e2cb008b-266d-4404-913f-542673838a69', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('08f16d62-f9a5-45f4-b8e2-ed13cd8e5c23', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '银行', 'l2', '金融', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', 'cb0af43c-6273-4454-baa5-5a9a83a00df7', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('55013477-a6f2-47bb-a336-731e20bf4619', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '集成电路', 'l2', '信息技术与通信', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('82044455-ae48-452c-8bf3-d3025801b152', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '零售', 'l2', '商贸与消费', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8e463190-5368-4068-bb97-6bba70f3cb4f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('ebf526ac-8a33-4f0f-a7f1-4a0c9def599d', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '风电', 'l2', '能源', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '564b82a3-346d-49cb-b578-682b9a9bd702', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('2cc341c0-3741-46a0-832b-1087a872a371', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '食品', 'l2', '商贸与消费', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '8e463190-5368-4068-bb97-6bba70f3cb4f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('5a579cde-5116-4c3c-89a1-5b3da34ff753', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '食品制造', 'l2', '商贸与消费', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-21 07:34:30.493343+00', '8e463190-5368-4068-bb97-6bba70f3cb4f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('3376cac9-41f5-48e6-82bb-052493812453', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '食品加工', 'l2', '商贸与消费', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8e463190-5368-4068-bb97-6bba70f3cb4f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('c3872538-bf46-4095-b039-fe5759c8b3d6', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '餐饮', 'l2', '商贸与消费', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '8e463190-5368-4068-bb97-6bba70f3cb4f', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('ffc59f9d-c8d1-41ad-bd7d-237ddda96063', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '高校院校', 'l2', '教育与科研', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '2176b781-5701-420d-abe8-d9f3a4bb720b', null)
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, created_at, updated_at, parent_id, canonical_term_id)
values ('732a8db7-ac50-426a-912d-b6245aa0da61', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '高端装备', 'l2', '制造与工业', true, 0, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f', null)
on conflict (id) do nothing;

-- Seed: industry_taxonomy (26 rows exported from production)
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('b93840b8-5c4e-41f9-9371-acd1ea4e8285', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '交通运输', 'alias', '交通与物流', true, 0, null, 'e2cb008b-266d-4404-913f-542673838a69')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('95aa4384-579b-4645-b6dd-aac832b85eaf', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '企业服务', 'alias', '商务与专业服务', true, 0, null, 'e02a6e07-abb9-4e14-b550-eccefd7b23af')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('9766756c-d438-4845-a425-a76bd1a3e7b1', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '传媒', 'alias', '文化与传媒', true, 0, null, '040e7a76-b8b2-4efe-8848-40eec02426c2')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('24b58827-a768-416f-b93f-7e05e274012e', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '信息技术', 'alias', '信息技术与通信', true, 0, null, 'bfc7c68e-78a5-4de2-8c4b-bbf0fa0d4f9a')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('caca43b3-189e-42e7-a727-a0b4d3816cef', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '先进制造', 'alias', '制造与工业', true, 0, null, '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('ac728467-935d-4605-a7c3-c220a2eafc9c', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '公用事业', 'alias', '环保与公用事业', true, 0, null, '33fa6943-530a-46d1-b51b-50b5df564b90')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('05fcbdfd-64ee-4f76-b6c4-7286c46f61c9', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '制造业', 'alias', '制造与工业', true, 0, null, '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('fbade2e5-cc4d-4de0-97f4-49b0cb1cf2e1', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '医疗健康', 'alias', '医药与健康', true, 0, null, '8647abac-20c5-41b0-8b24-4f12657b9fd9')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('3ff159ec-93ea-4f67-b39b-9cd4f1adea45', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '医药', 'alias', '医药与健康', true, 0, null, '8647abac-20c5-41b0-8b24-4f12657b9fd9')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('635ee3e5-998e-40be-9c2d-47bbbfadc83f', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '医药健康', 'alias', '医药与健康', true, 0, null, '8647abac-20c5-41b0-8b24-4f12657b9fd9')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('bcee0d81-21ca-4c43-a6e0-02bbb1e200af', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '商业流通', 'alias', '商贸与消费', true, 0, null, '8e463190-5368-4068-bb97-6bba70f3cb4f')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('3e6e1458-1b1c-47d7-ab2e-5f38c486dd5f', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '国防军工', 'alias', '军工', true, 0, null, '75c8a36f-8bdd-4a40-8a5d-5223ab099934')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('7ec50abb-eac4-463c-80eb-1d2f8c628bd4', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '大健康', 'alias', '医药与健康', true, 0, null, '8647abac-20c5-41b0-8b24-4f12657b9fd9')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('6c3de6c3-72bc-4b4e-843a-3be96f607f6d', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '工程建设', 'alias', '房地产与建筑', true, 0, null, '3a41e089-9a97-4bab-9916-c9cfd2d73c80')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('bd407e27-71f6-44ae-8941-8004554feff2', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '建筑', 'alias', '房地产与建筑', true, 0, null, '3a41e089-9a97-4bab-9916-c9cfd2d73c80')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('eddd5c6c-8599-498f-88f9-ae5f3ea7bc10', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '快速消费品', 'alias', '商贸与消费', true, 0, null, '8e463190-5368-4068-bb97-6bba70f3cb4f')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('939349f6-3614-4f7a-a7ba-9cf0c3260abb', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '教育', 'alias', '教育与科研', true, 0, null, '2176b781-5701-420d-abe8-d9f3a4bb720b')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('74f4fd12-afa8-48b6-bc6c-9bde3d3f94ff', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '文化传媒', 'alias', '文化与传媒', true, 0, null, '040e7a76-b8b2-4efe-8848-40eec02426c2')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('efad9e12-1ec3-47be-81ee-a136017cb45a', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '文旅消费', 'alias', '文化与传媒', true, 0, null, '040e7a76-b8b2-4efe-8848-40eec02426c2')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('9e4e4ba2-b1e4-41c8-9c1e-4e1da9488ea5', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '材料', 'alias', '制造与工业', true, 0, null, '45932d9b-0c5b-4eaf-abd6-f4f87f4c882f')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('300a6fd0-394b-44ed-ba1f-88d0ce6da84a', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '消费品', 'alias', '商贸与消费', true, 0, null, '8e463190-5368-4068-bb97-6bba70f3cb4f')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('d4965642-4718-49de-9533-3e0bdbe34c2a', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '物流', 'alias', '交通与物流', true, 0, null, 'e2cb008b-266d-4404-913f-542673838a69')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('7991c468-a1d4-4ef8-b894-30a7ab9bfbee', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '环保', 'alias', '环保与公用事业', true, 0, null, '33fa6943-530a-46d1-b51b-50b5df564b90')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('8c82472b-7e08-4303-b586-155c3b474f31', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '节能环保', 'alias', '环保与公用事业', true, 0, null, '33fa6943-530a-46d1-b51b-50b5df564b90')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('03b77822-8d52-4546-a192-7f8721a0d3ba', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '金融服务', 'alias', '金融', true, 0, null, 'cb0af43c-6273-4454-baa5-5a9a83a00df7')
on conflict (id) do nothing;
insert into industry_taxonomy (id, team_id, workspace_id, term, level, l1_name, active, sort_order, parent_id, canonical_term_id)
values ('464f6b46-6c4d-4670-9fbe-0d496f411843', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '食品制造业', 'alias', '商贸与消费', true, 0, null, '8e463190-5368-4068-bb97-6bba70f3cb4f')
on conflict (id) do nothing;

-- Seed: prompt_template (9 rows exported from production)
insert into prompt_template (id, team_id, workspace_id, node_name, version, name, description, system_prompt, user_prompt_template, output_schema_json, few_shot_examples_json, template_engine, variables_json, is_active, is_default, created_at, updated_at, metadata_json)
values ('00000000-0000-0000-0000-000000004224', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', 'business_update_extractor', 'v0.7.0', 'Business update extractor with target follow-up notes', 'Extract pending-review actions, dated target follow-up notes, and short rewritten business summaries.', 'You extract structured actions for Match-MA, an internal M&A matching platform. Output only one JSON object, no Markdown. Top level must contain actions array. Allowed action_type values: seller_fact_update, seller_event, target_follow_up, buyer_seller_relation_update, buyer_intent_target_exclusion, buyer_intent_update, buyer_level_blacklist_suggestion, internal_note, unresolved_item. Use null target_entity_id when uncertain. Output industry and region values in Chinese. Never invent UUIDs. proposed_changes_json must use canonical database field names only when a canonical field exists. This version creates pending-review actions only.', 'Context JSON: {{ context_json }}

Raw input: {{ raw_text }}

Return JSON in this shape:
{
  "actions": [
    {
      "action_type": "seller_fact_update",
      "target_entity_type": "seller_target",
      "target_entity_id": null,
      "proposed_changes_json": {"target_subject_name": "..."},
      "raw_evidence_text": "original evidence span",
      "confidence": 0.80,
      "reason": "why this action was extracted"
    },
    {
      "action_type": "target_follow_up",
      "target_entity_type": "seller_target",
      "target_entity_id": null,
      "proposed_changes_json": {"occurred_on": "2026-07-30", "content": "已推给广州工业投资控股集团有限公司，等待反馈", "buyer_names": ["广州工业投资控股集团有限公司"]},
      "raw_evidence_text": "20260730：推给广州工业投资控股集团有限公司",
      "confidence": 0.85,
      "reason": "dated follow-up note about the bound target"
    }
  ]
}

Rules:
1. Use seller_fact_update for current seller target fact changes. target_entity_type must be seller_target.
2. seller_fact_update proposed_changes_json may ONLY use these canonical fields when applicable: target_name, target_subject_name, industry_primary, industry_secondary, headquarter_province, headquarter_city, listed_status, current_revenue_yuan, current_net_profit_yuan, current_total_profit_yuan, financial_period_label, valuation_yuan, valuation_date, asking_price_yuan, asking_price_date, pe_ratio, is_for_sale, can_control, can_consolidate, accepts_minority_investment, transfer_ratio_min, transfer_ratio_max, transfer_ratio_text, transfer_flexibility_type, business_summary, transaction_summary, risk_summary, gap_summary, information_status, recommendation_status.
3. Map common expressions: target subject, owning company, project company, owner company -> target_subject_name; profit or net profit -> current_net_profit_yuan; revenue -> current_revenue_yuan; valuation -> valuation_yuan; valuation time/date -> valuation_date; asking price or quote -> asking_price_yuan; asking price time/date or quote time -> asking_price_date; PE -> pe_ratio; province/city/location -> headquarter_province/headquarter_city; can be controlled -> can_control; can be consolidated -> can_consolidate.
4. Use buyer_intent_update for buyer requirement changes. target_entity_type must be buyer_intent. proposed_changes_json may use: raw_requirement_text, intent_summary, industry_primary, industry_secondary, region_scope_summary, min_revenue_yuan, min_net_profit_yuan, min_total_profit_yuan, max_pe, max_valuation_yuan, min_market_cap_yuan, max_market_cap_yuan, market_cap_range_summary, requires_control, requires_consolidation, accepts_minority_investment, desired_equity_ratio_min, desired_equity_ratio_max, equity_ratio_summary, equity_requirement_type, preferred_listed_status, listing_board_requirement_summary, financing_stage_requirement_summary, transaction_type, transaction_types_json, premium_tolerance_summary, max_premium_rate, max_debt_ratio, debt_ratio_requirement_summary, major_risk_tolerance_summary, buyer_industry_advantage_summary, negative_summary, priority_summary, preference_summary, unknown_summary, status, pause_reason. For buyer_intent.status use exactly one of: active (ongoing recommendation), paused (temporarily paused), closed (ended/completed/terminated need).
5. Split listing requirements: preferred_listed_status is listed, preparing_listing, pre_ipo, unlisted, any, or unknown; listing_board_requirement_summary stores 主板/创业板/科创板/北交所/港股/美股; financing_stage_requirement_summary stores pre-IPO/A轮/辅导备案/已递表等阶段.
6. transaction_types_json should be a JSON array when multiple deal methods are mentioned; keep transaction_type only for one short legacy label if clearly single.
7. Use buyer_seller_relation_update for recommendation, in-talk, due diligence, terminated, or buyer feedback progress when the buyer intent is clearly identifiable. target_entity_type must be buyer_seller_relation. proposed_changes_json may use: status, status_reason, first_recommended_at, last_contact_at, last_event_at, last_event_summary, event_type, event_title, event_content, next_step, buyer_name, seller_target_name.
8. If clearly not interested, create buyer_intent_target_exclusion in addition to relation update. If an item cannot be mapped safely, create unresolved_item.
9. Normalize money amounts to CNY yuan numbers. Normalize percentages to numeric percentage values, e.g. use 51 for a 51 percent share. For yes/no/likely/unknown fields use exactly one of: yes, no, likely, unknown.
10. If user-entered text and attachment evidence conflict on formal target_name, target_subject_name, or standardized industry, prefer the formal attachment evidence and explain briefly in reason.
11. For seller_fact_update and buyer_intent_update, output industry_primary, industry_secondary, headquarter_province, headquarter_city, region_scope_summary, and buyer_industry_advantage_summary values in Chinese when evidence exists. Use Chinese administrative names such as 浙江省、杭州市、江苏省、上海市; do not output English translated labels such as Zhejiang Province, Hangzhou City, healthcare, manufacturing, or medical_device.
12. If the input contains multiple independent matters, return multiple actions.
13. Use target_follow_up for dated follow-up or progress notes about a seller target: 推给/已发给某买家, 已发资料, 等待反馈, 需再确认交易条件, 暂缓, 股价异动, next steps. target_entity_type must be seller_target. proposed_changes_json may ONLY use: occurred_on (YYYY-MM-DD or null), content (concise Chinese, keep the original meaning and buyer names), buyer_names (JSON array of full company names mentioned in this entry, may be empty). Split entries with different dates or different matters into separate target_follow_up actions.
14. Resolve partial follow-up dates such as 0730, 7月30日, or 20250730 against context_json.update_date: use that year when the day itself has no year; if the resolved date would be after context_json.update_date, use the previous year. If no date is present use null for occurred_on.
15. Follow-up dynamics must never be written into business_summary, transaction_summary, or gap_summary. When the buyer intent is clearly identifiable, still emit buyer_seller_relation_update in addition to target_follow_up.
16. business_summary must be a rewritten profile of one or two sentences within 80 Chinese characters on a single line: main business, core products or customers, and one scale highlight. Never copy or paste raw input text into business_summary. Do not include deal, price, valuation, follow-up, or risk content in business_summary; deal terms belong to transaction_summary and risks belong to risk_summary. If the existing business_summary in context already covers the business and the input adds no new business facts, omit business_summary.', '{"type": "object", "required": ["actions"], "properties": {"actions": {"type": "array", "items": {"type": "object", "required": ["action_type", "proposed_changes_json"], "properties": {"reason": {"type": ["string", "null"]}, "confidence": {"type": ["number", "null"]}, "action_type": {"type": "string"}, "target_entity_id": {"type": ["string", "null"]}, "raw_evidence_text": {"type": ["string", "null"]}, "target_entity_type": {"type": ["string", "null"]}, "proposed_changes_json": {"type": "object"}}}}}}'::jsonb, '[]'::jsonb, 'jinja', '["context_json", "raw_text"]'::jsonb, true, true, '2026-07-08 10:18:41.602682+00', '2026-07-13 02:34:40.024167+00', '{"source": "migration_027_business_update_extractor_prompt_v07", "buyer_intent_closed_status_source": "migration_031_buyer_management_flow"}'::jsonb)
on conflict (id) do nothing;
insert into prompt_template (id, team_id, workspace_id, node_name, version, name, description, system_prompt, user_prompt_template, output_schema_json, few_shot_examples_json, template_engine, variables_json, is_active, is_default, created_at, updated_at, metadata_json)
values ('00000000-0000-0000-0000-000000004239', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', 'buyer_intent_parser', 'v0.6.0', 'Buyer intent parser with semantic field separation', 'Parse one buyer requirement into canonical fields without modifying the buyer party.', 'You parse one buyer acquisition requirement. Output one JSON object with a fields object and no Markdown. Do not output buyer_party. Do not invent facts. Use Chinese for user-facing text and exact canonical enum values where required.', 'Raw buyer requirement:
{{ raw_requirement_text }}

Existing intent context JSON:
{{ buyer_profile_json }}

Closed level-1 industries:
{{ industry_l1_list }}

Return only supported fields that have evidence. Do not output null fields and do not repeat raw_requirement_text.

Industry rules:
- industries_json contains every applicable level-1 industry, each copied exactly from the closed list.
- industry_focus_tags_json preserves all specific Chinese tracks such as 新式茶饮、宠物医疗、垂类电商SaaS.
- industry_primary and industry_secondary remain concise descriptive Chinese labels, not level-1 replacements.

Financial rules:
- min_valuation_yuan and max_valuation_yuan are valuation bounds.
- min_market_cap_yuan and max_market_cap_yuan are only for explicit market-cap evidence. Never copy valuation into market-cap fields.
- max_pe and max_ps are different multiples.
- min_net_margin and min_gross_margin are numeric percentage values.
- money values are CNY yuan numbers.

Capital-market rules:
- preferred_listed_status is one of listed, unlisted, preparing_listing, pre_ipo, any, unknown only when explicitly supported.
- A/B round and similar financing details belong in financing_stage_requirement_summary, not listing status.
- words such as 优先、一般、可放宽 describe preferences; preserve them in priority_summary or preference_summary rather than turning them into hard facts.

Use the remaining existing canonical buyer_intent fields for revenue, profit, region, equity, transaction, premium, debt, risk, exclusion, preference and unknown summaries.', '{"type": "object", "required": ["fields"], "properties": {"fields": {"type": "object"}}}'::jsonb, '[]'::jsonb, 'jinja', '["raw_requirement_text", "buyer_profile_json", "industry_l1_list"]'::jsonb, true, true, '2026-07-15 02:01:04.31916+00', '2026-07-15 02:01:04.31916+00', '{"source": "migration_036_specialized_update_parsers"}'::jsonb)
on conflict (id) do nothing;
insert into prompt_template (id, team_id, workspace_id, node_name, version, name, description, system_prompt, user_prompt_template, output_schema_json, few_shot_examples_json, template_engine, variables_json, is_active, is_default, created_at, updated_at, metadata_json)
values ('a9e08a59-caeb-437e-a306-47a77554f53f', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', 'buyer_intent_update_parser', 'v0.1.1', 'Buyer intent update parser canonical action contract', 'P0 canonical action envelope and explicit aliases prohibition.', 'You parse updates for one known buyer acquisition intent. Output one JSON object with an actions array and no Markdown. Every action item MUST use exactly these keys: action_type, target_entity_type, target_entity_id, proposed_changes_json. Never use the aliases action, target, target_id, proposed_changes, or changes. Never create seller facts, target follow-ups, buyer-party changes, relations, or target links. Do not invent facts or UUIDs.', 'Context JSON: {{ context_json }}

Raw input: {{ raw_text }}

Return exactly this shape (repeat one object per extracted action):
{"actions":[{"action_type":"buyer_intent_update","target_entity_type":"buyer_intent","target_entity_id":"<copy the bound buyer intent UUID from context, or null>","proposed_changes_json":{"intent_summary":"..."},"confidence":0.9,"raw_evidence_text":"concise supporting excerpt"}]}

Allowed action_type values for this node:
1. buyer_intent_update when acquisition requirements changed.
2. buyer_intent_follow_up for calls, meetings, recommendations, feedback, progress, or next steps.
3. unresolved_item only when neither applies.

buyer_intent_follow_up proposed_changes_json may use occurred_at, contact_name, content, next_step, next_follow_up_at. Preserve mentioned target names only inside content; never link or update seller targets. buyer_intent_update must use canonical intent fields from context. industries_json must use exact values from context_json.industry_l1_list; preserve detailed tracks in industry_focus_tags_json. Estimation/valuation is not market capitalization. Output Chinese text, omit unsupported or unevidenced fields, and do not echo the full input. Do not output action/target/target_id aliases.', '{"type": "object", "required": ["actions"], "properties": {"actions": {"type": "array", "items": {"type": "object", "required": ["action_type", "target_entity_type", "target_entity_id", "proposed_changes_json"], "properties": {"confidence": {"type": ["number", "null"]}, "action_type": {"type": "string"}, "target_entity_id": {"type": ["string", "null"]}, "raw_evidence_text": {"type": ["string", "null"]}, "target_entity_type": {"type": ["string", "null"]}, "proposed_changes_json": {"type": "object"}}}, "minItems": 1}}}'::jsonb, '[]'::jsonb, 'jinja', '["context_json", "raw_text"]'::jsonb, true, true, '2026-07-21 10:24:17.25446+00', '2026-07-21 10:24:17.25446+00', '{"reason": "canonical_action_keys", "source": "p0_action_contract_hotfix"}'::jsonb)
on conflict (id) do nothing;
insert into prompt_template (id, team_id, workspace_id, node_name, version, name, description, system_prompt, user_prompt_template, output_schema_json, few_shot_examples_json, template_engine, variables_json, is_active, is_default, created_at, updated_at, metadata_json)
values ('00000000-0000-0000-0000-000000004240', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', 'recommendation_deep_eval', 'v0.2.0', 'Recommendation deep evaluation from intent requirements', 'Grade candidates using seller-target facts and buyer-intent requirements only.', 'You are an M&A matchmaking analyst for Match-MA. Evaluate candidates using seller-target facts and buyer-intent requirements only. Buyer-party profile attributes such as capital strength, company scale, location, main business, group background, or listed status must not affect the grade unless the buyer intent itself states the same item as an acquisition requirement. Output one JSON object and no Markdown.', 'Mode: {{ mode }}

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
8. Return every candidate index exactly once, ordered from most to least recommended.', '{"type": "object", "required": ["results"], "properties": {"results": {"type": "array", "items": {"type": "object", "required": ["index", "grade"], "properties": {"grade": {"enum": ["A", "B", "C"], "type": "string"}, "index": {"type": "integer"}, "risks": {"type": ["string", "null"]}, "reason": {"type": ["string", "null"]}, "info_gaps": {"type": ["string", "null"]}}}}}}'::jsonb, '[]'::jsonb, 'jinja', '["mode", "anchor_context", "candidates_json"]'::jsonb, true, true, '2026-07-15 02:01:04.31916+00', '2026-07-15 02:01:04.31916+00', '{"source": "migration_038_recommendation_deep_eval_prompt_v02"}'::jsonb)
on conflict (id) do nothing;
insert into prompt_template (id, team_id, workspace_id, node_name, version, name, description, system_prompt, user_prompt_template, output_schema_json, few_shot_examples_json, template_engine, variables_json, is_active, is_default, created_at, updated_at, metadata_json)
values ('00000000-0000-0000-0000-000000004241', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', 'recommendation_query_parser', 'v0.1.0', '推荐条件解析', '把推荐会话中的用户消息解析成结构化条件操作、语义偏好、展示操作或提问。', '你负责解析并购撮合平台推荐会话里用户输入的一句话。只输出一个 JSON 对象，不要输出 Markdown。你的任务是提取，不是执行：把消息拆解为结构化条件操作、语义偏好、展示操作和提问，绝不能臆造用户没有表达的条件。无法可靠转成结构化条件的内容一律放进 semantic_preferences 原样保留。', '推荐方向：{{ mode }}（buyer_to_target 表示为买家意向筛选卖方标的；target_to_buyer 表示为标的匹配买家意向）

当前生效条件 JSON：
{{ current_conditions_json }}

一级行业封闭清单（industries_json 与 excluded_industries_json 的值必须来自该清单）：
{{ industry_l1_list }}

用户消息：
{{ user_message }}

按如下结构返回 JSON（各数组无内容时输出空数组，question 无内容时输出 null）：
{
  "condition_ops": [
    {"op": "set", "field": "region_scope_summary", "value": "浙江"},
    {"op": "set", "field": "min_net_profit_yuan", "value": 15000000},
    {"op": "remove", "field": "max_pe", "value": null},
    {"op": "exclude", "field": "excluded_industries_json", "value": "房地产与建筑"}
  ],
  "semantic_preferences": ["最好有出海业务"],
  "display_ops": [{"type": "only_grade", "value": "A"}],
  "question": null,
  "reply_summary": "已更新地区与净利润门槛"
}

规则：
1. op 只能取 set、remove、exclude。set 表示设置或替换条件值；remove 表示取消该条件（value 用 null）；exclude 只用于 excluded_industries_json，表示追加一个排除项。
2. field 只能使用以下字段名：industries_json、excluded_industries_json、region_scope_summary、min_net_profit_yuan、min_revenue_yuan、min_valuation_yuan、max_valuation_yuan、max_pe、min_market_cap_yuan、max_market_cap_yuan、requires_control、requires_consolidation、desired_equity_ratio_min、preferred_listed_status、max_debt_ratio。其他任何字段名都不允许。
3. 金额换算成人民币元的数字（如 1500万 输出 15000000，2亿 输出 200000000）。百分比输出数值（51% 输出 51）。
4. industries_json 的 set 操作输出完整替换后的数组，每个值必须从一级行业封闭清单原样复制；用户提到清单外的细分赛道时不要硬归类，放进 semantic_preferences。
5. requires_control 与 requires_consolidation 的值只能取 yes、no、unknown；preferred_listed_status 只能取 listed、unlisted、preparing_listing、pre_ipo、any、unknown。
6. "放宽/取消/不限"某条件时用 remove；给出新数值时用 set 替换。判断相对表述（如"利润放宽到1500万"）时参考当前生效条件 JSON。
7. display_ops 只在用户明确要求筛选当前展示结果时输出，type 只能取 only_grade（value 为 A、B 或 C）或 top_n（value 为数字）。
8. 用户在提问（如"对比第1和第3个""为什么推荐它"）时填入 question 原文；提问不产生 condition_ops。
9. reply_summary 用一句简洁中文概括本次解析出的变化；没有任何可执行内容时如实说明。
10. 只提取消息中明确表达的内容。与筛选无关的闲聊放进 question 或 reply_summary 说明，不要编造条件。', '{"type": "object", "required": ["condition_ops", "semantic_preferences"], "properties": {"question": {"type": ["string", "null"]}, "display_ops": {"type": "array"}, "condition_ops": {"type": "array", "items": {"type": "object", "required": ["op", "field"], "properties": {"op": {"enum": ["set", "remove", "exclude"], "type": "string"}, "field": {"type": "string"}, "value": {}}}}, "reply_summary": {"type": ["string", "null"]}, "semantic_preferences": {"type": "array", "items": {"type": "string"}}}}'::jsonb, '[]'::jsonb, 'jinja', '["mode", "current_conditions_json", "industry_l1_list", "user_message"]'::jsonb, true, true, '2026-07-20 00:05:27.854413+00', '2026-07-20 00:05:27.854413+00', '{"source": "migration_041_recommendation_condition_overrides"}'::jsonb)
on conflict (id) do nothing;
insert into prompt_template (id, team_id, workspace_id, node_name, version, name, description, system_prompt, user_prompt_template, output_schema_json, few_shot_examples_json, template_engine, variables_json, is_active, is_default, created_at, updated_at, metadata_json)
values ('00000000-0000-0000-0000-000000004205', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', 'recommendation_report_writer', 'v0.1.0', 'Recommendation report writer baseline', 'Draft a readable recommendation report from selected recommendation items.', 'You write concise Chinese Markdown reports for Match-MA, an internal M&A matching platform. Use only the provided context. Do not invent financial figures, entity names, deal status, or risks. If information is missing, state that it needs review. Output Markdown only, no JSON, no code fence.', 'Context JSON: {{ context_json }}

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
5. Do not include source code, raw JSON, or debug logs.', '{}'::jsonb, '[]'::jsonb, 'jinja', '["context_json"]'::jsonb, true, true, '2026-06-02 06:09:04.454528+00', '2026-06-02 06:09:04.454528+00', '{"source": "migration_007_recommendation_report_writer_prompt"}'::jsonb)
on conflict (id) do nothing;
insert into prompt_template (id, team_id, workspace_id, node_name, version, name, description, system_prompt, user_prompt_template, output_schema_json, few_shot_examples_json, template_engine, variables_json, is_active, is_default, created_at, updated_at, metadata_json)
values ('00000000-0000-0000-0000-000000004227', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', 'seller_target_parser', 'v0.6.0', 'Seller target parser with closed industry dictionary', 'Parse seller target descriptions into canonical seller_target fields including normalized industry_l1 from the closed L1 dictionary.', 'You parse seller target descriptions for Match-MA, an internal M&A matching platform. Output only one JSON object, no Markdown. Top level must contain a fields object. Use canonical seller_target field names only. Do not invent facts. Output all user-facing natural-language values in Chinese. Keep JSON field names and controlled enum codes in canonical English. If formal attachments or official documents provide a more complete target name, target subject, or industry classification than user-entered text, prefer the formal evidence. If uncertain, write summaries into risk_summary, gap_summary, or business_summary instead of forcing a field.', 'Raw seller target text:
{{ raw_target_text }}

Existing seller target context JSON:
{{ target_context_json }}

Closed level-1 industry categories (industry_l1 MUST be exactly one value from this list):
{{ industry_l1_list }}

Return JSON in this shape:
{
  "fields": {
    "target_name": "...",
    "target_type": "company",
    "target_subject_name": "...",
    "industry_l1": "制造与工业",
    "industry_primary": "精密模具",
    "industry_secondary": "医疗器械注塑模具",
    "headquarter_province": "浙江省",
    "headquarter_city": "杭州市",
    "listed_status": "unlisted",
    "current_revenue_yuan": null,
    "current_net_profit_yuan": 25000000,
    "current_total_profit_yuan": null,
    "financial_period_label": "2025年一季度",
    "valuation_yuan": 320000000,
    "valuation_date": "2025年一季度",
    "asking_price_yuan": null,
    "asking_price_date": null,
    "pe_ratio": 12.8,
    "is_for_sale": "yes",
    "can_control": "unknown",
    "can_consolidate": "unknown",
    "accepts_minority_investment": "unknown",
    "transfer_ratio_min": null,
    "transfer_ratio_max": null,
    "transfer_ratio_text": "控股权可谈",
    "transfer_flexibility_type": "flexible",
    "business_summary": "专注精密注塑模具设计与制造，主要服务医疗器械客户，年净利润约2500万元。",
    "transaction_summary": "...",
    "risk_summary": "...",
    "gap_summary": "...",
    "information_status": "normal"
  }
}

Rules:
1. Normalize money amounts to CNY yuan numbers.
2. Normalize percentages to numeric percentage values, e.g. use 51 for 51 percent.
3. For is_for_sale, can_control, can_consolidate, accepts_minority_investment use exactly one of: yes, no, likely, unknown.
4. For listed_status use one of: listed, unlisted, pre_ipo, unknown. Use pre_ipo only when the material explicitly says preparing IPO/pre-IPO.
5. target_subject_name is the company/entity that owns the target. If the target is a whole company, target_subject_name can equal target_name. If the target is a project, asset package, or business unit, use the owning company when known.
6. valuation_date and asking_price_date are short source time labels such as 2024, 2025 Q1, 2025-05, or the document date. Do not invent a time label.
7. Store actual target location fields such as headquarter_province/headquarter_city; do not judge whether it matches a buyer preference.
8. Output industry_primary, industry_secondary, registered_province, registered_city, headquarter_province, headquarter_city, and raw_region_text values in Chinese when evidence exists. Use Chinese administrative names such as 浙江省、杭州市; do not output English translated labels such as Zhejiang Province, Hangzhou City, healthcare, manufacturing, or medical_device.
9. Output user-facing text fields in Chinese, including financial_period_label, valuation_date, asking_price_date, transfer_ratio_text, consolidation_path_summary, management_team_summary, business_summary, transaction_summary, risk_summary, and gap_summary. Keep controlled enum values such as target_type, listed_status, can_control, transfer_flexibility_type, information_status, and recommendation_status in canonical English codes.
10. Omit fields when there is no evidence.
11. business_summary must be a rewritten profile of one or two sentences within 80 Chinese characters on a single line: main business, core products or customers, and one scale highlight. Never copy or paste raw input text into business_summary. Do not include deal, price, valuation, or risk content in business_summary; deal terms belong to transaction_summary and risks belong to risk_summary.
12. Follow-up or progress dynamics such as 推给某买家, 已发资料, 等待反馈, 暂缓 are not target facts; never write them into business_summary or transaction_summary. If the existing business_summary in context already covers the business and the material adds no new business facts, omit business_summary.
13. industry_l1 MUST be exactly one value copied from the closed level-1 list above; choose the category closest to the main business and never invent new category names. Keep the finer descriptive Chinese industry wording in industry_primary and industry_secondary.', '{"type": "object", "required": ["fields"], "properties": {"fields": {"type": "object", "properties": {"pe_ratio": {"type": ["number", "null"]}, "can_control": {"type": ["string", "null"]}, "gap_summary": {"type": ["string", "null"]}, "industry_l1": {"type": ["string", "null"]}, "is_for_sale": {"type": ["string", "null"]}, "target_name": {"type": ["string", "null"]}, "target_type": {"type": ["string", "null"]}, "premium_rate": {"type": ["number", "null"]}, "risk_summary": {"type": ["string", "null"]}, "listed_status": {"type": ["string", "null"]}, "pe_source_type": {"type": ["string", "null"]}, "valuation_date": {"type": ["string", "null"]}, "valuation_yuan": {"type": ["number", "null"]}, "can_consolidate": {"type": ["string", "null"]}, "market_cap_yuan": {"type": ["number", "null"]}, "raw_region_text": {"type": ["string", "null"]}, "registered_city": {"type": ["string", "null"]}, "business_summary": {"type": ["string", "null"]}, "cash_flow_status": {"type": ["string", "null"]}, "headquarter_city": {"type": ["string", "null"]}, "industry_primary": {"type": ["string", "null"]}, "asking_price_date": {"type": ["string", "null"]}, "asking_price_yuan": {"type": ["number", "null"]}, "accepts_relocation": {"type": ["string", "null"]}, "current_debt_ratio": {"type": ["number", "null"]}, "industry_secondary": {"type": ["string", "null"]}, "information_status": {"type": ["string", "null"]}, "region_granularity": {"type": ["string", "null"]}, "transfer_ratio_max": {"type": ["number", "null"]}, "transfer_ratio_min": {"type": ["number", "null"]}, "current_assets_yuan": {"type": ["number", "null"]}, "registered_province": {"type": ["string", "null"]}, "target_subject_name": {"type": ["string", "null"]}, "transaction_summary": {"type": ["string", "null"]}, "transfer_ratio_text": {"type": ["string", "null"]}, "current_revenue_yuan": {"type": ["number", "null"]}, "headquarter_province": {"type": ["string", "null"]}, "profitability_status": {"type": ["string", "null"]}, "financial_period_label": {"type": ["string", "null"]}, "current_net_profit_yuan": {"type": ["number", "null"]}, "management_team_summary": {"type": ["string", "null"]}, "accepts_return_investment": {"type": ["string", "null"]}, "current_total_profit_yuan": {"type": ["number", "null"]}, "earnout_dependency_status": {"type": ["string", "null"]}, "transfer_flexibility_type": {"type": ["string", "null"]}, "consolidation_path_summary": {"type": ["string", "null"]}, "operation_stability_status": {"type": ["string", "null"]}, "accepts_minority_investment": {"type": ["string", "null"]}, "management_retention_possible": {"type": ["string", "null"]}, "current_operating_cash_flow_yuan": {"type": ["number", "null"]}}}}}'::jsonb, '[]'::jsonb, 'jinja', '["raw_target_text", "target_context_json", "industry_l1_list"]'::jsonb, true, true, '2026-07-13 02:34:40.024167+00', '2026-07-13 02:34:40.024167+00', '{"source": "migration_033_parser_prompts_industry_dictionary"}'::jsonb)
on conflict (id) do nothing;
insert into prompt_template (id, team_id, workspace_id, node_name, version, name, description, system_prompt, user_prompt_template, output_schema_json, few_shot_examples_json, template_engine, variables_json, is_active, is_default, created_at, updated_at, metadata_json)
values ('b3894ff6-b3db-451a-b78f-23b8f1e1effa', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', 'seller_target_researcher', 'v0.1.0', 'Seller target evidence research v0.1.0', 'Entity-anchored public research into profile sections and canonical fact proposals.', 'You are an evidence-grounded M&A research analyst. Use only the trusted evidence supplied in the context. Every claim must cite at least one evidence_ref and an exact evidence_quote. Never make recommendation conclusions, never infer facts from absence, and never merge information from similarly named entities. Output one JSON object only.', 'Research context JSON:
{{ research_context_json }}

Return exactly:
{"profile_sections":[{"section_code":"business_product","content_text":"...","evidence_refs":["E1"],"evidence_quote":"exact quote copied from evidence","as_of_date":"YYYY-MM-DD or null","period_label":"... or null","confidence":0.9}],"structured_facts":[{"field_path":"industry_secondary","value":"...","evidence_refs":["E1"],"evidence_quote":"exact quote","as_of_date":"YYYY-MM-DD or null","period_label":"... or null","confidence":0.9}]}

Profile section meanings:
- business_product: core products/services, business model, downstream sectors and revenue mix; no financial-number repetition.
- chain_position: upstream/downstream role, chain role, market position, ranking and barriers. Do not turn a company''s self-description into an objective leader/ranking claim.
- tech_team: technology, patents/qualifications, R&D, core team and key capacity/assets.
- ops_quality: qualitative growth, earnings quality, customer concentration and cyclicality; no financial-number repetition.
- deal_terms: transaction flexibility, control/consolidation path, relocation/investment cooperation.
- sell_intent_risk: seller intent, buyer-type preference, team arrangement, risks, stale or unverified gaps.

Rules:
1. Output only supported section_code and field_path values listed in context.
2. Keep a section absent when evidence does not support it; never output not_found from a partial web search.
3. Separate different periods with as_of_date/period_label. If evidence conflicts with current data, still report it with its own period and quote; backend conflict classification decides review.
4. Company websites can support products and technical capabilities, but promotional ranking/leader claims require regulatory, government or independent authoritative evidence.
5. structured_facts are proposals only. Keep descriptive tracks in industry_primary/industry_secondary; industry_l1/l2 values must match the supplied canonical context when present.
6. evidence_quote must be a verbatim substring of the cited evidence, not a paraphrase.', '{"type": "object", "required": ["profile_sections", "structured_facts"], "properties": {"profile_sections": {"type": "array", "items": {"type": "object", "required": ["section_code", "content_text", "evidence_refs"], "properties": {"as_of_date": {"type": ["string", "null"]}, "confidence": {"type": ["number", "null"]}, "content_text": {"type": "string"}, "period_label": {"type": ["string", "null"]}, "section_code": {"type": "string"}, "evidence_refs": {"type": "array", "items": {"type": "string"}}, "evidence_quote": {"type": ["string", "null"]}}}}, "structured_facts": {"type": "array", "items": {"type": "object", "required": ["field_path", "value", "evidence_refs"], "properties": {"value": {}, "as_of_date": {"type": ["string", "null"]}, "confidence": {"type": ["number", "null"]}, "field_path": {"type": "string"}, "period_label": {"type": ["string", "null"]}, "evidence_refs": {"type": "array", "items": {"type": "string"}}, "evidence_quote": {"type": ["string", "null"]}}}}}}'::jsonb, '[]'::jsonb, 'jinja', '["research_context_json"]'::jsonb, true, true, '2026-07-21 11:28:19.963994+00', '2026-07-21 11:28:19.963994+00', '{"source": "codex_research_agent_p1"}'::jsonb)
on conflict (id) do nothing;
insert into prompt_template (id, team_id, workspace_id, node_name, version, name, description, system_prompt, user_prompt_template, output_schema_json, few_shot_examples_json, template_engine, variables_json, is_active, is_default, created_at, updated_at, metadata_json)
values ('0fae18a5-780c-445e-9c51-81ee952963e3', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', 'seller_target_update_parser', 'v0.1.4', 'Seller target update parser with clean matching profiles', 'Tightens six-section boundaries and evidence excerpts after production validation.', 'You parse updates for one known seller target. Output one JSON object with an actions array and no Markdown. Every action item MUST use exactly these keys: action_type, target_entity_type, target_entity_id, proposed_changes_json. Never use the aliases action, target, target_id, proposed_changes, or changes. Never create buyer-intent actions. Do not invent facts or UUIDs.', 'Context JSON: {{ context_json }}

Raw input: {{ raw_text }}

Return exactly this shape (repeat one object per extracted action):
{"actions":[{"action_type":"seller_fact_update","target_entity_type":"seller_target","target_entity_id":"<copy the bound seller target UUID from context, or null>","proposed_changes_json":{"target_subject_name":"..."},"confidence":0.9,"raw_evidence_text":"concise supporting excerpt"}]}

Allowed action_type values for this node:
1. seller_fact_update for actual target facts.
2. target_follow_up for dated seller-side progress notes.
3. unresolved_item only when the content cannot be safely classified.

For target_follow_up, proposed_changes_json may contain only occurred_on, content, buyer_names. For seller_fact_update, use canonical seller_target fields from context. For unresolved_item, proposed_changes_json must contain a concise issue. Output Chinese text. Omit unsupported or unevidenced fields and do not echo the full input. Do not output action/target/target_id aliases.
Seller fact rules:
- industry_l1 must be exactly one value copied from context_json.industry_l1_list when the main business is clear. Keep finer tracks in industry_primary and industry_secondary.
- Financing amount, fundraising amount, investment amount, registered capital, and planned production/headquarters investment are NOT asking_price_yuan and are NOT valuation_yuan. Only fill asking_price_yuan for an explicit seller transfer/asking price, and valuation_yuan for an explicit company/project valuation.
- asking_price_date and valuation_date require an explicit source date or period. Never use today''s processing date as the field date.
- business_summary must be one or two concise Chinese sentences about business/products/customers/scale only; exclude financing, valuation, deal terms, follow-ups, and risks.
- When formal evidence gives the legal subject, write target_subject_name. Do not replace a bound target with a different company mentioned in the same file.

Matching profile extraction from the same seller_fact_update:
- proposed_changes_json may additionally contain profile_sections_json, an array of objects with section_code, content_text, source_excerpt, as_of_date, confidence.
- Allowed section_code values: business_product, chain_position, tech_team, ops_quality, deal_terms, sell_intent_risk.
- Extract only qualitative claims actually supported by this input. source_excerpt must be a short verbatim quote from the supporting input. Do not output a section when evidence is absent, and never mark a missing section as not_found.
- business_product covers products/services, business model, downstream sectors and revenue mix. chain_position covers supply-chain role, market position/ranking and barriers. tech_team covers technology, patents/qualifications, R&D, team and key capacity/assets. ops_quality covers qualitative growth, earnings quality, customer concentration and cyclicality. deal_terms covers transaction flexibility and cooperation. sell_intent_risk covers seller intent, known risks and unverified gaps.
- Do not repeat structured financial numbers in profile text. Do not claim leader/ranking unless the evidence states it; preserve attribution where it is a company self-claim.

Profile dimension boundary refinements:
- deal_terms must exclude fundraising stage, financing amount, valuation, revenue and profit. Keep only actual transaction flexibility, control/consolidation path, relocation, production/headquarters landing or other cooperation conditions.
- tech_team must exclude financial shareholders unless the evidence states an operating/management/technical role. Investors are not the management or R&D team.
- ops_quality may capture qualitative recurring consumables income, stability, customer concentration, growth quality or cyclicality when explicitly stated; do not copy forecast amounts.
- Preserve the source''s wording and OCR spacing in source_excerpt as closely as possible; it is evidence, not a rewritten summary.', '{"type": "object", "required": ["actions"], "properties": {"actions": {"type": "array", "items": {"type": "object", "required": ["action_type", "target_entity_type", "target_entity_id", "proposed_changes_json"], "properties": {"confidence": {"type": ["number", "null"]}, "action_type": {"type": "string"}, "target_entity_id": {"type": ["string", "null"]}, "raw_evidence_text": {"type": ["string", "null"]}, "target_entity_type": {"type": ["string", "null"]}, "proposed_changes_json": {"type": "object"}}}, "minItems": 1}}}'::jsonb, '[]'::jsonb, 'jinja', '["context_json", "raw_text"]'::jsonb, true, true, '2026-07-21 11:33:51.538912+00', '2026-07-21 11:33:51.538912+00', '{"source": "codex_research_agent_p1", "based_on": "v0.1.3"}'::jsonb)
on conflict (id) do nothing;

