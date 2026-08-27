/**
 * 买家条件的规则档位，只有两态：必须（初筛硬门槛）和优先（只影响排序）。
 * 对应 backend/app/services/recommendation_conditions.py 的 CONDITION_EFFECTS。
 *
 * 曾经有第三个取值 deep_eval，2026-08-02 随买家需求页重构下线（迁移 012 已洗掉
 * 库里的残值）。当时这个联合类型在本文件里被抄了 6 遍、组件里还有第 7 遍，
 * 只改了组件那份，CI 的 typecheck 因此红了两个提交。现在只留这一份。
 */
export type ConditionEffect = 'required' | 'preferred';

export interface SellerTarget {
  id: string;
  target_name: string;
  target_type: string | null;
  target_subject_name: string | null;
  // 级别是推荐初筛的唯一闸门（E 不进）；lifecycle_status 降级成 E 的细分原因。
  target_grade: string;
  lifecycle_status: string;
  information_status: string;
  ai_processing_state: 'parsing' | 'research_queued' | 'researching' | 'research_mapping' | 'parse_failed' | 'research_failed' | 'completed' | 'never';
  ai_processing_detail: string;
  pending_research_conflict_count?: number;
  research_job_type?: 'seller_target_research' | 'seller_target_research_map' | null;
  research_job_status?: 'queued' | 'running' | 'retry_waiting' | null;
  // L1/L2 是唯一展示与筛选行业维度；原始表述保存在更新/证据审计中。
  industry_l1: string | null;
  industry_l2: string | null;
  industry_pairs_json: Array<{ l1: string; l2?: string }>;
  main_products_text: string | null;
  location_province: string | null;
  location_city: string | null;
  location_district: string | null;
  listed_status: string | null;
  stock_code: string | null;
  listing_market_region: string | null;
  market_cap_yuan: string | null;
  current_revenue_yuan: string | null;
  current_net_profit_yuan: string | null;
  current_total_profit_yuan: string | null;
  current_assets_yuan: string | null;
  current_debt_ratio: string | null;
  current_operating_cash_flow_yuan: string | null;
  financial_period_label: string | null;
  financial_period_end_date: string | null;
  profitability_status: string | null;
  cash_flow_status: string | null;
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
  accepts_relocation: string | null;
  accepts_return_investment: string | null;
  management_retention_possible: string | null;
  acceptable_transaction_structures_json: string[];
  business_summary: string | null;
  transaction_summary: string | null;
  // [] 未核查 / ['none'] 已核查无风险 / 其余已核查有风险，三种状态一个字段表达。
  major_risk_flags_json: string[];
  risk_summary: string | null;
  gap_summary: string | null;
  owner_user_id?: string | null;
  owner_name?: string | null;
  created_at: string;
  updated_at: string;
  last_research_at?: string | null;
  last_parse_at?: string | null;
  research_last_outcome?: 'found' | 'found_but_rejected' | 'no_public_information' | 'failed' | null;
}

export interface SellerTargetListResponse {
  items: SellerTarget[];
  total: number;
  limit: number;
  offset: number;
}

export type SellerTargetSearchField = 'target_name' | 'target_subject_name' | 'business_summary' | 'industry';

export interface SellerTargetFilterOption {
  value: string;
  label: string;
  count: number;
}

/** A cascader level. `count` annotates a dictionary entry rather than defining
 * it: the picker renders the full industry taxonomy / area dictionary, and
 * these counts only say how many targets sit behind each choice. */
export interface SellerTargetCountedOption {
  value: string;
  count: number;
  children?: SellerTargetCountedOption[];
}

export interface SellerTargetFilterOptions {
  industries: SellerTargetCountedOption[];
  regions: SellerTargetCountedOption[];
  statuses: SellerTargetFilterOption[];
  owners?: SellerTargetFilterOption[];
}

