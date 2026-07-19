import { useState } from 'react';
import { History, Loader2 } from 'lucide-react';
import { recommendations } from '../../lib/api';
import type { RecommendationSessionSummary } from '../../types/api';

export default function SessionPicker({ onPick }: { onPick: (sessionId: string) => void }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [sessions, setSessions] = useState<RecommendationSessionSummary[]>([]);

  const load = async () => {
    setLoading(true);
    try {
      const page = await recommendations.page();
      const seen = new Set<string>();
      const merged: RecommendationSessionSummary[] = [];
      for (const summary of [...page.running_sessions, ...page.recent_sessions]) {
        const id = summary.session?.id;
        if (!id || seen.has(id)) continue;
        seen.add(id);
        merged.push(summary);
      }
      setSessions(merged.slice(0, 12));
    } catch {
      setSessions([]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => {
          setOpen((current) => !current);
          if (!open) void load();
        }}
        className="inline-flex items-center gap-1.5 border border-gray-200 px-3 py-1.5 text-sm font-medium text-gray-700 hover:border-brand-500 hover:text-brand-600"
      >
        <History className="h-3.5 w-3.5" />
        最近推荐
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-[calc(100%+4px)] z-40 w-[380px] border border-gray-200 bg-white shadow-lg">
            {loading ? (
              <div className="flex items-center gap-2 px-4 py-4 text-xs text-gray-400">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                正在加载...
              </div>
            ) : sessions.length === 0 ? (
              <p className="px-4 py-4 text-xs text-gray-400">暂无历史推荐会话</p>
            ) : (
              <div className="max-h-80 overflow-y-auto py-1">
                {sessions.map((summary) => {
                  const running = ['queued', 'running', 'retry_waiting'].includes(String(summary.rerank_status?.status || ''));
                  return (
                    <button
                      key={summary.session.id}
                      type="button"
                      onClick={() => {
                        onPick(summary.session.id);
                        setOpen(false);
                      }}
                      className="w-full px-4 py-2.5 text-left hover:bg-brand-50"
                    >
                      <div className="flex items-center gap-2">
                        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${running ? 'bg-amber-500' : 'bg-emerald-500'}`} />
                        <span className="truncate text-sm text-gray-900">{summary.display.title || '推荐会话'}</span>
                        <span className="shrink-0 text-[11px] text-gray-400">{summary.display.mode_label}</span>
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
