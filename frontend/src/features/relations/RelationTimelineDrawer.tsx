import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Loader2, X, ArrowRight, UserRound, Building2, Pencil, Trash2, Check } from 'lucide-react';
import { relations } from '../../lib/api';
import type { BuyerSellerRelation, RelationEvent, RelationEventType } from '../../types/api';
import { relationStatusClass, relationStatusLabel } from './relationLabels';

interface Props {
  relation: BuyerSellerRelation;
  side: 'seller_target' | 'buyer_intent';
  statuses: string[];
  eventTypes: RelationEventType[];
  onClose: () => void;
  onChanged: (relation: BuyerSellerRelation) => void;
}

const STATUS_SYSTEM_EVENT_TYPES = new Set([
  'recommended', 'buyer_interested', 'buyer_not_interested',
  'due_diligence_started', 'agreement_discussion', 'deal_closed', 'paused',
]);

export default function RelationTimelineDrawer({ relation, side, statuses, eventTypes, onClose, onChanged }: Props) {
  const [events, setEvents] = useState<RelationEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingStatus, setSavingStatus] = useState(false);
  const [current, setCurrent] = useState(relation);
  const labels = useMemo(() => Object.fromEntries(eventTypes.map((item) => [item.value, item.label])), [eventTypes]);

  const counterpartyName = side === 'seller_target'
    ? current.buyer_name || current.buyer_intent_name || '未绑定买家'
    : current.seller_target_name || '未命名标的';
  const counterpartyLink = side === 'seller_target'
    ? `/buyer-intents/${current.buyer_intent_id}` : `/targets/${current.seller_target_id}`;

  const loadEvents = () => relations.events(current.id, { limit: 100 })
    .then(setEvents).catch(() => {}).finally(() => setLoading(false));
  const refreshRelation = async () => {
    const updated = await relations.get(current.id);
    setCurrent(updated);
    onChanged(updated);
  };

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
    <div className="fixed inset-0 z-[60] flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative z-10 flex h-full w-full max-w-lg flex-col border-l border-gray-200 bg-white shadow-xl">
        <div className="flex items-start justify-between border-b border-gray-100 px-5 py-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              {side === 'seller_target' ? <UserRound className="h-4 w-4 text-gray-400" /> : <Building2 className="h-4 w-4 text-gray-400" />}
              <Link to={counterpartyLink} className="truncate text-sm font-semibold text-gray-900 hover:text-brand-600">{counterpartyName}</Link>
              <span className={`shrink-0 px-2 py-0.5 text-xs font-medium ${relationStatusClass(current.status)}`}>{relationStatusLabel(current.status)}</span>
            </div>
            <p className="mt-1 text-xs text-gray-400">
              {side === 'seller_target' ? `买家意向：${current.buyer_intent_name || '-'}` : `标的：${current.seller_target_name || '-'}`}
              {current.first_recommended_at ? ` · 始于 ${formatDate(current.first_recommended_at)}` : ''}
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="关闭时间线" className="p-1 text-gray-400 hover:text-gray-700"><X className="h-4 w-4" /></button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          <section className="mb-6">
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">推进状态</h4>
            <div className="flex flex-wrap gap-1.5">
              {statuses.map((status) => (
                <button key={status} type="button" disabled={savingStatus} onClick={() => void changeStatus(status)}
                  className={`px-2.5 py-1 text-xs font-medium disabled:opacity-50 ${status === current.status ? relationStatusClass(status) : 'bg-gray-50 text-gray-500 hover:bg-gray-100'}`}>
                  {relationStatusLabel(status)}
                </button>
              ))}
            </div>
          </section>

          <RecordEventForm relationId={current.id} eventTypes={eventTypes} labels={labels} onRecorded={async () => { await refreshRelation(); await loadEvents(); }} />

          <section className="mt-6">
            <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-500">时间线</h4>
            {loading ? <div className="flex items-center gap-2 py-6 text-sm text-gray-400"><Loader2 className="h-4 w-4 animate-spin" />正在加载</div>
              : events.length === 0 ? <p className="py-6 text-sm text-gray-400">暂无动态，记录一条上方的沟通进展。</p>
                : <ol className="space-y-3">{events.map((event) => (
                  <TimelineEvent key={event.id} event={event} relationId={current.id} eventTypes={eventTypes} labels={labels}
                    onChanged={async () => { await refreshRelation(); await loadEvents(); }} />
                ))}</ol>}
          </section>
        </div>
      </div>
    </div>
  );
}

