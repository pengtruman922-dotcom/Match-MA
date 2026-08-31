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
/** 上限只是防止标签列表长到把用户自己要写的话挤出输入框。 */
const MAX_INDUSTRIES = 10;

/**
 * Flatten however the business tags happen to be stored into one clean list.
 *
 * 存量数据里一格常常塞着几个用顿号连起来的方向（旧的 `industry_secondary` 就是
 * 这样），所以先按分隔符拆开再去重 —— 只对原值去重的话，同一个方向会出现两次：
 * 一次是数组元素，一次藏在那一串里。
 */
function industryList(values: (string | null | undefined)[]): string[] {
  const flat = values
    .flatMap((value) => String(value || '').split(/[、,，/;；]/))
    .map((value) => value.trim())
    .filter(Boolean);
  return [...new Set(flat)].slice(0, MAX_INDUSTRIES);
}

/** `[{province, city, district}]` → 「广东省、江苏省苏州市」，只拼填到的层级。 */
function regionText(regions: BuyerIntent['acceptable_regions_json']): string {
  if (!regions?.length) return '';
  const parts = regions
    .map((region) => {
      // 直辖市的省与市同名，直接拼会变成「北京市北京市」。
      const levels = [region.province, region.city, region.district].filter(Boolean) as string[];
      return [...new Set(levels)].join('');
    })
    .filter(Boolean);
  return [...new Set(parts)].join('、');
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

  // 0828：行业字典在需求侧下线，业务方向来自自由标签 + 业务说明。
  // 存量行业列（industry_primary / industries_json 等）迁移 022 已并进
  // intent_business_summary，所以这里不再逐个拼它们。
  push('目标业务', industryList(intent.intent_business_tags_json || []).join('、'));
  push('业务方向', intent.intent_business_summary);
  push('排除方向', intent.excluded_business_text);
  // 地区先说原话（「优先广东」这类语气只有它表达得了），再补结构化的省份。
  push('地区', intent.region_scope_summary);
  push('可接受地区', regionText(intent.acceptable_regions_json));
  push('排除地区', regionText(intent.excluded_regions_json));

  push('营收下限', money(intent.min_revenue_yuan));
  push('净利下限', money(intent.min_net_profit_yuan));
  push('PE 上限', intent.max_pe ? `不超过 ${intent.max_pe}` : null);
  const valuationLow = money(intent.min_valuation_yuan);
  const valuationHigh = money(intent.max_valuation_yuan);
  if (valuationLow || valuationHigh) {
    push('估值区间', `${valuationLow || '不限'} ~ ${valuationHigh || '不限'}`);
  }
  push(fieldLabel('buyer_intent', 'requires_control'), enumValue('requires_control'));
  push(fieldLabel('buyer_intent', 'requires_consolidation'), enumValue('requires_consolidation'));
  const listed = (intent.acceptable_listed_status_json || [])
    .map((value) => valueLabel('acceptable_listed_status_json', value))
    .join('、');
  push(fieldLabel('buyer_intent', 'acceptable_listed_status_json'), listed);

  const note = String(intent.raw_requirement_text || '').trim();
  if (note) lines.push(`其他要求：${note.slice(0, 500)}`);

  // 一条结构化的都没有（需求刚建、还没解析）时退回原文，总比给个空框强。
  if (!lines.length) {
    const fallback = String(intent.raw_requirement_text || '').trim();
    return fallback || `按「${intent.intent_name}」的条件找标的`;
  }
  return lines.join('\n');
}
