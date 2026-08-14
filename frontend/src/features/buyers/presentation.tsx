import { Loader2 } from 'lucide-react';
import type { BuyerIntent, BuyerIntentParseStatus, ConditionEffect } from '../../types/api';
import { valueLabel } from '../../lib/fieldLabels';
import { gradeClass, intentGrade, intentGradeLabel } from '../../lib/entityGrade';
import { formatCompactMoney } from '../../lib/format';

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
