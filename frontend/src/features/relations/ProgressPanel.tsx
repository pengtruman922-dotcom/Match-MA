import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, ChevronRight, Loader2, UserRound, Building2, Plus, Search, X } from 'lucide-react';
import { relations, sellerTargets, buyerIntents } from '../../lib/api';
import type { BuyerSellerRelation, RelationEventType } from '../../types/api';
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
  const [eventTypes, setEventTypes] = useState<RelationEventType[]>([]);
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<string | null>(null);
  const [linking, setLinking] = useState(false);

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
    relations.meta().then((meta) => {
      setStatuses(meta.statuses);
      setEventTypes(meta.event_types);
    }).catch(() => {});
  }, [load]);

  const linkCounterparty = async (counterpartyId: string) => {
    const payload =
      side === 'seller_target'
        ? { buyer_intent_id: counterpartyId, seller_target_id: entityId }
        : { buyer_intent_id: entityId, seller_target_id: counterpartyId };
    try {
      const result = await relations.create(payload);
      setLinking(false);
      await load();
      setOpenId(result.relation.id);
    } catch (err) {
      alert(err instanceof Error ? err.message : '关联失败');
    }
  };

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

  const header = (
    <div className="flex items-center justify-between">
      <p className="text-xs text-gray-400">
        {side === 'seller_target' ? '这个标的与各买家的推进' : '这个买家意向与各标的的推进'}
      </p>
      <button
        type="button"
        onClick={() => setLinking(true)}
        className="inline-flex items-center gap-1 border border-gray-200 px-2.5 py-1.5 text-xs text-gray-600 hover:border-brand-500 hover:text-brand-600"
      >
        <Plus className="h-3.5 w-3.5" />
        {side === 'seller_target' ? '关联买家意向' : '关联标的'}
      </button>
    </div>
  );

  if (items.length === 0) {
    return (
      <div className="space-y-4">
        {header}
        <div className="py-10 text-center">
          <ChevronRight className="mx-auto h-8 w-8 text-gray-300" />
          <p className="mt-2 text-sm text-gray-500">还没有撮合关系</p>
          <p className="mt-1 text-xs text-gray-400">
            点右上角关联对手方，或在智能推荐里点「开始推进」，关系会出现在这里。
          </p>
        </div>
        {linking && (
          <CounterpartyPicker side={side} onPick={linkCounterparty} onClose={() => setLinking(false)} />
        )}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {header}
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
          eventTypes={eventTypes}
          onClose={() => setOpenId(null)}
          onChanged={() => void load()}
        />
      )}

      {linking && (
        <CounterpartyPicker side={side} onPick={linkCounterparty} onClose={() => setLinking(false)} />
      )}
    </div>
  );
}

function CounterpartyPicker({
  side,
  onPick,
  onClose,
}: {
  side: 'seller_target' | 'buyer_intent';
  onPick: (id: string) => void | Promise<void>;
  onClose: () => void;
}) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Array<{ id: string; name: string; sub: string | null }>>([]);
  const [searching, setSearching] = useState(false);
  const [picking, setPicking] = useState(false);
  const debounce = useRef<number | undefined>(undefined);

  // 标的侧关联买家意向，买家意向侧关联标的。
  const pickTargets = side === 'seller_target';

  useEffect(() => {
    window.clearTimeout(debounce.current);
    if (query.trim().length < 2) {
      setResults([]);
      return;
    }
    debounce.current = window.setTimeout(() => {
      setSearching(true);
      const request = pickTargets
        ? buyerIntents
            .suggestions({ q: query.trim(), limit: 8 })
            .then((rows) => rows.map((row) => ({ id: row.id, name: row.intent_name, sub: row.buyer_name })))
        : sellerTargets
            .suggestions({ q: query.trim(), limit: 8 })
            .then((rows) => rows.map((row) => ({ id: row.id, name: row.target_name, sub: row.target_subject_name })));
      request
        .then(dedupeById)
        .then(setResults)
        .catch(() => setResults([]))
        .finally(() => setSearching(false));
    }, 250);
    return () => window.clearTimeout(debounce.current);
  }, [query, pickTargets]);

  const choose = async (id: string) => {
    setPicking(true);
    await onPick(id);
    setPicking(false);
  };

  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center pt-24" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div className="relative z-10 w-full max-w-md border border-gray-200 bg-white shadow-xl" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
          <h4 className="text-sm font-semibold text-gray-900">{pickTargets ? '关联买家意向' : '关联标的'}</h4>
          <button type="button" onClick={onClose} className="p-1 text-gray-400 hover:text-gray-700">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-4">
          <div className="flex items-center gap-2 border border-gray-200 px-2.5 py-1.5">
            <Search className="h-4 w-4 shrink-0 text-gray-400" />
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={pickTargets ? '搜索买家意向名称' : '搜索标的名称'}
              className="w-full text-sm text-gray-800 outline-none"
            />
            {searching ? <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-400" /> : null}
          </div>
          <div className="mt-2 max-h-64 overflow-y-auto">
            {query.trim().length < 2 ? (
              <p className="py-6 text-center text-xs text-gray-400">输入至少 2 个字符搜索</p>
            ) : results.length === 0 && !searching ? (
              <p className="py-6 text-center text-xs text-gray-400">没有匹配结果</p>
            ) : (
              results.map((row) => (
                <button
                  key={row.id}
                  type="button"
                  disabled={picking}
                  onClick={() => void choose(row.id)}
                  className="flex w-full items-center gap-2 px-2 py-2 text-left hover:bg-gray-50 disabled:opacity-50"
                >
                  {pickTargets ? (
                    <UserRound className="h-3.5 w-3.5 shrink-0 text-gray-400" />
                  ) : (
                    <Building2 className="h-3.5 w-3.5 shrink-0 text-gray-400" />
                  )}
                  <span className="min-w-0">
                    <span className="block truncate text-sm text-gray-800">{row.name}</span>
                    {row.sub ? <span className="block truncate text-xs text-gray-400">{row.sub}</span> : null}
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function dedupeById<T extends { id: string }>(rows: T[]): T[] {
  const seen = new Set<string>();
  return rows.filter((row) => (seen.has(row.id) ? false : (seen.add(row.id), true)));
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
          <div className="mt-1 space-y-0.5 text-[11px] text-gray-500">
            <p><span className="mr-1 text-gray-400">买家</span>{relation.buyer_name || '-'}</p>
            <p><span className="mr-1 text-gray-400">意向</span>{relation.buyer_intent_name || '-'}</p>
            <p><span className="mr-1 text-gray-400">标的</span>{relation.seller_target_name || '-'}</p>
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
