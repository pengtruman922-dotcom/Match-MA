import { useEffect, useRef, useState } from 'react';
import { Columns3, GripVertical, RotateCcw, X } from 'lucide-react';
import {
  INTENT_COLUMNS,
  moveColumn,
  resetColumnPrefs,
  resolveAllColumnsInOrder,
  toggleColumn,
  type IntentColumnDef,
  type IntentColumnKey,
  type IntentColumnPrefs,
} from './intentColumns';

const SIDE_LABEL: Record<IntentColumnDef['side'], string> = {
  buyer: '买家自身条件',
  intent: '需求条件',
  meta: '状态与归属',
};

/**
 * 列的显示/隐藏与排序。
 *
 * 只管中间那些列 —— 勾选框、买家名称、操作是冻结列，藏掉或挪走会让整行读不懂，
 * 所以它们根本不出现在这里，而不是列出来再禁用（列出来会让人反复去点）。
 */
export default function ColumnManager({
  prefs,
  onChange,
}: {
  prefs: IntentColumnPrefs;
  onChange: (next: IntentColumnPrefs) => void;
}) {
  const [open, setOpen] = useState(false);
  const [dragKey, setDragKey] = useState<IntentColumnKey | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    // 捕获阶段：面板里的按钮自己会 stopPropagation，冒泡阶段会漏掉外部点击。
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', escape);
    };
  }, [open]);

  const columns = resolveAllColumnsInOrder(prefs);
  const hidden = new Set(prefs.hidden);
  const visibleCount = columns.length - hidden.size;

  return (
    <div className="relative" ref={panelRef}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-1.5 border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition-colors hover:border-brand-600 hover:text-brand-600"
        title="选择要显示的列，拖动可调整顺序"
      >
        <Columns3 className="h-4 w-4" />
        列
        <span className="text-xs text-gray-400">{visibleCount}/{INTENT_COLUMNS.length}</span>
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-1 w-72 border border-gray-200 bg-white shadow-xl">
          <div className="flex items-center justify-between border-b border-gray-100 px-3 py-2">
            <span className="text-xs font-medium text-gray-700">显示的列</span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => onChange(resetColumnPrefs())}
                className="inline-flex items-center gap-1 px-1.5 py-1 text-[11px] text-gray-500 hover:text-brand-600"
                title="恢复默认顺序并显示全部"
              >
                <RotateCcw className="h-3 w-3" />
                重置
              </button>
              <button type="button" onClick={() => setOpen(false)} className="p-1 text-gray-400 hover:text-gray-700" aria-label="关闭">
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          <div className="max-h-[420px] overflow-y-auto py-1">
            {columns.map((column, index) => {
              const previous = columns[index - 1];
              const showHeader = !previous || previous.side !== column.side;
              return (
                <div key={column.key}>
                  {showHeader && (
                    <p className="px-3 pb-0.5 pt-2 text-[11px] font-medium text-gray-400">{SIDE_LABEL[column.side]}</p>
                  )}
                  <div
                    draggable
                    onDragStart={() => setDragKey(column.key)}
                    onDragEnd={() => setDragKey(null)}
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={(event) => {
                      event.preventDefault();
                      if (dragKey && dragKey !== column.key) onChange(moveColumn(prefs, dragKey, column.key));
                      setDragKey(null);
                    }}
                    className={`flex cursor-grab items-center gap-2 px-3 py-1.5 hover:bg-gray-50 ${
                      dragKey === column.key ? 'opacity-40' : ''
                    }`}
                  >
                    <GripVertical className="h-3.5 w-3.5 shrink-0 text-gray-300" />
                    <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2">
                      <input
                        type="checkbox"
                        checked={!hidden.has(column.key)}
                        onChange={() => onChange(toggleColumn(prefs, column.key))}
                        className="h-3.5 w-3.5 border-gray-300 text-brand-600 focus:ring-brand-600"
                      />
                      <span className={`truncate text-xs ${hidden.has(column.key) ? 'text-gray-400' : 'text-gray-700'}`} title={column.title}>
                        {column.label}
                      </span>
                    </label>
                  </div>
                </div>
              );
            })}
          </div>

          <p className="border-t border-gray-100 px-3 py-2 text-[11px] leading-4 text-gray-400">
            买家名称与操作列固定显示。设置只保存在这台设备上。
          </p>
        </div>
      )}
    </div>
  );
}
