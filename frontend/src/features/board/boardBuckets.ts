/**
 * 撮合看板的分桶、分组与排序——全是纯函数，不碰 React，不发请求。
 *
 * 卡片单元仍是一条关系（1 标的 × 1 意向）。这里的列映射和「同主体折叠」
 * 只是呈现层的事，不改领域模型：同一个标的同时出现在多列是正确的信息。
 *
 * ⚠ 列映射不要复用 relationLabels 的 isRelationEnded——那里把 deal_closed
 * 算作已结束，直接用会把成交卡冲进底部抽屉。看板需要自己这套 BUCKET_BY_STATUS。
 * stale 判定倒是可以复用：「已结束不预警」的语义两边一致。
 */
import type { RelationBoardCard } from '../../types/api';
import { daysSince, isStaleRelation } from '../relations/relationLabels';

export type BoardView = 'target' | 'intent';
export type BoardOwnership = 'all' | 'involved' | 'sole';
export type BoardBucket = 'early' | 'deep' | 'won' | 'closed';
export type BoardMainBucket = Exclude<BoardBucket, 'closed'>;

/** D1 状态映射：九个状态取值不变，只改看板分组。 */
const BUCKET_BY_STATUS: Record<string, BoardBucket> = {
  recommended: 'early',
  interested: 'early',
  in_discussion: 'early',
  due_diligence: 'deep',
  agreement: 'deep',
  deal_closed: 'won',
  paused: 'closed',
  not_interested: 'closed',
  lost: 'closed',
};

/**
 * 同一桶内的深浅排名——跨桶比较没有意义，只用来选摞头的代表状态、
 * 排组内成员，以及切「已推荐」尾巴块。
 */
const DEPTH_IN_BUCKET: Record<string, number> = {
  recommended: 1,
  interested: 2,
  in_discussion: 3,
  due_diligence: 1,
  agreement: 2,
  deal_closed: 1,
  not_interested: 1,
  lost: 2,
  paused: 3,
};

export const BOARD_COLUMNS: Array<{ key: BoardMainBucket; label: string; hint: string }> = [
  { key: 'early', label: '初步接触', hint: '已推荐 / 有意向 / 沟通中' },
  { key: 'deep', label: '深度交流', hint: '尽调中 / 协议阶段' },
  { key: 'won', label: '已成交', hint: '唯一产出，独立成列' },
];

/** 抽屉内的分组次序：暂停排在最前（还能救），后两个是真终态。 */
const CLOSED_STATUS_ORDER: string[] = ['paused', 'not_interested', 'lost'];

/**
 * 未知状态兜底进「初步接触」——卡片上仍会显示原始状态值，
 * 宁可摆错列也不能让卡片凭空消失。
 */
export function bucketOf(status: string): BoardBucket {
  return BUCKET_BY_STATUS[status] || 'early';
}

function depthOf(status: string): number {
  return DEPTH_IN_BUCKET[status] || 0;
}

// ---------------------------------------------------------------- 视角取值

export function subjectIdOf(card: RelationBoardCard, view: BoardView): string {
  return view === 'target' ? card.seller_target_id : card.buyer_intent_id;
}

export function subjectNameOf(card: RelationBoardCard, view: BoardView): string {
  return (view === 'target' ? card.seller_target_name : card.buyer_intent_name) || '未命名';
}

/** 卡片第三行的字段名：标的视角看意向，意向视角看标的（第二行固定是买家）。 */
export function counterpartLabel(view: BoardView): string {
  return view === 'target' ? '意向' : '标的';
}

export function counterpartNameOf(card: RelationBoardCard, view: BoardView): string {
  return (view === 'target' ? card.buyer_intent_name : card.seller_target_name) || '-';
}

/**
 * 卡片跳转目标：标的视角进标的详情，意向视角进意向详情，都落在「推进」tab。
 * `relation` 参数留给 B3——ProgressPanel 接上 initialOpenId 后即可自动展开对应时间线，
 * 现在多带一个 query 参数无副作用。
 */
