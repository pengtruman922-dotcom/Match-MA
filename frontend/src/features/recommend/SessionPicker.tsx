import { useEffect, useRef, useState } from 'react';
import { History, Loader2, Search, X } from 'lucide-react';
import { recommendations } from '../../lib/api';
import { isAdmin } from '../../lib/auth';
import type { RecommendationSessionSummary } from '../../types/api';

export default function SessionPicker({ onPick }: { onPick: (sessionId: string) => void }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [sessions, setSessions] = useState<RecommendationSessionSummary[]>([]);
  const [query, setQuery] = useState('');
  const [loadFailed, setLoadFailed] = useState(false);
  const requestSequence = useRef(0);
  const admin = isAdmin();

  useEffect(() => {
    if (!open) return;

    const sequence = ++requestSequence.current;
    const normalizedQuery = query.trim();
    setLoading(true);
    setLoadFailed(false);

    const timer = window.setTimeout(async () => {
      try {
        if (normalizedQuery) {
          const results = await recommendations.recentSessions({
            q: normalizedQuery,
            limit: 20,
            preview_limit: 0,
          });
          if (requestSequence.current === sequence) setSessions(results);
        } else {
          const page = await recommendations.page();
          const seen = new Set<string>();
          const merged: RecommendationSessionSummary[] = [];
          for (const summary of [...page.running_sessions, ...page.recent_sessions]) {
            const id = summary.session?.id;
            if (!id || seen.has(id)) continue;
            seen.add(id);
            merged.push(summary);
          }
          if (requestSequence.current === sequence) setSessions(merged.slice(0, 12));
        }
      } catch {
        if (requestSequence.current === sequence) {
          setSessions([]);
          setLoadFailed(true);
        }
      } finally {
        if (requestSequence.current === sequence) setLoading(false);
      }
    }, normalizedQuery ? 250 : 0);

    return () => {
      window.clearTimeout(timer);
      if (requestSequence.current === sequence) requestSequence.current += 1;
    };
  }, [open, query]);

  const close = () => {
    setOpen(false);
    setQuery('');
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => (open ? close() : setOpen(true))}
        className="inline-flex items-center gap-1.5 border border-gray-200 px-3 py-1.5 text-sm font-medium text-gray-700 hover:border-brand-500 hover:text-brand-600"
      >
        <History className="h-3.5 w-3.5" />
        最近推荐
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={close} />
          <div className="absolute right-0 top-[calc(100%+4px)] z-40 w-[400px] border border-gray-200 bg-white shadow-lg">
            <div className="border-b border-gray-100 p-2.5">
              <div className="flex items-center gap-2 border border-gray-200 px-2.5 focus-within:border-brand-500">
                <Search className="h-3.5 w-3.5 shrink-0 text-gray-400" />
                <input
                  autoFocus
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Escape') close();
                  }}
                  placeholder="搜索买家需求名或标的名"
                  className="min-w-0 flex-1 py-2 text-sm text-gray-800 outline-none placeholder:text-gray-400"
                />
                {query && (
                  <button
                    type="button"
                    onClick={() => setQuery('')}
                    aria-label="清空搜索"
                    className="p-0.5 text-gray-400 hover:text-gray-700"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            </div>
            {loading ? (
              <div className="flex items-center gap-2 px-4 py-4 text-xs text-gray-400">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                {query.trim() ? '正在搜索...' : '正在加载...'}
              </div>
            ) : loadFailed ? (
              <p className="px-4 py-4 text-xs text-red-500">推荐记录加载失败，请稍后重试</p>
            ) : sessions.length === 0 ? (
              <p className="px-4 py-4 text-xs text-gray-400">
                {query.trim() ? `未找到包含“${query.trim()}”的推荐记录` : '暂无历史推荐会话'}
              </p>
            ) : (
              <div className="max-h-80 overflow-y-auto py-1">
                {sessions.map((summary) => {
                  const running = ['queued', 'running', 'retry_waiting'].includes(String(summary.rerank_status?.status || ''));
                  const creatorUsername = typeof summary.session.created_by_username === 'string'
                    ? summary.session.created_by_username
                    : null;
                  const creatorName = typeof summary.session.created_by_name === 'string'
                    ? summary.session.created_by_name
                    : null;
                  const creatorLabel = creatorUsername ? `@${creatorUsername}` : creatorName || '未知用户';
                  const creatorTitle = creatorName && creatorUsername
                    ? `发起人：${creatorName}（@${creatorUsername}）`
                    : `发起人：${creatorLabel}`;
                  return (
                    <button
                      key={summary.session.id}
                      type="button"
                      onClick={() => {
                        onPick(summary.session.id);
                        close();
                      }}
                      className="w-full px-4 py-2.5 text-left hover:bg-brand-50"
                    >
                      <div className="flex items-center gap-2">
                        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${running ? 'bg-amber-500' : 'bg-emerald-500'}`} />
                        <span className="truncate text-sm text-gray-900">{summary.display.title || '推荐会话'}</span>
                        <span className="shrink-0 text-[11px] text-gray-400">{summary.display.mode_label}</span>
                        {admin && (
                          <span
                            title={creatorTitle}
                            className="max-w-28 shrink-0 truncate bg-sky-50 px-1.5 py-0.5 text-[11px] text-sky-700"
                          >
                            {creatorLabel}
                          </span>
                        )}
                      </div>
                      <p className="ml-3.5 mt-0.5 text-[11px] text-gray-400">
                        {summary.candidate_counts.latest} 候选 · 已选 {Number(summary.selected_status?.active_count ?? 0)}
                        {Number(summary.report_status?.report_count ?? 0) > 0 && ` · ${Number(summary.report_status?.report_count)} 报告`}
                        {running && ' · 深评进行中'}
                      </p>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
