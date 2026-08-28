import { Loader2 } from 'lucide-react';
import type { BuyerIntent, BuyerIntentParseStatus, BuyerParty, ConditionEffect } from '../../types/api';
import { valueLabel } from '../../lib/fieldLabels';
import { gradeClass, intentGrade, intentGradeLabel } from '../../lib/entityGrade';
import { formatCompactMoney, formatYuan } from '../../lib/format';

export function ParseStatusBadge({ item, parseStatus }: { item: BuyerIntent; parseStatus?: BuyerIntentParseStatus }) {
  const state = parseStatus?.processing_state || item.processing_state;
  const status = state?.overall_status || 'not_started';
  const isActive = status === 'processing';
  const color = status === 'processing'
    ? 'bg-blue-50 text-blue-700'
    : status === 'failed'
      ? 'bg-red-50 text-red-700'
      : status === 'succeeded'
        ? 'bg-emerald-50 text-emerald-700'
        : 'bg-gray-100 text-gray-500';
  const label = state?.status_label || '未解析';
  const title = state?.error_message || state?.stage_label || undefined;
  const needsCount = state?.needs_confirmation_count || 0;

  return (
    <span className="inline-flex flex-wrap items-center justify-center gap-1" title={title}>
      <span className={`inline-flex items-center gap-1 whitespace-nowrap px-2 py-0.5 text-xs font-medium ${color}`}>
        {isActive && <Loader2 className="h-3 w-3 animate-spin" />}
        {label}
      </span>
      {state?.stage_label && status !== 'succeeded' ? <span className="whitespace-nowrap text-[11px] text-gray-500">{state.stage_label}</span> : null}
      {needsCount > 0 && status === 'succeeded' ? <span className="whitespace-nowrap bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-700">{needsCount}项待确认</span> : null}
      {state?.review_status === 'reviewed' && status === 'succeeded' ? <span className="whitespace-nowrap bg-sky-50 px-1.5 py-0.5 text-[11px] text-sky-700">已人工复核</span> : null}
    </span>
  );
}

export function isActiveParseStatus(status: BuyerIntentParseStatus): boolean {
  return status.processing_state.overall_status === 'processing';
}

/** 必须条件实心、优先条件描边。 */
function ChipTag({ chip }: { chip: RequirementChip }) {
  const style = chip.effect === 'required'
    ? 'bg-gray-100 text-gray-700'
    : 'border border-gray-200 bg-white text-gray-500';
  return <span title={chip.title} className={`inline-block max-w-full truncate px-1.5 py-0.5 text-[11px] leading-4 ${style}`}>{chip.label}</span>;
}

export function RequirementCell({ item }: { item: BuyerIntent }) {
  const { industry, conditions } = requirementChips(item);

  if (!industry.length && !conditions.length) {
    const raw = item.raw_requirement_text?.trim();
    if (raw) {
      return <p className="line-clamp-2 text-xs italic leading-5 text-gray-400" title={raw}>{raw}</p>;
    }
    return <span className="text-xs text-gray-300">暂无结构化条件</span>;
  }

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-1">
        {industry.length
          ? industry.map((chip) => <ChipTag key={chip.key} chip={chip} />)
          : <span className="text-[11px] text-gray-300">行业未设置</span>}
      </div>
      <div className="flex flex-wrap items-center gap-1">
        {conditions.map((chip) => <ChipTag key={chip.key} chip={chip} />)}
      </div>
    </div>
  );
}

/** 空值统一长这样：一个灰破折号，别让空白看着像加载没完。 */
function Blank() {
  return <span className="text-gray-300">—</span>;
}

/** 买家侧的枚举单元（企业性质 / 上市状态）。`unknown` 与空等价，都当没填。 */
export function BuyerEnumCell({ value, column }: { value?: string | null; column: string }) {
  if (!value || value === 'unknown') return <Blank />;
  return <span className="text-xs text-gray-700">{valueLabel(column, value)}</span>;
}

