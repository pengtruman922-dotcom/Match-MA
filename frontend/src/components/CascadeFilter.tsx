import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import type { SellerTargetCountedOption } from '../types/api';

export interface CascadeOption {
  value: string;
  count: number;
  inventoryOnly?: boolean;
}

export interface CascadeLevel {
  placeholder: string;
  options: CascadeOption[];
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  /** Levels with hundreds of entries (二级行业, 区县) get a filter box. */
  searchable?: boolean;
}

/**
 * A filter whose levels narrow each other, e.g. 省 → 市 → 区.
 *
 * Options come from a dictionary (行业字典 / 行政区划), not from the values that
 * happen to exist in the library, so a freshly-added target is findable by a
 * category nobody has used yet. `count` only annotates how many targets sit
 * behind each choice; zero-count entries stay selectable but sort last and
 * render muted.
 */
export default function CascadeFilter({
  label,
  summary,
  levels,
  onClear,
}: {
  label: string;
  summary: string;
  levels: CascadeLevel[];
  onClear: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative w-[200px]">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="flex w-full items-center justify-between gap-2 border border-gray-200 bg-white px-3 py-2 text-left text-sm text-gray-600 outline-none transition-colors hover:border-brand-300 focus:border-brand-600"
        title={`${label} ${summary}`}
      >
        <span className="truncate">
          {label} {summary}
        </span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-gray-400" />
      </button>
      {open && (
        <>
          {/* Click-away without onBlur, so clicking inside the panel does not
              close it before the level buttons receive their event. */}
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-[calc(100%+4px)] z-40 w-[260px] border border-gray-200 bg-white p-2 shadow-lg">
            <div className="space-y-2">
              {levels.map((level) => (
                <LevelPicker key={level.placeholder} level={level} />
              ))}
            </div>
            <div className="mt-2 flex items-center justify-between border-t border-gray-100 pt-2">
              <button
                type="button"
                onClick={() => {
                  onClear();
                  setOpen(false);
                }}
                className="text-xs text-gray-400 hover:text-gray-600"
              >
                清空
              </button>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="text-xs text-brand-600 hover:text-brand-700"
              >
                完成
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function LevelPicker({ level }: { level: CascadeLevel }) {
  const [query, setQuery] = useState('');
  const needle = query.trim().toLowerCase();
  const visible = needle
    ? level.options.filter((option) => option.value.toLowerCase().includes(needle))
    : level.options;

  return (
    <div>
      {level.searchable && !level.disabled && (
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={`搜索${level.placeholder}`}
          className="mb-1 w-full border border-gray-200 px-2 py-1 text-xs outline-none focus:border-brand-500"
        />
      )}
      <select
        value={level.value}
        disabled={level.disabled}
        onChange={(event) => level.onChange(event.target.value)}
        className="w-full border border-gray-200 bg-white px-2 py-1.5 text-sm text-gray-700 outline-none focus:border-brand-600 disabled:bg-gray-50 disabled:text-gray-400"
      >
        <option value="">{level.placeholder}（全部）</option>
        {visible.map((option) => (
          <option key={option.value} value={option.value}>
            {option.value}
            {option.count ? ` (${option.count})` : ''}
            {option.inventoryOnly ? ' · 库内值' : ''}
          </option>
        ))}
      </select>
    </div>
  );
}

/**
 * Annotate dictionary terms with library counts.
 *
 * The dictionary defines what is selectable; counts only reorder and label.
 * Terms nobody has used yet keep count 0 and sort last, so "this category is
 * empty" reads differently from "this category is missing".
 */
export function withCounts(
  terms: string[],
  counted: SellerTargetCountedOption[] | undefined,
): CascadeOption[] {
  const countByValue = new Map((counted || []).map((item) => [item.value, item.count]));
  const dictionaryValues = new Set(terms);
  const allValues = [...terms];
  for (const item of counted || []) {
    if (!dictionaryValues.has(item.value)) allValues.push(item.value);
  }
  return [...new Set(allValues)]
    .map((term) => ({
      value: term,
      count: countByValue.get(term) || 0,
      inventoryOnly: !dictionaryValues.has(term),
    }))
    .sort((left, right) => right.count - left.count || left.value.localeCompare(right.value, 'zh'));
}

export function childrenOf(
  counted: SellerTargetCountedOption[] | undefined,
  value: string,
): SellerTargetCountedOption[] {
  return (counted || []).find((item) => item.value === value)?.children || [];
}
