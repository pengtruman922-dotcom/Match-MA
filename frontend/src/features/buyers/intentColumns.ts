/**
 * 买家列表的列定义与用户偏好。
 *
 * 19 列宽 2088px，谁都不会全都要看 —— 但「该看哪几列」因人因事而异（找标的时看
 * 需求那半边，做调研排期时看买家那半边）。所以列的显示与顺序是**每个人自己的**
 * 设置，存在浏览器里。
 *
 * 偏好只存「顺序 + 隐藏了哪些」，不存整份列表：这样以后新增一列时老用户会自动
 * 看到它（按默认位置插入），而不是因为存了一份旧快照就永远看不见新列。
 */

export type IntentColumnKey =
  | 'grade'
  | 'readiness'
  | 'ownership'
  | 'province'
  | 'listedStatus'
  | 'stockCode'
  | 'businessTags'
  | 'worth'
  | 'revenue'
  | 'wantIndustry'
  | 'wantListing'
  | 'wantWorth'
  | 'wantRevenue'
  | 'wantRegion'
  | 'updatedAt'
  | 'owner'
  | 'contact';

export interface IntentColumnDef {
  key: IntentColumnKey;
  label: string;
  /** 表头分组：买家自身条件 vs 需求条件。用于列管理面板分区与表头配色。 */
  side: 'buyer' | 'intent' | 'meta';
  /** Tailwind 列宽类，与 colgroup 一一对应。 */
  width: string;
  align?: 'left' | 'center';
  title?: string;
}

/**
 * 默认顺序即声明顺序。勾选框与买家名称是冻结列、操作是右冻结列，
 * 三者不可隐藏也不参与排序，所以不在这张表里。
 */
export const INTENT_COLUMNS: readonly IntentColumnDef[] = [
  { key: 'grade', label: '级别', side: 'meta', width: 'w-14', align: 'center' },
  {
    key: 'readiness',
    label: '状态',
    side: 'meta',
    width: 'w-16',
    align: 'center',
    title: '左点＝买家资料，右点＝需求解析。两点都亮才能进推荐。',
  },
  { key: 'ownership', label: '性质', side: 'buyer', width: 'w-20' },
  { key: 'province', label: '省份', side: 'buyer', width: 'w-20' },
  { key: 'listedStatus', label: '上市状态', side: 'buyer', width: 'w-20' },
  { key: 'stockCode', label: '代码', side: 'buyer', width: 'w-20' },
  { key: 'businessTags', label: '主营业务', side: 'buyer', width: 'w-40' },
  { key: 'worth', label: '市值/估值', side: 'buyer', width: 'w-24' },
  { key: 'revenue', label: '营收', side: 'buyer', width: 'w-20' },
  { key: 'wantIndustry', label: '关注业务', side: 'intent', width: 'w-40' },
  { key: 'wantListing', label: '上市要求', side: 'intent', width: 'w-20' },
  { key: 'wantWorth', label: '市值/估值要求', side: 'intent', width: 'w-24' },
  { key: 'wantRevenue', label: '营收要求', side: 'intent', width: 'w-20' },
  { key: 'wantRegion', label: '区域要求', side: 'intent', width: 'w-28' },
  { key: 'updatedAt', label: '更新时间', side: 'meta', width: 'w-[88px]' },
  { key: 'owner', label: '负责人', side: 'meta', width: 'w-20' },
  {
    key: 'contact',
    label: '对接人',
    side: 'buyer',
    width: 'w-20',
    title: '买家侧我方对接人，与「负责人」（记录归属）不是一回事',
  },
];

export const INTENT_COLUMN_BY_KEY: Record<IntentColumnKey, IntentColumnDef> = Object.fromEntries(
  INTENT_COLUMNS.map((column) => [column.key, column]),
) as Record<IntentColumnKey, IntentColumnDef>;

const STORAGE_KEY = 'match_ma_intent_columns_v1';

export interface IntentColumnPrefs {
  /** 用户调整过的顺序。只记出现过的键，新列按默认位置补进去。 */
  order: IntentColumnKey[];
  /** 被隐藏的列。存「隐藏」而不是「显示」，这样新增列默认可见。 */
  hidden: IntentColumnKey[];
}

const EMPTY_PREFS: IntentColumnPrefs = { order: [], hidden: [] };

function isKey(value: unknown): value is IntentColumnKey {
  return typeof value === 'string' && value in INTENT_COLUMN_BY_KEY;
}

export function readColumnPrefs(): IntentColumnPrefs {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return EMPTY_PREFS;
    const parsed = JSON.parse(raw) as Partial<IntentColumnPrefs>;
    return {
      // 逐项校验：存量里可能有已经改名或删掉的列键，原样吃进来会渲染出空列。
      order: (parsed.order || []).filter(isKey),
      hidden: (parsed.hidden || []).filter(isKey),
    };
  } catch {
    // 隐私模式下 localStorage 读取会直接抛，不能让它把整个列表带崩。
    return EMPTY_PREFS;
  }
}

export function writeColumnPrefs(prefs: IntentColumnPrefs): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    // 存不下就算了：列设置是便利，不是数据。
  }
}

/**
 * 偏好 + 默认 → 这一次要渲染的列。
 *
 * 顺序里没提到的列**按默认位置插回去**，而不是追加到末尾：新增一列时，
 * 老用户看到的位置和新用户一致。
 */
export function resolveColumns(prefs: IntentColumnPrefs): IntentColumnDef[] {
  const ordered: IntentColumnDef[] = [];
  const placed = new Set<IntentColumnKey>();
  for (const key of prefs.order) {
    const column = INTENT_COLUMN_BY_KEY[key];
    if (column && !placed.has(key)) {
      ordered.push(column);
      placed.add(key);
    }
  }
  INTENT_COLUMNS.forEach((column, index) => {
    if (placed.has(column.key)) return;
    // 插到它在默认顺序里的左邻居后面，找不到就放最前。
    let insertAt = 0;
    for (let step = index - 1; step >= 0; step -= 1) {
      const neighbour = ordered.findIndex((item) => item.key === INTENT_COLUMNS[step].key);
      if (neighbour !== -1) {
        insertAt = neighbour + 1;
        break;
      }
    }
    ordered.splice(insertAt, 0, column);
    placed.add(column.key);
  });
  const hidden = new Set(prefs.hidden);
  return ordered.filter((column) => !hidden.has(column.key));
}

/** 面板里要列出全部列（含隐藏的），顺序与表格一致。 */
export function resolveAllColumnsInOrder(prefs: IntentColumnPrefs): IntentColumnDef[] {
  return resolveColumns({ order: prefs.order, hidden: [] });
}

export function moveColumn(
  prefs: IntentColumnPrefs,
  from: IntentColumnKey,
  to: IntentColumnKey,
): IntentColumnPrefs {
  const current = resolveAllColumnsInOrder(prefs).map((column) => column.key);
  const fromIndex = current.indexOf(from);
  const toIndex = current.indexOf(to);
  if (fromIndex === -1 || toIndex === -1 || fromIndex === toIndex) return prefs;
  current.splice(toIndex, 0, ...current.splice(fromIndex, 1));
  return { ...prefs, order: current };
}

export function toggleColumn(prefs: IntentColumnPrefs, key: IntentColumnKey): IntentColumnPrefs {
  const hidden = new Set(prefs.hidden);
  if (hidden.has(key)) hidden.delete(key);
  else hidden.add(key);
  return { ...prefs, hidden: [...hidden] };
}

export function resetColumnPrefs(): IntentColumnPrefs {
  return { order: [], hidden: [] };
}
