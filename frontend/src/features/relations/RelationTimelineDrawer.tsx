import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Loader2, X, ArrowRight, UserRound, Building2 } from 'lucide-react';
import { relations } from '../../lib/api';
import type { BuyerSellerRelation, RelationEvent } from '../../types/api';
import {
  MANUAL_EVENT_TYPES,
  relationEventLabel,
  relationStatusClass,
  relationStatusLabel,
} from './relationLabels';

interface Props {
  relation: BuyerSellerRelation;
  /** 从哪一侧打开：标的详情页把对手方显示为买家，买家详情页显示为标的。 */
  side: 'seller_target' | 'buyer_intent';
  statuses: string[];
  onClose: () => void;
  /** 关系有任何写入后回调，父层据此刷新列表。 */
  onChanged: (relation: BuyerSellerRelation) => void;
}

export default function RelationTimelineDrawer({ relation, side, statuses, onClose, onChanged }: Props) {
  const [events, setEvents] = useState<RelationEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingStatus, setSavingStatus] = useState(false);
  const [current, setCurrent] = useState(relation);

  const counterpartyName =
    side === 'seller_target'
      ? current.buyer_name || current.buyer_intent_name || '未绑定买家'
      : current.seller_target_name || '未命名标的';
  const counterpartyLink =
    side === 'seller_target'
      ? `/buyer-intents/${current.buyer_intent_id}`
      : `/targets/${current.seller_target_id}`;

  const loadEvents = () =>
    relations
      .events(current.id, { limit: 100 })
      .then(setEvents)
      .catch(() => {})
      .finally(() => setLoading(false));

  useEffect(() => {
    setLoading(true);
    void loadEvents();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current.id]);

  const changeStatus = async (status: string) => {
    if (status === current.status) return;
    setSavingStatus(true);
    try {
      const updated = await relations.updateStatus(current.id, { status });
      setCurrent(updated);
      onChanged(updated);
      await loadEvents();
    } catch (err) {
      alert(err instanceof Error ? err.message : '更新状态失败');
    } finally {
      setSavingStatus(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative z-10 flex h-full w-full max-w-lg flex-col border-l border-gray-200 bg-white shadow-xl">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-gray-100 px-5 py-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              {side === 'seller_target' ? (
                <UserRound className="h-4 w-4 text-gray-400" />
              ) : (
                <Building2 className="h-4 w-4 text-gray-400" />
              )}
              <Link to={counterpartyLink} className="truncate text-sm font-semibold text-gray-900 hover:text-brand-600">
                {counterpartyName}
              </Link>
              <span className={`shrink-0 px-2 py-0.5 text-xs font-medium ${relationStatusClass(current.status)}`}>
                {relationStatusLabel(current.status)}
              </span>
            </div>
            <p className="mt-1 text-xs text-gray-400">
              {side === 'seller_target' ? current.buyer_intent_name : current.seller_target_name}
              {current.first_recommended_at ? ` · 始于 ${formatDate(current.first_recommended_at)}` : ''}
            </p>
          </div>
          <button type="button" onClick={onClose} className="p-1 text-gray-400 hover:text-gray-700">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {/* Status pipeline */}
          <section className="mb-6">
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">推进状态</h4>
            <div className="flex flex-wrap gap-1.5">
              {statuses.map((status) => (
                <button
                  key={status}
                  type="button"
                  disabled={savingStatus}
                  onClick={() => void changeStatus(status)}
                  className={`px-2.5 py-1 text-xs font-medium transition-colors disabled:opacity-50 ${
                    status === current.status
                      ? relationStatusClass(status)
                      : 'bg-gray-50 text-gray-500 hover:bg-gray-100'
                  }`}
                >
                  {relationStatusLabel(status)}
                </button>
              ))}
            </div>
          </section>

          {/* Add event */}
          <RecordEventForm
            relationId={current.id}
            onRecorded={async (updated) => {
              if (updated) {
                setCurrent(updated);
                onChanged(updated);
              }
              await loadEvents();
            }}
          />

          {/* Timeline */}
          <section className="mt-6">
            <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-500">时间线</h4>
            {loading ? (
              <div className="flex items-center gap-2 py-6 text-sm text-gray-400">
                <Loader2 className="h-4 w-4 animate-spin" />
                正在加载
              </div>
            ) : events.length === 0 ? (
              <p className="py-6 text-sm text-gray-400">暂无动态，记录一条上方的沟通进展。</p>
            ) : (
              <ol className="space-y-3">
                {events.map((event) => (
                  <li key={event.id} className="border-l-2 border-gray-100 pl-3">
                    <div className="flex items-baseline gap-2">
                      <span className="text-xs font-medium text-gray-700">{relationEventLabel(event.event_type)}</span>
                      <span className="font-mono text-[11px] text-gray-400">{formatDateTime(event.event_time)}</span>
                    </div>
                    {event.title ? <p className="mt-0.5 text-sm text-gray-800">{event.title}</p> : null}
                    {event.content ? <p className="mt-0.5 whitespace-pre-wrap text-sm text-gray-600">{event.content}</p> : null}
                    {event.next_step ? (
                      <p className="mt-1 flex items-center gap-1 text-xs text-brand-700">
                        <ArrowRight className="h-3 w-3" />
                        下一步：{event.next_step}
                      </p>
                    ) : null}
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function RecordEventForm({
  relationId,
  onRecorded,
}: {
  relationId: string;
  onRecorded: (relation: BuyerSellerRelation | null) => void | Promise<void>;
}) {
  const [eventType, setEventType] = useState<string>('meeting');
  const [content, setContent] = useState('');
  const [nextStep, setNextStep] = useState('');
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!content.trim()) return;
    setSaving(true);
    try {
      await relations.createEvent(relationId, {
        event_type: eventType,
        content: content.trim(),
        next_step: nextStep.trim() || null,
      });
      setContent('');
      setNextStep('');
      await onRecorded(null);
    } catch (err) {
      alert(err instanceof Error ? err.message : '记录动态失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="border border-gray-100 bg-gray-50/60 p-3">
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">记录动态</h4>
      <div className="space-y-2">
        <select
          value={eventType}
          onChange={(event) => setEventType(event.target.value)}
          className="w-full border border-gray-200 bg-white px-2 py-1.5 text-sm text-gray-700 outline-none focus:border-brand-500"
        >
          {MANUAL_EVENT_TYPES.map((type) => (
            <option key={type} value={type}>
              {relationEventLabel(type)}
            </option>
          ))}
        </select>
        <textarea
          value={content}
          onChange={(event) => setContent(event.target.value)}
          placeholder="这次沟通发生了什么"
          className="min-h-16 w-full resize-y border border-gray-200 bg-white px-2 py-1.5 text-sm text-gray-800 outline-none focus:border-brand-500"
        />
        <input
          value={nextStep}
          onChange={(event) => setNextStep(event.target.value)}
          placeholder="下一步（选填）"
          className="w-full border border-gray-200 bg-white px-2 py-1.5 text-sm text-gray-800 outline-none focus:border-brand-500"
        />
        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => void submit()}
            disabled={saving || !content.trim()}
            className="inline-flex items-center gap-1.5 bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            记录
          </button>
        </div>
      </div>
    </section>
  );
}

function formatDate(value: string | null): string {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleDateString('zh-CN', { year: '2-digit', month: '2-digit', day: '2-digit' });
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}
