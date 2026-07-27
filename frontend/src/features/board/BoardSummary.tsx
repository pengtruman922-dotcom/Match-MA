import { AlertTriangle } from 'lucide-react';
import type { BoardModel, BoardView } from './boardBuckets';

/** 顶部概况条：屏幕上自己能数出来的几个数，先摆明（D9 的全局版）。 */
export default function BoardSummary({
  model,
  view,
  truncated,
  loaded,
  fetchLimit,
}: {
  model: BoardModel;
  view: BoardView;
  truncated: boolean;
  loaded: number;
  fetchLimit: number;
}) {
  const subjectUnit = view === 'target' ? '个标的' : '个意向';
  const deep = model.columns.find((column) => column.key === 'deep');
  const won = model.columns.find((column) => column.key === 'won');

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border border-gray-200 bg-white px-3 py-2 text-xs text-gray-600">
        <span className="font-medium text-gray-900">{model.totalRelations} 条关系</span>
        <span className="text-gray-300">·</span>
        <span>
          {model.totalSubjects} {subjectUnit}
        </span>
        <span className="text-gray-300">·</span>
        <span>深度交流 {deep?.relationCount ?? 0}</span>
        <span className="text-gray-300">·</span>
        <span>已成交 {won?.relationCount ?? 0}</span>
        <span className="text-gray-300">·</span>
        <span className={model.staleRelations > 0 ? 'text-amber-600' : ''}>
          14天无动态 {model.staleRelations}
        </span>
        {model.hiddenRelations > 0 ? (
          <span className="text-amber-600">（筛选中，隐藏 {model.hiddenRelations} 条）</span>
        ) : null}
      </div>

      {truncated ? (
        <p className="flex items-start gap-1.5 border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            本次只取回 {loaded} 条，正好等于单次上限 {fetchLimit} 条——
            <strong className="font-semibold">后面可能还有数据</strong>
            ，上面的计数不能当作全量。请用责任范围收窄，并反馈给开发调整取数策略。
          </span>
        </p>
      ) : null}
    </div>
  );
}
