import { useState } from 'react';
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import type { RecommendationAgentSearchStep } from '../../types/api';
import { formatCompactMoney } from '../../lib/format';
import { valueLabel } from '../../lib/fieldLabels';

// 初筛 skill 支持的全部条件。少一个的后果不是报错，是那一条在过程行里**消失**——
// Agent 自己加的地区条件用户看不见，结果的来路就断了。
const FILTER_LABELS: Record<string, string> = {
  acceptable_regions_json: '地区',
  excluded_regions_json: '排除地区',
  region_scope_summary: '地区',
  min_revenue_yuan: '营收≥',
  min_net_profit_yuan: '净利≥',
  min_total_profit_yuan: '利润总额≥',
  max_pe: 'PE≤',
  min_valuation_yuan: '估值≥',
  max_valuation_yuan: '估值≤',
  min_market_cap_yuan: '市值≥',
  max_market_cap_yuan: '市值≤',
  acceptable_listed_status_json: '上市状态',
  listing_market_region: '上市地',
  transaction_types_json: '交易结构',
  unacceptable_risk_flags_json: '不接受风险',
  accepts_minority_investment: '少数股权',
  requires_control: '控股',
  requires_consolidation: '并表',
  requires_relocation: '迁址',
  requires_return_investment: '返投',
  requires_team_retention: '团队留任',
  desired_equity_ratio_min: '股比≥',
  desired_equity_ratio_max: '股比≤',
  preferred_listed_status: '上市',
};

// 买家侧的「可接受 X」与标的侧的 X 是同一个闭集，中文名复用后者那张表。
const VALUE_LABEL_FIELDS: Record<string, string> = {
  acceptable_listed_status_json: 'listed_status',
  acceptable_profitability_status_json: 'profitability_status',
  acceptable_cash_flow_status_json: 'cash_flow_status',
  transaction_types_json: 'acceptable_transaction_structures_json',
  unacceptable_risk_flags_json: 'major_risk_flags_json',
};

const MONEY_FILTERS = new Set([
  'min_net_profit_yuan',
  'min_revenue_yuan',
  'min_total_profit_yuan',
  'min_valuation_yuan',
  'max_valuation_yuan',
  'min_market_cap_yuan',
  'max_market_cap_yuan',
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
  elapsedMs,
  understandingDurationMs,
  deepEvalDurationMs,
  briefDurationMs,
  writerDurationMs,
  writerElapsedMs,
  writerRunning,
}: {
  steps: RecommendationAgentSearchStep[];
  running: boolean;
  elapsedMs: number;
  understandingDurationMs: number | null;
  deepEvalDurationMs: number | null;
  briefDurationMs: number | null;
  writerDurationMs: number | null;
  writerElapsedMs: number;
  writerRunning: boolean;
}) {
  const [open, setOpen] = useState(false);
  const searchSteps = steps.filter((step) => step.kind === 'search' || step.kind === 'search_rejected');
  const detailStep = [...steps].reverse().find((step) => step.kind === 'detail');
  const visibleSteps = steps.filter((step) => step.kind !== 'deep_eval');

  const phaseRows: { key: string; label: string; durationMs: number }[] = [];
  if (understandingDurationMs !== null) {
    phaseRows.push({ key: 'understanding', label: '理解当前需求快照', durationMs: understandingDurationMs });
  }
  for (const [index, step] of visibleSteps.entries()) {
    phaseRows.push({
      key: `step-${index}`,
      label: step.kind === 'detail'
        ? `读取详细资料 ${step.count} 家（累计 ${step.total}）`
        : describeSearch(step),
      durationMs: Math.max(0, Number(step.duration_ms) || 0),
    });
  }
  if (deepEvalDurationMs !== null) {
    phaseRows.push({ key: 'deep-eval', label: '深评候选池', durationMs: deepEvalDurationMs });
  }
  if (briefDurationMs !== null) {
    phaseRows.push({ key: 'brief', label: '主 Agent 选择名单并收口素材', durationMs: briefDurationMs });
  }
  if (writerDurationMs !== null || writerRunning) {
    phaseRows.push({
      key: 'writer',
      label: writerRunning ? '正在整理推荐正文…' : '整理推荐正文（至末字完成）',
      durationMs: writerRunning ? writerElapsedMs : writerDurationMs || 0,
    });
  }
  const persistedTotalMs = phaseRows.reduce((total, row) => total + row.durationMs, 0);
  const totalMs = running ? Math.max(elapsedMs, persistedTotalMs) : persistedTotalMs;

  const summary = running
    ? writerRunning
      ? `已筛选 ${searchSteps.length} 次${detailStep ? ` · 细看了 ${detailStep.total ?? detailStep.count} 家` : ''} · 正在整理推荐…`
      : searchSteps.length === 0
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
        <span className="tabular-nums text-gray-300">{formatDuration(totalMs)}</span>
      </button>
      {open && phaseRows.length > 0 && (
        <ul className="mt-1.5 space-y-1 border-l border-gray-200 pl-3">
          {phaseRows.map((row) => (
            <li key={row.key} className="flex items-start justify-between gap-3 text-gray-500">
              <span>{row.label}</span>
              <span className="shrink-0 tabular-nums text-gray-300">{formatDuration(row.durationMs)}</span>
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
  if (Array.isArray(value)) return value.map((item) => formatFilterValue(field, item)).join('、');
  // 地区条件是 {province, city, district}，只填到用户说到的层级。
  if (value && typeof value === 'object') {
    const region = value as Record<string, unknown>;
    return ['province', 'city', 'district'].map((level) => region[level] || '').join('');
  }
  if (MONEY_FILTERS.has(field) && typeof value === 'number') return formatCompactMoney(value);
  // 能力要求在 skill 里是布尔：带上这个条件本身就等于「要求」。
  if (typeof value === 'boolean') return value ? '需要' : '不需要';
  if (value === 'yes') return '需要';
  if (value === 'no') return '不需要';
  return valueLabel(VALUE_LABEL_FIELDS[field] || field, value);
}

function formatDuration(milliseconds: number): string {
  const safe = Math.max(0, Number(milliseconds) || 0);
  if (safe < 1000) return `${(safe / 1000).toFixed(1)}s`;
  const seconds = safe / 1000;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return `${minutes}:${String(rest).padStart(2, '0')}`;
}