export interface SellerTargetDedupCheck {
  query: string;
  matches: string[];
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
  // 创建只收 A-D，默认 C；刚建的标的就已售出/已停售没有意义。
  target_grade?: string;
  information_status?: string;
  industry_l1?: string;
  industry_l2?: string;
  industry_pairs_json?: Array<{ l1: string; l2?: string }>;
  location_province?: string;
  location_city?: string;
  location_district?: string;
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
  target_grade?: string;
  lifecycle_status?: string;
  industry_l1?: string;
  industry_l2?: string;
  industry_pairs_json?: Array<{ l1: string; l2?: string }>;
  location_province?: string;
  location_city?: string;
  location_district?: string;
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
  aliases_json: string[];
  /** 基本信息 */
  location_province: string | null;
  location_city: string | null;
  location_district: string | null;
  /** not null default 'unknown'：unknown 不是 null，判断「有没有值」时两者等价。 */
  ownership_type: string;
  listed_status: string;
  stock_code: string | null;
  listing_exchange: string | null;
  contact_name: string | null;
  contact_info_json: Record<string, unknown>;
  our_contact_name: string | null;
  /** 业务信息：产业协同度这一维的全部依据。 */
  business_tags_json: string[];
  business_summary: string | null;
  /** 财务信息。市值日期是真日期，估值时点是中文标签（「2025年一季度」）。 */
  market_cap_yuan: string | number | null;
  market_cap_as_of: string | null;
  valuation_yuan: string | number | null;
  valuation_date: string | null;
  current_revenue_yuan: string | number | null;
  current_operating_cash_flow_yuan: string | number | null;
  financial_period_label: string | null;
  /** 风险或其他可能影响并购的重要信息，进推荐上下文。 */
  supplementary_summary: string | null;
  /** 运营备注，不进任何推荐上下文。与 supplementary_summary 不要合并。 */
  notes: string | null;
  status: string;
  owner_user_id?: string | null;
  owner_name?: string | null;
  created_at: string;
  updated_at: string;
}

export interface BuyerPartyMaterialAttachment {
  attachment_id: string;
  file_name: string;
  file_type: string | null;
  file_size: number | null;
  /** auto_ocr | multimodal_image_only | skip_ocr —— 图片不进 OCR，直读多模态。 */
  ocr_policy: string;
  is_image: boolean;
  ocr_job_id: string | null;
}

export interface BuyerPartyMaterialUploadResponse {
  buyer_party_id: string;
  attachments: BuyerPartyMaterialAttachment[];
  attachment_ids: string[];
  image_attachment_ids: string[];
  image_constraints: Record<string, unknown>;
}

export type BuyerPartyIngestStage =
  | 'attachment_extraction'
  | 'parsing'
  | 'researching'
  | 'normalizing'
  | 'completed';

export type BuyerPartyIngestStageStatus =
  | 'not_started'
  | 'queued'
  | 'processing'
  | 'succeeded'
  | 'failed'
  | 'skipped';

export interface BuyerPartyIngestStageState {
  status: BuyerPartyIngestStageStatus;
  job_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  error_code?: string | null;
  error_message?: string | null;
}

/** 三个 job 派生出来的一条进度。后端不存状态列，所以这里没有「僵死态」。 */
export interface BuyerPartyIngestState {
  buyer_party_id: string;
  correlation_id: string | null;
  overall_status: 'not_started' | 'processing' | 'succeeded' | 'failed';
  current_stage: BuyerPartyIngestStage | null;
  status_label: string;
  stage_label: string | null;
  stages: Record<'parse' | 'research' | 'normalize', BuyerPartyIngestStageState>;
  mode: 'fill' | 'refresh';
  research_enabled: boolean;
  research_outcome: string | null;
  research_outcome_label: string | null;
  information_gaps: Array<{ field?: string; reason?: string }>;
  /** 图片上限 5 张，超出的被静默截断且不报错 —— 所以要一路带回界面。 */
  skipped_images: Array<{ attachment_id?: string; file_name?: string; reason?: string }>;
  material_text_truncated: boolean;
  waiting_attachment_ids: string[];
  auto_accepted_count: number | null;
  pending_review_count: number | null;
  apply_errors: string[];
  /** 单来源时收口不调模型：没有可调和的冲突，再翻译一次只会多一次改写机会。 */
  normalizer_invoked: boolean | null;
  /** 这一轮到底写出了几条（自动采纳 + 待复核）。0 条时状态文案不会说「已补全」。 */
  written_count: number;
  pending_proposal_count: number;
  stale_financial_fields: string[];
  latest_job_id: string | null;
  error_code: string | null;
  error_message: string | null;
  recoverable: boolean;
  started_at: string | null;
  finished_at: string | null;
}

export interface BuyerPartyIngestStatus {
  buyer_party_id: string;
  state: BuyerPartyIngestState;
  nodes_ready: { parser: boolean; researcher: boolean; normalizer: boolean };
  search_provider_ready: boolean;
}

export interface BuyerPartyIngestJob {
  job_id: string;
  job_type: string;
  status: string;
  queue_name: string;
  buyer_party_id: string;
  correlation_id: string;
  reused_existing: boolean;
}

export interface BuyerPartyBatchParseResponse {
  jobs: BuyerPartyIngestJob[];
  queued_count: number;
  reused_count: number;
}

