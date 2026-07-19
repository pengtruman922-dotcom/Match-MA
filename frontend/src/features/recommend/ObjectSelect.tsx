import { useEffect, useState } from 'react';
import { ChevronDown, Loader2, Search } from 'lucide-react';

export interface ObjectOption {
  id: string;
  label: string;
  subtitle?: string;
}

export default function ObjectSelect({
  placeholder,
  displayLabel,
  fetchOptions,
  onSelect,
  disabled = false,
}: {
  placeholder: string;
  displayLabel: string;
  fetchOptions: (q: string) => Promise<ObjectOption[]>;
  onSelect: (option: ObjectOption) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [options, setOptions] = useState<ObjectOption[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    const timer = window.setTimeout(() => {
      fetchOptions(query.trim())
        .then((next) => { if (!cancelled) setOptions(next); })
        .catch(() => { if (!cancelled) setOptions([]); })
        .finally(() => { if (!cancelled) setLoading(false); });
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [open, query, fetchOptions]);

  return (
    <div className="relative min-w-[260px]">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
        className="flex w-full items-center justify-between gap-2 border border-gray-200 bg-white px-3 py-1.5 text-left text-sm text-gray-700 hover:border-brand-300 disabled:opacity-50"
      >
        <span className="truncate">{displayLabel || placeholder}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-gray-400" />
      </button>
      {open && (
        <div className="absolute left-0 top-[calc(100%+4px)] z-40 w-[340px] border border-gray-200 bg-white shadow-lg">
          <div className="flex items-center gap-2 border-b border-gray-100 px-3 py-2">
            <Search className="h-3.5 w-3.5 text-gray-400" />
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="输入名称搜索..."
              className="flex-1 text-sm outline-none placeholder:text-gray-400"
            />
            {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-400" />}
          </div>
          <div className="max-h-72 overflow-y-auto py-1">
            {options.length === 0 ? (
              <p className="px-3 py-3 text-xs text-gray-400">{loading ? '搜索中...' : '暂无匹配'}</p>
            ) : (
              options.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  onMouseDown={(event) => {
                    event.preventDefault();
                    onSelect(option);
                    setOpen(false);
                    setQuery('');
                  }}
                  className="w-full px-3 py-2 text-left hover:bg-brand-50"
                >
                  <p className="truncate text-sm text-gray-900">{option.label}</p>
                  {option.subtitle && <p className="truncate text-[11px] text-gray-400">{option.subtitle}</p>}
                </button>
              ))
            )}
          </div>
        </div>
      )}
      {open && <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />}
    </div>
  );
}
