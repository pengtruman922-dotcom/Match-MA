import { useState } from 'react';
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import type { RecommendationAgentSearchStep } from '../../types/api';
import { formatCompactMoney } from '../../lib/format';

const FILTER_LABELS: Record<string, string> = {
  industries_json: '行业',
  excluded_industries_json: '排除',
  region_scope_summary: '地区',
  min_net_profit_yuan: '净利≥',
  min_revenue_yuan: '营收≥',
  max_pe: 'PE≤',
  min_valuation_yuan: '估值≥',
  max_valuation_yuan: '估值≤',
  max_debt_ratio: '负债率≤',
  requires_control: '控股',
  requires_consolidation: '并表',
  preferred_listed_status: '上市',
};

const MONEY_FILTERS = new Set([
  'min_net_profit_yuan',
  'min_revenue_yuan',
  'min_valuation_yuan',
  'max_valuation_yuan',
]);

/**
 * The one line that tells the user what the agent decided on its own.
 *
 * Collapsed by default so it never competes with the answer, but never hidden:
 * "PE 放宽到 15" is the agent overriding an explicit instruction, and a result
 * whose provenance is invisible is a result nobody trusts.
 */
export default function AgentProcessLine({
  steps,
  running,
  elapsedSeconds,
}: {
  steps: RecommendationAgentSearchStep[];
  running: boolean;
  elapsedSeconds: number;
}) {
  const [open, setOpen] = useState(false);
  const searchSteps = steps.filter((step) => step.kind !== 'detail');
  const detailStep = [...steps].reverse().find((step) => step.kind === 'detail');

  const summary = running
    ? searchSteps.length === 0
      ? '正在理解需求…'
      : detailStep
        ? `已筛选 ${searchSteps.length} 次 · 正在细看 ${detailStep.total ?? detailStep.count} 家资料…`
        : `已筛选 ${searchSteps.length} 次 · 正在收窄…`
    : `已筛选 ${searchSteps.length} 次${detailStep ? ` · 细看了 ${detailStep.total ?? detailStep.count} 家` : ''}`;

  return (
    <div className="text-xs text-gray-400">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-1.5 hover:text-gray-600"
        data-testid="agent-process-line"
      >
        {running ? <Loader2 className="h-3 w-3 animate-spin" /> : open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <span>{summary}</span>
        <span className="tabular-nums text-gray-300">{formatElapsed(elapsedSeconds)}</span>
      </button>
      {open && steps.length > 0 && (
        <ul className="mt-1.5 space-y-1 border-l border-gray-200 pl-3">
          {steps.map((step, index) => (
            <li key={index} className="text-gray-500">
              {step.kind === 'detail'
                ? `读取详细资料 ${step.count} 家（累计 ${step.total}）`
                : describeSearch(step)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function describeSearch(step: RecommendationAgentSearchStep): string {
  const parts: string[] = [`筛选 #${step.call_index ?? 1}`];
  const filters = describeFilters(step.filters);
  if (filters) parts.push(filters);
  if (step.count_only) {
    parts.push(`→ 命中 ${step.eligible_count ?? 0} 家（仅计数）`);
  } else {
    parts.push(`→ ${step.eligible_count ?? 0} 家符合基础条件`);
  }
  if (step.note) parts.push(`（${step.note}）`);
  return parts.join('  ');
}

function describeFilters(filters: Record<string, unknown> | undefined): string {
  if (!filters) return '';
  const parts: string[] = [];
  for (const [field, value] of Object.entries(filters)) {
    const label = FILTER_LABELS[field];
    if (!label || value === null || value === undefined) continue;
    parts.push(`${label}${formatFilterValue(field, value)}`);
  }
  return parts.join(' / ');
}

function formatFilterValue(field: string, value: unknown): string {
  if (Array.isArray(value)) return value.map(String).join('、');
  if (MONEY_FILTERS.has(field) && typeof value === 'number') return formatCompactMoney(value);
  if (value === 'yes') return '需要';
  if (value === 'no') return '不需要';
  return String(value);
}

function formatElapsed(seconds: number): string {
  if (seconds <= 0) return '';
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}:${String(rest).padStart(2, '0')}`;
}
