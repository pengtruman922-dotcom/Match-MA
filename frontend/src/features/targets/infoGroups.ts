import type { SellerTarget, IndicatorRegistryResponse, IndicatorMeta } from '../../types/api';
import { valueLabel } from '../../lib/fieldLabels';

/**
 * 标的信息的分组与字段结构来自后端指标注册表（/meta/indicators，唯一事实源）：
 * 哪些字段、属于哪个大类、中文名、是否参与筛选、省市如何折叠，全部由 API 决定。
 * 这里只负责把每个字段的原始值按 kind 格式化成展示文本——纯前端呈现逻辑。
 *
 * 「筛」角标同样来自注册表的 screening：补一个利润数字可能把标的从「未知」
 * 推进候选池，补一段描述只影响深评措辞，顾问需要看出区别。
 */

export type InfoField = {
  /** 对应的列名。 */
  field: string;
  label: string;
  value: string | null;
  screening?: boolean;
};

export type InfoGroup = {
  key: string;
  label: string;
  sectionCode: string | null;
  fields: InfoField[];
};

export type InfoHelpers = {
  formatYuan: (value: string | null) => string;
  formatListedStatus: (value: string | null) => string;
  formatTransferRatio: (target: SellerTarget) => string | null;
  getSubjectDisplay: (target: SellerTarget) => string | null;
};

function text(value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null;
  return String(value);
}

function labelled(fieldPath: string, value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null;
  const rendered = valueLabel(fieldPath, value);
  return rendered === '-' ? null : rendered;
}

/**
 * 一个字段的展示值。命名特例（省市折叠、出售比例、上市状态、标的主体、PE）
 * 单独处理，其余按 kind 走通用格式化。
 */
function formatValue(indicator: IndicatorMeta, target: SellerTarget, helpers: InfoHelpers): string | null {
  const raw = (target as unknown as Record<string, unknown>)[indicator.column];
  switch (indicator.column) {
    case 'registered_province':
      return text([target.registered_province, target.registered_city].filter(Boolean).join(''));
    case 'headquarter_province':
      return text([target.headquarter_province, target.headquarter_city].filter(Boolean).join(''));
    case 'target_subject_name':
      return helpers.getSubjectDisplay(target);
    case 'listed_status':
      return helpers.formatListedStatus(target.listed_status);
    case 'transfer_ratio_min':
      return text(target.transfer_ratio_text) || helpers.formatTransferRatio(target);
    case 'pe_ratio':
      return target.pe_ratio ? Number(target.pe_ratio).toFixed(1) : null;
    default:
      break;
  }
  switch (indicator.kind) {
    case 'yuan':
      return raw ? helpers.formatYuan(String(raw)) : null;
    case 'enum':
      return labelled(indicator.column, raw);
    default:
      return text(raw);
  }
}

/**
 * 按注册表把标的字段组装成分组结构。fold_into 不为空的列（如 registered_city、
 * transfer_ratio_max）已折叠进主列的展示，不单独成行。
 */
export function buildInfoGroups(
  target: SellerTarget,
  registry: IndicatorRegistryResponse,
  helpers: InfoHelpers,
): InfoGroup[] {
  return registry.groups.map((group) => ({
    key: group.key,
    label: group.label,
    sectionCode: group.section_code,
    fields: registry.indicators
      .filter((indicator) => indicator.group === group.key && indicator.fold_into === null)
      .map((indicator) => ({
        field: indicator.column,
        label: indicator.label,
        value: formatValue(indicator, target, helpers),
        screening: indicator.screening || undefined,
      })),
  }));
}

export function groupFilledCount(group: InfoGroup): number {
  return group.fields.filter((field) => field.value).length;
}
