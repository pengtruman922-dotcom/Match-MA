export interface SellerTarget {
  id: string;
  target_name: string;
  target_type: string | null;
  target_subject_name: string | null;
  lifecycle_status: string;
  recommendation_status: string;
  information_status: string;
  // L1/L2 是筛选实际读取的规范维度；industry_primary/secondary 是解析原文。
  industry_l1: string | null;
  industry_l2: string | null;
  industry_primary: string | null;
  industry_secondary: string | null;
  registered_province: string | null;
  registered_city: string | null;
  headquarter_province: string | null;
  headquarter_city: string | null;
  raw_region_text: string | null;
  region_granularity: string | null;
  listed_status: string | null;
  listing_market_region: string | null;
  market_cap_yuan: string | null;
  current_revenue_yuan: string | null;
  current_net_profit_yuan: string | null;
  current_total_profit_yuan: string | null;
  current_assets_yuan: string | null;
  current_debt_ratio: string | null;
  current_operating_cash_flow_yuan: string | null;
  financial_period_label: string | null;
  profitability_status: string | null;
  cash_flow_status: string | null;
  operation_stability_status: string | null;
  valuation_yuan: string | null;
  valuation_date: string | null;
  asking_price_yuan: string | null;
  asking_price_date: string | null;
  pe_ratio: string | null;
  pe_source_type: string | null;
  premium_rate: string | null;
  is_for_sale: string | null;
  can_control: string | null;
  can_consolidate: string | null;
  accepts_minority_investment: string | null;
  transfer_ratio_min: string | null;
  transfer_ratio_max: string | null;
  transfer_ratio_text: string | null;
  transfer_flexibility_type: string | null;
  consolidation_path_summary: string | null;
  accepts_relocation: string | null;
  accepts_return_investment: string | null;
  management_team_summary: string | null;
  management_retention_possible: string | null;
  earnout_dependency_status: string | null;
  business_summary: string | null;
  transaction_summary: string | null;
  risk_summary: string | null;
  gap_summary: string | null;
  owner_user_id?: string | null;
  owner_name?: string | null;
  created_at: string;
  updated_at: string;
  latest_follow_up_on?: string | null;
  latest_follow_up_content?: string | null;
  last_research_at?: string | null;
  research_last_outcome?: 'found' | 'no_public_information' | 'failed' | null;
}

export interface SellerTargetListResponse {
  items: SellerTarget[];
  total: number;
  limit: number;
  offset: number;
}

export type SellerTargetSearchField = 'target_name' | 'target_subject_name' | 'business_summary';

export interface SellerTargetFilterOption {
  value: string;
  label: string;
  count: number;
}

export interface SellerTargetFilterOptions {
  industries: SellerTargetFilterOption[];
  regions: SellerTargetFilterOption[];
  statuses: SellerTargetFilterOption[];
  recommendation_statuses?: SellerTargetFilterOption[];
  parse_statuses?: SellerTargetFilterOption[];
  owners?: SellerTargetFilterOption[];
}

export interface SellerTargetSuggestion {
  id: string;
  search_field: SellerTargetSearchField;
  match_type: 'target' | 'subject' | 'summary';
  match_label: string;
  match_text: string;
  target_name: string;
  target_subject_name: string | null;
  snippet: string | null;
}

export interface SellerTargetBulkDeleteResponse {
  status: string;
  deleted_count: number;
  deleted_ids: string[];
  skipped_ids: string[];
}

export interface TargetFollowUpBuyerRef {
  id: string;
  buyer_name: string;
}

export interface TargetFollowUp {
  id: string;
  seller_target_id: string;
  occurred_on: string;
  content: string;
  related_buyer_parties: TargetFollowUpBuyerRef[];
  created_at: string;
}

export interface TargetFollowUpCreate {
  content: string;
  occurred_on?: string;
  related_buyer_party_ids?: string[];
}

export interface SellerTargetCreate {
  target_name: string;
  target_type?: string;
  target_subject_name?: string;
  lifecycle_status?: string;
  recommendation_status?: string;
  information_status?: string;
  industry_primary?: string;
  industry_secondary?: string;
  headquarter_province?: string;
  headquarter_city?: string;
  listed_status?: string;
  current_revenue_yuan?: number;
  current_net_profit_yuan?: number;
  valuation_yuan?: number;
  valuation_date?: string;
  asking_price_yuan?: number;
  asking_price_date?: string;
  pe_ratio?: number;
  is_for_sale?: string;
  can_control?: string;
  can_consolidate?: string;
  business_summary?: string;
}

export interface SellerTargetUpdate {
  target_name?: string;
  target_type?: string;
  target_subject_name?: string;
  lifecycle_status?: string;
  recommendation_status?: string;
  information_status?: string;
  industry_primary?: string;
  industry_secondary?: string;
  headquarter_province?: string;
  headquarter_city?: string;
  listed_status?: string;
  current_revenue_yuan?: number;
  current_net_profit_yuan?: number;
  valuation_yuan?: number;
  valuation_date?: string;
  asking_price_yuan?: number;
  asking_price_date?: string;
  pe_ratio?: number;
  is_for_sale?: string;
  can_control?: string;
  can_consolidate?: string;
  business_summary?: string;
  owner_user_id?: string | null;
}

export interface BuyerParty {
  id: string;
  buyer_name: string;
  legal_name: string | null;
  aliases_json: string[];
  buyer_type: string | null;
  group_name: string | null;
  listed_status: string | null;
  region_province: string | null;
  region_city: string | null;
  main_business: string | null;
  capital_strength_summary: string | null;
  profile_summary: string | null;
  notes: string | null;
  status: string;
  owner_user_id?: string | null;
  owner_name?: string | null;
  created_at: string;
  updated_at: string;
}

export interface BuyerPartyListResponse {
  items: BuyerParty[];
  total: number;
  limit: number;
  offset: number;
}

export type BuyerPartySearchField = 'buyer_name' | 'legal_name' | 'main_business' | 'profile_summary';

export interface BuyerFilterOption {
  value: string;
  label: string;
  count: number;
}

export interface BuyerPartyFilterOptions {
  buyer_types: BuyerFilterOption[];
  regions: BuyerFilterOption[];
  listed_statuses: BuyerFilterOption[];
  statuses: BuyerFilterOption[];
  owners?: BuyerFilterOption[];
}

export interface BuyerPartySuggestion {
  id: string;
  search_field: BuyerPartySearchField;
  match_type: 'buyer' | 'legal' | 'business' | 'profile';
  match_label: string;
  match_text: string;
  buyer_name: string;
  legal_name: string | null;
  snippet: string | null;
}