function TimelineEvent({ event, relationId, eventTypes, labels, onChanged }: {
  event: RelationEvent; relationId: string; eventTypes: RelationEventType[]; labels: Record<string, string>; onChanged: () => Promise<void>;
}) {
  const editable = event.source_type === 'manual';
  const [editing, setEditing] = useState(false);
  const [eventType, setEventType] = useState(event.event_type);
  const [content, setContent] = useState(event.content || '');
  const [nextStep, setNextStep] = useState(event.next_step || '');
  const [saving, setSaving] = useState(false);
  const label = labels[event.event_type] || event.event_type;

  const save = async () => {
    setSaving(true);
    try {
      await relations.updateEvent(relationId, event.id, { event_type: eventType, content: content || null, next_step: nextStep || null });
      setEditing(false);
      await onChanged();
    } catch (err) { alert(err instanceof Error ? err.message : '修改动态失败'); } finally { setSaving(false); }
  };
  const remove = async () => {
    if (!window.confirm('删除这条手工动态？删除后不会出现在时间线中。')) return;
    setSaving(true);
    try { await relations.deleteEvent(relationId, event.id); await onChanged(); }
    catch (err) { alert(err instanceof Error ? err.message : '删除动态失败'); } finally { setSaving(false); }
  };

  return (
    <li className="border-l-2 border-gray-100 pl-3">
      <div className="flex items-baseline gap-2">
        <span className="text-xs font-medium text-gray-700">{label}</span>
        <span className="font-mono text-[11px] text-gray-400">{formatDateTime(event.event_time)}</span>
        {editable && !editing && <span className="ml-auto flex gap-1"><button type="button" onClick={() => setEditing(true)} className="text-gray-400 hover:text-brand-600" title="编辑"><Pencil className="h-3.5 w-3.5" /></button><button type="button" disabled={saving} onClick={() => void remove()} className="text-gray-400 hover:text-red-600" title="删除"><Trash2 className="h-3.5 w-3.5" /></button></span>}
      </div>
      {editing ? (
        <div className="mt-2 space-y-2 border border-gray-100 bg-gray-50 p-2">
          <select value={eventType} onChange={(item) => setEventType(item.target.value)} className="w-full border border-gray-200 bg-white px-2 py-1 text-xs">
            {eventTypes.filter((item) => !STATUS_SYSTEM_EVENT_TYPES.has(item.value)).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
          <textarea value={content} onChange={(item) => setContent(item.target.value)} className="min-h-16 w-full border border-gray-200 p-2 text-sm" />
          <input value={nextStep} onChange={(item) => setNextStep(item.target.value)} placeholder="下一步（选填）" className="w-full border border-gray-200 px-2 py-1 text-xs" />
          <div className="flex justify-end gap-2"><button type="button" onClick={() => setEditing(false)} className="text-xs text-gray-500">取消</button><button type="button" disabled={saving} onClick={() => void save()} className="inline-flex items-center gap-1 bg-brand-600 px-2 py-1 text-xs text-white"><Check className="h-3 w-3" />保存</button></div>
        </div>
      ) : <>
        {event.title ? <p className="mt-0.5 text-sm text-gray-800">{event.title}</p> : null}
        {event.content ? <p className="mt-0.5 whitespace-pre-wrap text-sm text-gray-600">{event.content}</p> : null}
        {event.next_step ? <p className="mt-1 flex items-center gap-1 text-xs text-brand-700"><ArrowRight className="h-3 w-3" />下一步：{event.next_step}</p> : null}
      </>}
    </li>
  );
}

function RecordEventForm({ relationId, eventTypes, labels, onRecorded }: { relationId: string; eventTypes: RelationEventType[]; labels: Record<string, string>; onRecorded: () => Promise<void> }) {
  const manualTypes = eventTypes.filter((item) => !STATUS_SYSTEM_EVENT_TYPES.has(item.value));
  const [eventType, setEventType] = useState('meeting');
  const [content, setContent] = useState('');
  const [nextStep, setNextStep] = useState('');
  const [saving, setSaving] = useState(false);
  const submit = async () => {
    setSaving(true);
    try {
      await relations.createEvent(relationId, { event_type: eventType, content: content.trim() || null, next_step: nextStep.trim() || null });
      setContent(''); setNextStep(''); await onRecorded();
    } catch (err) { alert(err instanceof Error ? err.message : '记录动态失败'); } finally { setSaving(false); }
  };
  return <section className="border border-gray-100 bg-gray-50/60 p-3">
    <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">记录动态</h4>
    <div className="space-y-2"><select value={eventType} onChange={(event) => setEventType(event.target.value)} className="w-full border border-gray-200 bg-white px-2 py-1.5 text-sm text-gray-700 outline-none focus:border-brand-500">
      {manualTypes.map((type) => <option key={type.value} value={type.value}>{labels[type.value] || type.label}</option>)}
    </select><textarea value={content} onChange={(event) => setContent(event.target.value)} placeholder="沟通内容（选填；不填将自动生成记录）" className="min-h-16 w-full resize-y border border-gray-200 bg-white px-2 py-1.5 text-sm text-gray-800 outline-none focus:border-brand-500" />
    <input value={nextStep} onChange={(event) => setNextStep(event.target.value)} placeholder="下一步（选填）" className="w-full border border-gray-200 bg-white px-2 py-1.5 text-sm text-gray-800 outline-none focus:border-brand-500" />
    <div className="flex justify-end"><button type="button" onClick={() => void submit()} disabled={saving || !eventType} className="inline-flex items-center gap-1.5 bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50">{saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}记录</button></div></div>
  </section>;
}

function formatDate(value: string | null): string { if (!value) return '-'; const date = new Date(value); return Number.isNaN(date.getTime()) ? '-' : date.toLocaleDateString('zh-CN', { year: '2-digit', month: '2-digit', day: '2-digit' }); }
function formatDateTime(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }); }
