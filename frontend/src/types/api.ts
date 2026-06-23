export interface SellerTarget {
  id: string;
  target_name: string;
  target_type: string | null;
  target_subject_name: string | null;
  recommendation_status: string;
  information_status: string;
  industry_primary: string | null;
  industry_secondary: string | null;
  registered_province: string | null;
  registered_city: string | null;
  headquarter_province: string | null;
  headquarter_city: string | null;
  raw_region_text: string | null;
  region_granularity: string | null;
  listed_status: string | null;
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
  created_at: string;
  updated_at: string;
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

export interface SellerTargetCreate {
  target_name: string;
  target_type?: string;
  target_subject_name?: string;
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
  status: string;
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

export interface BuyerBulkDeleteResponse {
  status: string;
  deleted_count: number;
  deleted_ids: string[];
  skipped_ids: string[];
}

export interface BuyerPartyCreate {
  buyer_name: string;
  legal_name?: string;
  buyer_type?: string;
  listed_status?: string;
  region_province?: string;
  region_city?: string;
  main_business?: string;
  profile_summary?: string;
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
  region_scope_summary: string | null;
  min_revenue_yuan: string | null;
  min_net_profit_yuan: string | null;
  min_total_profit_yuan: string | null;
  max_pe: string | null;
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
  transaction_type: string | null;
  transaction_types_json: string[] | Record<string, unknown> | null;
  premium_tolerance_summary: string | null;
  max_premium_rate: string | null;
  max_debt_ratio: string | null;
  debt_ratio_requirement_summary: string | null;
  major_risk_tolerance_summary: string | null;
  buyer_industry_advantage_summary: string | null;
  negative_summary: string | null;
  preference_summary: string | null;
  unknown_summary: string | null;
  created_at: string;
  updated_at: string;
}

export interface BuyerIntentListResponse {
  items: BuyerIntent[];
  total: number;
  limit: number;
  offset: number;
}

export type BuyerIntentSearchField = 'intent_name' | 'buyer_name' | 'raw_requirement_text' | 'intent_summary';

export interface BuyerIntentFilterOptions {
  industries: BuyerFilterOption[];
  regions: BuyerFilterOption[];
  statuses: BuyerFilterOption[];
  listed_statuses: BuyerFilterOption[];
  consolidation_requirements: BuyerFilterOption[];
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
  region_scope_summary?: string;
  min_revenue_yuan?: number;
  min_net_profit_yuan?: number;
  min_total_profit_yuan?: number;
  max_pe?: number;
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

export interface BuyerIntentUpdate {
  intent_name?: string;
  status?: string;
  contact_name?: string;
  raw_requirement_text?: string;
  industry_primary?: string;
  region_scope_summary?: string;
  min_revenue_yuan?: number;
  min_net_profit_yuan?: number;
  min_total_profit_yuan?: number;
  max_pe?: number;
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

export interface WorkbenchActionGroup {
  key: string;
  label: string;
  count: number;
  items: ExtractedAction[];
}

export interface WorkbenchOverview {
  pending_review_count: number;
  recent_update_count: number;
  failed_job_count: number;
  running_job_count: number;
  active_relation_count: number;
  weekly_new_target_count?: number;
  weekly_new_buyer_intent_count?: number;
  weekly_updated_target_count?: number;
  weekly_business_update_count?: number;
  auto_applied_review_count?: number;
  exception_count?: number;
  mode?: string;
  [key: string]: unknown;
}

export interface WorkbenchActivity {
  activity_type: string;
  entity_id: string;
  status: string;
  activity_label?: string;
  object_name?: string | null;
  summary?: string | null;
  title?: string;
  subtitle?: string | null;
  happened_at: string | null;
  route?: string | null;
}

export interface WorkbenchData {
  groups: WorkbenchActionGroup[];
  recent_updates: BusinessUpdate[];
  recent_relations: BuyerSellerRelation[];
  overview: WorkbenchOverview;
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
}

export interface RecommendationCandidateRequest {
  mode: 'buyer_to_target' | 'target_to_buyer';
  buyer_intent_id?: string;
  seller_target_id?: string;
  limit?: number;
  create_session?: boolean;
  enable_rerank?: boolean;
  user_message?: string;
}

export interface RecommendationCandidateResponse {
  session_id: string | null;
  mode: 'buyer_to_target' | 'target_to_buyer';
  candidates: RecommendationCandidate[];
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

export interface WorkbenchTaskBoardData {
  groups: WorkbenchActionGroup[];
  auto_applied_recent: ExtractedAction[];
  exception_items: Record<string, unknown>[];
  recent_activity: WorkbenchActivity[];
  quick_actions: Record<string, unknown>[];
  overview: WorkbenchOverview;
  queue_summary: QueueSummary;
  failure_summary: FailureSummary;
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