/** 纯文本单元，过长省略，鼠标停留看全文。 */
export function TextCell({ value, className = 'text-gray-700' }: { value?: string | null; className?: string }) {
  const text = (value || '').trim();
  if (!text) return <Blank />;
  return <span className={`block truncate text-xs ${className}`} title={text}>{text}</span>;
}

/**
 * 主营业务：买家自己做什么。
 *
 * 标签可能有五六个，列宽放不下 —— 截断显示，`title` 给全量。这不是装饰字段：
 * 它就是深评「买方自身情况」块里的「主营业务」那一行，协同性判断靠它。
 */
export function BuyerTagsCell({ item }: { item: BuyerIntent }) {
  const tags = (item.buyer_business_tags_json || []).map(String).map((tag) => tag.trim()).filter(Boolean);
  if (!tags.length) return <Blank />;
  return (
    <span className="block truncate text-xs text-gray-700" title={tags.join('、')}>
      {tags.join('、')}
    </span>
  );
}

/**
 * 市值 / 估值：一个展示位两个来源。
 *
 * 上市看市值、非上市看估值 —— 与深评那个块、以及买家详情页同一条规则。分成两列的话
 * 任何一行都必然有一列是空的。
 */
export function BuyerWorthCell({ item }: { item: BuyerIntent }) {
  if (item.buyer_listed_status === 'listed' && item.buyer_market_cap_yuan) {
    return <span className="whitespace-nowrap text-xs text-gray-700">{formatCompactMoney(Number(item.buyer_market_cap_yuan))}</span>;
  }
  if (item.buyer_valuation_yuan) {
    return (
      <span className="whitespace-nowrap text-xs text-gray-700" title="估值">
        {formatCompactMoney(Number(item.buyer_valuation_yuan))}
        <span className="ml-0.5 text-[10px] text-gray-400">估</span>
      </span>
    );
  }
  return <Blank />;
}

/** 金额单元：营收这类单值。 */
export function MoneyCell({ value }: { value?: string | number | null }) {
  if (value === null || value === undefined || value === '') return <Blank />;
  const amount = Number(value);
  if (!Number.isFinite(amount)) return <Blank />;
  return <span className="whitespace-nowrap text-xs text-gray-700">{formatCompactMoney(amount)}</span>;
}

/** 关注行业：需求的可接受行业，一级为主、二级补充。 */
export function IntentIndustriesCell({ item }: { item: BuyerIntent }) {
  const primary = (item.industries_json || []).map(String).filter(Boolean);
  const secondary = (item.industry_l2_json || []).map(String).filter(Boolean);
  if (!primary.length && !secondary.length) return <Blank />;
  const all = [...primary, ...secondary];
  return (
    <span className="block truncate text-xs text-gray-700" title={all.join('、')}>
      {primary.length ? primary.join('、') : secondary.join('、')}
    </span>
  );
}

/**
 * 上市要求：买家想买上市的还是非上市的。
 *
 * `preferred` 是倾向、`acceptable` 是可接受集合，两者都在时显示倾向、悬停看全集。
 * 只显示 acceptable 会把「都可以但偏好上市」压成「都可以」。
 */
export function ListingWantedCell({ item }: { item: BuyerIntent }) {
  const acceptable = (item.acceptable_listed_status_json || []).map(String).filter(Boolean);
  const preferred = item.preferred_listed_status && item.preferred_listed_status !== 'unknown'
    ? item.preferred_listed_status
    : null;
  if (!preferred && !acceptable.length) return <Blank />;
  const full = acceptable.map((value) => valueLabel('preferred_listed_status', value)).join('、');
  if (preferred) {
    const label = valueLabel('preferred_listed_status', preferred);
    return (
      <span className="whitespace-nowrap text-xs text-gray-700" title={full ? `可接受：${full}` : undefined}>
        {label}
        {acceptable.length > 1 ? <span className="ml-0.5 text-[10px] text-gray-400">偏好</span> : null}
      </span>
    );
  }
  return <span className="block truncate text-xs text-gray-700" title={full}>{full}</span>;
}

