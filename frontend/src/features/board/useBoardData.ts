import { useEffect, useMemo, useState } from 'react';
import { relations } from '../../lib/api';
import type { RelationBoardCard } from '../../types/api';
import { buildBoard, type BoardModel, type BoardOwnership, type BoardView } from './boardBuckets';

/**
 * 一次拉完整块数据的条数上限。端点自身允许到 5000；这里留在 2000，
 * 是因为 2000 行瘦卡片约 760 KB（gzip 后约 190 KB），再往上浏览器端
 * 分组和渲染的收益就不如上分页/游标了。真触到上限会显式提示，见 truncated。
 */
export const BOARD_FETCH_LIMIT = 2000;

export interface BoardData {
  model: BoardModel;
  loading: boolean;
  error: string | null;
  /** 本次加载的关系总数（筛选前）。 */
  loaded: number;
  /**
   * 返回条数正好等于 limit —— 无从判断后面还有没有数据，必须显式提示。
   * 这正是 B-1 缺陷的本体：旧看板要 200 条、后端上限也是 200，拿到 200
   * 条时静默当成全部，列头计数因此可能是假的。
   */
  truncated: boolean;
}

export function useBoardData(options: {
  ownership: BoardOwnership;
  owner: string;
  view: BoardView;
  q: string;
  hideStale: boolean;
}): BoardData {
  const { ownership, owner, view, q, hideStale } = options;
  const [cards, setCards] = useState<RelationBoardCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 只有 ownership / owner 变化才重新取数——两者都是后端谓词，改了必须重拉。
  // 视角、搜索、隐藏无动态仍全在内存里做。
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    relations
      .board({ ownership, owner: owner || undefined, limit: BOARD_FETCH_LIMIT })
      .then((rows) => {
        if (!cancelled) setCards(rows);
      })
      .catch((err) => {
        if (!cancelled) {
          setCards([]);
          setError(err instanceof Error ? err.message : '加载失败');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [ownership, owner]);

  const model = useMemo(
    () => buildBoard(cards, { view, q, hideStale }),
    [cards, view, q, hideStale],
  );

  return {
    model,
    loading,
    error,
    loaded: cards.length,
    truncated: cards.length >= BOARD_FETCH_LIMIT,
  };
}
