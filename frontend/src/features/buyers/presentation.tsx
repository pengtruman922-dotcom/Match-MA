import { Loader2 } from 'lucide-react';
import type {
  BuyerIntent,
  BuyerIntentParseStatus,
  BuyerIntentScenarioSummary,
  BuyerParty,
} from '../../types/api';
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

/** 角标不再分「必须 / 优先」两种画法。
 *
 * 那个区分 2026-09-01 删掉了：`screening_sql.py` 是一组纯 AND，从来不区分
 * 强弱，描边的「优先」和实心的「必须」在筛选里一模一样 —— 画法在骗人。
 * 「优先大湾区」这类语气现在住在方案的「其他要求」文本里。 */
function ChipTag({ chip }: { chip: RequirementChip }) {
  return <span title={chip.title} className="inline-block max-w-full truncate bg-gray-100 px-1.5 py-0.5 text-[11px] leading-4 text-gray-700">{chip.label}</span>;
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

/**
 * 关注业务：需求的业务标签（0828 起是自由标签，不过行业字典）。
 *
 * 行业字典只有 16 个一级行业，接不住买家说的「薄膜电容器」「线控底盘」这类
 * 细分方向 —— 实测人均只填 1.25 个一级行业，而真正的信息落在原文里。
 * 标签为空时退回业务说明的首句，比显示一个「-」有用。
 */

/** 一条需求的全部启用方案。0901 起业务与门槛住在这里，需求本身只是容器。
 *
 * 列表的每一格都要**并起来**显示，不能取最严或最宽的那一个：多方案是 OR，
 * 取最严会漏掉宽档能吃下的标的，取最宽会让顾问以为这个买家什么都收。 */
function scenariosOf(item: BuyerIntent): BuyerIntentScenarioSummary[] {
  return item.scenarios_json || [];
}

function joinUnique(values: Array<string | null | undefined>): string {
  return [...new Set(values.map((value) => (value || '').trim()).filter(Boolean))].join('、');
}

/** 数字类门槛：每个方案一段，多方案时并列显示。 */
function moneyList(
  item: BuyerIntent,
  read: (scenario: BuyerIntentScenarioSummary) => string | number | null,
  prefix: string,
): string {
  const parts = scenariosOf(item)
    .map(read)
    .map(Number)
    .filter(Number.isFinite)
    .map((value) => `${prefix}${formatCompactMoney(value)}`);
  return joinUnique(parts);
}

export function IntentIndustriesCell({ item }: { item: BuyerIntent }) {
  const tags = joinUnique(scenariosOf(item).flatMap((scenario) => scenario.business_tags_json || []));
  if (tags) {
    return <span className="block truncate text-xs text-gray-700" title={tags}>{tags}</span>;
  }
  // 标签为空时退回方案摘要，比显示一个「-」有用。
  const summary = joinUnique(scenariosOf(item).map((scenario) => scenario.scenario_summary));
  if (!summary) return <Blank />;
  return <span className="block truncate text-xs text-gray-500" title={summary}>{summary}</span>;
}

/**
 * 上市要求：买家想买上市的还是非上市的。
 *
 * `preferred` 是倾向、`acceptable` 是可接受集合，两者都在时显示倾向、悬停看全集。
 * 只显示 acceptable 会把「都可以但偏好上市」压成「都可以」。
 */
export function ListingWantedCell({ item }: { item: BuyerIntent }) {
  const acceptable = [...new Set(
    scenariosOf(item).flatMap((scenario) => (scenario.acceptable_listed_status_json || []).map(String)),
  )].filter(Boolean);
  // preferred_listed_status 是 022 之前的兼容派生列，0901 随需求侧门槛一起退役。
  // 存量值还在，作为空集时的兜底 —— 重跑之后它不再更新。
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
  const scenarios = scenariosOf(item);
  const wantsListed = scenarios.some((scenario) =>
    (scenario.acceptable_listed_status_json || []).map(String).includes('listed'),
  );
  const marketCap = joinUnique(
    scenarios.map((scenario) => moneyRange(scenario.min_market_cap_yuan, scenario.max_market_cap_yuan)),
  );
  const valuation = joinUnique(
    scenarios.map((scenario) => moneyRange(scenario.min_valuation_yuan, scenario.max_valuation_yuan)),
  );
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
  const text = moneyList(item, (scenario) => scenario.min_revenue_yuan, '≥');
  if (!text) return <Blank />;
  return <span className="whitespace-nowrap text-xs text-gray-700" title={text}>{text}</span>;
}

/**
 * 区域要求：需求侧的省份。
 *
 * 结构化的 `region_constraints_json` 只有 12% 有值，而文本摘要 `region_scope_summary`
 * 有 64% —— 所以结构化没有时退回文本，宁可显示一句话也别让这一列大面积空白。
 * 退回时标灰，提示它没被结构化（初筛闸门只认结构化的那份）。
 */
export function RegionWantedCell({ item }: { item: BuyerIntent }) {
  const provinces = joinUnique(
    scenariosOf(item)
      .flatMap((scenario) => scenario.required_regions_json || [])
      .map((entry) => (entry?.province || '').trim()),
  );
  if (provinces) {
    return <span className="block truncate text-xs text-gray-700" title={provinces}>{provinces}</span>;
  }
  // 「要求地区」是硬要求，留空是常态而不是缺数据：实测 36 家买家里提到地域的
  // 16 家中有 9 家说的是「优先/最好」，那种语气进的是方案的「其他要求」。
  // 所以这里退回「其他要求」的原话并标灰，而不是显示一个「-」。
  const other = joinUnique(scenariosOf(item).map((scenario) => scenario.other_requirements_text));
  if (!other) return <Blank />;
  return (
    <span className="block truncate text-xs text-gray-400" title={`非硬性要求，原话：${other}`}>{other}</span>
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

export type RequirementChip = { key: string; label: string; title: string };

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
  key: string,
  build: () => { label: string; title: string } | null,
): RequirementChip | null {
  const built = build();
  if (!built) return null;
  return { key, label: built.label, title: built.title };
}

/**
 * 关键需求列的 5 个维度、2 行。只消费需求字段契约内的列，
 * 不再读 industry_primary / industry_secondary / region_scope_summary / preferred_listed_status
 * 这些不在契约里、详情页也编辑不到的影子列。
 */
export function requirementChips(item: BuyerIntent): { industry: RequirementChip[]; conditions: RequirementChip[] } {
  // 0901：业务与门槛住在方案里。一条需求可能有多个方案，列表把它们**并起来**
  // 显示 —— 多方案是 OR，所以「营收≥1亿 或 营收≥5亿」在列表这一格里显示成
  // 两个角标，而不是取最严或最宽的那一个。取任何一个都会误导：
  // 取最严会漏掉宽档能吃下的标的，取最宽会让顾问以为这个买家什么都收。
  const scenarios = item.scenarios_json || [];
  const pick = <T,>(read: (scenario: BuyerIntentScenarioSummary) => T | null | undefined): T[] =>
    scenarios.map(read).filter((value): value is T => value !== null && value !== undefined);

  // 第一行讲「要买什么业务」。0828 起它来自自由业务标签而不是行业字典 ——
  // 字典只有 16 个一级行业，接不住「薄膜电容器」「线控底盘」这类细分方向。
  const industry = [
    chip('business_tags', () => collapseValues(scenarios.flatMap((scenario) => scenario.business_tags_json || []))),
  ].filter(Boolean) as RequirementChip[];

  const conditions = [
    chip('listed', () => {
      const labels = scenarios
        .flatMap((scenario) => scenario.acceptable_listed_status_json || [])
        .map((value) => valueLabel('acceptable_listed_status_json', value));
      return collapseValues(labels, 3);
    }),
    chip('revenue', () => {
      const values = pick((scenario) => scenario.min_revenue_yuan).map(Number).filter(Number.isFinite);
      return collapseValues(values.map((value) => `营收≥${formatCompactMoney(value)}`));
    }),
    chip('profit', () => {
      const values = pick((scenario) => scenario.min_net_profit_yuan).map(Number).filter(Number.isFinite);
      return collapseValues(values.map((value) => `净利≥${formatCompactMoney(value)}`));
    }),
    chip('pe', () => {
      const values = pick((scenario) => scenario.max_pe).map(Number).filter(Number.isFinite);
      return collapseValues(values.map((value) => `PE≤${value.toFixed(0)}`));
    }),
    chip('region', () => {
      const provinces = scenarios
        .flatMap((scenario) => scenario.required_regions_json || [])
        .map((region) => shortProvince(region.province || ''));
      return collapseValues(provinces);
    }),
  ].filter(Boolean) as RequirementChip[];

  return { industry, conditions };
}
