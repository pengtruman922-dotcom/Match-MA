import { Loader2 } from 'lucide-react';
import type { BuyerIntent, BuyerIntentParseStatus } from '../../types/api';
import { valueLabel } from '../../lib/fieldLabels';
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

export function IntentStatusBadge({ status }: { status: string }) {
  const color = status === 'active'
    ? 'bg-emerald-50 text-emerald-700'
    : status === 'paused'
      ? 'bg-amber-50 text-amber-700'
      : 'bg-gray-100 text-gray-600';
  return <span className={`text-xs px-2 py-0.5 font-medium ${color}`}>{valueLabel('buyer_intent_status', status)}</span>;
}

export function PartyStatusBadge({ status }: { status: string }) {
  const color = status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-600';
  return <span className={`text-xs px-2 py-0.5 font-medium ${color}`}>{valueLabel('buyer_party_status', status)}</span>;
}

export function dedupMatchLabel(value: string): string {
  if (value === 'buyer_name') return '买家名称';
  if (value === 'legal_name') return '公司全称';
  if (value === 'alias') return '别名';
  return value;
}

export function listingRequirementLabel(item: BuyerIntent): string {
  const parts = [item.preferred_listed_status ? valueLabel('preferred_listed_status', item.preferred_listed_status) : null, item.listing_board_requirement_summary, item.financing_stage_requirement_summary].filter(Boolean);
  return parts.length ? parts.join(' / ') : '-';
}

export function marketCapRangeLabel(item: BuyerIntent): string {
  if (item.market_cap_range_summary) return item.market_cap_range_summary;
  const min = item.min_market_cap_yuan ? `${(Number(item.min_market_cap_yuan) / 100000000).toFixed(1)}亿` : '';
  const max = item.max_market_cap_yuan ? `${(Number(item.max_market_cap_yuan) / 100000000).toFixed(1)}亿` : '';
  if (min && max) return `${min}-${max}`;
  if (min) return `≥${min}`;
  if (max) return `≤${max}`;
  return '-';
}

export function compactRequirementNotes(item: BuyerIntent): string {
  const industry = [item.industry_primary, item.industry_secondary].filter(Boolean).join('/');
  const profit = item.min_net_profit_yuan ? `净利≥${formatCompactMoney(Number(item.min_net_profit_yuan))}` : null;
  const marketCap = marketCapRangeLabel(item);
  const parts = [
    industry || null,
    item.region_scope_summary,
    listingRequirementLabel(item) !== '-' ? listingRequirementLabel(item) : null,
    profit,
    item.max_pe ? `PE≤${Number(item.max_pe).toFixed(0)}` : null,
    marketCap !== '-' ? `市值${marketCap}` : null,
    item.max_debt_ratio ? `负债率≤${Number(item.max_debt_ratio).toFixed(0)}%` : null,
    item.max_premium_rate ? `溢价≤${Number(item.max_premium_rate).toFixed(0)}%` : item.premium_tolerance_summary,
    item.major_risk_tolerance_summary,
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : '暂无关键门槛';
}
