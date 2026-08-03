/**
 * 撮合关系的状态与事件类型标签、分组与配色。
 *
 * 进度的单元是「买家意向 × 标的」这一对关系，不是任何单个实体。
 * 这里是两侧详情页「推进」tab 共用的展示层。取值集合由后端
 * /relations-meta 提供（对齐 DB check 约束）；这里仅保留状态视觉与阶段判断。
 */

export const RELATION_STATUS_LABELS: Record<string, string> = {
  recommended: '已推荐',
  interested: '有意向',
  in_discussion: '沟通中',
  due_diligence: '尽调中',
  agreement: '协议阶段',
  deal_closed: '已成交',
  not_interested: '不感兴趣',
  paused: '暂停',
  lost: '终止',
};

const ENDED_STATUSES = new Set(['deal_closed', 'not_interested', 'paused', 'lost']);

/** 超过这个天数没有任何动态的活跃关系，卡片上给「无动态」预警。 */
export const STALE_RELATION_DAYS = 14;

export function relationStatusLabel(status: string): string {
  return RELATION_STATUS_LABELS[status] || status;
}

export function isRelationEnded(status: string): boolean {
  return ENDED_STATUSES.has(status);
}

export function relationStatusClass(status: string): string {
  if (status === 'deal_closed') return 'bg-emerald-50 text-emerald-700';
  if (status === 'not_interested' || status === 'lost') return 'bg-gray-100 text-gray-500';
  if (status === 'paused') return 'bg-amber-50 text-amber-700';
  if (status === 'due_diligence' || status === 'agreement') return 'bg-brand-50 text-brand-700';
  return 'bg-blue-50 text-blue-700';
}

/** 距今天数（负值/非法返回 null）。 */
export function daysSince(iso: string | null): number | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  const diff = Date.now() - then;
  if (diff < 0) return null;
  return Math.floor(diff / (1000 * 60 * 60 * 24));
}

export function isStaleRelation(status: string, lastEventAt: string | null): boolean {
  if (isRelationEnded(status)) return false;
  const days = daysSince(lastEventAt);
  return days !== null && days >= STALE_RELATION_DAYS;
}