export interface BuyerPartyListResponse {
  items: BuyerParty[];
  total: number;
  limit: number;
  offset: number;
}

export type BuyerPartySearchField = 'buyer_name' | 'alias' | 'contact_name';

export interface BuyerFilterOption {
  value: string;
  label: string;
  count: number;
}

export interface BuyerPartyFilterOptions {
  ownership_types: BuyerFilterOption[];
  business_tags: BuyerFilterOption[];
  regions: BuyerFilterOption[];
  statuses: BuyerFilterOption[];
  owners?: BuyerFilterOption[];
}

export interface BuyerPartySuggestion {
  id: string;
  search_field: BuyerPartySearchField;
  match_type: 'buyer' | 'alias' | 'contact';
  match_label: string;
  match_text: string;
  buyer_name: string;
  snippet: string | null;
}

export interface BuyerPartyDedupMatch {
  id: string;
  buyer_name: string;
  owner_name: string | null;
  match_type: 'buyer_name' | 'alias';
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
  aliases_json?: string[];
  location_province?: string | null;
  location_city?: string | null;
  location_district?: string | null;
  ownership_type?: string;
  listed_status?: string;
  stock_code?: string | null;
  listing_exchange?: string | null;
  contact_name?: string | null;
  contact_info_json?: Record<string, unknown>;
  our_contact_name?: string | null;
  business_tags_json?: string[];
  business_summary?: string | null;
  market_cap_yuan?: string | number | null;
  market_cap_as_of?: string | null;
  valuation_yuan?: string | number | null;
  valuation_date?: string | null;
  current_revenue_yuan?: string | number | null;
  current_operating_cash_flow_yuan?: string | number | null;
  financial_period_label?: string | null;
  supplementary_summary?: string | null;
  notes?: string | null;
  owner_user_id?: string | null;
}

export interface BuyerIntentConfirmationItem {
  field: string;
  proposed_value?: unknown;
  reason: string;
  evidence?: string;
  uncertain_part?: string;
  operator?: string;
  effect?: ConditionEffect;
  scope?: string;
  item_key?: string;
  proposed_value_status?: 'invalid' | 'requires_review';
}

export interface BuyerRegionConstraint {
  province: string;
  city?: string;
  district?: string;
  effect: 'required' | 'preferred' | 'excluded';
}

export interface BuyerIntentProcessingState {
  overall_status: 'not_started' | 'processing' | 'succeeded' | 'failed';
  current_stage: string | null;
  status_label: string;
  stage_label: string | null;
  attachment_summary: {
    total: number;
    pending: number;
    processing: number;
    succeeded: number;
    failed: number;
    skipped: number;
  };
  attachment_warning_count: number;
  ai_parse_status: string;
  semantic_parse_status: string;
  normalization_status: string;
  write_status: string;
  review_status: 'pending' | 'needs_confirmation' | 'reviewed';
  needs_confirmation_count: number;
  source_business_update_id: string | null;
  latest_job_id: string | null;
  error_code: string | null;
  error_message: string | null;
  recoverable: boolean;
  started_at: string | null;
  finished_at: string | null;
}

export interface BuyerIntent {
  id: string;
  buyer_party_id: string | null;
  buyer_name?: string | null;
  intent_name: string;
  // 与标的侧同一套语义：级别是闸门，status 是 E 的细分原因。
  intent_grade: string;
  status: string;
  contact_name: string | null;
  contact_info_json: Record<string, unknown>;
  raw_requirement_text: string | null;
  intent_summary: string | null;
  industry_primary: string | null;
  industry_secondary: string | null;
  industries_json?: string[];
  industry_l2_json: string[] | null;
  excluded_industries_json?: string[];
  industry_focus_tags_json?: string[];
  region_scope_summary: string | null;
  parsed_requirement_json?: Record<string, unknown>;
  region_constraints_json?: BuyerRegionConstraint[];
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
  acceptable_listed_status_json?: string[];
  condition_effects_json?: Record<string, ConditionEffect>;
  listing_board_requirement_summary: string | null;
  financing_stage_requirement_summary: string | null;
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
  transaction_types_json: string[] | null;
  premium_tolerance_summary: string | null;
  max_premium_rate: string | null;
  max_debt_ratio: string | null;
  debt_ratio_requirement_summary: string | null;
  major_risk_tolerance_summary: string | null;
  unacceptable_risk_flags_json: string[];
  buyer_industry_advantage_summary: string | null;
  needs_confirmation_json?: BuyerIntentConfirmationItem[];
  reviewed_at?: string | null;
  reviewed_by?: string | null;
  acceptable_control_paths_json?: string[];
  owner_user_id?: string | null;
  owner_name?: string | null;
  scenario_labels?: string[];
  created_at: string;
  updated_at: string;
  processing_state?: BuyerIntentProcessingState | null;
}

