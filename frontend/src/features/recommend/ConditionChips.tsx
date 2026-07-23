import { Check, X } from 'lucide-react';
import type {
  BuyerIntent,
  RecommendationConditionAction,
  RecommendationConditionOverrides,
  RecommendationScenarioRef,
  SellerTarget,
} from '../../types/api';
import { valueLabel } from '../../lib/fieldLabels';
import { formatCompactMoney } from '../../lib/format';

export interface ConditionChip {
  label: string;
  field?: string;
}

const OVERRIDE_FIELD_LABELS: Record<string, string> = {
  industries_json: '行业',
  excluded_industries_json: '排除行业',
  region_scope_summary: '地区',
  min_net_profit_yuan: '净利润下限',
  min_revenue_yuan: '营收下限',
  min_valuation_yuan: '估值下限',
  max_valuation_yuan: '估值上限',
  max_pe: 'PE上限',
  min_market_cap_yuan: '市值下限',
  max_market_cap_yuan: '市值上限',
  requires_control: '控股要求',
  requires_consolidation: '并表要求',
  desired_equity_ratio_min: '最低股比',
  preferred_listed_status: '上市偏好',
  max_debt_ratio: '负债率上限',
};

const MONEY_FIELDS = new Set([
  'min_net_profit_yuan',
  'min_revenue_yuan',
  'min_valuation_yuan',
  'max_valuation_yuan',
  'min_market_cap_yuan',
  'max_market_cap_yuan',
]);

/** Base chips: intent fields the chat can override, tagged with the field name. */
export function intentConditionChips(intent: BuyerIntent): ConditionChip[] {
  const chips: ConditionChip[] = [];
  const industries = Array.isArray(intent.industries_json) && intent.industries_json.length
    ? (intent.industries_json as string[]).join('、')
    : [intent.industry_primary, intent.industry_secondary].filter(Boolean).join('/');
  if (industries) chips.push({ label: `行业:${industries}`, field: 'industries_json' });
  if (intent.region_scope_summary) chips.push({ label: `地区:${intent.region_scope_summary}`, field: 'region_scope_summary' });
  if (intent.min_net_profit_yuan) chips.push({ label: `净利≥${formatCompactMoney(Number(intent.min_net_profit_yuan))}`, field: 'min_net_profit_yuan' });
  if (intent.min_revenue_yuan) chips.push({ label: `营收≥${formatCompactMoney(Number(intent.min_revenue_yuan))}`, field: 'min_revenue_yuan' });
  if (intent.max_pe) chips.push({ label: `PE≤${Number(intent.max_pe).toFixed(0)}`, field: 'max_pe' });
  if (intent.max_valuation_yuan) chips.push({ label: `估值≤${formatCompactMoney(Number(intent.max_valuation_yuan))}`, field: 'max_valuation_yuan' });
  if (intent.preferred_listed_status && intent.preferred_listed_status !== 'unknown') {
    chips.push({ label: `上市:${valueLabel('preferred_listed_status', intent.preferred_listed_status)}`, field: 'preferred_listed_status' });
  }
  if (intent.requires_consolidation === 'yes') chips.push({ label: '需并表', field: 'requires_consolidation' });
  if (intent.requires_control === 'yes') chips.push({ label: '需控股', field: 'requires_control' });
  if (intent.negative_summary) chips.push({ label: `排除:${intent.negative_summary}` });
  return chips;
}

export function targetConditionChips(target: SellerTarget): ConditionChip[] {
  const chips: ConditionChip[] = [];
  const industry = [target.industry_l1, target.industry_l2].filter(Boolean).join('/');
  if (industry) chips.push({ label: `行业:${industry}` });
  const region = [target.location_province, target.location_city, target.location_district].filter(Boolean).join(' ');
  if (region) chips.push({ label: `地区:${region}` });
  if (target.current_net_profit_yuan) chips.push({ label: `净利:${formatCompactMoney(Number(target.current_net_profit_yuan))}` });
  if (target.asking_price_yuan) chips.push({ label: `报价:${formatCompactMoney(Number(target.asking_price_yuan))}` });
  else if (target.valuation_yuan) chips.push({ label: `估值:${formatCompactMoney(Number(target.valuation_yuan))}` });
  if (target.can_consolidate === 'yes') chips.push({ label: '可并表' });
  if (target.can_control === 'yes') chips.push({ label: '可控股' });
  return chips;
}

function overrideValueLabel(field: string, value: unknown): string {
  if (Array.isArray(value)) return value.map(String).join('、');
  if (MONEY_FIELDS.has(field) && typeof value === 'number') return formatCompactMoney(value);
  if (field === 'requires_control' || field === 'requires_consolidation') {
    return value === 'yes' ? '需要' : value === 'no' ? '不需要' : String(value);
  }
  if (field === 'preferred_listed_status') return valueLabel('preferred_listed_status', String(value));
  return String(value);
}

export function normalizeOverrides(raw: unknown): {
  fields: Record<string, unknown>;
  removedFields: string[];
  extraExcluded: string[];
  preferences: string[];
  disabledScenarios: string[];
} {
  const data = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  return {
    fields: (data.fields && typeof data.fields === 'object' ? data.fields : {}) as Record<string, unknown>,
    removedFields: Array.isArray(data.removed_fields) ? data.removed_fields.map(String) : [],
    extraExcluded: Array.isArray(data.extra_excluded_industries) ? data.extra_excluded_industries.map(String) : [],
    preferences: Array.isArray(data.semantic_preferences) ? data.semantic_preferences.map(String) : [],
    disabledScenarios: Array.isArray(data.disabled_scenarios) ? data.disabled_scenarios.map(String) : [],
  };
}

