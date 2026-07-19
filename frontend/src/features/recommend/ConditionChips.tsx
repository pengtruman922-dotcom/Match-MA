import type { BuyerIntent, SellerTarget } from '../../types/api';
import { valueLabel } from '../../lib/fieldLabels';
import { formatCompactMoney } from '../../lib/format';

export interface ConditionChip {
  label: string;
}

export function intentConditionChips(intent: BuyerIntent): ConditionChip[] {
  const chips: ConditionChip[] = [];
  const industry = [intent.industry_primary, intent.industry_secondary].filter(Boolean).join('/');
  if (industry) chips.push({ label: `行业:${industry}` });
  if (intent.region_scope_summary) chips.push({ label: `地区:${intent.region_scope_summary}` });
  if (intent.min_net_profit_yuan) chips.push({ label: `净利≥${formatCompactMoney(Number(intent.min_net_profit_yuan))}` });
  if (intent.min_revenue_yuan) chips.push({ label: `营收≥${formatCompactMoney(Number(intent.min_revenue_yuan))}` });
  if (intent.max_pe) chips.push({ label: `PE≤${Number(intent.max_pe).toFixed(0)}` });
  if (intent.max_valuation_yuan) chips.push({ label: `估值≤${formatCompactMoney(Number(intent.max_valuation_yuan))}` });
  if (intent.preferred_listed_status && intent.preferred_listed_status !== 'unknown') {
    chips.push({ label: `上市:${valueLabel('preferred_listed_status', intent.preferred_listed_status)}` });
  }
  if (intent.requires_consolidation === 'yes') chips.push({ label: '需并表' });
  if (intent.requires_control === 'yes') chips.push({ label: '需控股' });
  if (intent.negative_summary) chips.push({ label: `排除:${intent.negative_summary}` });
  return chips;
}

export function targetConditionChips(target: SellerTarget): ConditionChip[] {
  const chips: ConditionChip[] = [];
  const industry = [target.industry_primary, target.industry_secondary].filter(Boolean).join('/');
  if (industry) chips.push({ label: `行业:${industry}` });
  const region = [target.headquarter_province, target.headquarter_city].filter(Boolean).join(' ');
  if (region) chips.push({ label: `地区:${region}` });
  if (target.current_net_profit_yuan) chips.push({ label: `净利:${formatCompactMoney(Number(target.current_net_profit_yuan))}` });
  if (target.asking_price_yuan) chips.push({ label: `报价:${formatCompactMoney(Number(target.asking_price_yuan))}` });
  else if (target.valuation_yuan) chips.push({ label: `估值:${formatCompactMoney(Number(target.valuation_yuan))}` });
  if (target.can_consolidate === 'yes') chips.push({ label: '可并表' });
  if (target.can_control === 'yes') chips.push({ label: '可控股' });
  return chips;
}

export default function ConditionChips({ chips }: { chips: ConditionChip[] }) {
  if (!chips.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 border border-gray-200 bg-white px-3 py-2 text-xs">
      <span className="text-gray-400 shrink-0">生效条件:</span>
      {chips.map((chip) => (
        <span key={chip.label} className="bg-gray-100 px-2 py-0.5 text-gray-600" title="来自意向/标的的基础条件">
          {chip.label}
        </span>
      ))}
    </div>
  );
}
