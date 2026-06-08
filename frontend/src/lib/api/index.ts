import type {
  SellerTarget,
  SellerTargetCreate,
  SellerTargetUpdate,
  AttachmentUploadPolicy,
  BackgroundJob,
  BackgroundJobRetryPreview,
  BusinessUpdate,
  BusinessUpdateCreate,
  BusinessUpdateReviewPage,
  BusinessUpdateUploadResponse,
  BuyerIntent,
  BuyerIntentCreate,
  BuyerIntentTargetExclusion,
  BuyerIntentUpdate,
  BuyerParty,
  BuyerPartyCreate,
  BuyerSellerRelation,
  BusinessUpdateDebugBundle,
  ExtractedAction,
  ExtractedActionCreate,
  RelationEvent,
  RecommendationCandidateRequest,
  RecommendationCandidateResponse,
  RecommendationMessage,
  RecommendationMessageCreate,
  RecommendationReport,
  RecommendationReportCreate,
  RecommendationReportJob,
  RecommendationSelectedItem,
  RecommendationSelectedItemCreate,
  RecommendationSessionDebugBundle,
  RecommendationSession,
  RecommendationSessionBundle,
  UpdateLog,
  WorkbenchData,
  WorkbenchTaskBoardData,
  FailureSummary,
  QueueSummary,
} from '../../types/api';
import type { AuthUser, LoginResponse } from '../auth';
import { apiRequest, buildQuery } from './client';

export const auth = {
  login: (data: { username: string; password: string }) =>
    apiRequest<LoginResponse>('/auth/login', { method: 'POST', body: JSON.stringify(data) }),
  me: () => apiRequest<AuthUser>('/auth/me'),
};

export const sellerTargets = {
  list: (params?: { q?: string; limit?: number; offset?: number }) =>
    apiRequest<SellerTarget[]>(`/seller-targets${buildQuery(params || {})}`),
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
  delete: (id: string) => apiRequest<{ status: string }>(`/seller-targets/${id}`, { method: 'DELETE' }),
};

export const buyerParties = {
  list: (params?: { q?: string; limit?: number; offset?: number }) =>
    apiRequest<BuyerParty[]>(`/buyer-parties${buildQuery(params || {})}`),
  get: (id: string) => apiRequest<BuyerParty>(`/buyer-parties/${id}`),
  create: (data: BuyerPartyCreate) =>
    apiRequest<BuyerParty>('/buyer-parties', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<BuyerPartyCreate>) =>
    apiRequest<BuyerParty>(`/buyer-parties/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: (id: string) => apiRequest<{ status: string }>(`/buyer-parties/${id}`, { method: 'DELETE' }),
  intents: (id: string) => apiRequest<BuyerIntent[]>(`/buyer-parties/${id}/intents`),
};

export const buyerIntents = {
  list: (params?: { q?: string; buyer_party_id?: string; limit?: number; offset?: number }) =>
    apiRequest<BuyerIntent[]>(`/buyer-intents${buildQuery(params || {})}`),
  get: (id: string) => apiRequest<BuyerIntent>(`/buyer-intents/${id}`),
  create: (data: BuyerIntentCreate) =>
    apiRequest<BuyerIntent>('/buyer-intents', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: BuyerIntentUpdate) =>
    apiRequest<BuyerIntent>(`/buyer-intents/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: (id: string) => apiRequest<{ status: string }>(`/buyer-intents/${id}`, { method: 'DELETE' }),
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
  process: (id: string) =>
    apiRequest<{ job_id: string; job_type: string; status: string; queue_name: string; business_update_id: string }>(
      `/business-updates/${id}/process`,
      { method: 'POST' }
    ),
};

export const attachments = {
  uploadPolicy: () => apiRequest<AttachmentUploadPolicy>('/attachments/upload-policy'),
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
};

export const backgroundJobs = {
  list: (params?: {
    status?: string;
    job_type?: string;
    queue_name?: string;
    entity_type?: string;
    entity_id?: string;
    include_ignored?: boolean;
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
  summaryFailures: (params?: { lookback_hours?: number; limit?: number; include_ignored?: boolean }) =>
    apiRequest<FailureSummary>(`/background-jobs/summary/failures${buildQuery(params || {})}`),
  summaryQueues: (params?: { include_empty?: boolean; include_ignored?: boolean; lookback_hours?: number }) =>
    apiRequest<QueueSummary>(`/background-jobs/summary/queues${buildQuery(params || {})}`),
};

export const updateLogs = {
  list: (params: { entity_type: string; entity_id: string }) =>
    apiRequest<UpdateLog[]>(`/update-logs${buildQuery(params)}`),
};

export const workbench = {
  get: () => apiRequest<WorkbenchData>('/workbench'),
  taskBoard: () => apiRequest<WorkbenchTaskBoardData>('/workbench/task-board'),
};

export const debugApi = {
  businessUpdate: (id: string) => apiRequest<BusinessUpdateDebugBundle>(`/debug/business-updates/${id}`),
  recommendationSession: (id: string) =>
    apiRequest<RecommendationSessionDebugBundle>(`/debug/recommendation-sessions/${id}`),
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
};
