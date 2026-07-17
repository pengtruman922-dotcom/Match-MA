import { Loader2, Tag } from 'lucide-react';

interface SuggestionLike {
  id: string;
  search_field: string;
  match_text: string;
  match_label: string;
}

export default function SearchSuggestionList<T extends SuggestionLike>({
  open,
  loading,
  suggestions,
  onSelect,
  subtitle,
}: {
  open: boolean;
  loading: boolean;
  suggestions: T[];
  onSelect: (suggestion: T) => void;
  subtitle: (suggestion: T) => string;
}) {
  if (!open) return null;

  return (
    <div className="absolute left-0 right-0 top-[calc(100%+4px)] z-40 border border-gray-200 bg-white shadow-lg">
      {loading ? (
        <div className="flex items-center gap-2 px-3 py-3 text-xs text-gray-400">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          正在查找匹配项...
        </div>
      ) : suggestions.length === 0 ? (
        <div className="px-3 py-3 text-xs text-gray-400">暂无匹配建议，回车可全文搜索</div>
      ) : (
        <div className="py-1">
          {suggestions.map((suggestion) => (
            <button
              key={`${suggestion.id}-${suggestion.search_field}`}
              type="button"
              onMouseDown={(event) => {
                event.preventDefault();
                onSelect(suggestion);
              }}
              className="w-full px-3 py-2 text-left hover:bg-brand-50 transition-colors"
            >
              <div className="flex items-center gap-2">
                <span className="max-w-[260px] truncate text-sm text-gray-900">{suggestion.match_text}</span>
                <span className="inline-flex shrink-0 items-center gap-1 rounded-sm bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600">
                  <Tag className="h-2.5 w-2.5" />
                  {suggestion.match_label}
                </span>
              </div>
              <p className="mt-0.5 truncate text-[11px] text-gray-400">{subtitle(suggestion)}</p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
