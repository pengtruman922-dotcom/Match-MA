import { useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Layers, Loader2 } from 'lucide-react';
import { buyerIntents } from '../../lib/api';
import type { BuyerIntentScenario } from '../../types/api';
import { formatCompactMoney } from '../../lib/format';
import { valueLabel } from '../../lib/fieldLabels';

/** 把一个方案压成一句话；只取列表用得上的几个维度。
 *
 * 0901 起读的是方案表的真列，不再是 fields_json 那个没有 schema 的袋子 ——
 * 实测 18 个方案的 83 个取值里有 25 个打在已退役的列上，那正是没 schema 的后果。 */
function scenarioSummary(scenario: BuyerIntentScenario): string {
  const parts: string[] = [];

  const listed = scenario.acceptable_listed_status_json;
  if (Array.isArray(listed) && listed.length) {
    parts.push(listed.map((value) => valueLabel('acceptable_listed_status_json', String(value))).join('、'));
  }
  const tags = scenario.business_tags_json;
  if (Array.isArray(tags) && tags.length) parts.push(tags.map(String).join('、'));
  if (scenario.min_revenue_yuan) parts.push(`营收≥${formatCompactMoney(Number(scenario.min_revenue_yuan))}`);
  if (scenario.min_net_profit_yuan) parts.push(`净利≥${formatCompactMoney(Number(scenario.min_net_profit_yuan))}`);
  if (scenario.max_pe) parts.push(`PE≤${Number(scenario.max_pe).toFixed(0)}`);
  if (scenario.max_market_cap_yuan) parts.push(`市值≤${formatCompactMoney(Number(scenario.max_market_cap_yuan))}`);

  // 一条门槛都没提**不是**「信息不足」，它是库里最灵活的那批方案，恰恰最该推。
  return parts.length ? parts.join(' · ') : '没有门槛，不构成障碍';
}

/** 方案没有名称（0901 判决三：摘要就是标题），抬头取摘要首句。 */
function scenarioTitle(scenario: BuyerIntentScenario, index: number): string {
  const summary = (scenario.scenario_summary || '').trim();
  if (!summary) return `方案 ${index + 1}`;
  const firstLine = summary.split(/[\n。；;]/)[0].trim();
  return firstLine.length > 18 ? `${firstLine.slice(0, 18)}…` : firstLine || `方案 ${index + 1}`;
}

export default function ScenarioBadge({ intentId, labels }: { intentId: string; labels: string[] }) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const [scenarios, setScenarios] = useState<BuyerIntentScenario[] | null>(null);
  const [loading, setLoading] = useState(false);
  const anchorRef = useRef<HTMLSpanElement | null>(null);

  if (!labels.length) return null;

  const show = () => {
    if (anchorRef.current) {
      const rect = anchorRef.current.getBoundingClientRect();
      const width = 300;
      setPosition({
        top: rect.bottom + 6,
        left: Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)),
      });
    }
    setOpen(true);
    if (scenarios || loading) return;
    setLoading(true);
    buyerIntents
      .scenarios(intentId)
      .then((rows) => setScenarios(rows.filter((row) => row.active)))
      .catch(() => setScenarios([]))
      .finally(() => setLoading(false));
  };

  const initials = labels
    .map((label) => label.replace(/^方案\s*/, '').trim().charAt(0) || '·')
    .slice(0, 3)
    .join('|');

  return (
    <>
      <span
        ref={anchorRef}
        onMouseEnter={show}
        onMouseLeave={() => setOpen(false)}
        className="mt-1 inline-flex cursor-default items-center gap-1 bg-violet-50 px-1.5 py-0.5 text-[11px] leading-4 text-violet-700"
      >
        <Layers className="h-3 w-3" />
        {initials} {labels.length}个方案
      </span>
      {open
        ? createPortal(
            <div
              className="pointer-events-none fixed z-[90] w-[300px] border border-gray-200 bg-white p-2 shadow-xl"
              style={{ top: position.top, left: position.left }}
            >
              {loading ? (
                <p className="flex items-center gap-1.5 px-1 py-1 text-xs text-gray-500">
                  <Loader2 className="h-3 w-3 animate-spin" />读取方案...
                </p>
              ) : scenarios && scenarios.length ? (
                scenarios.map((scenario, index) => (
                  <p key={scenario.id} className="px-1 py-1 text-xs leading-5 text-gray-600">
                    <span className="font-medium text-gray-900">{scenarioTitle(scenario, index)}</span>
                    <span className="text-gray-400">：</span>
                    {scenarioSummary(scenario)}
                  </p>
                ))
              ) : (
                <p className="px-1 py-1 text-xs text-gray-400">未读取到启用中的方案</p>
              )}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