export interface BuyerPartyDedupMatch {
  buyer_name: string;
  legal_name: string | null;
  owner_name: string | null;
  match_type: 'buyer_name' | 'legal_name' | 'alias';
  status: string;
}

export interface BuyerPartyDedupCheck {
  exists: boolean;
  query: string;
  matches: BuyerPartyDedupMatch[];
}

export interface BuyerBulkDeleteResponse {
  status: string;
  deleted_count: number;
  deleted_ids: string[];
  skipped_ids: string[];
}

export interface BuyerPartyCreate {
  buyer_name: string;
  legal_name?: string | null;
  buyer_type?: string | null;
  group_name?: string | null;
  listed_status?: string | null;
  region_province?: string | null;
  region_city?: string | null;
  main_business?: string | null;
  capital_strength_summary?: string | null;
  profile_summary?: string | null;
  notes?: string | null;
  owner_user_id?: string | null;
}

export interface BuyerIntent {
  id: string;
  buyer_party_id: string | null;
  buyer_name?: string | null;
  intent_name: string;
  status: string;
  contact_name: string | null;
  raw_requirement_text: string | null;
  intent_summary: string | null;
  industry_primary: string | null;
  industry_secondary: string | null;
  industries_json?: string[];
  excluded_industries_json?: string[];
  industry_focus_tags_json?: string[];
  region_scope_summary: string | null;
  min_revenue_yuan: string | null;
  min_net_profit_yuan: string | null;
  min_total_profit_yuan: string | null;
  max_pe: string | null;
  max_ps: string | null;
  min_net_margin: string | null;
  min_gross_margin: string | null;
  min_valuation_yuan: string | null;
  max_valuation_yuan: string | null;
  min_market_cap_yuan: string | null;
  max_market_cap_yuan: string | null;
  market_cap_range_summary: string | null;
  requires_control: string | null;
  requires_consolidation: string | null;
  accepts_minority_investment: string | null;
  desired_equity_ratio_min: string | null;
  desired_equity_ratio_max: string | null;
  equity_ratio_summary: string | null;
  equity_requirement_type: string | null;
  preferred_listed_status: string | null;
  listing_board_requirement_summary: string | null;
  financing_stage_requirement_summary: string | null;
  industry_l2_json: string[] | null;
  budget_min_yuan: string | null;
  budget_max_yuan: string | null;
  acceptable_cash_flow_status_json: string[] | null;
  acceptable_profitability_status_json: string[] | null;
  requires_relocation: string | null;
  relocation_target_regions_json: string[] | null;
  requires_return_investment: string | null;
  return_investment_multiple: string | null;
  requires_team_retention: string | null;
  earnout_requirement: string | null;
  listing_market_region: string | null;
  transaction_type: string | null;
  transaction_types_json: string[] | Record<string, unknown> | null;
  premium_tolerance_summary: string | null;
  max_premium_rate: string | null;
  max_debt_ratio: string | null;
  debt_ratio_requirement_summary: string | null;
  major_risk_tolerance_summary: string | null;
  buyer_industry_advantage_summary: string | null;
  negative_summary: string | null;
  priority_summary: string | null;
  preference_summary: string | null;
  unknown_summary: string | null;
  owner_user_id?: string | null;
  owner_name?: string | null;
  created_at: string;
  updated_at: string;
}

export interface BuyerIntentListResponse {
  items: BuyerIntent[];
  total: number;
  limit: number;
  offset: number;
}

export interface BuyerIntentFollowUp {
  id: string;
  buyer_intent_id: string;
  occurred_at: string;
  contact_name: string | null;
  content: string;
  next_step: string | null;
  next_follow_up_at: string | null;
  business_update_id: string | null;
  extracted_action_id: string | null;
  created_by: string | null;
  created_by_name: string | null;
  created_at: string;
}

export interface BuyerIntentFollowUpCreate {
  occurred_at?: string;
  contact_name?: string;
  content: string;
  next_step?: string;
  next_follow_up_at?: string;
}

export interface ModelProviderConfig {
  id: string;
  provider_name: string;
  model_name: string;
  provider_type: string;
  base_url: string | null;
  secret_mode: 'env' | 'direct';
  api_key_secret_ref: string | null;
  secret_configured: boolean;
  key_display: string;
  auth_type: string;
  extra_headers_json: Record<string, unknown>;
  extra_config_json: Record<string, unknown>;
  is_active: boolean;
  is_default: boolean;
  created_at: string;
  updated_at: string;
  metadata_json: Record<string, unknown>;
}

export interface ModelConnectionTestResult {
  status: 'succeeded' | 'failed';
  model_name: string;
  latency_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  output_preview: string | null;
  error_code: string | null;
  error_message: string | null;
}

export interface PromptTemplateConfig {
  id: string;
  node_name: string;
  version: string;
  name: string | null;
  system_prompt: string | null;
  user_prompt_template: string | null;
  output_schema_json: Record<string, unknown>;
  variables_json: unknown[];
  is_active: boolean;
  is_default: boolean;
  updated_at: string;
}

export interface ModelNodeConfig {
  id: string;
  node_name: string;
  node_type: string;
  provider_config_id: string;
  provider_name: string | null;
  model_name: string;
  temperature: number | string | null;
  top_p: number | string | null;
  max_tokens: number | null;
  timeout_seconds: number;
  response_format: string | null;
  output_mode: string;
  embedding_dimension: number | null;
  is_active: boolean;
  is_default: boolean;
  prompt_editable: boolean;
  default_prompt: PromptTemplateConfig | null;
  test_summary: {
    latest_status: string | null;
    latest_latency_ms: number | null;
    latest_error_code: string | null;
    latest_error_message: string | null;
  };
}

export interface ModelConfigSettingsPage {
  capabilities: {
    direct_key_encryption_configured?: boolean;
    [key: string]: unknown;
  };
  providers: ModelProviderConfig[];
  nodes: ModelNodeConfig[];
  prompts: PromptTemplateConfig[];
  overview: Record<string, number>;
  security_note: string;
}

export interface IndustryDictionaryTerm {
  id: string;
  term: string;
  level: 'l1' | 'l2';
  l1_name: string;
  parent_id: string | null;
  parent_name: string | null;
  aliases: Array<{ id: string; term: string; active: boolean }>;
  active: boolean;
  sort_order: number;
  usage_count: number;
  created_at: string;
  updated_at: string;
}

export interface IndustryDictionaryImportRow {
  row_number: number;
  l1: string;
  l2: string | null;
  aliases: string[];
  active: boolean;
  status: 'ready' | 'error';
  message: string;
}