/** 市值/估值要求：与买家侧同一个展示位规则，上市看市值区间、非上市看估值区间。 */
export function WorthWantedCell({ item }: { item: BuyerIntent }) {
  const wantsListed = item.preferred_listed_status === 'listed'
    || (item.acceptable_listed_status_json || []).map(String).includes('listed');
  const marketCap = moneyRange(item.min_market_cap_yuan, item.max_market_cap_yuan);
  const valuation = moneyRange(item.min_valuation_yuan, item.max_valuation_yuan);
  // 想买上市的就优先给市值区间；它没填就退回估值区间，而不是留白。
  const text = (wantsListed ? marketCap || valuation : valuation || marketCap);
  if (!text) return <Blank />;
  const isValuation = text === valuation && text !== marketCap;
  return (
    <span className="whitespace-nowrap text-xs text-gray-700" title={isValuation ? '估值要求' : '市值要求'}>
      {text}
      {isValuation ? <span className="ml-0.5 text-[10px] text-gray-400">估</span> : null}
    </span>
  );
}

function moneyRange(min?: string | number | null, max?: string | number | null): string {
  const low = min === null || min === undefined || min === '' ? null : Number(min);
  const high = max === null || max === undefined || max === '' ? null : Number(max);
  const lowOk = low !== null && Number.isFinite(low);
  const highOk = high !== null && Number.isFinite(high);
  if (lowOk && highOk) return `${formatCompactMoney(low)}–${formatCompactMoney(high)}`;
  if (lowOk) return `≥${formatCompactMoney(low)}`;
  if (highOk) return `≤${formatCompactMoney(high)}`;
  return '';
}

/** 营收要求：需求侧的营收下限。 */
export function RevenueWantedCell({ item }: { item: BuyerIntent }) {
  const value = item.min_revenue_yuan;
  if (value === null || value === undefined || value === '') return <Blank />;
  const amount = Number(value);
  if (!Number.isFinite(amount)) return <Blank />;
  return <span className="whitespace-nowrap text-xs text-gray-700">≥{formatCompactMoney(amount)}</span>;
}

/**
 * 区域要求：需求侧的省份。
 *
 * 结构化的 `region_constraints_json` 只有 12% 有值，而文本摘要 `region_scope_summary`
 * 有 64% —— 所以结构化没有时退回文本，宁可显示一句话也别让这一列大面积空白。
 * 退回时标灰，提示它没被结构化（初筛闸门只认结构化的那份）。
 */
export function RegionWantedCell({ item }: { item: BuyerIntent }) {
  const constraints = Array.isArray(item.region_constraints_json) ? item.region_constraints_json : [];
  const provinces = constraints
    // 排除项不是「它要哪里」，混进来会把「不要华北」显示成「华北」。
    .filter((entry) => (entry?.effect || 'preferred') !== 'excluded')
    .map((entry) => (entry?.province || '').trim())
    .filter(Boolean);
  const unique = [...new Set(provinces)];
  if (unique.length) {
    return <span className="block truncate text-xs text-gray-700" title={unique.join('、')}>{unique.join('、')}</span>;
  }
  const summary = (item.region_scope_summary || '').trim();
  if (!summary) return <Blank />;
  return (
    <span className="block truncate text-xs text-gray-400" title={`未结构化，原文：${summary}`}>{summary}</span>
  );
}

/**
 * 两个半边各自的就绪度。
 *
 * 匹配要同时用买家自身条件和它的要求，所以「这个买家为什么还进不了推荐」的答案
 * 只有两种：资料没补，或需求没解析。一列两个点就能回答，不用点进去查。
 */
