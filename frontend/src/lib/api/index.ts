import type {
  SellerTarget,
  SellerTargetCreate,
  SellerTargetUpdate,
  BackgroundJob,
  BusinessUpdate,
  BusinessUpdateCreate,
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
  RecommendationSelectedItemCreate,
  UpdateLog,
  WorkbenchData,
} from '../../types/api';
import { apiRequest, buildQuery } from './client';

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
  process: (id: string) =>
    apiRequest<{ job_id: string; job_type: string; status: string; queue_name: string; business_update_id: string }>(
      `/business-updates/${id}/process`,
      { method: 'POST' }
    ),
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
  list: (params?: { status?: string; job_type?: string; queue_name?: string; entity_type?: string; entity_id?: string; limit?: number; offset?: number }) =>
    apiRequest<BackgroundJob[]>(`/background-jobs${buildQuery(params || {})}`),
  get: (id: string) => apiRequest<BackgroundJob>(`/background-jobs/${id}`),
  traces: (id: string) => apiRequest<BusinessUpdateDebugBundle['traces']>(`/background-jobs/${id}/traces`),
};

export const updateLogs = {
  list: (params: { entity_type: string; entity_id: string }) =>
    apiRequest<UpdateLog[]>(`/update-logs${buildQuery(params)}`),
};

export const workbench = {
  get: () => apiRequest<WorkbenchData>('/workbench'),
};

export const debugApi = {
  businessUpdate: (id: string) => apiRequest<BusinessUpdateDebugBundle>(`/debug/business-updates/${id}`),
};

export const recommendations = {
  candidates: (data: RecommendationCandidateRequest) =>
    apiRequest<RecommendationCandidateResponse>('/recommendations/candidates', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  selectItem: (sessionId: string, data: RecommendationSelectedItemCreate) =>
    apiRequest<{ id: string }>(`/recommendations/sessions/${sessionId}/selected-items`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
};