export interface BuyerIntentListResponse {
  items: BuyerIntent[];
  total: number;
  limit: number;
  offset: number;
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
  /** 死存储：不会注入模型。非空时设置页才提示，见 AGENTS.md。 */
  few_shot_examples_json: unknown[];
  variables_json: unknown[];
  is_active: boolean;
  is_default: boolean;
  updated_at: string;
}

export interface ModelNodeConfig {
  /** 未建配置的目录节点为 null —— 节点存在与否由代码目录决定，不由数据库。 */
  id: string | null;
  node_name: string;
  node_type: string;
  provider_config_id: string | null;
  provider_name: string | null;
  model_name: string | null;
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
  /** 以下字段来自后端节点目录 backend/app/registry/nodes.py，前端不再维护任何节点字典。 */
  label: string;
  domain: 'target' | 'buyer' | 'recommendation' | 'common';
  description: string;
  /** 运行时吃什么，已是中文，直接渲染。与 prompt_variables 不是一回事。 */
  runtime_inputs: string[];
  prompt_variables: string[];
  prompt_required: boolean;
  /** 本节点缺配置时替它干活的节点。 */
  understudy: string | null;
  /** and = 同组全就绪才生效（只配一个等于没配）；solo = 各自独立。 */
  understudy_kind: 'and' | 'solo' | null;
  understudy_group: string[];
  lifecycle: 'active' | 'retired';
  /** model = 绑模型的 AI 节点；external_api = 第三方 API 集成（OCR），在「模型与搜索」维护。 */
  kind: 'model' | 'external_api';
  sort_order: number;
  /** 库里有、代码目录没有的节点：照常显示并标「未登记」，不得据此过滤。 */
  registered: boolean;
  configured: boolean;
  /** 库里的 node_type 与代码目录不一致，需要显式提示，不能静默按库值运行。 */
  type_mismatch: boolean;
  latest_production_call: NodeProductionCall | null;
  latest_test: Record<string, unknown> | null;
  /** 未发布提示词时，可从代跑节点复制的起点；变量不兼容时只给理由不给内容。 */
  prompt_seed: PromptSeed | null;
}

export interface PromptSeed {
  source_node_name: string;
  source_version: string | null;
  /** 代跑节点模板用到的变量是否都在本节点的输入里。false 时不下发内容。 */
  compatible: boolean;
  /** 代跑节点用到、但本节点收不到的变量。 */
  extra_variables: string[];
  system_prompt: string | null;
  user_prompt_template: string | null;
  output_schema_json: Record<string, unknown> | null;
}

