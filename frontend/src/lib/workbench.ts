import { businessUpdates, extractedActions, workbench } from './api';
import type { BusinessUpdate, ExtractedAction, FailureSummary, QueueSummary } from '../types/api';

export interface ActionGroup {
  key: string;
  label: string;
  count: number;
  items: ExtractedAction[];
}

export interface WorkbenchData {
  groups: ActionGroup[];
  recentUpdates: BusinessUpdate[];
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
    const data = await workbench.get();
    return {
      groups: data.groups,
      recentUpdates: data.recent_updates,
      failureSummary: null,
      queueSummary: null,
    };
  } catch {
    // Keep the Bolt UI usable against older API deployments while Railway catches up.
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

  return { groups, recentUpdates: updates, failureSummary: null, queueSummary: null };
}
