import { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import RelationCard from './RelationCard';
import RelationGroupCard from './RelationGroupCard';
import type { BoardColumnData, BoardGroup, BoardView } from './boardBuckets';

/**
 * 首屏每块最多渲染多少个「条目」（一个条目 = 一张独立卡或一摞）。
 * 三个主列各 40，加上默认收起的尾巴块与抽屉，首屏条目数 ≤120，
 * 满足施工单 B2-3 的 ≤150 张预算。「显示更多」是纯前端切片，不发请求。
 */
const INITIAL_ITEMS = 40;
const MORE_STEP = 40;

export default function BoardColumn({
  column,
  view,
}: {
  column: BoardColumnData;
  view: BoardView;
}) {
  const [tailOpen, setTailOpen] = useState(false);
  const subjectUnit = view === 'target' ? '个标的' : '个意向';

  return (
    <div className="flex min-w-0 flex-col border border-gray-200 bg-gray-50/40">
      <div className="sticky top-0 z-10 border-b border-gray-100 bg-gray-50/95 px-3 py-2 backdrop-blur">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-xs font-semibold text-gray-700" title={column.hint}>
            {column.label}
          </span>
          <span className="shrink-0 text-[11px] text-gray-500">
            {column.relationCount}条 · {column.subjectCount}
            {subjectUnit}
          </span>
        </div>
        {column.hiddenCount > 0 ? (
          <p className="mt-0.5 text-[11px] text-amber-600">筛选中，隐藏 {column.hiddenCount} 条</p>
        ) : null}
      </div>

      <div className="max-h-[calc(100vh-19rem)] min-h-[6rem] flex-1 space-y-2 overflow-y-auto p-2">
        {column.main.length === 0 && column.tail.length === 0 ? (
          <p className="px-1 py-3 text-center text-[11px] text-gray-300">—</p>
        ) : null}

        <GroupList groups={column.main} view={view} />

        {column.tail.length > 0 ? (
          <div className="pt-1">
            <button
              type="button"
              onClick={() => setTailOpen((current) => !current)}
              className="flex w-full items-center gap-1 border-t border-dashed border-gray-200 pt-2 text-left text-[11px] text-gray-500 hover:text-brand-700"
            >
              {tailOpen ? (
                <ChevronDown className="h-3 w-3 shrink-0" />
              ) : (
                <ChevronRight className="h-3 w-3 shrink-0" />
              )}
              <span className="truncate">
                已推荐 {countRelations(column.tail)} 条（推了还没回音）
              </span>
            </button>
            {tailOpen ? (
              <div className="mt-2 space-y-2">
                <GroupList groups={column.tail} view={view} />
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** 一个组：单条渲染独立卡，≥2 条折成一摞（D5）。 */
export function GroupList({ groups, view }: { groups: BoardGroup[]; view: BoardView }) {
  const [limit, setLimit] = useState(INITIAL_ITEMS);

  // 切换视角/排序/筛选后组会整体换掉，切片要跟着回到首屏，否则会停在上一次展开的位置。
  useEffect(() => {
    setLimit(INITIAL_ITEMS);
  }, [groups]);

  const shown = groups.slice(0, limit);
  const rest = groups.length - shown.length;

  return (
    <>
      {shown.map((group) =>
        group.relations.length === 1 ? (
          <RelationCard key={group.subjectId} card={group.relations[0]} view={view} />
        ) : (
          <RelationGroupCard key={group.subjectId} group={group} view={view} />
        ),
      )}
      {rest > 0 ? (
        <button
          type="button"
          onClick={() => setLimit((current) => current + MORE_STEP)}
          className="w-full border border-dashed border-gray-200 py-1.5 text-[11px] text-gray-500 hover:border-brand-300 hover:text-brand-700"
        >
          显示更多（还有 {rest} 组）
        </button>
      ) : null}
    </>
  );
}

function countRelations(groups: BoardGroup[]): number {
  return groups.reduce((total, group) => total + group.relations.length, 0);
}