export interface IndustryDictionaryImportResult {
  dry_run: boolean;
  total_rows: number;
  ready_rows: number;
  error_rows: number;
  created_l1: number;
  created_l2: number;
  created_aliases: number;
  rows: IndustryDictionaryImportRow[];
}

export type BuyerIntentSearchField = 'intent_name' | 'buyer_name' | 'raw_requirement_text' | 'intent_summary';

export interface BuyerIntentFilterOptions {
  industries: BuyerFilterOption[];
  regions: BuyerFilterOption[];
  statuses: BuyerFilterOption[];
  listed_statuses: BuyerFilterOption[];
  consolidation_requirements: BuyerFilterOption[];
  owners?: BuyerFilterOption[];
}

export interface AppUser {
  id: string;
  username: string | null;
  name: string;
  role: string;
  status: string;
  created_at: string;
  owned_seller_targets: number;
  owned_buyer_parties: number;
  owned_buyer_intents: number;
}

export interface AppUserOption {
  id: string;
  name: string;
  username: string | null;
  role: string;
  status: string;
}

export interface AppUserCreate {
  username: string;
  name: string;
  password: string;
  role: 'admin' | 'consultant';
}

export interface AppUserActivitySummary {
  user: AppUserOption;
  owned_seller_targets: number;
  owned_buyer_parties: number;
  owned_buyer_intents: number;
  seller_target_status_counts: Record<string, number>;
  weekly_new_seller_targets: number;
  weekly_new_buyer_parties: number;
  weekly_new_buyer_intents: number;
  weekly_business_updates: number;
  weekly_follow_ups: number;
  weekly_application_logs: number;
  latest_activity_at: string | null;
}

export interface BatchAssignOwnerResponse {
  status: string;
  updated_count: number;
  updated_ids: string[];
}

export interface BuyerIntentSuggestion {
  id: string;
  search_field: BuyerIntentSearchField;
  match_type: 'intent' | 'buyer' | 'requirement' | 'summary';
  match_label: string;
  match_text: string;
  intent_name: string;
  buyer_party_id: string | null;
  buyer_name: string | null;
  snippet: string | null;
}

export interface BuyerIntentCreate {
  intent_name: string;
  buyer_party_id?: string;
  contact_name?: string;
  raw_requirement_text?: string;
  industry_primary?: string;
  industry_focus_tags_json?: string[];
  region_scope_summary?: string;
  min_revenue_yuan?: number;
  min_net_profit_yuan?: number;
  min_total_profit_yuan?: number;
  max_pe?: number;
  max_ps?: number;
  min_net_margin?: number;
  min_gross_margin?: number;
  min_valuation_yuan?: number;
  max_valuation_yuan?: number;
  min_market_cap_yuan?: number;
  max_market_cap_yuan?: number;
  market_cap_range_summary?: string;
  requires_control?: string;
  requires_consolidation?: string;
  accepts_minority_investment?: string;
  desired_equity_ratio_min?: number;
  desired_equity_ratio_max?: number;
  equity_ratio_summary?: string;
  equity_requirement_type?: string;
  preferred_listed_status?: string;
  listing_board_requirement_summary?: string;
  financing_stage_requirement_summary?: string;
  industry_l2_json?: string[];
  budget_min_yuan?: number;
  budget_max_yuan?: number;
  acceptable_cash_flow_status_json?: string[];
  acceptable_profitability_status_json?: string[];
  requires_relocation?: string;
  relocation_target_regions_json?: string[];
  requires_return_investment?: string;
  return_investment_multiple?: number;
  requires_team_retention?: string;
  earnout_requirement?: string;
  listing_market_region?: string;
  transaction_type?: string;
  transaction_types_json?: string[] | Record<string, unknown>;
  premium_tolerance_summary?: string;
  max_premium_rate?: number;
  max_debt_ratio?: number;
  debt_ratio_requirement_summary?: string;
  major_risk_tolerance_summary?: string;
  buyer_industry_advantage_summary?: string;
  negative_summary?: string;
  preference_summary?: string;
}

export interface BuyerIntentParseJob {
  job_id: string;
  job_type: string;
  status: string;
  queue_name: string;
  buyer_intent_id: string;
}

export interface BuyerIntentParseStatus {
  buyer_intent: BuyerIntent;
  latest_job: {
    id: string;
    job_type: string;
    status: string;
    queue_name: string;
    error_code: string | null;
    error_message: string | null;
    attempt_count: number;
    max_attempts: number;
    started_at: string | null;
    finished_at: string | null;
    created_at: string;
    updated_at: string;
    result_json: Record<string, unknown>;
    debug_ref?: DebugRef;
  } | null;
  latest_trace: {
    status: string;
    error_code?: string | null;
    error_message?: string | null;
  } | null;
  recent_update_logs: Array<Record<string, unknown>>;
  debug_ref: DebugRef;
}

export interface BuyerIntentUpdate {
  intent_name?: string;
  status?: string;
  contact_name?: string;
  raw_requirement_text?: string;
  industry_primary?: string;
  industry_focus_tags_json?: string[];
  region_scope_summary?: string;
  min_revenue_yuan?: number;
  min_net_profit_yuan?: number;
  min_total_profit_yuan?: number;
  max_pe?: number;
  max_ps?: number;
  min_net_margin?: number;
  min_gross_margin?: number;
  min_valuation_yuan?: number;
  max_valuation_yuan?: number;
  min_market_cap_yuan?: number;
  max_market_cap_yuan?: number;
  market_cap_range_summary?: string;
  requires_control?: string;
  requires_consolidation?: string;
  accepts_minority_investment?: string;
  desired_equity_ratio_min?: number;
  desired_equity_ratio_max?: number;
  equity_ratio_summary?: string;
  equity_requirement_type?: string;
  preferred_listed_status?: string;
  listing_board_requirement_summary?: string;
  financing_stage_requirement_summary?: string;
  industry_l2_json?: string[];
  budget_min_yuan?: number;
  budget_max_yuan?: number;
  acceptable_cash_flow_status_json?: string[];
  acceptable_profitability_status_json?: string[];
  requires_relocation?: string;
  relocation_target_regions_json?: string[];
  requires_return_investment?: string;
  return_investment_multiple?: number;
  requires_team_retention?: string;
  earnout_requirement?: string;
  listing_market_region?: string;
  transaction_type?: string;
  transaction_types_json?: string[] | Record<string, unknown>;
  premium_tolerance_summary?: string;
  max_premium_rate?: number;
  max_debt_ratio?: number;
  debt_ratio_requirement_summary?: string;
  major_risk_tolerance_summary?: string;
  buyer_industry_advantage_summary?: string;
  negative_summary?: string;
  preference_summary?: string;
  pause_reason?: string;
  owner_user_id?: string | null;
}