export function ReadinessCell({ item, parseStatus }: { item: BuyerIntent; parseStatus?: BuyerIntentParseStatus }) {
  const state = parseStatus?.processing_state || item.processing_state;
  const parseOk = state?.overall_status === 'succeeded';
  const parseFailed = state?.overall_status === 'failed';
  const parsing = state?.overall_status === 'processing';
  const profileOk = Boolean(item.buyer_profile_ready);

  const hint = [
    profileOk ? '买家资料已补全' : '买家资料未补全，协同性类要求无法判断',
    parseFailed ? `需求解析失败：${state?.error_message || '未知原因'}`
      : parsing ? `需求解析中（${state?.stage_label || '进行中'}）`
      : parseOk ? '需求已解析' : '需求未解析',
  ].join('\n');

  return (
    <span className="inline-flex flex-col items-center gap-1" title={hint}>
      <span className="inline-flex items-center gap-1">
        <Dot filled={profileOk} label="买家资料" />
        <Dot filled={parseOk} failed={parseFailed} pending={parsing} label="需求解析" />
      </span>
      {parsing ? <span className="whitespace-nowrap text-[11px] text-blue-600">解析中</span> : null}
      {parseFailed ? <span className="whitespace-nowrap text-[11px] text-red-600">解析失败</span> : null}
      {parseOk && (state?.needs_confirmation_count || 0) > 0 ? (
        <span className="whitespace-nowrap bg-amber-50 px-1 text-[11px] text-amber-700">{state?.needs_confirmation_count}项待确认</span>
      ) : null}
    </span>
  );
}

function Dot({ filled, failed, pending, label }: { filled: boolean; failed?: boolean; pending?: boolean; label: string }) {
  const color = failed ? 'bg-red-500' : pending ? 'bg-blue-500 animate-pulse' : filled ? 'bg-emerald-500' : 'bg-gray-200';
  return <span aria-label={label} className={`inline-block h-2.5 w-2.5 rounded-full ${color}`} />;
}

/** 需求级别，也是推荐初筛的唯一闸门：E 不参与筛选，A-D 都参与。 */
export function IntentStatusBadge({ item }: { item: BuyerIntent }) {
  return (
    <span className={`text-xs px-2 py-0.5 font-medium ${gradeClass(intentGrade(item))}`}>
      {intentGradeLabel(item)}
    </span>
  );
}

export function PartyStatusBadge({ status }: { status: string }) {
  const color = status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-600';
  return <span className={`text-xs px-2 py-0.5 font-medium ${color}`}>{valueLabel('buyer_party_status', status)}</span>;
}

export function dedupMatchLabel(value: string): string {
  if (value === 'buyer_name') return '买家名称';
  if (value === 'alias') return '别名';
  return value;
}

/** 三级地区，与标的侧同一口径；缺失的层级留空而不是补占位。 */
export function partyLocationText(party: BuyerParty): string {
  return [party.location_province, party.location_city, party.location_district].filter(Boolean).join(' / ');
}

/**
 * 市值与估值是**一个展示位**：数据层是两列，用户看到的是一个位置。
 * 上市看市值，非上市/拟上市看估值，unknown 有哪个显示哪个。
 *
 * 数字必须带时间一起给：没有时间的财务数字是不可用的，
 * 不要为了版面把 as_of / 时点藏起来。
 */
export function partyMarketValue(party: BuyerParty): { label: string; value: string; asOf: string | null } | null {
  const marketCap = party.market_cap_yuan === null || party.market_cap_yuan === undefined
    ? null
    : { label: '市值', value: formatYuan(party.market_cap_yuan), asOf: party.market_cap_as_of };
  const valuation = party.valuation_yuan === null || party.valuation_yuan === undefined
    ? null
    : { label: '估值', value: formatYuan(party.valuation_yuan), asOf: party.valuation_date };
  if (party.listed_status === 'listed') return marketCap || valuation;
  if (party.listed_status === 'unlisted' || party.listed_status === 'pre_ipo') return valuation || marketCap;
  return marketCap || valuation;
}

/** 该显示哪一位的中文名，编辑态与展示态共用，避免两处判断漂开。 */
export function partyMarketValueField(party: BuyerParty): 'market_cap' | 'valuation' | 'both' {
  if (party.listed_status === 'listed') return 'market_cap';
  if (party.listed_status === 'unlisted' || party.listed_status === 'pre_ipo') return 'valuation';
  return 'both';
}

/**
 * 顾问录财务数字时写的是「32.6亿」「3260万」，不是 3260000000。
 * 解析成人民币元；纯数字按元处理；解析不出来返回 null（调用方保留原值不写）。
 */
