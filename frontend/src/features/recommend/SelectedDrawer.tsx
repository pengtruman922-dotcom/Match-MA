import { useState } from 'react';
import { ChevronDown, FileText, X } from 'lucide-react';
import type { RecommendationSelectedItem } from '../../types/api';

export default function SelectedDrawer({
  items,
  onRemove,
  onOpenReport,
}: {
  items: RecommendationSelectedItem[];
  onRemove: (item: RecommendationSelectedItem) => void;
  onOpenReport: () => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="inline-flex items-center gap-1.5 border border-gray-200 px-3 py-1.5 text-sm font-medium text-gray-700 hover:border-brand-500 hover:text-brand-600"
      >
        已选 <span className="font-semibold text-emerald-700">{items.length}</span>
        <ChevronDown className="h-3.5 w-3.5" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-[calc(100%+4px)] z-40 w-[360px] border border-gray-200 bg-white shadow-lg">
            {items.length === 0 ? (
              <p className="px-4 py-4 text-xs text-gray-400">尚未加入任何推荐项</p>
            ) : (
              <div className="max-h-72 overflow-y-auto py-1">
                {items.map((item, index) => (
                  <div key={item.id} className="flex items-center justify-between gap-2 px-4 py-2 hover:bg-gray-50">
                    <span className="min-w-0 truncate text-sm text-gray-800">
                      {index + 1}. {item.seller_target_name || `${item.buyer_name || ''} / ${item.buyer_intent_name || ''}`}
                    </span>
                    <button
                      type="button"
                      onClick={() => onRemove(item)}
                      className="shrink-0 p-1 text-gray-400 hover:text-red-600"
                      title="移出推荐列表"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className="border-t border-gray-100 px-4 py-2">
              <button
                type="button"
                disabled={items.length === 0}
                onClick={() => {
                  setOpen(false);
                  onOpenReport();
                }}
                className="inline-flex w-full items-center justify-center gap-1.5 bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-40"
              >
                <FileText className="h-3.5 w-3.5" />
                生成推荐报告
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