export interface BusinessUpdate {
  id: string;
  raw_text: string;
  input_type: string;
  processing_status: string;
  bound_seller_target_ids_json: string[];
  bound_buyer_party_ids_json: string[];
  bound_buyer_intent_ids_json: string[];
  bound_recommendation_session_id: string | null;
  created_by: string;
  created_at: string;
  metadata_json: Record<string, unknown> | null;
}

export interface BusinessUpdateCreate {
  raw_text: string;
  input_type?: string;
  bound_seller_target_ids?: string[];
  bound_buyer_party_ids?: string[];
  bound_buyer_intent_ids?: string[];
  metadata_json?: Record<string, unknown>;
}

export interface BusinessUpdateUploadResponse {
  business_update: BusinessUpdate;
  uploaded_attachment_ids: string[];
  ocr_attachment_ids: string[];
  multimodal_image_attachment_ids: string[];
  skipped_ocr_attachment_ids: string[];
  ocr_jobs: Array<Record<string, unknown>>;
  process_job: Record<string, unknown> | null;
}

export interface BusinessUpdateReviewPage {
  business_update: Record<string, unknown>;
  overview: Record<string, unknown>;
  action_groups: Array<Record<string, unknown>>;
  actions: Array<Record<string, unknown>>;
  application_logs: Array<Record<string, unknown>>;
  jobs: Array<Record<string, unknown>>;
  traces: Array<Record<string, unknown>>;
  attachments: Array<Record<string, unknown>>;
  bound_entities: Record<string, unknown>;
  quick_actions: Array<Record<string, unknown>>;
  debug_ref: DebugRef;
}

export interface AttachmentUploadPolicy {
  max_upload_bytes: number;
  max_upload_mb: number;
  max_files_per_business_update: number;
  storage_backend: string;
  object_storage_configured: boolean;
  text_capture_max_bytes: number;
  supported_uploads: {
    text_extensions: string[];
    text_mime_types: string[];
    text_mime_prefixes: string[];
    document_extensions: string[];
    image_mime_types: string[];
    binary_uploads_allowed: boolean;
  };
  pdf_policy: {
    text_detection: {
      sample_page_limit: number;
      min_total_chars_for_text_pdf: number;
    };
    text_pdf: {
      strategy: string;
      ocr_provider_required: boolean;
    };
    scanned_pdf: {
      strategy: string;
      ocr_provider_required: boolean;
      requires_object_storage: boolean;
      doc2x_configured: boolean;
    };
  };
  image_policy: {
    strategy: string;
    auto_ocr: boolean;
    constraints: {
      supported_types: string[];
      max_count_per_business_update: number;
      max_upload_bytes_per_image: number;
      max_upload_mb_per_image: number;
      model_preprocess_max_side_px: number;
      model_preprocess_target_bytes: number;
      evidence_policy: string;
    };
    preprocess: {
      output_mime_type: string;
      max_side_px: number;
      jpeg_quality: number;
      target_bytes: number;
    };
  };
  ocr_policy: {
    provider: string;
    doc2x: {
      configured: boolean;
      model: string;
      upload_timeout_seconds: number;
      poll_interval_seconds: number;
      max_wait_seconds: number;
    };
  };
  upload_form_defaults: {
    visibility: string;
    auto_start_ocr: boolean;
    process_after_ocr: boolean;
    auto_process: boolean;
  };
  user_guidance: string[];
}

export interface TargetAttachmentItem {
  id: string;
  file_name: string;
  file_type: string | null;
  mime_type: string | null;
  file_size: number | null;
  uploaded_by: string | null;
  uploaded_by_name: string | null;
  uploaded_at: string;
  link_type: string | null;
  linked_at: string | null;
  parse_status: string;
  display_status: string;
  parse_readiness: Record<string, unknown>;
  latest_job: Record<string, unknown> | null;
  latest_parsed_document: Record<string, unknown> | null;
  latest_evidence: Record<string, unknown> | null;
  evidence_count: number;
  related_business_updates: Array<Record<string, unknown>>;
  download_route: string;
  delete_route: string;
  debug_ref: DebugRef;
}

export interface TargetAttachmentListResponse {
  seller_target_id: string;
  items: TargetAttachmentItem[];
}

export interface ExtractedAction {
  id: string;
  business_update_id: string;
  action_type: string;
  target_entity_type: string;
  target_entity_id: string | null;
  proposed_changes_json: Record<string, unknown>;
  raw_evidence_text: string | null;
  confidence: string | null;
  review_status: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  applied_at: string | null;
  metadata_json: Record<string, unknown> | null;
  created_at: string;
  task_title?: string;
  task_subtitle?: string | null;
  task_group_key?: string;
  task_group_label?: string;
  task_priority?: 'high' | 'medium' | 'normal' | string;
  target_display_name?: string;
  proposed_field_labels?: string[];
  proposed_field_count?: number;
  review_route?: string;
  debug_ref?: DebugRef;
}

export interface ExtractedActionCreate {
  action_type: string;
  target_entity_type: string;
  target_entity_id: string;
  proposed_changes_json: Record<string, unknown>;
  raw_evidence_text?: string;
  confidence?: number;
  metadata_json?: Record<string, unknown>;
}

export interface UpdateLog {
  id: string;
  entity_type: string;
  entity_id: string;
  field_path: string;
  old_value_json: string | null;
  new_value_json: string | null;
  source_type: string;
  applied_by: string;
  applied_at: string;
  edited_before_apply: boolean;
  can_rollback: boolean;
  rollback_at: string | null;
}

export interface AttachmentItem {
  id: string;
  visibility: string;
  file_name: string;
  file_type: string | null;
  mime_type: string | null;
  file_size: number | null;
  storage_path: string;
  uploaded_by: string | null;
  uploaded_at: string;
  parse_status: string;
  metadata_json: Record<string, unknown>;
  deleted_at: string | null;
  links: Array<{
    id: string;
    attachment_id: string;
    entity_type: string;
    entity_id: string;
    link_type: string | null;
    created_at: string;
    created_by: string | null;
  }>;
}

export interface UpdateBatchAttachment {
  id: string;
  file_name: string;
  mime_type: string | null;
  file_size: number | null;
  uploaded_at: string;
  download_route: string;
}

export interface UpdateBatchChange {
  log_id: string;
  field_path: string;
  old_value: unknown;
  new_value: unknown;
  applied_at: string;
  rollback_at: string | null;
}

