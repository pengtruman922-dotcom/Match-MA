import type {
  SearchConfigOverview,
  SearchProviderTestResult,
  PlatformOverview,
  ProfileSection,
  ProfileSectionsResponse,
  ProfileSectionWrite,
  ResearchBatchResponse,
  ResearchJob,
  ResearchReport,
  ResearchProposal,
  SellerResearchStatus,
  SellerTarget,
  SellerTargetBulkDeleteResponse,
  SellerTargetCreate,
  SellerTargetFilterOptions,
  SellerTargetListResponse,
  SellerTargetSearchField,
  SellerTargetSuggestion,
  SellerTargetUpdate,
  TargetAttachmentListResponse,
  AttachmentUploadPolicy,
  AttachmentItem,
  BackgroundJob,
  BackgroundJobRetryPreview,
  BusinessUpdate,
  BusinessUpdateCreate,
  BusinessUpdateProcessResponse,
  BusinessUpdateReviewPage,
  BusinessUpdateUploadResponse,
  BuyerBulkDeleteResponse,
  BuyerIntentFilterOptions,
  BuyerIntentListResponse,
  BuyerIntentSearchField,
  BuyerIntentSuggestion,
  BuyerIntent,
  BuyerIntentCreate,
  BuyerIntentScenario,
  BuyerIntentScenarioWrite,
  BuyerIntentTargetExclusion,
  BuyerIntentUpdate,
  BuyerIntentParseJob,
  BuyerIntentParseStatus,
  BuyerParty,
  BuyerPartyCreate,
  BuyerPartyDedupCheck,
  BuyerPartyFilterOptions,
  BuyerPartyListResponse,
  BuyerPartySearchField,
  BuyerPartySuggestion,
  BuyerSellerRelation,
  BusinessUpdateDebugBundle,
  DebugCenterData,
  DebugEntity,
  ExtractedAction,
  ExtractedActionCreate,
  RelationEvent,
  RelationMeta,
  RelationCreateResult,
  RecommendationCandidateRequest,
  RecommendationCandidateResponse,
  RecommendationMessage,
  RecommendationMessageCreate,
  RecommendationPage,
  RecommendationReport,
  RecommendationReportCreate,
  RecommendationReportJob,
  RecommendationRerankJob,
  RecommendationSelectedItem,
  RecommendationSelectedItemCreate,
  RecommendationSessionDebugBundle,
  RecommendationSession,
  RecommendationSessionBundle,
  AppUser,
  AppUserCreate,
  AppUserOption,
  BatchAssignOwnerResponse,
  UpdateBatchListResponse,
  UpdateBatchRollbackResponse,
  UpdateLog,
  FailureSummary,
  FieldValueSource,
  GlobalSearchResponse,
  IndustryDictionaryImportResult,
  IndustryDictionaryTerm,
  IndicatorRegistryResponse,
  IndustryOptionsResponse,
  ModelConnectionTestResult,
  ModelConfigSettingsPage,
  ModelNodeConfig,
  ModelProviderConfig,
  PromptTemplateConfig,
  QueueSummary,
  RelationBoardCard,
  TaskCenterData,
} from '../../types/api';
import type { AuthUser, LoginResponse } from '../auth';
import { apiBlobResponse, apiRequest, buildQuery } from './client';

export const auth = {
  login: (data: { username: string; password: string }) =>
    apiRequest<LoginResponse>('/auth/login', { method: 'POST', body: JSON.stringify(data) }),
  me: () => apiRequest<AuthUser>('/auth/me'),
};