export function cardPath(card: RelationBoardCard, view: BoardView): string {
  const base =
    view === 'target' ? `/targets/${card.seller_target_id}` : `/buyer-intents/${card.buyer_intent_id}`;
  return `${base}?tab=progress&relation=${card.id}`;
}

// ---------------------------------------------------------------- 时间

/** 与 relationLabels.daysSince 同一套解析约定（后端时间戳来自 `::text`）。 */
function activityTime(card: RelationBoardCard): number {
  if (!card.last_activity_at) return 0;
  const parsed = new Date(card.last_activity_at).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

/** 触发「N 天无动态」预警时返回天数，否则 null。已结束的关系永远不预警。 */
export function cardStaleDays(card: RelationBoardCard): number | null {
  if (!isStaleRelation(card.status, card.last_event_at)) return null;
  return daysSince(card.last_event_at);
}

/** 距最近活动的天数，用于卡片右下角的「N天前」。 */
export function cardActivityDays(card: RelationBoardCard): number | null {
  return daysSince(card.last_activity_at);
}

// ---------------------------------------------------------------- 分组

export interface BoardGroup {
  subjectId: string;
  subjectName: string;
  /** 组内成员：固定按最近活动降序。 */
  relations: RelationBoardCard[];
  /** 组内最深状态，用来切尾巴块并给摞头选代表。 */
  deepestStatus: string;
  /** 组内最新活动时间戳（毫秒），排序用。 */
  latestActivityTime: number;
  /** 组内真正按 last_activity_at 最新的成员，供收起摞的“最近”摘要使用。 */
  latestRelation: RelationBoardCard;
  /** 组内最久无动态的天数；没有成员触发预警时为 null。 */
  staleDays: number | null;
  /** 组内各状态条数，摞头收起时显示「有意向2 · 已推荐2」。 */
  statusCounts: Array<{ status: string; count: number }>;
}

function toGroup(subjectId: string, view: BoardView, members: RelationBoardCard[]): BoardGroup {
  const relations = [...members].sort(
    (a, b) => activityTime(b) - activityTime(a) || depthOf(b.status) - depthOf(a.status),
  );
  const deepestRelation = relations.reduce((deepest, card) =>
    depthOf(card.status) > depthOf(deepest.status) ? card : deepest,
  );
  const latestRelation = relations[0];

  const counts = new Map<string, number>();
  let staleDays: number | null = null;
  for (const card of relations) {
    counts.set(card.status, (counts.get(card.status) || 0) + 1);
    const days = cardStaleDays(card);
    if (days !== null && (staleDays === null || days > staleDays)) staleDays = days;
  }

  return {
    subjectId,
    subjectName: subjectNameOf(relations[0], view),
    relations,
    deepestStatus: deepestRelation.status,
    latestActivityTime: activityTime(latestRelation),
    latestRelation,
    staleDays,
    statusCounts: [...counts.entries()]
      .map(([status, count]) => ({ status, count }))
      .sort((a, b) => depthOf(b.status) - depthOf(a.status)),
  };
}

function groupBySubject(
  cards: RelationBoardCard[],
  view: BoardView,
): BoardGroup[] {
  const bySubject = new Map<string, RelationBoardCard[]>();
  for (const card of cards) {
    const key = subjectIdOf(card, view);
    const existing = bySubject.get(key);
    if (existing) existing.push(card);
    else bySubject.set(key, [card]);
  }

  const groups = [...bySubject.entries()].map(([subjectId, members]) =>
    toGroup(subjectId, view, members),
  );

  groups.sort((a, b) => b.latestActivityTime - a.latestActivityTime);
  return groups;
}

// ---------------------------------------------------------------- 筛选与计数

function matchesQuery(card: RelationBoardCard, needle: string): boolean {
  if (!needle) return true;
  return [card.seller_target_name, card.buyer_name, card.buyer_intent_name].some((name) =>
    (name || '').toLowerCase().includes(needle),
  );
}

export interface BoardColumnData {
  key: BoardMainBucket;
  label: string;
  hint: string;
  /** 主区：早期列里 deepest 是「有意向 / 沟通中」的组，其余列的全部组。 */
  main: BoardGroup[];
  /** 尾巴块：只有早期列非空，deepest === recommended，默认收起（D7）。 */
  tail: BoardGroup[];
  /** 筛后关系数（D9 主计数）。 */
  relationCount: number;
  /** 筛后主体数（D9 次计数）。 */
  subjectCount: number;
  /** 被客户端筛选挡掉的关系数，列头注明「隐藏 N」，别让人以为数据丢了。 */
  hiddenCount: number;
}

export interface BoardClosedData {
  sections: Array<{ status: string; groups: BoardGroup[]; relationCount: number }>;
  relationCount: number;
  hiddenCount: number;
}

export interface BoardModel {
  columns: BoardColumnData[];
  closed: BoardClosedData;
  /** 筛后总关系数与总主体数（跨全部桶去重）。 */
  totalRelations: number;
  totalSubjects: number;
  hiddenRelations: number;
  staleRelations: number;
}

/**
 * 一次算完看板要显示的全部结构。
 *
 * 搜索刻意在**内存里**做：数据已经整块加载，这样按键即出结果不用重新取数；
 * 更重要的是筛前总数还留在手上，D9 的「隐藏 N」才有得算——交给后端 q 就没了。
 * 代价是只能匹配卡片上那三个名字，匹配不到后端 q 覆盖的 last_event_summary /
 * status_reason，这点在搜索框 placeholder 里说明。
 */
export function buildBoard(
  cards: RelationBoardCard[],
  options: { view: BoardView; q?: string; hideStale?: boolean },
): BoardModel {
  const { view } = options;
  const needle = (options.q || '').trim().toLowerCase();
  const hideStale = options.hideStale === true;

  const totalByBucket: Record<BoardBucket, number> = { early: 0, deep: 0, won: 0, closed: 0 };
  const visibleByBucket: Record<BoardBucket, RelationBoardCard[]> = {
    early: [],
    deep: [],
    won: [],
    closed: [],
  };
  const subjects = new Set<string>();
  let staleRelations = 0;
  let hiddenRelations = 0;

  for (const card of cards) {
    const bucket = bucketOf(card.status);
    totalByBucket[bucket] += 1;
    const stale = cardStaleDays(card) !== null;
    if (!matchesQuery(card, needle) || (hideStale && stale)) {
      hiddenRelations += 1;
      continue;
    }
    visibleByBucket[bucket].push(card);
    subjects.add(subjectIdOf(card, view));
    if (stale) staleRelations += 1;
  }

  const columns = BOARD_COLUMNS.map((meta) => {
    const groups = groupBySubject(visibleByBucket[meta.key], view);
    const isEarly = meta.key === 'early';
    return {
      ...meta,
      main: isEarly ? groups.filter((group) => group.deepestStatus !== 'recommended') : groups,
      tail: isEarly ? groups.filter((group) => group.deepestStatus === 'recommended') : [],
      relationCount: visibleByBucket[meta.key].length,
      subjectCount: groups.length,
      hiddenCount: totalByBucket[meta.key] - visibleByBucket[meta.key].length,
    };
  });

  // 抽屉的分组次序以 CLOSED_STATUS_ORDER 为准，但没列进去的状态也要兜住，不能吞卡。
  const presentStatuses = [...new Set(visibleByBucket.closed.map((card) => card.status))];
  const orderedStatuses = [
    ...CLOSED_STATUS_ORDER.filter((status) => presentStatuses.includes(status)),
    ...presentStatuses.filter((status) => !CLOSED_STATUS_ORDER.includes(status)),
  ];
  const sections = orderedStatuses.map((status) => {
    const subset = visibleByBucket.closed.filter((card) => card.status === status);
    return { status, groups: groupBySubject(subset, view), relationCount: subset.length };
  });

  return {
    columns,
    closed: {
      sections,
      relationCount: visibleByBucket.closed.length,
      hiddenCount: totalByBucket.closed - visibleByBucket.closed.length,
    },
    totalRelations: cards.length - hiddenRelations,
    totalSubjects: subjects.size,
    hiddenRelations,
    staleRelations,
  };
}