export interface UpdateBatch {
  batch_key: string;
  entity_type: 'seller_target' | 'buyer_intent';
  entity_id: string;
  source_type: string;
  batch_category: 'business_update' | 'management_operation' | 'rollback';
  source_id: string | null;
  input_type: string | null;
  input_summary: string | null;
  raw_input: string | null;
  attachments: UpdateBatchAttachment[];
  operator_user_id: string | null;
  operator_name: string;
  submitted_at: string;
  applied_at: string | null;
  status: 'parsing' | 'failed' | 'applied' | 'rolled_back' | string;
  changes: UpdateBatchChange[];
  changed_field_count: number;
  is_latest_effective_batch: boolean;
  can_rollback: boolean;
  rollback_block_reason: string | null;
}

export interface UpdateBatchListResponse {
  items: UpdateBatch[];
  total: number;
  limit: number;
  offset: number;
}

export interface UpdateBatchRollbackResponse {
  status: string;
  rollback_count: number;
  rolled_back_logs: Array<Record<string, unknown>>;
  skipped_logs: Array<Record<string, unknown>>;
}

export interface BuyerSellerRelation {
  id: string;
  buyer_intent_id: string;
  buyer_party_id: string | null;
  seller_target_id: string;
  status: string;
  status_reason: string | null;
  first_recommended_at: string | null;
  last_contact_at: string | null;
  last_event_at: string | null;
  last_event_summary: string | null;
  buyer_intent_name: string | null;
  buyer_name: string | null;
  seller_target_name: string | null;
  created_at: string;
  updated_at: string;
  metadata_json: Record<string, unknown>;
}

