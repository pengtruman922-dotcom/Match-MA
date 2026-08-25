import { useMemo, useState } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';
import type { BuyerParty } from '../../types/api';

/** 行情日更，7 天内通常不改变量级判断。与后端 MARKET_CAP_STALE_DAYS 同一口径。 */
const MARKET_CAP_STALE_DAYS = 7;

function marketCapIsStale(party: BuyerParty, now = Date.now()): boolean {
  if (party.listed_status !== 'listed') return false;
  if (!party.market_cap_as_of) return true;
  const at = Date.parse(party.market_cap_as_of);
  if (Number.isNaN(at)) return true;
  return now - at > MARKET_CAP_STALE_DAYS * 24 * 60 * 60 * 1000;
}

/**
 * 批量联网补全 / 刷新前的二次确认。
 *
 * 形态照标的侧的 BatchResearchDialog：**不做服务器静默过滤**。用户勾了 30 个，
 * 系统悄悄少跑 12 个、界面什么都不说，是标的侧改掉过的老毛病。
 * 这里把「最近刷过的」列出来让人自己决定。
 */
export default function BatchPartyIngestDialog({
  parties,
  submitting,
  onCancel,
  onConfirm,
}: {
  parties: BuyerParty[];
  submitting: boolean;
  onCancel: () => void;
  onConfirm: (ids: string[], mode: 'fill' | 'refresh') => void;
}) {
  const [mode, setMode] = useState<'fill' | 'refresh'>('refresh');
  const { stale, fresh } = useMemo(() => {
    const now = Date.now();
    return {
      stale: parties.filter((item) => marketCapIsStale(item, now)),
      fresh: parties.filter((item) => !marketCapIsStale(item, now)),
    };
  }, [parties]);

  const defaultIds = mode === 'refresh' ? stale.map((item) => item.id) : parties.map((item) => item.id);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set(defaultIds));

  const switchMode = (next: 'fill' | 'refresh') => {
    setMode(next);
    setSelectedIds(
      new Set(next === 'refresh' ? stale.map((item) => item.id) : parties.map((item) => item.id)),
    );
  };

  const toggle = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4">
      <div className="max-h-[80vh] w-full max-w-2xl overflow-y-auto bg-white shadow-lg">
        <div className="border-b border-gray-100 px-5 py-3">
          <h2 className="text-sm font-semibold text-gray-900">批量 AI 补全买家信息</h2>
          <p className="mt-1 text-xs text-gray-500">
            共选择 {parties.length} 个买家主体，当前将提交 {selectedIds.size} 个任务。每个任务约需 5–10 分钟，在后台跑。
          </p>
        </div>

        <div className="space-y-4 px-5 py-4">
          <div className="flex flex-wrap gap-4 text-xs">
            <label className="flex items-center gap-1.5">
              <input type="radio" checked={mode === 'refresh'} onChange={() => switchMode('refresh')} className="h-3.5 w-3.5" />
              只刷新过期的财务数据（预算小，不重新认公司）
            </label>
            <label className="flex items-center gap-1.5">
              <input type="radio" checked={mode === 'fill'} onChange={() => switchMode('fill')} className="h-3.5 w-3.5" />
              联网补全所有空字段
            </label>
          </div>

          <section>
            <h3 className="text-xs font-medium text-gray-700">
              {mode === 'refresh' ? `财务数据已过期（${stale.length}）` : `本次选择（${parties.length}）`}
            </h3>
            <p className="mt-1 text-xs text-gray-400">
              {mode === 'refresh'
                ? `上市买家的市值超过 ${MARKET_CAP_STALE_DAYS} 天，或从未记录过行情日期。`
                : '会去补全材料与库里都还空着的字段。'}
            </p>
            <ul className="mt-2 max-h-48 divide-y divide-gray-100 overflow-y-auto border border-gray-200">
              {(mode === 'refresh' ? stale : parties).map((item) => (
                <li key={item.id} className="flex items-center gap-2 px-3 py-2 text-xs">
                  <input
                    type="checkbox"
                    checked={selectedIds.has(item.id)}
                    onChange={() => toggle(item.id)}
                    className="h-3.5 w-3.5"
                  />
                  <span className="min-w-0 flex-1 truncate text-gray-800">{item.buyer_name}</span>
                  <span className="shrink-0 text-gray-400">{item.market_cap_as_of || '无行情日期'}</span>
                </li>
              ))}
            </ul>
            {(mode === 'refresh' ? stale : parties).length === 0 ? (
              <p className="mt-2 text-xs text-gray-400">没有需要处理的买家主体。</p>
            ) : null}
          </section>

          {mode === 'refresh' && fresh.length > 0 ? (
            <section>
              <p className="flex items-start gap-1.5 border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                  以下 {fresh.length} 个买家的市值在 {MARKET_CAP_STALE_DAYS} 天内刷新过，或本来就不是上市公司。
                  重复调研会产生费用，需要的话自己勾上。
                </span>
              </p>
              <ul className="mt-2 max-h-36 divide-y divide-gray-100 overflow-y-auto border border-gray-200">
                {fresh.map((item) => (
                  <li key={item.id} className="flex items-center gap-2 px-3 py-2 text-xs">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(item.id)}
                      onChange={() => toggle(item.id)}
                      className="h-3.5 w-3.5"
                    />
                    <span className="min-w-0 flex-1 truncate text-gray-800">{item.buyer_name}</span>
                    <span className="shrink-0 text-gray-400">{item.market_cap_as_of || '非上市'}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-gray-100 px-5 py-3">
          <button type="button" onClick={onCancel} className="px-3 py-1.5 text-sm text-gray-500">
            取消
          </button>
          <button
            type="button"
            disabled={submitting || selectedIds.size === 0}
            onClick={() => onConfirm(Array.from(selectedIds), mode)}
            className="inline-flex cursor-pointer items-center gap-1.5 bg-brand-600 px-3 py-1.5 text-sm text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            提交 {selectedIds.size} 个任务
          </button>
        </div>
      </div>
    </div>
  );
}
