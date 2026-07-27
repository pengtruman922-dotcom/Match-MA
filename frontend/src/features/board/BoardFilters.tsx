import { Info, Search } from 'lucide-react';
import type { BoardOwnership, BoardView } from './boardBuckets';

const VIEW_TABS: Array<{ value: BoardView; label: string }> = [
  { value: 'target', label: '按标的' },
  { value: 'intent', label: '按意向' },
];

/** 责任范围三态（D6）。默认「我参与的」——OR 语义，避免一方归同事的关系变成孤儿卡。 */
const OWNERSHIP_OPTIONS: Array<{ value: BoardOwnership; label: string; hint: string }> = [
  { value: 'all', label: '全部', hint: '权限范围内全看' },
  { value: 'involved', label: '我参与的', hint: '标的、意向、买家任一方归我' },
  { value: 'sole', label: '我全权的', hint: '标的和买家双方都归我；一方归同事的关系不会出现' },
];

const SELECT_CLASS =
  'border border-gray-200 bg-white px-2 py-2 text-sm text-gray-600 outline-none transition-colors hover:border-brand-300 focus:border-brand-600';

export default function BoardFilters({
  view,
  q,
  ownership,
  hideStale,
  onViewChange,
  onQChange,
  onOwnershipChange,
  onHideStaleChange,
}: {
  view: BoardView;
  q: string;
  ownership: BoardOwnership;
  hideStale: boolean;
  onViewChange: (value: BoardView) => void;
  onQChange: (value: string) => void;
  onOwnershipChange: (value: BoardOwnership) => void;
  onHideStaleChange: (value: boolean) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex border border-gray-200 bg-white">
        {VIEW_TABS.map((tab) => (
          <button
            key={tab.value}
            type="button"
            onClick={() => onViewChange(tab.value)}
            className={`px-3 py-2 text-sm transition-colors ${
              view === tab.value
                ? 'bg-brand-50 font-medium text-brand-700'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="relative min-w-[220px] flex-1 md:max-w-xs">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
        <input
          type="text"
          value={q}
          onChange={(event) => onQChange(event.target.value)}
          placeholder="在已加载的卡片里找标的/买家/意向"
          className="w-full border border-gray-200 bg-white py-2 pl-9 pr-3 text-sm outline-none transition-colors focus:border-brand-600"
        />
      </div>

      <label className="flex items-center gap-1.5 text-sm text-gray-500">
        <span className="shrink-0">责任范围</span>
        <select
          value={ownership}
          onChange={(event) => onOwnershipChange(event.target.value as BoardOwnership)}
          className={SELECT_CLASS}
          title={OWNERSHIP_OPTIONS.find((option) => option.value === ownership)?.hint}
        >
          {OWNERSHIP_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>

      <div className="flex items-center gap-1.5 text-sm text-gray-500">
        <label className="flex cursor-pointer items-center gap-1.5">
          <input
            type="checkbox"
            checked={hideStale}
            onChange={(event) => onHideStaleChange(event.target.checked)}
            className="h-3.5 w-3.5 accent-brand-600"
          />
          <span>隐藏最近无动态</span>
        </label>
        <span
          className="group relative inline-flex"
          aria-label="勾选隐藏超过14天无动态的项目"
          tabIndex={0}
        >
          <Info className="h-3.5 w-3.5 text-gray-400" />
          <span
            role="tooltip"
            className="pointer-events-none invisible absolute right-0 top-[calc(100%+6px)] z-30 w-max max-w-64 bg-gray-900 px-2.5 py-1.5 text-xs leading-5 text-white opacity-0 shadow-lg transition-opacity group-hover:visible group-hover:opacity-100 group-focus:visible group-focus:opacity-100"
          >
            勾选隐藏超过14天无动态的项目
          </span>
        </span>
      </div>
    </div>
  );
}
