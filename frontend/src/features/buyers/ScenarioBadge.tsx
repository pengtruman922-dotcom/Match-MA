import { useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Layers, Loader2 } from 'lucide-react';
import { buyerIntents } from '../../lib/api';
import type { BuyerIntentScenario } from '../../types/api';
import { formatCompactMoney } from '../../lib/format';
import { valueLabel } from '../../lib/fieldLabels';

/** 把方案的 fields_json 压成一句话；只取列表用得上的几个维度。 */
function scenarioSummary(scenario: BuyerIntentScenario): string {
  const fields = scenario.fields_json || {};
  const parts: string[] = [];

  const listed = fields.acceptable_listed_status_json;
  if (Array.isArray(listed) && listed.length) {
    parts.push(listed.map((value) => valueLabel('preferred_listed_status', String(value))).join('、'));
  }
  const industries = fields.industries_json;
  if (Array.isArray(industries) && industries.length) parts.push(industries.map(String).join('、'));
  if (fields.min_revenue_yuan) parts.push(`营收≥${formatCompactMoney(Number(fields.min_revenue_yuan))}`);
  if (fields.min_net_profit_yuan) parts.push(`净利≥${formatCompactMoney(Number(fields.min_net_profit_yuan))}`);
  if (fields.max_pe) parts.push(`PE≤${Number(fields.max_pe).toFixed(0)}`);
  if (fields.max_market_cap_yuan) parts.push(`市值≤${formatCompactMoney(Number(fields.max_market_cap_yuan))}`);

  return parts.length ? parts.join(' · ') : '未设置结构化条件';
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
                scenarios.map((scenario) => (
                  <p key={scenario.id} className="px-1 py-1 text-xs leading-5 text-gray-600">
                    <span className="font-medium text-gray-900">{scenario.label}</span>
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
