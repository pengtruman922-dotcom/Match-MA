import { useState } from 'react';
import { AlertTriangle, ChevronDown, ChevronRight } from 'lucide-react';
import { relationStatusLabel } from '../relations/relationLabels';
import RelationCard from './RelationCard';
import { cardActivityDays, type BoardGroup, type BoardView } from './boardBuckets';

/**
 * 折叠摞：同一列内同主体 ≥2 张时把它们收成一摞，默认收起（D5）。
 *
 * 折叠**只是呈现**。展开后每张内层卡仍是独立关系、独立跳转目标——
 * 摞头本身不可点击，避免用户以为点摞头能进「这一摞」的详情页。
 */
export default function RelationGroupCard({ group, view }: { group: BoardGroup; view: BoardView }) {
  const [open, setOpen] = useState(false);
  const latest = group.latestRelation;
  const latestDays = cardActivityDays(latest);

  return (
    <div className="border border-gray-200 bg-white">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="flex w-full items-center gap-1 px-2 py-1.5 text-left hover:bg-gray-50"
        title={open ? '收起' : '展开这一摞'}
      >
        {open ? (
          <ChevronDown className="h-3 w-3 shrink-0 text-gray-400" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0 text-gray-400" />
        )}
        <span className="flex-1 truncate text-xs font-medium text-gray-900">{group.subjectName}</span>
        <span className="shrink-0 text-[11px] text-gray-400">×{group.relations.length}</span>
      </button>

      {open ? (
        <div className="space-y-1 px-2 pb-1.5">
          {group.relations.map((card) => (
            <RelationCard key={card.id} card={card} view={view} nested />
          ))}
        </div>
      ) : (
        <div className="px-2 pb-1.5 pl-6">
          <p className="truncate text-[11px] text-gray-500">
            {group.statusCounts.map((entry) => `${relationStatusLabel(entry.status)}${entry.count}`).join(' · ')}
          </p>
          <div className="mt-0.5 flex items-center justify-between gap-1">
            <span className="truncate text-[11px] text-gray-400">
              最近 {latest.buyer_name || '-'}
            </span>
            {group.staleDays !== null ? (
              <span className="inline-flex shrink-0 items-center gap-0.5 text-[11px] text-amber-600">
                <AlertTriangle className="h-2.5 w-2.5" />
                {group.staleDays}天无动态
              </span>
            ) : (
              <span className="shrink-0 text-[11px] text-gray-400">
                {latestDays === null ? '' : latestDays === 0 ? '今天' : `${latestDays}天前`}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
