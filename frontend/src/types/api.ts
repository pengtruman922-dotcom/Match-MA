export interface SellerTarget {
  id: string;
  target_name: string;
  target_type: string | null;
  recommendation_status: string;
  information_status: string;
  industry_primary: string | null;
  industry_secondary: string | null;
  headquarter_province: string | null;
  headquarter_city: string | null;
  listed_status: string | null;
  current_revenue_yuan: string | null;
  current_net_profit_yuan: string | null;
  valuation_yuan: string | null;
  asking_price_yuan: string | null;
  pe_ratio: string | null;
  is_for_sale: string | null;
  can_control: string | null;
  can_consolidate: string | null;
  business_summary: string | null;
  transaction_summary: string | null;
  risk_summary: string | null;
  created_at: string;
  updated_at: string;
}

export interface SellerTargetCreate {
  target_name: string;
  target_type?: string;
  industry_primary?: string;
  industry_secondary?: string;
  headquarter_province?: string;
  headquarter_city?: string;
  listed_status?: string;
  current_revenue_yuan?: number;
  current_net_profit_yuan?: number;
  valuation_yuan?: number;
  pe_ratio?: number;
  is_for_sale?: string;
  can_control?: string;
  can_consolidate?: string;
  business_summary?: string;
}

export interface SellerTargetUpdate {
  target_name?: string;
  target_type?: string;
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
  asking_price_yuan?: number;
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
  max_pe: string | null;
  max_valuation_yuan: string | null;
  requires_control: string | null;
  requires_consolidation: string | null;
  accepts_minority_investment: string | null;
  preferred_listed_status: string | null;
  transaction_type: string | null;
  negative_summary: string | null;
  preference_summary: string | null;
  unknown_summary: string | null;
  created_at: string;
  updated_at: string;
}

export interface BuyerIntentCreate {
  intent_name: string;
  buyer_party_id?: string;
  contact_name?: string;
  raw_requirement_text?: string;
  industry_primary?: string;
  region_scope_summary?: string;
  min_net_profit_yuan?: number;
  max_pe?: number;
  requires_consolidation?: string;
  preferred_listed_status?: string;
  negative_summary?: string;
}

export interface BuyerIntentUpdate {
  intent_name?: string;
  status?: string;
  contact_name?: string;
  raw_requirement_text?: string;
  industry_primary?: string;
  region_scope_summary?: string;
  min_net_profit_yuan?: number;
  max_pe?: number;
  requires_consolidation?: string;
  preferred_listed_status?: string;
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

export interface WorkbenchData {
  groups: WorkbenchActionGroup[];
  recent_updates: BusinessUpdate[];
  recent_relations: BuyerSellerRelation[];
  overview: {
    pending_review_count: number;
    recent_update_count: number;
    failed_job_count: number;
    running_job_count: number;
    active_relation_count: number;
  };
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
