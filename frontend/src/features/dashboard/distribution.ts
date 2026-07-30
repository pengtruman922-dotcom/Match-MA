import type { TargetProvinceCount } from '../../types/api';

/**
 * 固定分档，不做数量编码。
 *
 * 用固定阈值而不是按当前最大值分位，是为了让同一个颜色在两次打开之间含义
 * 不变——大屏上一个省从深色退成浅色应该意味着标的少了，而不是别的省多了。
 * 代价是库存量级整体上一个台阶后需要回来调这张表。
 */
export interface DistributionTier {
  /** 该档的下限（含）。 */
  min: number;
  label: string;
  fill: string;
  /** 图例与省份描边共用，保证浅色档在白底上仍有轮廓。 */
  stroke: string;
}

export const PROVINCE_TIERS: DistributionTier[] = [
  { min: 11, label: '11 个以上', fill: '#D4000F', stroke: '#9A000B' },
  { min: 6, label: '6–10 个', fill: '#FF7068', stroke: '#D4000F' },
  { min: 3, label: '3–5 个', fill: '#FFCDC9', stroke: '#FF7068' },
  { min: 1, label: '1–2 个', fill: '#FFE4E2', stroke: '#FFA8A1' },
];

/**
 * 买家侧另一套阈值，档位更密。
 *
 * 买家主体总数只有标的的一半不到，单省最多 2 个；套用标的的阈值会让整张图
 * 全部落在最浅一档，等于没有信息。分档表按指标各配一份，「同一个颜色含义不变」
 * 的约束在每张图内部仍然成立。配色也换成金色，避免两张红图叠在一起认错。
 */
export const BUYER_PROVINCE_TIERS: DistributionTier[] = [
  { min: 7, label: '7 家以上', fill: '#CA8A04', stroke: '#A16207' },
  { min: 4, label: '4–6 家', fill: '#FACC15', stroke: '#CA8A04' },
  { min: 2, label: '2–3 家', fill: '#FDE047', stroke: '#FACC15' },
  { min: 1, label: '1 家', fill: '#FEF9C3', stroke: '#FDE047' },
];

export const EMPTY_TIER: DistributionTier = {
  min: 0,
  label: '暂无',
  fill: '#F3F4F6',
  stroke: '#D1D5DB',
};

export function tierOf(count: number, tiers: DistributionTier[] = PROVINCE_TIERS): DistributionTier {
  return tiers.find((tier) => count >= tier.min) ?? EMPTY_TIER;
}

/**
 * 省名 → 数量。
 *
 * 后端返回的是数据库里的原样取值，底图用的是 DataV 的规范省名；两边目前都是
 * 「江苏省 / 北京市 / 内蒙古自治区」这一套全称，所以这里只做一次去后缀的兜底
 * 匹配，不引入省份别名字典——真出现对不上的值，宁可在 unmatched 里显出来，
 * 也不要静默归零。
 */
export interface ProvinceLookup {
  countOf: (provinceName: string) => number;
  unmatched: TargetProvinceCount[];
}

function shortName(value: string): string {
  return value.replace(/(维吾尔自治区|壮族自治区|回族自治区|自治区|特别行政区|省|市)$/u, '');
}

export function buildProvinceLookup(
  provinces: TargetProvinceCount[],
  mapNames: string[],
): ProvinceLookup {
  const byExact = new Map<string, number>();
  const byShort = new Map<string, number>();
  for (const item of provinces) {
    byExact.set(item.province, item.count);
    byShort.set(shortName(item.province), item.count);
  }
  const mapExactNames = new Set(mapNames);
  const mapShortNames = new Set(mapNames.map(shortName));
  const unmatched = provinces.filter(
    (item) => !mapExactNames.has(item.province) && !mapShortNames.has(shortName(item.province)),
  );
  return {
    countOf: (provinceName: string) =>
      byExact.get(provinceName) ?? byShort.get(shortName(provinceName)) ?? 0,
    unmatched,
  };
}

/** 条形图按最长条归一化；总数为 0 时不除零。 */
export function barWidth(count: number, max: number): string {
  if (max <= 0) return '0%';
  return `${Math.max(2, Math.round((count / max) * 100))}%`;
}
