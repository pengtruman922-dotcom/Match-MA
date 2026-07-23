import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, ChevronRight, Loader2, UserRound, Building2 } from 'lucide-react';
import { relations } from '../../lib/api';
import type { BuyerSellerRelation } from '../../types/api';
import RelationTimelineDrawer from './RelationTimelineDrawer';
import {
  daysSince,
  isRelationEnded,
  isStaleRelation,
  relationStatusClass,
  relationStatusLabel,
} from './relationLabels';

interface Props {
  /** 从标的详情打开则传 seller_target_id，从买家意向详情打开则传 buyer_intent_id。 */
  side: 'seller_target' | 'buyer_intent';
  entityId: string;
}

/**
 * 「推进」tab：一个实体参与的全部撮合关系，按推进中/已结束分组。
 * 标的侧与买家意向侧共用本组件，对手方一侧镜像显示。
 */
export default function ProgressPanel({ side, entityId }: Props) {
  const [items, setItems] = useState<BuyerSellerRelation[]>([]);
  const [statuses, setStatuses] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<string | null>(null);

  const load = useCallback(() => {
    const params = side === 'seller_target' ? { seller_target_id: entityId } : { buyer_intent_id: entityId };
    return relations
      .list({ ...params, limit: 100 })
      .then(setItems)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [side, entityId]);

  useEffect(() => {
    setLoading(true);
    void load();
    relations.meta().then((meta) => setStatuses(meta.statuses)).catch(() => {});
  }, [load]);

  const active = items.filter((relation) => !isRelationEnded(relation.status));
  const ended = items.filter((relation) => isRelationEnded(relation.status));
  const openRelation = items.find((relation) => relation.id === openId) || null;

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-10 text-sm text-gray-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        正在加载推进情况
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="py-12 text-center">
        <ChevronRight className="mx-auto h-8 w-8 text-gray-300" />
        <p className="mt-2 text-sm text-gray-500">还没有撮合关系</p>
        <p className="mt-1 text-xs text-gray-400">
          在智能推荐里点「开始推进」，或录入含对手方的跟进动态，关系会出现在这里。
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {active.length > 0 && (
        <section>
          <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-500">
            推进中 ({active.length})
          </h4>
          <div className="space-y-2">
            {active.map((relation) => (
              <RelationCard key={relation.id} relation={relation} side={side} onOpen={() => setOpenId(relation.id)} />
            ))}
          </div>
        </section>
      )}

      {ended.length > 0 && (
        <section>
          <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-400">
            已结束 ({ended.length})
          </h4>
          <div className="space-y-2">
            {ended.map((relation) => (
              <RelationCard key={relation.id} relation={relation} side={side} onOpen={() => setOpenId(relation.id)} muted />
            ))}
          </div>
        </section>
      )}

      {openRelation && (
        <RelationTimelineDrawer
          relation={openRelation}
          side={side}
          statuses={statuses}
          onClose={() => setOpenId(null)}
          onChanged={() => void load()}
        />
      )}
    </div>
  );
}

function RelationCard({
  relation,
  side,
  onOpen,
  muted = false,
}: {
  relation: BuyerSellerRelation;
  side: 'seller_target' | 'buyer_intent';
  onOpen: () => void;
  muted?: boolean;
}) {
  const counterpartyName =
    side === 'seller_target'
      ? relation.buyer_name || relation.buyer_intent_name || '未绑定买家'
      : relation.seller_target_name || '未命名标的';
  const counterpartyLink =
    side === 'seller_target' ? `/buyer-intents/${relation.buyer_intent_id}` : `/targets/${relation.seller_target_id}`;
  const stale = isStaleRelation(relation.status, relation.last_event_at);
  const staleDays = daysSince(relation.last_event_at);

  return (
    <div className={`border px-3 py-2.5 ${muted ? 'border-gray-100 bg-gray-50/40' : 'border-gray-200'}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            {side === 'seller_target' ? (
              <UserRound className="h-3.5 w-3.5 shrink-0 text-gray-400" />
            ) : (
              <Building2 className="h-3.5 w-3.5 shrink-0 text-gray-400" />
            )}
            <Link
              to={counterpartyLink}
              className="truncate text-sm font-medium text-gray-900 hover:text-brand-600"
              onClick={(event) => event.stopPropagation()}
            >
              {counterpartyName}
            </Link>
          </div>
          {relation.last_event_summary ? (
            <p className="mt-1 line-clamp-2 text-xs text-gray-500">{relation.last_event_summary}</p>
          ) : null}
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-gray-400">
            {relation.last_event_at ? <span>最新 {formatDate(relation.last_event_at)}</span> : <span>暂无动态</span>}
            {stale ? (
              <span className="inline-flex items-center gap-0.5 text-amber-600">
                <AlertTriangle className="h-3 w-3" />
                {staleDays}天无动态
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className={`px-2 py-0.5 text-xs font-medium ${relationStatusClass(relation.status)}`}>
            {relationStatusLabel(relation.status)}
          </span>
          <button
            type="button"
            onClick={onOpen}
            className="inline-flex items-center gap-0.5 border border-gray-200 px-2 py-1 text-xs text-gray-600 hover:border-brand-500 hover:text-brand-600"
          >
            时间线
            <ChevronRight className="h-3 w-3" />
          </button>
        </div>
      </div>
    </div>
  );
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
}
