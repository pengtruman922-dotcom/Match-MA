import { valueLabel } from '../../lib/fieldLabels';
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
  const money = (value: string | number | null | undefined) =>
    value === null || value === undefined || value === '' ? null : formatYuan(String(value));

  push('买家', intent.buyer_name);

  // 0901：业务方向与全部门槛住在方案里，需求本身只是容器。继续读 intent 上那些
  // 退役列的表现是**这段话越来越空**：重跑解析之后新值全在方案上，而这里读的是
  // 存量值，看不出错、只是推荐对话的开场白里什么条件都没有了。
  const scenarios = intent.scenarios_json || [];
  const multi = scenarios.length > 1;
  scenarios.forEach((scenario, index) => {
    // 多方案是 OR。不写这一句，读的人（和模型）会把几档的条件叠加起来当一档看，
    // 于是「酒店」那一档凭空背上「粮油食品」那一档的营收与估值要求。
    const prefix = multi ? `方案 ${index + 1} · ` : '';
    push(`${prefix}目标业务`, industryList(scenario.business_tags_json || []).join('、'));
    push(`${prefix}业务方向`, scenario.scenario_summary);
    push(`${prefix}排除方向`, scenario.excluded_business_text);
    push(`${prefix}要求地区`, regionText(scenario.required_regions_json));
    push(`${prefix}营收下限`, money(scenario.min_revenue_yuan));
    push(`${prefix}净利下限`, money(scenario.min_net_profit_yuan));
    push(`${prefix}PE 上限`, scenario.max_pe ? `不超过 ${scenario.max_pe}` : null);
    const valuationLow = money(scenario.min_valuation_yuan);
    const valuationHigh = money(scenario.max_valuation_yuan);
    if (valuationLow || valuationHigh) {
      push(`${prefix}估值区间`, `${valuationLow || '不限'} ~ ${valuationHigh || '不限'}`);
    }
    const marketLow = money(scenario.min_market_cap_yuan);
    const marketHigh = money(scenario.max_market_cap_yuan);
    if (marketLow || marketHigh) {
      push(`${prefix}市值区间`, `${marketLow || '不限'} ~ ${marketHigh || '不限'}`);
    }
    const listed = (scenario.acceptable_listed_status_json || [])
      .map((value) => valueLabel('acceptable_listed_status_json', value))
      .join('、');
    push(`${prefix}上市状态`, listed);
    // 「广东优先」这类偏好只住在这里 —— 丢了它，读的人会以为这个买家不限地区。
    push(`${prefix}其他要求`, scenario.other_requirements_text);
  });
  if (multi) lines.push('（以上方案满足任意一个即可，不要把它们的条件叠加起来看）');

  const note = String(intent.raw_requirement_text || '').trim();
  if (note) lines.push(`其他要求：${note.slice(0, 500)}`);

  // 一条结构化的都没有（需求刚建、还没解析）时退回原文，总比给个空框强。
  if (!lines.length) {
    const fallback = String(intent.raw_requirement_text || '').trim();
    return fallback || `按「${intent.intent_name}」的条件找标的`;
  }
  return lines.join('\n');
}