export interface NodeProductionCall {
  status: string;
  model_name: string | null;
  latency_ms: number | null;
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface RequiredBusinessNodeStatus {
  node_name: string;
  label: string;
  description: string;
  fallback_node_name: string;
  configured: boolean;
  prompt_configured: boolean;
  ready: boolean;
  node_id: string | null;
  model_name: string | null;
  using_fallback: boolean;
  fallback_ready: boolean;
  effective_node_name: string | null;
  test_summary: ModelNodeConfig['test_summary'] | null;
  latest_test: Record<string, unknown> | null;
  latest_production_call: NodeProductionCall | null;
}

export interface ModelConfigSettingsPage {
  capabilities: {
    direct_key_encryption_configured?: boolean;
    [key: string]: unknown;
  };
  providers: ModelProviderConfig[];
  nodes: ModelNodeConfig[];
  prompts: PromptTemplateConfig[];
  required_business_nodes: RequiredBusinessNodeStatus[];
  /** Prompt 变量名 → 中文说明，来自后端节点目录。 */
  prompt_variable_labels: Record<string, string>;
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
  /** 最近一次**人主动做的事**（业务更新/推进动态/字段应用/推荐提问），不含 AI 回填。 */
  latest_activity_at: string | null;
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
  contact_info_json?: Record<string, unknown>;
  raw_requirement_text?: string;
  intent_summary?: string;
  industry_primary?: string;
  industries_json?: string[];
  industry_l2_json?: string[];
  excluded_industries_json?: string[];
  industry_focus_tags_json?: string[];
  region_scope_summary?: string;
  region_constraints_json?: BuyerRegionConstraint[];
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
  acceptable_listed_status_json?: string[];
  condition_effects_json?: Record<string, ConditionEffect>;
  listing_board_requirement_summary?: string;
  financing_stage_requirement_summary?: string;
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
  unacceptable_risk_flags_json?: string[];
  buyer_industry_advantage_summary?: string;
  needs_confirmation_json?: BuyerIntentConfirmationItem[];
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
  processing_state: BuyerIntentProcessingState;
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
  intent_grade?: string;
  status?: string;
  contact_name?: string | null;
  contact_info_json?: Record<string, unknown>;
  raw_requirement_text?: string | null;
  intent_summary?: string | null;
  industry_primary?: string | null;
  industries_json?: string[];
  industry_l2_json?: string[];
  excluded_industries_json?: string[];
  industry_focus_tags_json?: string[];
  region_scope_summary?: string | null;
  region_constraints_json?: BuyerRegionConstraint[];
  min_revenue_yuan?: number | null;
  min_net_profit_yuan?: number | null;
  min_total_profit_yuan?: number | null;
  max_pe?: number | null;
  max_ps?: number | null;
  min_net_margin?: number | null;
  min_gross_margin?: number | null;
  min_valuation_yuan?: number | null;
  max_valuation_yuan?: number | null;
  min_market_cap_yuan?: number | null;
  max_market_cap_yuan?: number | null;
  market_cap_range_summary?: string | null;
  requires_control?: string;
  requires_consolidation?: string;
  accepts_minority_investment?: string;
  desired_equity_ratio_min?: number | null;
  desired_equity_ratio_max?: number | null;
  equity_ratio_summary?: string | null;
  equity_requirement_type?: string | null;
  preferred_listed_status?: string | null;
  acceptable_listed_status_json?: string[];
  condition_effects_json?: Record<string, ConditionEffect>;
  listing_board_requirement_summary?: string | null;
  financing_stage_requirement_summary?: string | null;
  budget_min_yuan?: number | null;
  budget_max_yuan?: number | null;
  acceptable_cash_flow_status_json?: string[];
  acceptable_profitability_status_json?: string[];
  requires_relocation?: string;
  relocation_target_regions_json?: string[];
  requires_return_investment?: string;
  return_investment_multiple?: number | null;
  requires_team_retention?: string;
  earnout_requirement?: string;
  listing_market_region?: string | null;
  transaction_type?: string | null;
  transaction_types_json?: string[] | Record<string, unknown>;
  premium_tolerance_summary?: string | null;
  max_premium_rate?: number | null;
  max_debt_ratio?: number | null;
  debt_ratio_requirement_summary?: string | null;
  major_risk_tolerance_summary?: string | null;
  unacceptable_risk_flags_json?: string[] | null;
  buyer_industry_advantage_summary?: string | null;
  needs_confirmation_json?: BuyerIntentConfirmationItem[];
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
  processing_scope?: BusinessUpdateProcessingScope;
  bound_relation_id?: string;
  followup_entry_mode?: 'ai' | 'direct';
  followup_event_type?: string;
  auto_process?: boolean;
  process_after_ocr?: boolean;
  include_attachment_text?: boolean;
  metadata_json?: Record<string, unknown>;
}

export type BusinessUpdateProcessingScope = 'basic_info' | 'follow_up' | 'both';

export interface RelationFollowUpDraft {
  content: string;
  next_step: string | null;
}

export interface BusinessUpdateProcessResponse {
  job_id: string;
  job_type: string;
  status: string;
  queue_name: string;
  business_update_id: string;
  jobs: Array<Record<string, unknown>>;
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
  content_extraction_status: 'pending' | 'processing' | 'succeeded' | 'failed' | 'skipped' | 'multimodal';
  extraction_strategy: string | null;
  latest_job_status: string | null;
  error_message: string | null;
  recoverable: boolean;
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
  content_extraction_status: 'pending' | 'processing' | 'succeeded' | 'failed' | 'skipped' | 'multimodal';
  extraction_strategy: string | null;
  error_message: string | null;
  recoverable: boolean;
}

export interface UpdateBatchChange {
  log_id: string;
  field_path: string;
  old_value: unknown;
  new_value: unknown;
  applied_at: string;
  rollback_at: string | null;
  research_evidence?: FieldValueSource['research_evidence'];
}

export interface UpdateBatch {
  batch_key: string;
  entity_type: 'seller_target' | 'buyer_intent';
  entity_id: string;
  source_type: string;
  batch_category: 'business_update' | 'management_operation' | 'rollback';
  source_id: string | null;
  report_available: boolean;
  input_type: string | null;
  input_summary: string | null;
  raw_input: string | null;
  attachments: UpdateBatchAttachment[];
  operator_user_id: string | null;
  operator_name: string;
  submitted_at: string;
  applied_at: string | null;
  status: 'parsing' | 'failed' | 'applied' | 'rolled_back' | string;
  stage_label: string | null;
  error_message: string | null;
  attachment_warning_count: number;
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
  last_event_type: string | null;
  last_event_content: string | null;
  last_event_next_step: string | null;
  deep_progress_elsewhere: boolean;
  seller_target_has_other_deep_progress: boolean;
  buyer_intent_has_other_deep_progress: boolean;
  buyer_intent_name: string | null;
  buyer_name: string | null;
  seller_target_name: string | null;
  created_at: string;
  updated_at: string;
  metadata_json: Record<string, unknown>;
}

/**
 * /relations/board 的瘦卡片。刻意只有 9 个字段——看板 4 行卡片用不到
 * BuyerSellerRelation 里那些靠关联子查询捞出来的事件文本。别往这里加字段，
 * 加了就把 B-2 的载荷问题重新引回来。
 */
export interface RelationBoardCard {
  id: string;
  seller_target_id: string;
  buyer_intent_id: string;
  status: string;
  /** 最近一条动态的时间；没有动态时为 null，「N 天无动态」预警看它。 */
  last_event_at: string | null;
  /** coalesce(last_event_at, updated_at, created_at)，与后端 order by 同源的排序键。 */
  last_activity_at: string | null;
  seller_target_name: string | null;
  buyer_intent_name: string | null;
  buyer_name: string | null;
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
  updated_at: string;
  updated_by: string | null;
}

export interface RelationEventType {
  value: string;
  label: string;
}

export interface RelationMeta {
  statuses: string[];
  event_types: RelationEventType[];
}

export interface RelationCreateResult {
  relation: BuyerSellerRelation;
  created: boolean;
}

export interface IndicatorGroupMeta {
  key: string;
  label: string;
  section_code: string | null;
  /** 补充栏的标题。栏名自带信息时是栏名（如「产业优势」），否则是「其他」。 */
  section_label: string | null;
  /** 该栏该装什么。与解析/调研提示词的栏目说明同一份真源。 */
  section_hint: string | null;
}

export interface IndicatorMeta {
  column: string;
  label: string;
  group: string | null;
  kind: 'text' | 'yuan' | 'ratio' | 'enum' | 'date' | 'json';
  screening: boolean;
  enum_options: Array<{ value: string; label: string }>;
  writable_by: string[];
  fold_into: string | null;
  target_column: string | null;
  operator: string | null;
  default_effect: ConditionEffect | null;
  effect_editable: boolean;
  scenario_allowed: boolean;
  multi_value: boolean;
  sql_recall: boolean;
  deterministic_rank: boolean;
  deep_eval: boolean;
  editor: string | null;
}

export interface IndicatorRegistryResponse {
  groups: IndicatorGroupMeta[];
  indicators: IndicatorMeta[];
}

export interface IndustryOptionsResponse {
  l1: Array<{ term: string }>;
  l2: Array<{ term: string; l1: string }>;
}

export interface FieldValueSource {
  id: string;
  entity_type: string;
  entity_id: string;
  field_path: string;
  value_snapshot_json: { value?: unknown; source_context?: Record<string, unknown> };
  source_type: string | null;
  source_label: string | null;
  review_status: string;
  created_at: string;
  created_by: string | null;
  created_by_name: string | null;
  evidence_span?: {
    id?: string | null;
    attachment_id?: string | null;
    parsed_document_id?: string | null;
    page_no?: number | null;
    text_excerpt?: string | null;
    char_start?: number | null;
    char_end?: number | null;
  } | null;
  research_evidence?: {
    proposal_id: string | null;
    job_id: string | null;
    source_type: string | null;
    source_url: string | null;
    source_title: string | null;
    source_excerpt: string | null;
    period_label: string | null;
    as_of_date: string | null;
  } | null;
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

export interface RecommendationSessionSummary {
  session: { id: string; mode: 'buyer_to_target' | 'target_to_buyer'; updated_at?: string; [key: string]: unknown };
  display: {
    title: string | null;
    subtitle: string | null;
    mode_label: string;
    [key: string]: unknown;
  };
  agent_status?: { status?: string; turn_id?: string | null; writer_pending?: boolean; [key: string]: unknown };
  activity: { last_activity_at?: string | null; [key: string]: unknown };
}

export interface RecommendationPage {
  recent_sessions: RecommendationSessionSummary[];
  running_sessions: RecommendationSessionSummary[];
  overview: Record<string, unknown>;
  quick_actions: Array<Record<string, unknown>>;
  polling_hint: Record<string, unknown>;
}

export interface BuyerIntentScenario {
  id: string;
  buyer_intent_id: string;
  label: string;
  sort_order: number;
  active: boolean;
  fields_json: Record<string, unknown>;
  needs_confirmation_json: BuyerIntentConfirmationItem[];
  condition_effects_json: Record<string, ConditionEffect>;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface BuyerIntentScenarioWrite {
  label: string;
  sort_order: number;
  active: boolean;
  fields_json: Record<string, unknown>;
  needs_confirmation_json?: BuyerIntentConfirmationItem[];
  condition_effects_json?: Record<string, ConditionEffect>;
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

export interface AttachmentUploadResult {
  attachment: { id: string; file_name: string; file_type: string | null };
  ocr_job: { job_id: string; status: string } | null;
}

export interface AttachmentOcrStatus {
  attachment: Record<string, unknown>;
  latest_job: { status: string; [key: string]: unknown } | null;
  latest_parsed_document: { parse_status: string; [key: string]: unknown } | null;
}

export interface AttachmentExtractedText {
  attachment_id: string;
  parse_status: string;
  text: string;
  truncated: boolean;
}

export interface RecommendationAgentTurn {
  session_id: string;
  turn_id: string;
  job_id: string;
  queue_name: string;
  /** 这一轮在重试哪一轮；不是重试时为 null。 */
  retry_of_turn_id: string | null;
}

/** 轮询消息表看不出「还在想」和「已经死了」的区别，这个端点补上这一半。 */
export interface RecommendationAgentTurnStatus {
  session_id: string;
  turn_id: string;
  job_status: string;
  failed: boolean;
  aborted: boolean;
  error_code: string | null;
  error_message: string | null;
  /** 原始异常，只有管理员拿得到。 */
  error_detail: string | null;
}

/**
 * 一次轮询要的东西，一个请求给全。
 *
 * 以前每 tick 并发拉「整份消息表」和「任务状态」两条 —— 单看消息表分不出
 * 「还在想」和「已经死了」（任务挂掉时一条消息都不会写）。合并之后请求量减半，
 * 更重要的是消掉了两次读取相隔一瞬而互相矛盾的窗口。
 */
export interface RecommendationAgentTurnProgress extends RecommendationAgentTurnStatus {
  has_brief: boolean;
  has_answer: boolean;
  has_question: boolean;
  messages: RecommendationMessage[];
}

/** 一次筛选调用的记录。过程行直接渲染它，让用户看见 Agent 做了什么决定。 */
export interface RecommendationAgentSearchStep {
  kind?: string;
  call_index?: number;
  valid?: boolean;
  group_id?: string | null;
  note?: string | null;
  filters?: Record<string, unknown>;
  applied_conditions?: Record<string, unknown>;
  count_only?: boolean;
  eligible_count?: number | null;
  matched_count?: number | null;
  full_conditions?: boolean;
  relaxed_fields?: { field: string; label: string; strength: 'required' | 'preferred' }[];
  relaxation_reason?: string | null;
  based_on_call_index?: number | null;
  scan_count?: number | null;
  conflict_count?: number | null;
  returned_count?: number;
  count?: number;
  total?: number;
  duration_ms?: number;
}

export interface RecommendationAgentQuestion {
  questions: { question: string; options: string[] }[];
  reason?: string | null;
}

export interface RecommendationAgentBrief {
  brief_version: 2;
  mode: string;
  intent_summary: string;
  parser_status: string;
  selection_source: 'deep_eval' | 'agent_fallback' | 'screening_fallback';
  deep_eval_status: string;
  candidate_pool_count: number;
  candidate_pool_capped: boolean;
  screening_runs?: RecommendationAgentSearchStep[];
  recommended?: {
    id: string;
    name?: string | null;
    facts?: Record<string, unknown>;
    qualitative_verdicts?: Record<string, string>;
    reason_points?: string[];
    risks?: string | null;
    info_gaps?: string | null;
    matched_full_conditions?: boolean;
    relaxed_fields?: { field: string; label: string; strength: 'required' | 'preferred' }[];
    required_relaxation?: boolean;
  }[];
  runner_ups?: RecommendationAgentBrief['recommended'];
  follow_up_suggestions?: string[];
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
  review_status: string;
  updated_at: string;
  updated_by_name: string | null;
}

export interface ProfileSectionCatalogEntry {
  code: string;
  label: string;
}

export interface ProfileSectionsResponse {
  entity_type: string;
  entity_id: string;
  sections: ProfileSection[];
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

export interface ResearchSearchObservation {
  query: string;
  returned_count: number;
  matched_result_count: number;
  error?: string;
  candidates?: Array<{
    title: string | null;
    url: string;
    subject_match: boolean;
  }>;
}

export interface ResearchReport {
  job_id: string;
  seller_target_id: string;
  status: string;
  created_at: string;
  finished_at: string | null;
  raw_output_text: string | null;
  agent_output_json: Record<string, unknown> | null;
  prompt_version: string | null;
  mapper_status: string | null;
  execution_trace: {
    searched_queries?: string[];
    search_observations?: ResearchSearchObservation[];
    fetched_urls?: string[];
    skipped_urls?: Array<{ url: string; reason: string }>;
    early_stop_reason?: string;
    llm_calls?: number;
    tool_calls?: Record<string, number>;
    content_inspection_retry_count?: number;
    hit_iteration_limit?: boolean;
  };
}

export interface ResearchProposal {
  id: string;
  /** 0825 起买家主体的解析与调研提案也落这张表，用 source_type 区分 material / web。 */
  entity_type: 'seller_target' | 'buyer_party';
  entity_id: string;
  job_id: string | null;
  proposal_kind: 'profile_section' | 'structured_fact';
  section_code: string | null;
  section_label: string | null;
  field_path: string | null;
  proposed_value_json: Record<string, unknown>;
  current_value_json: Record<string, unknown>;
  normalized_proposed_value: unknown;
  conflict_kind: 'consistent' | 'supplement' | 'temporal_update' | 'same_period_conflict';
  period_label: string | null;
  as_of_date: string | null;
  source_type: string | null;
  source_url: string | null;
  source_title: string | null;
  source_excerpt: string | null;
  anchor_matches_json: Array<{ kind: string; value: string }>;
  review_status: string;
  reviewed_at: string | null;
  created_at: string;
  is_actionable: boolean;
  validation_error: string | null;
}

export interface SellerResearchStatus {
  seller_target_id: string;
  last_research_at: string | null;
  research_last_outcome: 'found' | 'found_but_rejected' | 'no_public_information' | 'failed' | null;
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

export interface OcrProviderConfig {
  id: string;
  provider_name: string;
  adapter: string;
  base_url: string | null;
  model: string;
  secret_mode: 'env' | 'direct';
  api_key_secret_ref: string | null;
  secret_configured: boolean;
  key_display: string;
  extra_config_json: Record<string, unknown>;
  is_active: boolean;
  is_default: boolean;
  updated_at: string;
}

export interface OcrConfigOverview {
  adapter: string;
  base_url: string;
  model: string;
  key_configured: boolean;
  configured: boolean;
  source: 'database' | 'environment';
  provider_config_id: string | null;
  provider_name: string | null;
  adapters: string[];
  providers: OcrProviderConfig[];
  upload_timeout_seconds: number;
  poll_interval_seconds: number;
  max_wait_seconds: number;
  direct_key_encryption_configured: boolean;
}

export interface TargetProvinceCount {
  province: string;
  count: number;
}

export interface TargetIndustryCount {
  /** 二级行业。一级行业太粗，看板上读不出赛道。 */
  l2: string;
  count: number;
}

export interface RevenueBucketCount {
  key: string;
  label: string;
  count: number;
}

export interface PlatformOverview {
  /** 服务端取数时刻；大屏长时间不刷新时用来判断屏上的数还新不新。 */
  generated_at: string;
  targets: {
    total: number;
    provinces: TargetProvinceCount[];
    /** 标的总数减去有省份的标的数；地图上单独标注，不混进「0 个」。 */
    province_unknown_count: number;
    /** 只含前 N 名；一个标的可挂多个二级行业，因此各项之和可能大于 total。 */
    industries: TargetIndustryCount[];
    /** 榜外还有多少个二级行业。 */
    industry_other_count: number;
    /** 完全没有二级行业的标的数。 */
    industry_unknown_count: number;
    /** 含计数为 0 的档位，顺序即档位顺序。 */
    revenue_buckets: RevenueBucketCount[];
    revenue_unknown_count: number;
  };
  /** 买家主体（buyer_party）的所在地分布，不是买家需求的目标地域。 */
  buyers: {
    total: number;
    provinces: TargetProvinceCount[];
    province_unknown_count: number;
  };
}
