import { useEffect, useRef, useState } from 'react';
import { Loader2, Search, X } from 'lucide-react';
import { buyerIntents } from '../../lib/api';
import type { BuyerIntent } from '../../types/api';

/**
 * A quiet way back to an existing buyer intent.
 *
 * Deliberately a text link rather than a select: typing the requirement is the
 * main path now, and a dropdown sitting above the box would put the old
 * "pick an object first" flow back in front of it. Picking one only fills the
 * box — no session is anchored and nothing is created.
 */
export default function IntentPicker({ onPick }: { onPick: (intentId: string) => void }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<BuyerIntent[]>([]);
  const [query, setQuery] = useState('');
  const [failed, setFailed] = useState(false);
  const requestSequence = useRef(0);

  useEffect(() => {
    if (!open) return;
    const sequence = ++requestSequence.current;
    setLoading(true);
    setFailed(false);
    const timer = window.setTimeout(async () => {
      try {
        const page = await buyerIntents.list({ q: query.trim() || undefined, limit: 20 });
        if (requestSequence.current === sequence) setItems(page.items);
      } catch {
        if (requestSequence.current === sequence) {
          setItems([]);
          setFailed(true);
        }
      } finally {
        if (requestSequence.current === sequence) setLoading(false);
      }
    }, query.trim() ? 250 : 0);
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
        className="text-xs text-gray-400 hover:text-brand-600"
        data-testid="intent-picker-open"
      >
        从已有买家需求带入 ›
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={close} />
          <div className="absolute left-0 top-[calc(100%+6px)] z-40 w-[380px] border border-gray-200 bg-white shadow-lg">
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
                  placeholder="搜索买家或需求名"
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
                正在加载...
              </div>
            ) : failed ? (
              <p className="px-4 py-4 text-xs text-red-500">买家需求加载失败，请稍后重试</p>
            ) : items.length === 0 ? (
              <p className="px-4 py-4 text-xs text-gray-400">
                {query.trim() ? `未找到包含“${query.trim()}”的买家需求` : '暂无买家需求'}
              </p>
            ) : (
              <div className="max-h-72 overflow-y-auto py-1">
                {items.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => {
                      onPick(item.id);
                      close();
                    }}
                    className="w-full px-4 py-2 text-left hover:bg-brand-50"
                  >
                    <p className="truncate text-sm text-gray-900">{item.intent_name}</p>
                    <p className="mt-0.5 truncate text-[11px] text-gray-400">
                      {[item.buyer_name, item.industry_primary, item.region_scope_summary]
                        .filter(Boolean)
                        .join(' · ') || '未填写条件'}
                    </p>
                  </button>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
