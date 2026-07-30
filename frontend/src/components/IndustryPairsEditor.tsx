import { useMemo, useState } from 'react';
import type { IndustryOptionsResponse } from '../types/api';

export interface IndustryPairValue {
  l1: string;
  l2?: string;
}

export default function IndustryPairsEditor({
  value,
  options,
  onChange,
  showL2 = true,
}: {
  value: IndustryPairValue[];
  options: IndustryOptionsResponse;
  onChange: (value: IndustryPairValue[]) => void;
  showL2?: boolean;
}) {
  const [l1Query, setL1Query] = useState('');
  const [l2Query, setL2Query] = useState('');
  const [l2Scope, setL2Scope] = useState('selected');
  const selectedL1 = useMemo(() => [...new Set(value.map((pair) => pair.l1))], [value]);
  const visibleL1 = options.l1.filter(({ term }) => term.includes(l1Query.trim()));
  const visibleL2 = options.l2.filter(({ l1, term }) => {
    const inScope = l2Scope === 'all' || (l2Scope === 'selected' ? selectedL1.includes(l1) : l1 === l2Scope);
    return inScope && term.includes(l2Query.trim());
  });

  const toggleL1 = (l1: string) => {
    onChange(value.some((pair) => pair.l1 === l1)
      ? value.filter((pair) => pair.l1 !== l1)
      : [...value, { l1 }]);
  };
  const toggleL2 = (l1: string, l2: string) => {
    onChange(value.some((pair) => pair.l1 === l1 && pair.l2 === l2)
      ? value.filter((pair) => !(pair.l1 === l1 && pair.l2 === l2))
      : [...value, { l1, l2 }]);
  };

  return (
    <div className="space-y-3 border border-gray-200 bg-gray-50 p-3">
      <div>
        <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-gray-600">
          <span className="font-medium">一级行业（可多选）</span>
          <input value={l1Query} onChange={(event) => setL1Query(event.target.value)} placeholder="搜索行业" className="min-w-0 border border-gray-200 bg-white px-2 py-1 text-xs" />
        </div>
        <div className="grid max-h-40 grid-cols-2 gap-x-3 gap-y-1 overflow-y-auto sm:grid-cols-3">
          {visibleL1.map(({ term }) => (
            <label key={term} className="flex min-w-0 items-center gap-1 text-xs text-gray-700">
              <input type="checkbox" checked={selectedL1.includes(term)} onChange={() => toggleL1(term)} />
              <span className="truncate">{term}</span>
            </label>
          ))}
        </div>
      </div>
      {showL2 ? (
        <div className="border-t border-gray-200 pt-3">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-gray-600">
            <span className="font-medium">二级行业（可多选）</span>
            <select value={l2Scope} onChange={(event) => setL2Scope(event.target.value)} className="border border-gray-200 bg-white px-2 py-1 text-xs">
              <option value="selected">已选一级行业</option>
              <option value="all">全部一级行业</option>
              {selectedL1.map((l1) => <option key={l1} value={l1}>{l1}</option>)}
            </select>
            <input value={l2Query} onChange={(event) => setL2Query(event.target.value)} placeholder="搜索二级行业" className="min-w-0 border border-gray-200 bg-white px-2 py-1 text-xs" />
          </div>
          {selectedL1.length === 0 && l2Scope === 'selected' ? (
            <p className="text-xs text-gray-400">先选择一级行业，或切换为“全部一级行业”。</p>
          ) : (
            <div className="grid max-h-40 grid-cols-1 gap-x-3 gap-y-1 overflow-y-auto sm:grid-cols-2">
              {visibleL2.map(({ term, l1 }) => (
                <label key={`${l1}:${term}`} className="flex min-w-0 items-center gap-1 text-xs text-gray-700">
                  <input type="checkbox" checked={value.some((pair) => pair.l1 === l1 && pair.l2 === term)} onChange={() => toggleL2(l1, term)} />
                  <span className="truncate">{term}</span>
                  <span className="ml-auto shrink-0 text-[10px] text-gray-400">{l1}</span>
                </label>
              ))}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