export function hasOverrides(raw: unknown): boolean {
  const data = normalizeOverrides(raw);
  return (
    Object.keys(data.fields).length > 0
    || data.removedFields.length > 0
    || data.extraExcluded.length > 0
    || data.preferences.length > 0
    || data.disabledScenarios.length > 0
  );
}

export default function ConditionChips({
  baseChips,
  overrides,
  interactive,
  busy = false,
  scenarios = [],
  onAction,
}: {
  baseChips: ConditionChip[];
  overrides: unknown;
  interactive: boolean;
  busy?: boolean;
  scenarios?: RecommendationScenarioRef[];
  onAction?: (actions: RecommendationConditionAction[]) => void;
}) {
  const data = normalizeOverrides(overrides as RecommendationConditionOverrides);
  const overriddenFields = new Set([...Object.keys(data.fields), ...data.removedFields]);
  const act = (action: RecommendationConditionAction) => {
    if (!busy && onAction) onAction([action]);
  };

  if (!baseChips.length && !hasOverrides(overrides) && !scenarios.length) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5 border border-gray-200 bg-white px-3 py-2 text-xs">
      <span className="shrink-0 text-gray-400">生效条件:</span>

      {/* 方案是"或"关系的分支，停用只影响本次会话，不改买家需求 */}
      {scenarios.map((scenario) => {
        const disabled = data.disabledScenarios.includes(scenario.id);
        return (
          <span
            key={`sc-${scenario.id}`}
            className={`inline-flex items-center gap-1 border px-2 py-0.5 ${
              disabled
                ? 'border-gray-200 bg-gray-50 text-gray-300 line-through'
                : 'border-indigo-200 bg-indigo-50 text-indigo-700'
            }`}
            title={disabled ? '该方案已在本会话停用，点 ✓ 恢复' : '并列方案之一，点 × 本会话内停用'}
          >
            {scenario.label}
            {interactive && (
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  act({
                    op: disabled ? 'enable_scenario' : 'disable_scenario',
                    scenario_id: scenario.id,
                    label: scenario.label,
                  })
                }
                className="text-current opacity-60 hover:opacity-100 disabled:opacity-40"
              >
                {disabled ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
              </button>
            )}
          </span>
        );
      })}

      {baseChips.map((chip) => {
        const suppressed = chip.field ? overriddenFields.has(chip.field) : false;
        return (
          <span
            key={`base-${chip.label}`}
            className={`inline-flex items-center gap-1 px-2 py-0.5 ${suppressed ? 'bg-gray-50 text-gray-300 line-through' : 'bg-gray-100 text-gray-600'}`}
            title={suppressed ? '该基础条件已被对话覆盖或临时停用' : '来自意向/标的的基础条件'}
          >
            {chip.label}
            {interactive && chip.field && !suppressed && (
              <button
                type="button"
                disabled={busy}
                onClick={() => act({ op: 'disable_field', field: chip.field })}
                className="text-gray-400 hover:text-red-600 disabled:opacity-40"
                title="本会话内临时停用该条件"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </span>
        );
      })}

      {Object.entries(data.fields).map(([field, value]) => (
        <span key={`ov-${field}`} className="inline-flex items-center gap-1 bg-brand-50 px-2 py-0.5 text-brand-700" title="对话补充条件">
          {OVERRIDE_FIELD_LABELS[field] || field}:{overrideValueLabel(field, value)}
          {interactive && (
            <button type="button" disabled={busy} onClick={() => act({ op: 'remove_field', field })} className="text-brand-400 hover:text-red-600 disabled:opacity-40">
              <X className="h-3 w-3" />
            </button>
          )}
        </span>
      ))}

      {data.removedFields.map((field) => (
        <span key={`rm-${field}`} className="inline-flex items-center gap-1 bg-amber-50 px-2 py-0.5 text-amber-700" title="该条件已在本会话停用，点 × 恢复">
          已停用:{OVERRIDE_FIELD_LABELS[field] || field}
          {interactive && (
            <button type="button" disabled={busy} onClick={() => act({ op: 'remove_field', field })} className="text-amber-400 hover:text-red-600 disabled:opacity-40">
              <X className="h-3 w-3" />
            </button>
          )}
        </span>
      ))}

      {data.extraExcluded.map((term) => (
        <span key={`ex-${term}`} className="inline-flex items-center gap-1 bg-brand-50 px-2 py-0.5 text-brand-700" title="对话补充的排除项">
          排除:{term}
          {interactive && (
            <button type="button" disabled={busy} onClick={() => act({ op: 'remove_exclusion', value: term })} className="text-brand-400 hover:text-red-600 disabled:opacity-40">
              <X className="h-3 w-3" />
            </button>
          )}
        </span>
      ))}

      {data.preferences.map((preference) => (
        <span key={`pref-${preference}`} className="inline-flex items-center gap-1 bg-violet-50 px-2 py-0.5 text-violet-700" title="语义偏好（影响 AI 深评）">
          偏好:{preference}
          {interactive && (
            <button type="button" disabled={busy} onClick={() => act({ op: 'remove_preference', value: preference })} className="text-violet-400 hover:text-red-600 disabled:opacity-40">
              <X className="h-3 w-3" />
            </button>
          )}
        </span>
      ))}

      {interactive && hasOverrides(overrides) && (
        <button
          type="button"
          disabled={busy}
          onClick={() => act({ op: 'clear_all' })}
          className="ml-1 text-gray-400 underline-offset-2 hover:text-gray-600 hover:underline disabled:opacity-40"
        >
          恢复默认条件
        </button>
      )}
    </div>
  );
}