export function parseYuanInput(raw: string): number | null {
  const text = raw.replace(/[,，\s]/g, '').replace(/元$/, '');
  if (!text) return null;
  const match = /^(-?\d+(?:\.\d+)?)(亿|万)?$/.exec(text);
  if (!match) return null;
  const amount = Number(match[1]);
  if (!Number.isFinite(amount)) return null;
  if (match[2] === '亿') return amount * 100000000;
  if (match[2] === '万') return amount * 10000;
  return amount;
}

export type RequirementChip = { key: string; label: string; effect: ConditionEffect; title: string };

/**
 * 各维度的默认匹配作用，来源是 backend/app/registry/indicators.py 的 BUYER_INDICATORS
 * default_effect。这里是有意的复制：列表页不加载指标契约接口。改契约默认值时需同步这里。
 */
const DEFAULT_EFFECTS = {
  industries_json: 'required',
  industry_l2_json: 'preferred',
  acceptable_listed_status_json: 'preferred',
  min_revenue_yuan: 'required',
  min_net_profit_yuan: 'required',
  region_constraints_json: 'preferred',
} as const;

type ChipColumn = keyof typeof DEFAULT_EFFECTS;

/** 返回该维度的生效作用。规则只有两态，六个维度都会进列表。 */
function resolveEffect(item: BuyerIntent, column: ChipColumn): ConditionEffect {
  return item.condition_effects_json?.[column] || DEFAULT_EFFECTS[column];
}

/** 多值维度收敛成「前 2 个 + N」，title 保留全量。 */
function collapseValues(values: string[], max = 2): { label: string; title: string } | null {
  const cleaned = Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
  if (!cleaned.length) return null;
  const shown = cleaned.slice(0, max).join('、');
  return {
    label: cleaned.length > max ? `${shown} +${cleaned.length - max}` : shown,
    title: cleaned.join('、'),
  };
}

function shortProvince(value: string): string {
  return value.replace(/(省|市|自治区|特别行政区|壮族|回族|维吾尔)/g, '') || value;
}

function chip(
  item: BuyerIntent,
  column: ChipColumn,
  key: string,
  build: () => { label: string; title: string } | null,
): RequirementChip | null {
  const effect = resolveEffect(item, column);
  const built = build();
  if (!built) return null;
  return { key, label: built.label, effect, title: built.title };
}

/**
 * 关键需求列的 5 个维度、2 行。只消费需求字段契约内的列，
 * 不再读 industry_primary / industry_secondary / region_scope_summary / preferred_listed_status
 * 这些不在契约里、详情页也编辑不到的影子列。
 */
export function requirementChips(item: BuyerIntent): { industry: RequirementChip[]; conditions: RequirementChip[] } {
  const industry = [
    chip(item, 'industries_json', 'industry_l1', () => collapseValues(item.industries_json || [])),
    chip(item, 'industry_l2_json', 'industry_l2', () => collapseValues(item.industry_l2_json || [])),
  ].filter(Boolean) as RequirementChip[];

  const conditions = [
    chip(item, 'acceptable_listed_status_json', 'listed', () => {
      const labels = (item.acceptable_listed_status_json || []).map((value) => valueLabel('preferred_listed_status', value));
      return collapseValues(labels, 3);
    }),
    chip(item, 'min_revenue_yuan', 'revenue', () => {
      if (!item.min_revenue_yuan) return null;
      const text = `营收≥${formatCompactMoney(Number(item.min_revenue_yuan))}`;
      return { label: text, title: text };
    }),
    chip(item, 'min_net_profit_yuan', 'profit', () => {
      if (!item.min_net_profit_yuan) return null;
      const text = `净利≥${formatCompactMoney(Number(item.min_net_profit_yuan))}`;
      return { label: text, title: text };
    }),
    chip(item, 'region_constraints_json', 'region', () => {
      const provinces = (item.region_constraints_json || [])
        .filter((constraint) => constraint.effect !== 'excluded')
        .map((constraint) => shortProvince(constraint.province || ''));
      return collapseValues(provinces);
    }),
  ].filter(Boolean) as RequirementChip[];

  return { industry, conditions };
}