export const users = {
  list: () => apiRequest<AppUser[]>('/users'),
  options: () => apiRequest<AppUserOption[]>('/users/options'),
  create: (data: AppUserCreate) =>
    apiRequest<AppUser>('/users', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: { name?: string; role?: string; status?: string }) =>
    apiRequest<AppUser>(`/users/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  resetPassword: (id: string, password: string) =>
    apiRequest<{ status: string }>(`/users/${id}/reset-password`, {
      method: 'POST',
      body: JSON.stringify({ password }),
    }),
};

export const sellerTargets = {
  list: (params?: {
    q?: string;
    search_field?: SellerTargetSearchField;
    industry_l1?: string;
    industry_l2?: string;
    province?: string;
    city?: string;
    district?: string;
    status?: string;
    owner?: string;
    limit?: number;
    offset?: number;
  }) => apiRequest<SellerTargetListResponse>(`/seller-targets${buildQuery(params || {})}`),
  filterOptions: () => apiRequest<SellerTargetFilterOptions>('/seller-targets/filter-options'),
  suggestions: (params: { q: string; limit?: number }) =>
    apiRequest<SellerTargetSuggestion[]>(`/seller-targets/suggestions${buildQuery(params)}`),
  get: (id: string) => apiRequest<SellerTarget>(`/seller-targets/${id}`),
  create: (data: SellerTargetCreate) =>
    apiRequest<SellerTarget>('/seller-targets', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  update: (id: string, data: SellerTargetUpdate) =>
    apiRequest<SellerTarget>(`/seller-targets/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  updateFields: (id: string, changes: Record<string, unknown>) =>
    apiRequest<SellerTarget>(`/seller-targets/${id}/fields`, {
      method: 'PATCH',
      body: JSON.stringify({ changes }),
    }),
  delete: (id: string) => apiRequest<{ status: string }>(`/seller-targets/${id}`, { method: 'DELETE' }),
  bulkDelete: (ids: string[]) =>
    apiRequest<SellerTargetBulkDeleteResponse>('/seller-targets/bulk-delete', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),
  batchAssignOwner: (ids: string[], ownerUserId: string | null) =>
    apiRequest<BatchAssignOwnerResponse>('/seller-targets/batch-assign-owner', {
      method: 'POST',
      body: JSON.stringify({ ids, owner_user_id: ownerUserId }),
    }),
  attachments: (id: string) => apiRequest<TargetAttachmentListResponse>(`/seller-targets/${id}/attachments`),
  downloadAttachment: (id: string, attachmentId: string) =>
    apiBlobResponse(`/seller-targets/${id}/attachments/${attachmentId}/download`),
  deleteAttachment: (id: string, attachmentId: string) =>
    apiRequest<{ status: string }>(`/seller-targets/${id}/attachments/${attachmentId}`, { method: 'DELETE' }),
};

export const buyerParties = {
  list: (params?: {
    q?: string;
    search_field?: BuyerPartySearchField;
    buyer_type?: string;
    region?: string;
    listed_status?: string;
    status?: string;
    owner?: string;
    limit?: number;
    offset?: number;
  }) => apiRequest<BuyerPartyListResponse>(`/buyer-parties${buildQuery(params || {})}`),
  filterOptions: () => apiRequest<BuyerPartyFilterOptions>('/buyer-parties/filter-options'),
  dedupCheck: (params: { q: string; limit?: number }) =>
    apiRequest<BuyerPartyDedupCheck>(`/buyer-parties/dedup-check${buildQuery(params)}`),
  suggestions: (params: { q: string; limit?: number }) =>
    apiRequest<BuyerPartySuggestion[]>(`/buyer-parties/suggestions${buildQuery(params)}`),
  get: (id: string) => apiRequest<BuyerParty>(`/buyer-parties/${id}`),
  create: (data: BuyerPartyCreate) =>
    apiRequest<BuyerParty>('/buyer-parties', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<BuyerPartyCreate>) =>
    apiRequest<BuyerParty>(`/buyer-parties/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: (id: string) => apiRequest<{ status: string }>(`/buyer-parties/${id}`, { method: 'DELETE' }),
  bulkDelete: (ids: string[]) =>
    apiRequest<BuyerBulkDeleteResponse>('/buyer-parties/bulk-delete', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),
  batchAssignOwner: (ids: string[], ownerUserId: string | null) =>
    apiRequest<BatchAssignOwnerResponse>('/buyer-parties/batch-assign-owner', {
      method: 'POST',
      body: JSON.stringify({ ids, owner_user_id: ownerUserId }),
    }),
  intents: (id: string) => apiRequest<BuyerIntent[]>(`/buyer-parties/${id}/intents`),
};

export const buyerIntents = {
  list: (params?: {
    q?: string;
    search_field?: BuyerIntentSearchField;
    buyer_party_id?: string;
    industry?: string;
    region?: string;
    status?: string;
    listed_status?: string;
    requires_consolidation?: string;
    owner?: string;
    limit?: number;
    offset?: number;
  }) => apiRequest<BuyerIntentListResponse>(`/buyer-intents${buildQuery(params || {})}`),
  filterOptions: () => apiRequest<BuyerIntentFilterOptions>('/buyer-intents/filter-options'),
  suggestions: (params: { q: string; limit?: number }) =>
    apiRequest<BuyerIntentSuggestion[]>(`/buyer-intents/suggestions${buildQuery(params)}`),
  get: (id: string) => apiRequest<BuyerIntent>(`/buyer-intents/${id}`),
  create: (data: BuyerIntentCreate) =>
    apiRequest<BuyerIntent>('/buyer-intents', { method: 'POST', body: JSON.stringify(data) }),
  parse: (id: string, data?: { raw_requirement_text?: string; force?: boolean }) =>
    apiRequest<BuyerIntentParseJob>(`/buyer-intents/${id}/parse`, {
      method: 'POST',
      body: JSON.stringify(data || {}),
    }),
  parseStatus: (id: string) => apiRequest<BuyerIntentParseStatus>(`/buyer-intents/${id}/parse-status`),
  update: (id: string, data: BuyerIntentUpdate) =>
    apiRequest<BuyerIntent>(`/buyer-intents/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  review: (id: string, clearConfirmations = false) =>
    apiRequest<BuyerIntent>(`/buyer-intents/${id}/review`, {
      method: 'POST',
      body: JSON.stringify({ clear_confirmations: clearConfirmations }),
    }),
  scenarios: (id: string) =>
    apiRequest<BuyerIntentScenario[]>(`/buyer-intents/${id}/scenarios`),
  createScenario: (id: string, data: BuyerIntentScenarioWrite) =>
    apiRequest<BuyerIntentScenario>(`/buyer-intents/${id}/scenarios`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateScenario: (id: string, scenarioId: string, data: BuyerIntentScenarioWrite) =>
    apiRequest<BuyerIntentScenario>(`/buyer-intents/${id}/scenarios/${scenarioId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteScenario: (id: string, scenarioId: string) =>
    apiRequest<void>(`/buyer-intents/${id}/scenarios/${scenarioId}`, { method: 'DELETE' }),
  delete: (id: string) => apiRequest<{ status: string }>(`/buyer-intents/${id}`, { method: 'DELETE' }),
  bulkDelete: (ids: string[]) =>
    apiRequest<BuyerBulkDeleteResponse>('/buyer-intents/bulk-delete', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),
  batchAssignOwner: (ids: string[], ownerUserId: string | null) =>
    apiRequest<BatchAssignOwnerResponse>('/buyer-intents/batch-assign-owner', {
      method: 'POST',
      body: JSON.stringify({ ids, owner_user_id: ownerUserId }),
    }),
};

export const businessUpdates = {
  list: (params?: {
    processing_status?: string;
    seller_target_id?: string;
    buyer_intent_id?: string;
    limit?: number;
    offset?: number;
  }) => apiRequest<BusinessUpdate[]>(`/business-updates${buildQuery(params || {})}`),
  get: (id: string) => apiRequest<BusinessUpdate>(`/business-updates/${id}`),
  create: (data: BusinessUpdateCreate) =>
    apiRequest<BusinessUpdate>('/business-updates', { method: 'POST', body: JSON.stringify(data) }),
  upload: (data: FormData) =>
    apiRequest<BusinessUpdateUploadResponse>('/business-updates/upload', { method: 'POST', body: data }),
  reviewPage: (id: string) => apiRequest<BusinessUpdateReviewPage>(`/business-updates/${id}/review-page`),
  process: (id: string, data?: { branch?: 'all' | 'basic_info' | 'follow_up'; include_attachment_text?: boolean }) =>
    apiRequest<BusinessUpdateProcessResponse>(
      `/business-updates/${id}/process`,
      { method: 'POST', body: JSON.stringify(data || {}) }
    ),
};

export const attachments = {
  uploadPolicy: () => apiRequest<AttachmentUploadPolicy>('/attachments/upload-policy'),
  list: (params?: {
    parse_status?: string;
    entity_type?: string;
    entity_id?: string;
    limit?: number;
    offset?: number;
  }) => apiRequest<AttachmentItem[]>(`/attachments${buildQuery(params || {})}`),
  download: (id: string) => apiBlobResponse(`/attachments/${id}/download`),
};

export const extractedActions = {
  list: (params?: {
    business_update_id?: string;
    review_status?: string;
    target_entity_type?: string;
    target_entity_id?: string;
    limit?: number;
    offset?: number;
  }) => apiRequest<ExtractedAction[]>(`/extracted-actions${buildQuery(params || {})}`),
  get: (id: string) => apiRequest<ExtractedAction>(`/extracted-actions/${id}`),
  create: (businessUpdateId: string, data: ExtractedActionCreate) =>
    apiRequest<ExtractedAction>(`/business-updates/${businessUpdateId}/extracted-actions`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  update: (id: string, data: { review_status: string }) =>
    apiRequest<ExtractedAction>(`/extracted-actions/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  apply: (id: string) =>
    apiRequest<{ status: string; applied_fields?: string[] }>(`/extracted-actions/${id}/apply`, {
      method: 'POST',
    }),
};

export const stats = {
  overview: () => apiRequest<PlatformOverview>('/stats/overview'),
};

export const relations = {
  list: (params?: {
    seller_target_id?: string;
    buyer_intent_id?: string;
    buyer_party_id?: string;
    status?: string;
    q?: string;
    limit?: number;
    offset?: number;
  }) => apiRequest<BuyerSellerRelation[]>(`/relations${buildQuery(params || {})}`),
  /**
   * 撮合看板专用瘦端点：9 字段、零关联子查询、limit 上限 5000。
   * 看板一次拉完整块数据在前端分组，所以这里不传 q——搜索在内存里做，
   * 见 features/board/boardBuckets.ts 的 filter 说明。
   */
  board: (params?: {
    ownership?: 'all' | 'involved' | 'sole';
    owner?: string;
    limit?: number;
    offset?: number;
  }) =>
    apiRequest<RelationBoardCard[]>(`/relations/board${buildQuery(params || {})}`),
  get: (id: string) => apiRequest<BuyerSellerRelation>(`/relations/${id}`),
  events: (id: string, params?: { limit?: number; offset?: number }) =>
    apiRequest<RelationEvent[]>(`/relations/${id}/events${buildQuery(params || {})}`),
  listEvents: (params?: {
    relation_id?: string;
    seller_target_id?: string;
    buyer_intent_id?: string;
    buyer_party_id?: string;
    event_type?: string;
    limit?: number;
    offset?: number;
  }) => apiRequest<RelationEvent[]>(`/relation-events${buildQuery(params || {})}`),
  exclusions: (params?: { buyer_intent_id?: string; seller_target_id?: string; active?: boolean; limit?: number; offset?: number }) =>
    apiRequest<BuyerIntentTargetExclusion[]>(`/buyer-intent-target-exclusions${buildQuery(params || {})}`),
  meta: () => apiRequest<RelationMeta>('/relations-meta'),
  create: (data: { buyer_intent_id: string; seller_target_id: string; source_summary?: string | null }) =>
    apiRequest<RelationCreateResult>('/relations', { method: 'POST', body: JSON.stringify(data) }),
  updateStatus: (id: string, data: { status: string; status_reason?: string | null; next_step?: string | null }) =>
    apiRequest<BuyerSellerRelation>(`/relations/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  createEvent: (id: string, data: { event_type: string; title?: string | null; content?: string | null; next_step?: string | null }) =>
    apiRequest<RelationEvent>(`/relations/${id}/events`, { method: 'POST', body: JSON.stringify(data) }),
  updateEvent: (relationId: string, eventId: string, data: { event_type?: string; title?: string | null; content?: string | null; next_step?: string | null }) =>
    apiRequest<RelationEvent>(`/relations/${relationId}/events/${eventId}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteEvent: (relationId: string, eventId: string) =>
    apiRequest<void>(`/relations/${relationId}/events/${eventId}`, { method: 'DELETE' }),
};

export const backgroundJobs = {
  list: (params?: {
    status?: string;
    job_type?: string;
    queue_name?: string;
    entity_type?: string;
    entity_id?: string;
    include_ignored?: boolean;
    include_archived?: boolean;
    include_test_data?: boolean;
    limit?: number;
    offset?: number;
  }) =>
    apiRequest<BackgroundJob[]>(`/background-jobs${buildQuery(params || {})}`),
  get: (id: string) => apiRequest<BackgroundJob>(`/background-jobs/${id}`),
  traces: (id: string) => apiRequest<BusinessUpdateDebugBundle['traces']>(`/background-jobs/${id}/traces`),
  retryPreview: (id: string) => apiRequest<BackgroundJobRetryPreview>(`/background-jobs/${id}/retry-preview`),
  retry: (id: string) => apiRequest<BackgroundJob>(`/background-jobs/${id}/retry`, { method: 'POST' }),
  ignore: (id: string, reason?: string) =>
    apiRequest<BackgroundJob>(`/background-jobs/${id}/ignore`, {
      method: 'POST',
      body: JSON.stringify({ reason: reason || null }),
    }),
  unignore: (id: string) => apiRequest<BackgroundJob>(`/background-jobs/${id}/unignore`, { method: 'POST' }),
  archive: (id: string, reason?: string) =>
    apiRequest<BackgroundJob>(`/background-jobs/${id}/archive`, {
      method: 'POST',
      body: JSON.stringify({ reason: reason || null }),
    }),
  unarchive: (id: string) => apiRequest<BackgroundJob>(`/background-jobs/${id}/unarchive`, { method: 'POST' }),
  markTestData: (id: string, data?: { label?: string; reason?: string }) =>
    apiRequest<BackgroundJob>(`/background-jobs/${id}/mark-test-data`, {
      method: 'POST',
      body: JSON.stringify({ label: data?.label || null, reason: data?.reason || null }),
    }),
  unmarkTestData: (id: string) =>
    apiRequest<BackgroundJob>(`/background-jobs/${id}/unmark-test-data`, { method: 'POST' }),
  summaryFailures: (params?: {
    lookback_hours?: number;
    limit?: number;
    include_ignored?: boolean;
    include_archived?: boolean;
    include_test_data?: boolean;
  }) =>
    apiRequest<FailureSummary>(`/background-jobs/summary/failures${buildQuery(params || {})}`),
  summaryQueues: (params?: {
    include_empty?: boolean;
    include_ignored?: boolean;
    include_archived?: boolean;
    include_test_data?: boolean;
    lookback_hours?: number;
  }) =>
    apiRequest<QueueSummary>(`/background-jobs/summary/queues${buildQuery(params || {})}`),
  taskCenter: (params?: {
    status_group?: string;
    initiated_by_user_id?: string;
    queue_name?: string;
    job_type?: string;
    q?: string;
    lookback_hours?: number;
    include_test_data?: boolean;
    limit?: number;
    offset?: number;
  }) =>
    apiRequest<TaskCenterData>(`/background-jobs/task-center${buildQuery(params || {})}`),
};

export const updateLogs = {
  list: (params: { entity_type: string; entity_id: string }) =>
    apiRequest<UpdateLog[]>(`/update-logs${buildQuery(params)}`),
  batches: (params: { entity_type: 'seller_target' | 'buyer_intent'; entity_id: string; limit?: number; offset?: number }) =>
    apiRequest<UpdateBatchListResponse>(`/update-logs/batches${buildQuery(params)}`),
  rollbackBatch: (
    batchKey: string,
    data: { entity_type: 'seller_target' | 'buyer_intent'; entity_id: string; reason?: string },
  ) => apiRequest<UpdateBatchRollbackResponse>(`/update-logs/batches/${encodeURIComponent(batchKey)}/rollback`, {
    method: 'POST',
    body: JSON.stringify(data),
  }),
};

export const profileSections = {
  list: (entityType: 'seller_target' | 'buyer_intent', entityId: string) =>
    apiRequest<ProfileSectionsResponse>(`/profile-sections/${entityType}/${entityId}`),
  write: (entityType: 'seller_target' | 'buyer_intent', entityId: string, data: ProfileSectionWrite) =>
    apiRequest<ProfileSection>(`/profile-sections/${entityType}/${entityId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
};

export const fieldSources = {
  list: (params: { entity_type: string; entity_id: string; limit?: number }) =>
    apiRequest<FieldValueSource[]>(`/field-sources${buildQuery(params)}`),
};

export const research = {
  startSellerTarget: (sellerTargetId: string) =>
    apiRequest<ResearchJob>(`/research/seller-targets/${sellerTargetId}`, { method: 'POST' }),
  startSellerTargets: (sellerTargetIds: string[]) =>
    apiRequest<ResearchBatchResponse>('/research/seller-targets', {
      method: 'POST',
      body: JSON.stringify({ seller_target_ids: sellerTargetIds }),
    }),
  sellerTargetStatus: (sellerTargetId: string) =>
    apiRequest<SellerResearchStatus>(`/research/seller-targets/${sellerTargetId}/status`),
  report: (jobId: string) =>
    apiRequest<ResearchReport>(`/research/jobs/${jobId}/report`),
  proposals: (entityId: string, reviewStatus?: string) =>
    apiRequest<ResearchProposal[]>(`/research/proposals${buildQuery({
      entity_type: 'seller_target',
      entity_id: entityId,
      review_status: reviewStatus,
    })}`),
  acceptProposal: (proposalId: string) =>
    apiRequest<ResearchProposal>(`/research/proposals/${proposalId}/accept`, { method: 'POST' }),
  rejectProposal: (proposalId: string) =>
    apiRequest<ResearchProposal>(`/research/proposals/${proposalId}/reject`, { method: 'POST' }),
};

export const globalSearch = {
  query: (params: { q: string; limit_per_type?: number }) =>
    apiRequest<GlobalSearchResponse>(`/search${buildQuery(params)}`),
};

export const searchConfig = {
  overview: () => apiRequest<SearchConfigOverview>('/search-config/overview'),
  test: (data: { provider_id?: string | null; query?: string; api_key?: string | null }) =>
    apiRequest<SearchProviderTestResult>('/search-config/test', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  create: (data: {
    provider_name: string;
    adapter: string;
    base_url: string;
    secret_mode: 'env' | 'direct';
    api_key_secret_ref?: string | null;
    api_key?: string | null;
    extra_config_json?: Record<string, unknown>;
  }) => apiRequest<ModelProviderConfig>('/model-config/providers', {
    method: 'POST',
    body: JSON.stringify({
      provider_name: data.provider_name,
      model_name: data.adapter,
      base_url: data.base_url,
      secret_mode: data.secret_mode,
      api_key_secret_ref: data.api_key_secret_ref,
      api_key: data.api_key,
      provider_type: 'search',
      auth_type: 'bearer',
      is_default: true,
      extra_config_json: { adapter: data.adapter, ...(data.extra_config_json || {}) },
    }),
  }),
  update: (id: string, data: {
    provider_name?: string;
    base_url?: string;
    secret_mode?: 'env' | 'direct';
    api_key_secret_ref?: string | null;
    api_key?: string | null;
    is_active?: boolean;
  }) => apiRequest<ModelProviderConfig>(`/model-config/providers/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  }),
  remove: (id: string) =>
    apiRequest<ModelProviderConfig>(`/model-config/providers/${id}`, { method: 'DELETE' }),
};

export const modelConfig = {
  settingsPage: () => apiRequest<ModelConfigSettingsPage>('/model-config/settings-page?include_inactive=true&tests_per_node=1'),
  createModel: (data: {
    provider_name: string;
    model_name: string;
    base_url: string;
    secret_mode: 'env' | 'direct';
    api_key_secret_ref?: string | null;
    api_key?: string | null;
  }) => apiRequest<ModelProviderConfig>('/model-config/models', {
    method: 'POST',
    body: JSON.stringify({ ...data, provider_type: 'openai_compatible', auth_type: 'bearer' }),
  }),
  updateModel: (id: string, data: {
    provider_name?: string;
    model_name?: string;
    base_url?: string;
    secret_mode?: 'env' | 'direct';
    api_key_secret_ref?: string | null;
    api_key?: string | null;
    is_active?: boolean;
  }) => apiRequest<ModelProviderConfig>(`/model-config/models/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteModel: (id: string) =>
    apiRequest<ModelProviderConfig>(`/model-config/models/${id}`, { method: 'DELETE' }),
  testModelDraft: (data: {
    provider_config_id?: string | null;
    model_name: string;
    base_url: string;
    secret_mode: 'env' | 'direct';
    api_key_secret_ref?: string | null;
    api_key?: string | null;
  }) => apiRequest<ModelConnectionTestResult>('/model-config/models/test', {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  testModel: (id: string) =>
    apiRequest<ModelConnectionTestResult>(`/model-config/models/${id}/test`, { method: 'POST' }),
  updateProvider: (id: string, data: Partial<ModelProviderConfig>) =>
    apiRequest<ModelProviderConfig>(`/model-config/providers/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  updateNode: (id: string, data: Partial<ModelNodeConfig>) =>
    apiRequest<ModelNodeConfig>(`/model-config/nodes/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  createPrompt: (data: Record<string, unknown>) =>
    apiRequest<PromptTemplateConfig>('/model-config/prompts', { method: 'POST', body: JSON.stringify(data) }),
  listPrompts: (nodeName: string) =>
    apiRequest<PromptTemplateConfig[]>(`/model-config/prompts?node_name=${encodeURIComponent(nodeName)}&include_inactive=true`),
  renderPromptPreview: (data: { system_prompt?: string | null; user_prompt_template?: string | null }) =>
    apiRequest<{
      variables: string[];
      resolved_variables: Record<string, string>;
      rendered_system_prompt: string;
      rendered_user_prompt: string;
    }>('/model-config/prompts/render-preview', { method: 'POST', body: JSON.stringify(data) }),
  updatePrompt: (id: string, data: Partial<PromptTemplateConfig>) =>
    apiRequest<PromptTemplateConfig>(`/model-config/prompts/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  testNode: (id: string, input_text: string) =>
    apiRequest<{ job_id: string; job_status: string }>(`/model-config/nodes/${id}/test-jobs`, {
      method: 'POST',
      body: JSON.stringify({ input_text }),
    }),
};

export const indicatorRegistry = {
  list: (entity: string = 'seller_target') =>
    apiRequest<IndicatorRegistryResponse>(`/meta/indicators${buildQuery({ entity })}`),
};

export const meta = {
  industryOptions: () => apiRequest<IndustryOptionsResponse>('/meta/industry-options'),
};

export const dataDictionaries = {
  industry: (params?: { q?: string; level?: string; include_inactive?: boolean }) =>
    apiRequest<IndustryDictionaryTerm[]>(`/data-dictionaries/industry${buildQuery(params || {})}`),
  createIndustryTerm: (data: {
    term: string;
    level: 'l1' | 'l2';
    parent_id?: string | null;
    aliases?: string[];
    active?: boolean;
    sort_order?: number;
  }) =>
    apiRequest<IndustryDictionaryTerm>('/data-dictionaries/industry', { method: 'POST', body: JSON.stringify(data) }),
  updateIndustryTerm: (id: string, data: {
    term?: string;
    parent_id?: string | null;
    aliases?: string[];
    active?: boolean;
    sort_order?: number;
  }) =>
    apiRequest<IndustryDictionaryTerm>(`/data-dictionaries/industry/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  industryImportTemplate: () => apiBlobResponse('/data-dictionaries/industry/import-template'),
  importIndustry: (file: File, dryRun: boolean) => {
    const body = new FormData();
    body.append('file', file);
    return apiRequest<IndustryDictionaryImportResult>(`/data-dictionaries/industry/import?dry_run=${dryRun}`, {
      method: 'POST',
      body,
    });
  },
};

export const debugApi = {
  businessUpdate: (id: string) => apiRequest<BusinessUpdateDebugBundle>(`/debug/business-updates/${id}`),
  recommendationSession: (id: string) =>
    apiRequest<RecommendationSessionDebugBundle>(`/debug/recommendation-sessions/${id}`),
  center: (params?: { limit?: number }) => apiRequest<DebugCenterData>(`/debug/center${buildQuery(params || {})}`),
  entity: (entityType: string, entityId: string) =>
    apiRequest<DebugEntity>(`/debug/entities/${encodeURIComponent(entityType)}/${encodeURIComponent(entityId)}`),
};

export const recommendations = {
  candidates: (data: RecommendationCandidateRequest) =>
    apiRequest<RecommendationCandidateResponse>('/recommendations/candidates', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  sessions: (params?: {
    mode?: 'buyer_to_target' | 'target_to_buyer';
    buyer_intent_id?: string;
    seller_target_id?: string;
    limit?: number;
    offset?: number;
  }) => apiRequest<RecommendationSession[]>(`/recommendations/sessions${buildQuery(params || {})}`),
  getSession: (sessionId: string) => apiRequest<RecommendationSession>(`/recommendations/sessions/${sessionId}`),
  bundle: (sessionId: string, params?: { include_canceled?: boolean }) =>
    apiRequest<RecommendationSessionBundle>(
      `/recommendations/sessions/${sessionId}/bundle${buildQuery(params || {})}`,
    ),
  messages: (sessionId: string, params?: { limit?: number; offset?: number }) =>
    apiRequest<RecommendationMessage[]>(
      `/recommendations/sessions/${sessionId}/messages${buildQuery(params || {})}`,
    ),
  createMessage: (sessionId: string, data: RecommendationMessageCreate) =>
    apiRequest<RecommendationMessage>(`/recommendations/sessions/${sessionId}/messages`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  selectItem: (sessionId: string, data: RecommendationSelectedItemCreate) =>
    apiRequest<RecommendationSelectedItem>(`/recommendations/sessions/${sessionId}/selected-items`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  selectedItems: (params?: {
    session_id?: string;
    buyer_intent_id?: string;
    seller_target_id?: string;
    relation_id?: string;
    include_canceled?: boolean;
    limit?: number;
    offset?: number;
  }) => apiRequest<RecommendationSelectedItem[]>(`/recommendations/selected-items${buildQuery(params || {})}`),
  sessionSelectedItems: (sessionId: string, params?: { include_canceled?: boolean }) =>
    apiRequest<RecommendationSelectedItem[]>(
      `/recommendations/sessions/${sessionId}/selected-items${buildQuery(params || {})}`,
    ),
  cancelSelectedItem: (selectedItemId: string) =>
    apiRequest<RecommendationSelectedItem>(`/recommendations/selected-items/${selectedItemId}/cancel`, {
      method: 'POST',
    }),
  createReport: (sessionId: string, data: RecommendationReportCreate = {}) =>
    apiRequest<RecommendationReport>(`/recommendations/sessions/${sessionId}/reports`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  createReportJob: (sessionId: string, data: RecommendationReportCreate = {}) =>
    apiRequest<RecommendationReportJob>(`/recommendations/sessions/${sessionId}/reports/jobs`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  reports: (sessionId: string, params?: { limit?: number; offset?: number }) =>
    apiRequest<RecommendationReport[]>(`/recommendations/sessions/${sessionId}/reports${buildQuery(params || {})}`),
  getReport: (reportId: string) => apiRequest<RecommendationReport>(`/recommendations/reports/${reportId}`),
  page: () => apiRequest<RecommendationPage>('/recommendations/page'),
  createRerankJob: (sessionId: string) =>
    apiRequest<RecommendationRerankJob>(`/recommendations/sessions/${sessionId}/rerank-jobs`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
};