export interface RelationEvent {
  id: string;
  relation_id: string;
  buyer_intent_id: string;
  buyer_party_id: string | null;
  seller_target_id: string;
  event_type: string;
  event_time: string;
  title: string | null;
  content: string | null;
  next_step: string | null;
  source_type: string | null;
  source_id: string | null;
  buyer_intent_name: string | null;
  buyer_name: string | null;
  seller_target_name: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface RelationMeta {
  statuses: string[];
  event_types: string[];
}

export interface RelationCreateResult {
  relation: BuyerSellerRelation;
  created: boolean;
}

export interface IndicatorGroupMeta {
  key: string;
  label: string;
  section_code: string | null;
}

export interface IndicatorMeta {
  column: string;
  label: string;
  group: string | null;
  kind: 'text' | 'yuan' | 'ratio' | 'enum' | 'date';
  screening: boolean;
  fold_into: string | null;
}

export interface IndicatorRegistryResponse {
  groups: IndicatorGroupMeta[];
  indicators: IndicatorMeta[];
}

export interface BuyerIntentTargetExclusion {
  id: string;
  buyer_intent_id: string;
  buyer_party_id: string | null;
  seller_target_id: string;
  reason: string | null;
  source_relation_id: string | null;
  source_update_id: string | null;
  source_event_id: string | null;
  active: boolean;
  buyer_intent_name: string | null;
  buyer_name: string | null;
  seller_target_name: string | null;
  created_at: string;
  canceled_at: string | null;
}

export interface BackgroundJob {
  id: string;
  job_type: string;
  status: string;
  priority: number;
  queue_name: string;
  entity_type: string | null;
  entity_id: string | null;
  idempotency_key: string | null;
  payload_json: Record<string, unknown>;
  result_json: Record<string, unknown>;
  error_code: string | null;
  error_message: string | null;
  error_detail_json: Record<string, unknown>;
  attempt_count: number;
  max_attempts: number;
  run_after: string;
  locked_by: string | null;
  locked_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  parent_job_id: string | null;
  correlation_id: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  metadata_json: Record<string, unknown>;
}

export interface DebugRef {
  entity_type: string;
  entity_id: string;
  route: string;
}

export interface DebugCenterOverview {
  failed_job_count: number;
  queued_job_count: number;
  running_job_count: number;
  retry_waiting_job_count: number;
  failed_trace_count: number;
  recent_trace_count: number;
  failed_model_node_test_count: number;
  failed_business_update_count: number;
  recent_business_update_count: number;
  recent_recommendation_session_count: number;
  active_job_count: number;
  health_level: 'ok' | 'warning' | 'error' | string;
  mode: string;
  generated_at: string;
  [key: string]: string | number;
}

export interface DebugCenterJob {
  id: string;
  title: string;
  job_type: string | null;
  status: string | null;
  queue_name: string | null;
  priority: number | null;
  entity_type: string | null;
  entity_id: string | null;
  error_code: string | null;
  error_message: string | null;
  attempt_count: number | null;
  max_attempts: number | null;
  run_after: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  debug_ref: DebugRef;
  related_entity_ref: DebugRef | null;
  node_id?: string | null;
  node_name?: string | null;
  node_type?: string | null;
  model_name?: string | null;
  provider_name?: string | null;
  provider_type?: string | null;
  node_debug_ref?: DebugRef | null;
}

export interface DebugCenterTrace {
  id: string;
  title: string;
  trace_type: string | null;
  node_name: string | null;
  status: string | null;
  provider_name: string | null;
  model_name: string | null;
  prompt_version: string | null;
  entity_type: string | null;
  entity_id: string | null;
  job_id: string | null;
  error_code: string | null;
  error_message: string | null;
  raw_output_preview: string | null;
  latency_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  started_at: string | null;
  finished_at: string | null;
  debug_ref: DebugRef | null;
  related_entity_ref: DebugRef | null;
}

export interface DebugCenterBusinessUpdate {
  id: string;
  title: string;
  raw_text_preview: string | null;
  input_type: string | null;
  processing_status: string | null;
  action_count: number;
  pending_action_count: number;
  application_log_count: number;
  job_count: number;
  failed_job_count: number;
  trace_count: number;
  created_at: string | null;
  review_route: string;
  debug_ref: DebugRef;
}

export interface DebugCenterRecommendationSession {
  id: string;
  title: string;
  mode: string | null;
  status: string | null;
  selected_count: number;
  report_count: number;
  job_count: number;
  failed_job_count: number;
  trace_count: number;
  buyer_intent_id: string | null;
  buyer_intent_name: string | null;
  buyer_party_id: string | null;
  buyer_name: string | null;
  seller_target_id: string | null;
  seller_target_name: string | null;
  created_at: string | null;
  updated_at: string | null;
  status_route: string;
  debug_ref: DebugRef;
}

export interface DebugCenterQuickAction {
  key: string;
  label: string;
  route: string;
  action: string;
  badge_count: number | null;
}

export interface DebugCenterData {
  overview: DebugCenterOverview;
  failed_jobs: DebugCenterJob[];
  running_jobs: DebugCenterJob[];
  recent_traces: DebugCenterTrace[];
  failed_traces: DebugCenterTrace[];
  recent_business_updates: DebugCenterBusinessUpdate[];
  recent_recommendation_sessions: DebugCenterRecommendationSession[];
  model_node_test_failures: DebugCenterJob[];
  quick_actions: DebugCenterQuickAction[];
}

export interface DebugEntity {
  entity_type: string;
  entity_id: string;
  summary: Record<string, unknown>;
  payload: Record<string, unknown>;
}

export interface BackgroundJobCompact {
  id: string;
  job_type: string;
  status: string;
  priority: number | null;
  queue_name: string | null;
  entity_type: string | null;
  entity_id: string | null;
  run_after: string | null;
  created_at: string | null;
  updated_at: string | null;
  error_message: string | null;
  debug_ref: DebugRef;
}

export interface BackgroundJobRecommendedAction {
  key: string;
  label: string;
  route: string | null;
  method?: 'GET' | 'POST' | string;
}

export interface BackgroundJobFailure extends BackgroundJobCompact {
  error_code: string | null;
  failure_category: string;
  failure_summary: string;
  attempt_count: number | null;
  max_attempts: number | null;
  related_entity_ref: DebugRef | null;
  ignored: boolean;
  ignore_reason: string | null;
  ignored_at: string | null;
  archived: boolean;
  archive_reason: string | null;
  archived_at: string | null;
  is_test_data: boolean;
  test_data_label: string | null;
  test_data_reason: string | null;
  can_retry: boolean;
  retry_route: string | null;
  retry_preview_route: string | null;
  ignore_route: string | null;
  unignore_route: string | null;
  archive_route: string | null;
  unarchive_route: string | null;
  mark_test_data_route: string | null;
  unmark_test_data_route: string | null;
  recommended_actions: BackgroundJobRecommendedAction[];
}

export interface QueueSummaryItem {
  queue_name: string;
  health_status: 'idle' | 'active' | 'has_failures' | string;
  active_count: number;
  counts: {
    total: number;
    queued: number;
    retry_waiting: number;
    running: number;
    failed: number;
    ignored_failed: number;
    succeeded: number;
    cancelled: number;
    recent_created: number;
    recent_succeeded: number;
    recent_failed: number;
  };
  lookback_hours: number;
  next_run_after: string | null;
  last_updated_at: string | null;
  next_job: BackgroundJobCompact | null;
  latest_failed_job: BackgroundJobCompact | null;
  debug_ref: DebugRef;
}

export interface QueueSummary {
  generated_at: string;
  totals: {
    queue_count: number;
    active_queue_count: number;
    failed_queue_count: number;
    active_job_count: number;
    failed_job_count: number;
    ignored_failed_job_count: number;
    queued_job_count: number;
    running_job_count: number;
    retry_waiting_job_count: number;
    [key: string]: number;
  };
  queues: QueueSummaryItem[];
  debug_ref: Record<string, unknown>;
}

export interface FailureSummaryGroupItem {
  failed_count: number;
  latest_failed_at: string | null;
  list_route: string;
  queue_name?: string;
  job_type?: string;
}

export interface FailureSummary {
  generated_at: string;
  lookback_hours: number;
  include_ignored: boolean;
  include_archived: boolean;
  include_test_data: boolean;
  totals: {
    failed_job_count: number;
    failed_queue_count: number;
    failed_job_type_count: number;
    recent_failure_count: number;
    [key: string]: number;
  };
  by_queue: FailureSummaryGroupItem[];
  by_job_type: FailureSummaryGroupItem[];
  recent_failures: BackgroundJobFailure[];
  debug_ref: Record<string, unknown>;
}

export interface BackgroundJobRetryPreview {
  job: BackgroundJobFailure & {
    payload_json: Record<string, unknown>;
    metadata_json: Record<string, unknown>;
    result_json: Record<string, unknown>;
    error_detail_json: Record<string, unknown>;
  };
  retry: {
    eligible: boolean;
    route: string | null;
    method: 'POST' | string | null;
    queue_name: string | null;
    will_reset_attempt_count_to: number | null;
    will_run_after: 'now' | string | null;
  };
  related: {
    entity_ref: DebugRef | null;
    same_entity_job_count: number;
    active_same_entity_job_count: number;
    trace_count: number;
    business_update?: {
      id: string;
      processing_status: string;
      created_at: string;
      metadata_json: Record<string, unknown> | null;
      action_count: number;
      application_log_count: number;
    } | null;
    [key: string]: unknown;
  };
  effects: Array<{
    key: string;
    label: string;
    description: string;
  }>;
  warnings: Array<{
    key: string;
    severity: 'info' | 'warning' | 'blocker' | string;
    message: string;
  }>;
  debug_ref: DebugRef;
}

export interface TaskCenterJob {
  id: string;
  job_type: string;
  task_display_name: string;
  status: string;
  priority: number | null;
  queue_name: string | null;
  entity_type: string | null;
  entity_id: string | null;
  related_object_name: string;
  related_object_route: string | null;
  initiated_by_user_id: string | null;
  initiated_by_name: string;
  initiated_by_username: string | null;
  run_after: string | null;
  created_at: string | null;
  updated_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
  error_message: string | null;
  failure_category: string;
  failure_summary: string;
  attempt_count: number | null;
  max_attempts: number | null;
  ignored: boolean;
  ignore_reason: string | null;
  ignored_at: string | null;
  archived: boolean;
  archive_reason: string | null;
  archived_at: string | null;
  is_test_data: boolean;
  test_data_label: string | null;
  can_retry: boolean;
  retry_route: string | null;
  ignore_route: string | null;
  unignore_route: string | null;
  debug_ref: DebugRef;
  related_entity_ref: DebugRef | null;
}

export interface TaskCenterData {
  generated_at: string;
  status_group: string;
  lookback_hours: number;
  limit: number;
  offset: number;
  totals: {
    total_count: number;
    needs_attention_count: number;
    active_count: number;
    ignored_count: number;
    archived_count: number;
    failed_count: number;
    [key: string]: number;
  };
  tasks: TaskCenterJob[];
}

export interface AiTrace {
  id: string;
  trace_type: string;
  node_name: string;
  job_id: string | null;
  correlation_id: string | null;
  entity_type: string | null;
  entity_id: string | null;
  provider_name: string | null;
  model_name: string | null;
  prompt_version: string | null;
  status: string;
  input_json: Record<string, unknown>;
  prompt_messages_json: unknown[];
  raw_output_text: string | null;
  parsed_output_json: Record<string, unknown> | null;
  schema_validation_json: Record<string, unknown>;
  retrieval_output_json: Record<string, unknown>;
  tool_calls_json: unknown[];
  error_code: string | null;
  error_message: string | null;
  latency_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  cost_json: Record<string, unknown>;
  started_at: string;
  finished_at: string | null;
  metadata_json: Record<string, unknown>;
}

export interface BusinessUpdateDebugBundle {
  business_update: BusinessUpdate;
  jobs: BackgroundJob[];
  traces: AiTrace[];
  actions: ExtractedAction[];
  application_logs: UpdateLog[];
}

export interface RecommendationSessionDebugBundle {
  session: Record<string, unknown>;
  jobs: Record<string, unknown>[];
  traces: Record<string, unknown>[];
  messages: Record<string, unknown>[];
  selected_items: Record<string, unknown>[];
  reports: Record<string, unknown>[];
  relations: Record<string, unknown>[];
  relation_events: Record<string, unknown>[];
  debug: Record<string, unknown>;
}

export interface RecommendationCandidate {
  rank: number;
  mode: 'buyer_to_target' | 'target_to_buyer';
  seller_target_id: string | null;
  seller_target_name: string | null;
  buyer_intent_id: string | null;
  buyer_intent_name: string | null;
  buyer_party_id: string | null;
  buyer_name: string | null;
  score: number;
  recommendation_level: 'strong' | 'recommended' | 'possible' | 'weak';
  match_summary: string;
  gap_summary: string | null;
  risk_summary: string | null;
  evidence_json: Record<string, unknown>;
  /** 三态：compatible / possible / conflict（conflict 不会出现在结果里） */
  match_state?: string | null;
  known_count?: number;
  /** 本次意向引用的维度里，该候选尚缺的部分——调研任务的输入 */
  missing_dimensions?: string[];
  best_scenario_id?: string | null;
  best_scenario_label?: string | null;
  matched_scenarios?: string[];
  matched_scenario_labels?: string[];
  deep_eval?: {
    grade: string;
    reason?: string | null;
    risks?: string | null;
    info_gaps?: string | null;
    model?: string | null;
  } | null;
  /** 该候选与本意向已有的关系（已在推进）。 */
  relation_id?: string | null;
  relation_status?: string | null;
  /** 对手方正与其他买家深入推进（尽调及以后），标注但不透露对方。 */
  deep_progress_elsewhere?: boolean;
}

export interface RecommendationConditionAction {
  op:
    | 'remove_field'
    | 'disable_field'
    | 'remove_exclusion'
    | 'remove_preference'
    | 'clear_all'
    | 'disable_scenario'
    | 'enable_scenario';
  field?: string;
  value?: string;
  scenario_id?: string;
  label?: string;
}

export interface RecommendationConditionOverrides {
  fields: Record<string, unknown>;
  removed_fields: string[];
  extra_excluded_industries: string[];
  semantic_preferences: string[];
  disabled_scenarios?: string[];
}

export interface RecommendationConversation {
  route: 'refilter' | 're_evaluate' | 'display' | 'question' | 'noop';
  parsed_ops: Array<{ op: string; field: string; value: unknown }>;
  new_semantic_preferences: string[];
  display_ops: Array<{ type: 'only_grade' | 'top_n'; value: string | number }>;
  question: string | null;
  parser_status: 'ok' | 'fallback' | null;
  applied_conditions: Record<string, unknown>;
  system_reply: string;
}

export interface RecommendationCandidateRequest {
  mode: 'buyer_to_target' | 'target_to_buyer';
  buyer_intent_id?: string;
  seller_target_id?: string;
  limit?: number;
  create_session?: boolean;
  enable_rerank?: boolean;
  user_message?: string;
  session_id?: string;
  condition_actions?: RecommendationConditionAction[];
}

export interface RecommendationSessionSummary {
  session: { id: string; mode: 'buyer_to_target' | 'target_to_buyer'; updated_at?: string; [key: string]: unknown };
  display: {
    title: string | null;
    subtitle: string | null;
    mode_label: string;
    [key: string]: unknown;
  };
  candidate_counts: { initial: number; reranked: number; latest: number };
  candidate_source: string;
  rerank_status: { status?: string; [key: string]: unknown };
  report_status: { status?: string; report_count?: number; [key: string]: unknown };
  selected_status: { active_count?: number; [key: string]: unknown };
  activity: { last_activity_at?: string | null; [key: string]: unknown };
}

export interface RecommendationPage {
  recent_sessions: RecommendationSessionSummary[];
  running_sessions: RecommendationSessionSummary[];
  overview: Record<string, unknown>;
  quick_actions: Array<Record<string, unknown>>;
  polling_hint: Record<string, unknown>;
}

export interface RecommendationRerankJob {
  job_id: string;
  job_status: string;
  queue_name: string;
  candidate_count: number;
  source: string;
}

export interface RecommendationFunnel {
  scenario_count?: number;
  eligible_by_scenario?: Record<string, number>;
  scan_count: number;
  excluded_count: number;
  conflict_count: number;
  eligible_count: number;
  deep_eval_count: number;
  display_count: number;
}

export interface RecommendationScenarioRef {
  id: string;
  label: string;
}

export interface BuyerIntentScenario {
  id: string;
  buyer_intent_id: string;
  label: string;
  sort_order: number;
  active: boolean;
  fields_json: Record<string, unknown>;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface RecommendationCandidateResponse {
  session_id: string | null;
  mode: 'buyer_to_target' | 'target_to_buyer';
  candidates: RecommendationCandidate[];
  conversation?: RecommendationConversation;
  funnel?: RecommendationFunnel | null;
  scenarios?: RecommendationScenarioRef[];
  debug: Record<string, unknown>;
}

export interface RecommendationSession {
  id: string;
  mode: 'buyer_to_target' | 'target_to_buyer';
  buyer_intent_id: string | null;
  buyer_party_id: string | null;
  seller_target_id: string | null;
  status: string;
  selected_count: number;
  report_count: number;
  anonymous_input_snapshot: string | null;
  initial_condition_snapshot_json: Record<string, unknown>;
  latest_condition_snapshot_json: Record<string, unknown>;
  condition_overrides_json?: RecommendationConditionOverrides | Record<string, never>;
  created_at: string;
  updated_at: string;
  metadata_json: Record<string, unknown>;
}

export interface RecommendationMessageCreate {
  role?: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  content_type?: 'text' | 'json' | 'markdown';
  metadata_json?: Record<string, unknown>;
}

export interface RecommendationMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  content_type: 'text' | 'json' | 'markdown';
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface RecommendationSelectedItemCreate {
  mode: 'buyer_to_target' | 'target_to_buyer';
  seller_target_id?: string | null;
  buyer_intent_id?: string | null;
  buyer_party_id?: string | null;
  rank_at_selection?: number;
  recommendation_level?: 'strong' | 'recommended' | 'possible' | 'weak';
  match_summary?: string | null;
  risk_summary?: string | null;
  gap_summary?: string | null;
  reason_snapshot?: string | null;
  evidence_snapshot_json?: Record<string, unknown>;
  metadata_json?: Record<string, unknown>;
}

export interface RecommendationSelectedItem {
  id: string;
  session_id: string;
  mode: 'buyer_to_target' | 'target_to_buyer';
  seller_target_id: string | null;
  seller_target_name: string | null;
  buyer_intent_id: string | null;
  buyer_intent_name: string | null;
  buyer_party_id: string | null;
  buyer_name: string | null;
  rank_at_selection: number | null;
  recommendation_level: 'strong' | 'recommended' | 'possible' | 'weak' | null;
  match_summary: string | null;
  risk_summary: string | null;
  gap_summary: string | null;
  reason_snapshot: string | null;
  evidence_snapshot_json: Record<string, unknown>;
  selected_at: string;
  canceled_at: string | null;
  metadata_json: Record<string, unknown>;
}

export interface RecommendationReportCreate {
  report_type?: 'buyer_facing_target_report' | 'internal_buyer_list';
  selected_item_ids?: string[];
  title?: string | null;
  metadata_json?: Record<string, unknown>;
}

export interface RecommendationReport {
  id: string;
  session_id: string;
  report_type: 'buyer_facing_target_report' | 'internal_buyer_list';
  selected_item_ids_json: string[];
  title: string | null;
  markdown_content: string | null;
  file_path: string | null;
  file_format: 'markdown' | 'docx' | 'pdf' | null;
  status: 'generating' | 'generated' | 'failed' | 'archived';
  generated_by_model: string | null;
  prompt_version: string | null;
  created_at: string;
  metadata_json: Record<string, unknown>;
}

export interface RecommendationReportJob {
  report: RecommendationReport;
  job_id: string;
  job_status: string;
  queue_name: string;
}

export interface RecommendationSessionBundle {
  session: RecommendationSession;
  messages: RecommendationMessage[];
  initial_candidates?: RecommendationCandidate[];
  reranked_candidates?: RecommendationCandidate[];
  latest_candidates?: RecommendationCandidate[];
  candidate_source?: string;
  rerank_status?: {
    requested: boolean;
    status: string;
    job_id: string | null;
    [key: string]: unknown;
  };
  selected_items: RecommendationSelectedItem[];
  reports: RecommendationReport[];
  debug: {
    selected_count: number;
    canceled_selected_count: number;
    message_count: number;
    report_count: number;
    engine_hint: string;
  };
}

export interface GlobalSearchItem {
  entity_type: 'seller_target' | 'buyer_party' | 'buyer_intent' | string;
  entity_id: string;
  title: string;
  subtitle: string | null;
  snippet: string | null;
  route: string;
  updated_at: string | null;
  match_reason: string | null;
  metadata: Record<string, unknown>;
}

export interface GlobalSearchGroup {
  key: string;
  label: string;
  count: number;
  items: GlobalSearchItem[];
}

export interface GlobalSearchResponse {
  query: string;
  groups: GlobalSearchGroup[];
  total_count: number;
}

export interface ProfileSection {
  id: string;
  entity_type: 'seller_target' | 'buyer_intent';
  entity_id: string;
  section_code: string;
  section_label: string;
  info_status: 'filled' | 'not_found' | 'not_applicable';
  content_text: string | null;
  source_type: string | null;
  source_url: string | null;
  source_title: string | null;
  source_excerpt: string | null;
  as_of_date: string | null;
  confidence: number | null;
  review_status: string;
  updated_at: string;
}

export interface ProfileSectionCatalogEntry {
  code: string;
  label: string;
}

export interface ProfileSectionsResponse {
  entity_type: string;
  entity_id: string;
  sections: ProfileSection[];
  coverage: { filled_sections: string[]; missing_sections: string[] };
  section_catalog: ProfileSectionCatalogEntry[];
}

export interface ProfileSectionWrite {
  section_code: string;
  info_status?: 'filled' | 'not_found' | 'not_applicable';
  content_text?: string | null;
  source_type?: string | null;
  source_url?: string | null;
  as_of_date?: string | null;
}

export interface ResearchJob {
  job_id: string;
  seller_target_id: string;
  status: string;
  queue_name: string;
  reused_existing: boolean;
}

export interface ResearchBatchResponse {
  jobs: ResearchJob[];
  queued_count: number;
  reused_count: number;
}

export interface ResearchProposal {
  id: string;
  entity_type: 'seller_target';
  entity_id: string;
  job_id: string | null;
  proposal_kind: 'profile_section' | 'structured_fact';
  section_code: string | null;
  section_label: string | null;
  field_path: string | null;
  proposed_value_json: Record<string, unknown>;
  current_value_json: Record<string, unknown>;
  conflict_kind: 'consistent' | 'supplement' | 'temporal_update' | 'same_period_conflict';
  period_label: string | null;
  as_of_date: string | null;
  source_type: string | null;
  source_url: string | null;
  source_title: string | null;
  source_excerpt: string | null;
  anchor_matches_json: Array<{ kind: string; value: string }>;
  confidence: number | null;
  review_status: string;
  reviewed_at: string | null;
  created_at: string;
}

export interface SellerResearchStatus {
  seller_target_id: string;
  last_research_at: string | null;
  research_last_outcome: 'found' | 'no_public_information' | 'failed' | null;
  latest_job: Pick<BackgroundJob, 'id' | 'status' | 'result_json' | 'error_code' | 'error_message' | 'created_at' | 'finished_at'> | null;
}

export interface SearchProviderConfig {
  id: string;
  provider_name: string;
  adapter: string;
  base_url: string | null;
  secret_mode: 'env' | 'direct';
  api_key_secret_ref: string | null;
  secret_configured: boolean;
  key_display: string;
  extra_config_json: Record<string, unknown>;
  is_active: boolean;
  is_default: boolean;
  updated_at: string;
}

export interface SearchConfigOverview {
  providers: SearchProviderConfig[];
  available_adapters: string[];
  direct_key_encryption_configured: boolean;
  security_note: string;
}

export interface SearchProviderTestResult {
  status: 'succeeded' | 'failed';
  error_message: string | null;
  result_count: number;
  sample_titles: string[];
}
