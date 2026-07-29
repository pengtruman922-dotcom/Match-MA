import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import { setOrDelete } from '../lib/utils';
import { relationStatusLabel } from '../features/relations/relationLabels';
import BoardColumn, { GroupList } from '../features/board/BoardColumn';
import BoardFilters from '../features/board/BoardFilters';
import BoardSummary from '../features/board/BoardSummary';
import { useBoardData, BOARD_FETCH_LIMIT } from '../features/board/useBoardData';
import type {
  BoardModel,
  BoardOwnership,
  BoardView,
} from '../features/board/boardBuckets';

/**
 * 全局撮合看板：概览 + 跳转，只读，不做状态编辑也不记动态（D8）。
 *
 * 取数走 /relations/board 瘦端点，一次拉完整块数据；分桶、同主体折叠、
 * 搜索和无动态筛选全在前端做（见 features/board/boardBuckets.ts）。
 * 视角 / 责任范围 / 搜索 / 无动态筛选都进 URL，刷新和分享保持同一个视图。
 */
export default function Board() {
  const [searchParams, setSearchParams] = useSearchParams();
  const view = readView(searchParams);
  const ownership = readOwnership(searchParams);
  const owner = searchParams.get('owner') || '';
  const hideStale = searchParams.get('stale') === 'hide';

  // 兼容旧分享链接：排序控件已移除，固定按最近关系动态降序。
  useEffect(() => {
    if (!searchParams.has('sort')) return;
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.delete('sort');
      return next;
    }, { replace: true });
  }, [searchParams, setSearchParams]);

  // 搜索是内存筛选，按键即出结果；URL 同步延后 300ms，免得每敲一个字写一次地址栏。
  // 相等就直接返回——否则「写 URL → searchParams 变 → 再写」会绕成死循环。
  const urlQ = searchParams.get('q') || '';
  const [qDraft, setQDraft] = useState(urlQ);
  useEffect(() => {
    if (qDraft === urlQ) return;
    const timer = window.setTimeout(() => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current);
          setOrDelete(next, 'q', qDraft || undefined);
          return next;
        },
        { replace: true },
      );
    }, 300);
    return () => window.clearTimeout(timer);
  }, [qDraft, urlQ, setSearchParams]);

  const { model, loading, error, loaded, truncated } = useBoardData({
    ownership,
    owner,
    view,
    q: qDraft,
    hideStale,
  });

  function patchParams(patch: Record<string, string | undefined>) {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(patch)) setOrDelete(next, key, value);
    setSearchParams(next, { replace: true });
  }

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">撮合看板</h1>
          <p className="mt-0.5 text-xs text-gray-500">
            每张卡是一对「买家意向 × 标的」的推进。点卡片进对应详情页的「推进」tab 编辑。
          </p>
        </div>
      </div>

      <BoardFilters
        view={view}
        q={qDraft}
        ownership={ownership}
        owner={owner}
        hideStale={hideStale}
        onViewChange={(value) => patchParams({ view: value === 'target' ? undefined : value })}
        onQChange={setQDraft}
        onOwnershipChange={(value) =>
          patchParams({ ownership: value === 'involved' ? undefined : value })
        }
        onOwnerChange={(value) => patchParams({ owner: value || undefined })}
        onHideStaleChange={(value) => patchParams({ stale: value ? 'hide' : undefined })}
      />

      {error ? (
        <div className="border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
      ) : null}

      {loading ? (
        <div className="flex items-center justify-center py-20 text-sm text-gray-400">
          <Loader2 className="mr-2 h-5 w-5 animate-spin text-brand-600" />
          正在加载撮合看板
        </div>
      ) : loaded === 0 && !error ? (
        <div className="border border-gray-200 bg-white py-16 text-center">
          <p className="text-sm text-gray-500">
            {owner
              ? '该负责人名下没有撮合关系'
              : ownership === 'involved'
                ? '当前责任范围下还没有撮合关系'
                : ownership === 'sole'
                  ? '没有标的与买家都归你的撮合关系'
                  : '还没有撮合关系'}
          </p>
          <p className="mt-1 text-xs text-gray-400">
            {owner
              ? '责任范围与负责人是「且」的关系——先把责任范围切到「全部」，再看这个人名下有没有。'
              : '在智能推荐里点「开始推进」，或在标的/买家详情页关联对手方；也可以把责任范围切到「全部」再看。'}
          </p>
        </div>
      ) : (
        <>
          <BoardSummary
            model={model}
            view={view}
            truncated={truncated}
            loaded={loaded}
            fetchLimit={BOARD_FETCH_LIMIT}
          />

          {/* 深度交流和已成交天生比初步接触少得多，列宽跟着让开。 */}
          <div className="grid grid-cols-1 items-start gap-3 lg:grid-cols-[2fr_1fr_1fr]">
            {model.columns.map((column) => (
              <BoardColumn key={column.key} column={column} view={view} />
            ))}
          </div>

          <ClosedDrawer model={model} view={view} />
        </>
      )}
    </div>
  );
}

/** 底部抽屉：已关闭的三个状态，默认收起；暂停单独分组排最前（D1）。 */
function ClosedDrawer({ model, view }: { model: BoardModel; view: BoardView }) {
  const [open, setOpen] = useState(false);
  if (model.closed.relationCount === 0 && model.closed.hiddenCount === 0) return null;

  return (
    <section className="border border-gray-200 bg-gray-50/40">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="flex w-full flex-wrap items-center gap-2 px-3 py-2 text-left hover:bg-gray-50"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-gray-400" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-gray-400" />
        )}
        <span className="text-xs font-semibold text-gray-700">
          已关闭 {model.closed.relationCount} 条
        </span>
        {model.closed.sections.map((section) => (
          <span
            key={section.status}
            className={`text-[11px] ${section.status === 'paused' ? 'text-amber-600' : 'text-gray-400'}`}
          >
            {relationStatusLabel(section.status)} {section.relationCount}
          </span>
        ))}
        {model.closed.hiddenCount > 0 ? (
          <span className="text-[11px] text-amber-600">筛选中，隐藏 {model.closed.hiddenCount} 条</span>
        ) : null}
      </button>

      {open ? (
        <div className="space-y-4 border-t border-gray-100 p-3">
          {model.closed.sections.map((section) => (
            <div key={section.status}>
              <p
                className={`mb-2 text-[11px] font-medium ${
                  section.status === 'paused' ? 'text-amber-600' : 'text-gray-400'
                }`}
              >
                {relationStatusLabel(section.status)} {section.relationCount} 条
              </p>
              <div className="grid grid-cols-1 items-start gap-2 sm:grid-cols-2 lg:grid-cols-4">
                <GroupList groups={section.groups} view={view} />
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function readView(params: URLSearchParams): BoardView {
  return params.get('view') === 'intent' ? 'intent' : 'target';
}

function readOwnership(params: URLSearchParams): BoardOwnership {
  const value = params.get('ownership');
  return value === 'all' || value === 'sole' ? value : 'involved';
}
