import { useMemo, useState } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';
import type { SellerTarget } from '../../types/api';
import { RECENT_RESEARCH_DAYS } from './researchWindow';

function isRecentlyCompleted(target: SellerTarget, now = Date.now()): boolean {
  if (target.research_last_outcome === 'failed') return false;
  if (!target.last_research_at) return false;
  const at = Date.parse(target.last_research_at);
  if (Number.isNaN(at)) return false;
  return now - at < RECENT_RESEARCH_DAYS * 24 * 60 * 60 * 1000;
}

function isResearching(target: SellerTarget): boolean {
  return target.ai_processing_state === 'researching' || target.information_status === 'researching';
}

/**
 * 批量调研前的二次确认。
 *
 * 服务端曾用 research_retry_after 静默跳过近期调研过的标的：用户勾了 50 个，
 * 系统悄悄少跑 12 个，界面上什么都不说。改成显式列出来让人决定 ——
 * 用户知情、可覆盖，而且"系统记得上次什么时候查过"这件事本身变得可见。
 */
export default function BatchResearchDialog({
  targets,
  submitting,
  onCancel,
  onConfirm,
}: {
  targets: SellerTarget[];
  submitting: boolean;
  onCancel: () => void;
  onConfirm: (ids: string[]) => void;
}) {
  const { ready, researching, recent } = useMemo(() => {
    const now = Date.now();
    return {
      ready: targets.filter((item) => !isResearching(item) && !isRecentlyCompleted(item, now)),
      researching: targets.filter(isResearching),
      recent: targets.filter((item) => !isResearching(item) && isRecentlyCompleted(item, now)),
    };
  }, [targets]);

  const [includeRecent, setIncludeRecent] = useState<Set<string>>(new Set());

  const selectedIds = [...ready.map((item) => item.id), ...Array.from(includeRecent)];

  const toggle = (id: string) => {
    setIncludeRecent((prev) => {
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
          <h2 className="text-sm font-semibold text-gray-900">批量 AI 调研</h2>
          <p className="mt-1 text-xs text-gray-500">
            共选择 {targets.length} 个标的，当前将提交 {selectedIds.length} 个调研任务。
          </p>
        </div>

        <div className="space-y-4 px-5 py-4">
          <section>
            <h3 className="text-xs font-medium text-gray-700">即将调研（{ready.length}）</h3>
            <p className="mt-1 text-xs text-gray-400">包含从未调研、超过 30 天，以及最近一次调研失败的标的。</p>
            {ready.length > 0 ? (
              <ul className="mt-2 max-h-44 divide-y divide-gray-100 overflow-y-auto border border-gray-200">
                {ready.map((item) => (
                  <li key={item.id} className="px-3 py-2 text-xs text-gray-800">{item.target_name}</li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-xs text-gray-400">暂无默认提交的标的。</p>
            )}
          </section>

          {researching.length > 0 ? (
            <section>
              <p className="flex items-start gap-1.5 border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800">
                <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin" />
                以下 {researching.length} 个标的正在调研中，本次不会重复提交。
              </p>
              <ul className="mt-2 max-h-36 divide-y divide-gray-100 overflow-y-auto border border-gray-200">
                {researching.map((item) => (
                  <li key={item.id} className="flex items-center justify-between gap-2 px-3 py-2 text-xs">
                    <span className="truncate text-gray-700">{item.target_name}</span>
                    <span className="shrink-0 text-blue-600">调研中</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {recent.length > 0 ? (
            <section>
              <p className="flex items-start gap-1.5 border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                  以下 {recent.length} 个标的在 {RECENT_RESEARCH_DAYS} 天内已经调研过。公网信息变化通常没那么快，
                  重复调研会产生费用。勾选需要重新调研的标的。
                </span>
              </p>
              <ul className="mt-2 divide-y divide-gray-100 border border-gray-200">
                {recent.map((item) => (
                  <li key={item.id} className="flex items-center gap-2 px-3 py-2 text-xs">
                    <input
                      type="checkbox"
                      checked={includeRecent.has(item.id)}
                      onChange={() => toggle(item.id)}
                      className="h-3.5 w-3.5"
                    />
                    <span className="flex-1 truncate text-gray-800">{item.target_name}</span>
                    <span className="shrink-0 text-gray-400">
                      {item.last_research_at?.slice(0, 10)}
                    </span>
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
            disabled={submitting || selectedIds.length === 0}
            onClick={() => onConfirm(selectedIds)}
            className="inline-flex items-center gap-1.5 bg-brand-600 px-3 py-1.5 text-sm text-white disabled:opacity-40"
          >
            {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            调研 {selectedIds.length} 个标的
          </button>
        </div>
      </div>
    </div>
  );
}
