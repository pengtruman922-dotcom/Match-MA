import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Loader2, AlertTriangle } from 'lucide-react';
import { relations } from '../lib/api';
import type { BuyerSellerRelation } from '../types/api';
import {
  daysSince,
  isRelationEnded,
  isStaleRelation,
  relationStatusLabel,
} from '../features/relations/relationLabels';

// 看板列 = 活跃流水线的状态；终态收进底部归档区。
const PIPELINE: string[] = ['recommended', 'interested', 'in_discussion', 'due_diligence', 'agreement'];

/**
 * 全局撮合看板：每张卡是一对「买家意向 × 标的」的关系。
 * 后端 /relations 已按负责人可见性过滤——管理员看全局，顾问只看自己负责的。
 */
export default function Board() {
  const [items, setItems] = useState<BuyerSellerRelation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    relations
      .list({ limit: 200 })
      .then(setItems)
      .catch((err) => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false));
  }, []);

  const byStatus = useMemo(() => {
    const map: Record<string, BuyerSellerRelation[]> = {};
    for (const relation of items) {
      (map[relation.status] ||= []).push(relation);
    }
    return map;
  }, [items]);

  const ended = items.filter((relation) => isRelationEnded(relation.status));

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-sm text-gray-400">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-brand-600" />
        正在加载撮合看板
      </div>
    );
  }

  if (error) {
    return <div className="border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>;
  }

  return (
    <div className="space-y-5">
      <div className="flex items-baseline justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">撮合看板</h1>
          <p className="mt-0.5 text-xs text-gray-500">每张卡是一对「买家 × 标的」的推进；管理员看全局，顾问看自己负责的。</p>
        </div>
        <span className="text-xs text-gray-400">共 {items.length} 条关系</span>
      </div>

      {items.length === 0 ? (
        <div className="border border-gray-200 bg-white py-16 text-center">
          <p className="text-sm text-gray-500">还没有撮合关系</p>
          <p className="mt-1 text-xs text-gray-400">在智能推荐里点「开始推进」，或在标的/买家详情页关联对手方。</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
          {PIPELINE.map((status) => (
            <Column key={status} status={status} relations={byStatus[status] || []} />
          ))}
        </div>
      )}

      {ended.length > 0 && (
        <section className="border-t border-gray-100 pt-4">
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-400">
            终态 ({ended.length})
          </h2>
          <div className="flex flex-wrap gap-2">
            {ended.map((relation) => (
              <Link
                key={relation.id}
                to={targetProgressPath(relation)}
                className="border border-gray-100 bg-gray-50/60 px-2.5 py-1.5 text-xs text-gray-500 hover:border-gray-300"
              >
                {relation.seller_target_name} × {relation.buyer_name || relation.buyer_intent_name}
                <span className="ml-1 text-gray-400">· {relationStatusLabel(relation.status)}</span>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function Column({ status, relations: cards }: { status: string; relations: BuyerSellerRelation[] }) {
  return (
    <div className="flex flex-col border border-gray-200 bg-gray-50/40">
      <div className="flex items-center justify-between border-b border-gray-100 px-3 py-2">
        <span className="text-xs font-semibold text-gray-700">{relationStatusLabel(status)}</span>
        <span className="text-xs text-gray-400">{cards.length}</span>
      </div>
      <div className="flex-1 space-y-2 p-2">
        {cards.length === 0 ? (
          <p className="px-1 py-3 text-center text-[11px] text-gray-300">—</p>
        ) : (
          cards.map((relation) => <Card key={relation.id} relation={relation} />)
        )}
      </div>
    </div>
  );
}

function Card({ relation }: { relation: BuyerSellerRelation }) {
  const stale = isStaleRelation(relation.status, relation.last_event_at);
  const staleDays = daysSince(relation.last_event_at);
  return (
    <Link
      to={targetProgressPath(relation)}
      className="block border border-gray-200 bg-white px-2.5 py-2 hover:border-brand-400"
    >
      <p className="truncate text-xs text-gray-500"><span className="mr-1 text-gray-400">标的</span><span className="font-medium text-gray-900">{relation.seller_target_name || '-'}</span></p>
      <p className="mt-0.5 truncate text-[11px] text-gray-500"><span className="mr-1 text-gray-400">买家</span>{relation.buyer_name || '-'}</p>
      <p className="mt-0.5 truncate text-[11px] text-gray-500"><span className="mr-1 text-gray-400">意向</span>{relation.buyer_intent_name || '-'}</p>
      {relation.last_event_summary ? (
        <p className="mt-1 line-clamp-2 text-[11px] text-gray-400">{relation.last_event_summary}</p>
      ) : null}
      {stale ? (
        <p className="mt-1 inline-flex items-center gap-0.5 text-[11px] text-amber-600">
          <AlertTriangle className="h-2.5 w-2.5" />
          {staleDays}天无动态
        </p>
      ) : null}
    </Link>
  );
}

// 看板卡点进标的详情的推进 tab——那里能看到这条关系的完整时间线。
function targetProgressPath(relation: BuyerSellerRelation): string {
  return `/targets/${relation.seller_target_id}?tab=progress`;
}
