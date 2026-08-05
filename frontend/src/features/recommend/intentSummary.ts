import { fieldLabel, valueLabel } from '../../lib/fieldLabels';
import { formatYuan } from '../../lib/format';
import type { BuyerIntent } from '../../types/api';

/**
 * Turn a stored buyer intent into a requirement the consultant can send as-is.
 *
 * Structured rather than the raw text on purpose: the raw text is whatever the
 * client happened to write, often pages of it, and it pushes the consultant's
 * own additions out of the box. Labels come from the shared registry so these
 * lines read the same as the intent detail page.
 */
/** 上限只是防止行业列表长到把用户自己要写的话挤出输入框。 */
const MAX_INDUSTRIES = 10;

/**
 * Flatten however the industries happen to be stored into one clean list.
 *
 * `industry_secondary` is a single column that in practice often holds several
 * industries joined by a separator, so deduplicating the raw values leaves the
 * same industries listed twice — once as array entries, once inside that
 * string. Split first, then dedupe.
 */
function industryList(values: (string | null | undefined)[]): string[] {
  const flat = values
    .flatMap((value) => String(value || '').split(/[、,，/;；]/))
    .map((value) => value.trim())
    .filter(Boolean);
  return [...new Set(flat)].slice(0, MAX_INDUSTRIES);
}

export function intentToRequirementText(intent: BuyerIntent): string {
  const lines: string[] = [];
  const push = (label: string, value: string | null | undefined) => {
    const text = String(value || '').trim();
    if (text && text !== '-') lines.push(`${label}：${text}`);
  };
  const enumValue = (field: keyof BuyerIntent) => {
    const raw = intent[field];
    if (raw === null || raw === undefined || raw === '' || raw === 'unknown') return null;
    return valueLabel(String(field), raw);
  };
  const money = (value: string | null) => (value ? formatYuan(value) : null);

  push('买家', intent.buyer_name);

  push(
    '目标行业',
    industryList([
      ...(intent.industries_json || []),
      intent.industry_primary,
      intent.industry_secondary,
      ...(intent.industry_l2_json || []),
    ]).join('、'),
  );
  push('排除行业', industryList(intent.excluded_industries_json || []).join('、'));
  push('地区', intent.region_scope_summary);

  push('营收下限', money(intent.min_revenue_yuan));
  push('净利下限', money(intent.min_net_profit_yuan));
  push('PE 上限', intent.max_pe ? `不超过 ${intent.max_pe}` : null);
  const valuationLow = money(intent.min_valuation_yuan);
  const valuationHigh = money(intent.max_valuation_yuan);
  if (valuationLow || valuationHigh) {
    push('估值区间', `${valuationLow || '不限'} ~ ${valuationHigh || '不限'}`);
  }
  const budgetLow = money(intent.budget_min_yuan);
  const budgetHigh = money(intent.budget_max_yuan);
  if (budgetLow || budgetHigh) {
    push('预算', `${budgetLow || '不限'} ~ ${budgetHigh || '不限'}`);
  }

  push(fieldLabel('buyer_intent', 'requires_control'), enumValue('requires_control'));
  push(fieldLabel('buyer_intent', 'requires_consolidation'), enumValue('requires_consolidation'));
  push(
    fieldLabel('buyer_intent', 'accepts_minority_investment'),
    enumValue('accepts_minority_investment'),
  );
  push('股权比例', intent.equity_ratio_summary);
  push(fieldLabel('buyer_intent', 'preferred_listed_status'), enumValue('preferred_listed_status'));

  const note = String(intent.intent_summary || intent.raw_requirement_text || '').trim();
  if (note) lines.push(`其他要求：${note.slice(0, 500)}`);

  // 一条结构化的都没有（需求刚建、还没解析）时退回原文，总比给个空框强。
  if (!lines.length) {
    const fallback = String(intent.raw_requirement_text || '').trim();
    return fallback || `按「${intent.intent_name}」的条件找标的`;
  }
  return lines.join('\n');
}
