import type { ReactNode } from 'react';
import { Search, Tag } from 'lucide-react';
import FilterSelect, { type FilterOption } from '../../components/FilterSelect';
import SearchSuggestionList from '../../components/SearchSuggestionList';
import type { BuyerSuggestion } from './filters';
import { suggestionSubtitle } from './filters';

export default function ListToolbar({
  searchValue,
  placeholder,
  suggestions,
  suggestionsOpen,
  suggestionsLoading,
  onSearchValueChange,
  onSearchFocus,
  onSearchBlur,
  onSearch,
  onSuggestionSelect,
  searchFieldBadge,
  filters,
  activeFilterCount,
  onClear,
  total,
  totalLabel,
  trailing,
}: {
  searchValue: string;
  placeholder: string;
  suggestions: BuyerSuggestion[];
  suggestionsOpen: boolean;
  suggestionsLoading: boolean;
  onSearchValueChange: (value: string) => void;
  onSearchFocus: () => void;
  onSearchBlur: () => void;
  onSearch: () => void;
  onSuggestionSelect: (suggestion: BuyerSuggestion) => void;
  searchFieldBadge: string;
  filters: Array<{ label: string; value: string; options: FilterOption[]; onChange: (value: string) => void }>;
  activeFilterCount: number;
  onClear: () => void;
  total: number;
  totalLabel: string;
  /** 挂在条件行末尾的额外控件（买家列表用它放列管理器）。 */
  trailing?: ReactNode;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 min-w-[280px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={searchValue}
            onChange={(event) => onSearchValueChange(event.target.value)}
            onFocus={onSearchFocus}
            onBlur={onSearchBlur}
            onKeyDown={(event) => event.key === 'Enter' && onSearch()}
            placeholder={placeholder}
            className="w-full pl-9 pr-4 py-2 border border-gray-200 text-sm outline-none focus:border-brand-600 transition-colors bg-white"
          />
          <SearchSuggestionList
            open={suggestionsOpen}
            loading={suggestionsLoading}
            suggestions={suggestions}
            onSelect={onSuggestionSelect}
            subtitle={suggestionSubtitle}
          />
        </div>
        {filters.map((filter) => <FilterSelect key={filter.label} label={filter.label} value={filter.value} options={filter.options} onChange={filter.onChange} />)}
        <button onClick={onSearch} className="px-3 py-2 border border-gray-200 text-sm font-medium text-gray-700 hover:border-brand-600 hover:text-brand-600 transition-colors bg-white">搜索</button>
        {activeFilterCount > 0 && <button onClick={onClear} className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700">清空条件</button>}
        <span className="text-xs text-gray-400">共 {total} 个{totalLabel}</span>
        {trailing ? <div className="ml-auto">{trailing}</div> : null}
      </div>
      {searchFieldBadge && <div className="flex items-center gap-2 text-xs text-gray-500"><span className="inline-flex items-center gap-1 bg-brand-50 text-brand-700 px-2 py-1"><Tag className="w-3 h-3" />{searchFieldBadge}</span></div>}
    </div>
  );
}
