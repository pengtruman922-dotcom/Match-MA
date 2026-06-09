import { businessUpdates, extractedActions, workbench } from './api';
import type {
  BusinessUpdate,
  ExtractedAction,
  FailureSummary,
  QueueSummary,
  WorkbenchActivity,
  WorkbenchOverview,
} from '../types/api';

export interface ActionGroup {
  key: string;
  label: string;
  count: number;
  items: ExtractedAction[];
}

export interface WorkbenchData {
  groups: ActionGroup[];
  recentUpdates: BusinessUpdate[];
  recentActivity: WorkbenchActivity[];
  overview: WorkbenchOverview | null;
  failureSummary: FailureSummary | null;
  queueSummary: QueueSummary | null;
  loading: boolean;
}

function categorizeAction(action: ExtractedAction): string {
  if (action.target_entity_type === 'seller_target') {
    if (action.action_type === 'seller_fact_update') return 'seller_update_review';
    if (action.action_type === 'seller_event') return 'seller_update_review';
  }
  if (action.target_entity_type === 'buyer_intent') return 'buyer_intent_review';
  if (action.action_type === 'buyer_seller_relation_update') return 'relation_progress_review';
  return 'parse_exception';
}

const GROUP_LABELS: Record<string, string> = {
  seller_update_review: '标的自动更新待复核',
  buyer_intent_review: '买家意向自动更新待复核',
  relation_progress_review: '关系进展待复核',
  parse_exception: '解析异常',
};

const GROUP_ORDER = [
  'seller_update_review',
  'buyer_intent_review',
  'relation_progress_review',
  'parse_exception',
];

export async function fetchWorkbenchData(): Promise<Omit<WorkbenchData, 'loading'>> {
  try {
    const data = await workbench.taskBoard();
    return {
      groups: data.groups,
      recentUpdates: [],
      recentActivity: data.recent_activity,
      overview: data.overview,
      failureSummary: data.failure_summary,
      queueSummary: data.queue_summary,
    };
  } catch {
    // Keep the UI usable against older API deployments while Railway catches up.
  }

  const [actions, updates] = await Promise.all([
    extractedActions.list({ review_status: 'pending_review', limit: 50 }),
    businessUpdates.list({ limit: 8 }),
  ]);

  const grouped: Record<string, ExtractedAction[]> = {};
  for (const action of actions) {
    const key = categorizeAction(action);
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(action);
  }

  const groups: ActionGroup[] = GROUP_ORDER.map((key) => ({
    key,
    label: GROUP_LABELS[key] || key,
    count: grouped[key]?.length || 0,
    items: grouped[key] || [],
  })).filter((g) => g.count > 0);

  return {
    groups,
    recentUpdates: updates,
    recentActivity: updates.map((update) => ({
      activity_type: 'business_update',
      entity_id: update.id,
      status: update.processing_status,
      activity_label: businessUpdateActivityLabel(update),
      object_name: '未绑定对象',
      summary: businessUpdateStatusLabel(update.processing_status),
      title: `${businessUpdateActivityLabel(update)}：未绑定对象`,
      subtitle: businessUpdateStatusLabel(update.processing_status),
      happened_at: update.created_at,
      route: `/updates/${update.id}`,
    })),
    overview: null,
    failureSummary: null,
    queueSummary: null,
  };
}

function businessUpdateActivityLabel(update: BusinessUpdate): string {
  if (update.processing_status === 'failed') return '解析异常';
  if (update.bound_seller_target_ids_json.length > 0) return '标的更新';
  if (update.bound_buyer_party_ids_json.length > 0 || update.bound_buyer_intent_ids_json.length > 0) return '买家更新';
  return '业务更新';
}

function businessUpdateStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: '处理中',
    processing: '处理中',
    parsed: '已解析，待复核',
    partially_applied: '已部分应用',
    applied: '已应用',
    failed: '需要查看异常',
  };
  return labels[status] || status;
}
