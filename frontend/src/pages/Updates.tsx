import { useState, useEffect } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { Plus, X, CheckCircle2, XCircle, Clock, Play, ChevronDown, ChevronUp } from 'lucide-react';
import { businessUpdates, extractedActions, sellerTargets } from '../lib/api';
import type { BusinessUpdate, ExtractedAction, SellerTarget, BusinessUpdateCreate, ExtractedActionCreate } from '../types/api';
import BusinessUpdateReviewPanel from '../components/BusinessUpdateReviewPanel';

export default function Updates() {
  const { id: routeUpdateId } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const [updates, setUpdates] = useState<BusinessUpdate[]>([]);
  const [actions, setActions] = useState<ExtractedAction[]>([]);
  const [targets, setTargets] = useState<SellerTarget[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [selectedUpdateId, setSelectedUpdateId] = useState<string | null>(null);
  const [showCreateAction, setShowCreateAction] = useState(false);
  const highlightedActionId = searchParams.get('actionId');

  const fetchData = () => {
    setLoading(true);
    Promise.all([
      businessUpdates.list({ limit: 20 }),
      extractedActions.list({ limit: 50 }),
      sellerTargets.list({ limit: 50 }),
    ])
      .then(async ([u, a, t]) => {
        let nextUpdates = u;
        if (routeUpdateId && !u.some((update) => update.id === routeUpdateId)) {
          try {
            const selected = await businessUpdates.get(routeUpdateId);
            nextUpdates = [selected, ...u];
          } catch {
            // Keep the list usable even if a stale direct link no longer exists.
          }
        }
        setUpdates(nextUpdates);
        setActions(a);
        setTargets(t);
        if (routeUpdateId) setSelectedUpdateId(routeUpdateId);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchData(); }, [routeUpdateId]);

  const selectedUpdate = updates.find((u) => u.id === selectedUpdateId);
  const updateActions = selectedUpdateId
    ? actions.filter((a) => a.business_update_id === selectedUpdateId)
    : [];

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">业务更新与复核</h1>
          <p className="text-xs text-gray-500 mt-0.5">自动应用后的变更在此复核、编辑或回退</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 px-4 py-2 bg-brand-600 text-white text-sm font-medium hover:bg-brand-700"
        >
          <Plus className="w-4 h-4" />
          录入业务更新
        </button>
      </div>

      <div className="grid grid-cols-12 gap-5">
        {/* Left: Update List */}
        <div className="col-span-5">
          <div className="bg-white border border-gray-200 max-h-[calc(100vh-12rem)] overflow-y-auto">
            <div className="px-4 py-3 border-b border-gray-100 bg-gray-50">
              <h2 className="text-sm font-semibold text-gray-900">业务更新记录</h2>
            </div>
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
              </div>
            ) : updates.length === 0 ? (
              <p className="text-sm text-gray-400 py-6 text-center">暂无业务更新</p>
            ) : (
              <div className="divide-y divide-gray-100">
                {updates.map((update) => (
                  <button
                    key={update.id}
                    onClick={() => setSelectedUpdateId(update.id)}
                    className={`w-full text-left px-4 py-3 hover:bg-brand-50 transition-colors ${selectedUpdateId === update.id ? 'bg-brand-50 border-l-2 border-l-brand-600' : ''}`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <ProcessingBadge status={update.processing_status} />
                      <span className="text-xs text-gray-400 font-mono">
                        {new Date(update.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>
                    <p className="text-sm text-gray-800 line-clamp-2">{update.raw_text}</p>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right: Detail + Actions */}
        <div className="col-span-7">
          {selectedUpdate ? (
            <div className="space-y-4">
              {/* Update Detail */}
              <div className="bg-white border border-gray-200 p-5">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-gray-900">原始输入</h3>
                  <ProcessingBadge status={selectedUpdate.processing_status} />
                </div>
                <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">{selectedUpdate.raw_text}</p>
                <div className="mt-3 flex items-center gap-4 text-xs text-gray-400">
                  <span>类型：{selectedUpdate.input_type}</span>
                  <span>时间：{new Date(selectedUpdate.created_at).toLocaleString('zh-CN')}</span>
                  {selectedUpdate.bound_seller_target_ids_json.length > 0 && (
                    <span>关联标的：{selectedUpdate.bound_seller_target_ids_json.length} 个</span>
                  )}
                </div>
              </div>

              <BusinessUpdateReviewPanel businessUpdateId={selectedUpdate.id} onProcessed={fetchData} />

              {/* Extracted Actions */}
              <div className="bg-white border border-gray-200">
                <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-gray-900">拆分动作 ({updateActions.length})</h3>
                  <button
                    onClick={() => setShowCreateAction(true)}
                    className="text-xs text-brand-600 hover:text-brand-700 font-medium flex items-center gap-1"
                  >
                    <Plus className="w-3 h-3" />
                    人工创建动作
                  </button>
                </div>
                {updateActions.length === 0 ? (
                  <p className="text-sm text-gray-400 py-6 text-center">暂无拆分动作</p>
                ) : (
                  <div className="divide-y divide-gray-100">
                    {updateActions.map((action) => (
                      <ActionCard
                        key={action.id}
                        action={action}
                        highlighted={highlightedActionId === action.id}
                        onUpdated={fetchData}
                      />
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="bg-white border border-gray-200 flex items-center justify-center h-64">
              <p className="text-sm text-gray-400">选择左侧一条业务更新查看详情</p>
            </div>
          )}
        </div>
      </div>

      {showCreate && (
        <CreateUpdateModal targets={targets} onClose={() => setShowCreate(false)} onCreated={() => { setShowCreate(false); fetchData(); }} />
      )}

      {showCreateAction && selectedUpdateId && (
        <CreateActionModal
          businessUpdateId={selectedUpdateId}
          targets={targets}
          onClose={() => setShowCreateAction(false)}
          onCreated={() => { setShowCreateAction(false); fetchData(); }}
        />
      )}
    </div>
  );
}

function ActionCard({
  action,
  highlighted,
  onUpdated,
}: {
  action: ExtractedAction;
  highlighted: boolean;
  onUpdated: () => void;
}) {
  const [expanded, setExpanded] = useState(highlighted);
  const [applying, setApplying] = useState(false);

  useEffect(() => {
    if (highlighted) setExpanded(true);
  }, [highlighted]);

  const handleStatusChange = async (newStatus: string) => {
    await extractedActions.update(action.id, { review_status: newStatus });
    onUpdated();
  };

  const handleApply = async () => {
    setApplying(true);
    try {
      await extractedActions.apply(action.id);
      onUpdated();
    } catch (err) {
      alert(`应用失败: ${err}`);
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className={`px-5 py-3 ${highlighted ? 'bg-amber-50/50' : ''}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ActionTypeBadge type={action.action_type} />
          <ReviewBadge status={action.review_status} />
        </div>
        <button onClick={() => setExpanded(!expanded)} className="text-xs text-gray-400 hover:text-gray-600">
          {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </button>
      </div>
      <p className="text-sm text-gray-700 mt-1.5 line-clamp-2">{action.raw_evidence_text}</p>

      {expanded && (
        <div className="mt-3 space-y-2">
          <div className="text-xs text-gray-500 bg-gray-50 p-3 border border-gray-100">
            <span className="font-medium">proposed_changes: </span>
            <pre className="whitespace-pre-wrap mt-1 text-gray-700">{JSON.stringify(action.proposed_changes_json, null, 2)}</pre>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {action.review_status === 'pending_review' && (
              <>
                <button onClick={() => handleStatusChange('accepted')} className="text-xs px-2 py-1 bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100 flex items-center gap-1">
                  <CheckCircle2 className="w-3 h-3" /> 标记已复核
                </button>
                <button onClick={() => handleStatusChange('rejected')} className="text-xs px-2 py-1 bg-red-50 text-red-700 border border-red-200 hover:bg-red-100 flex items-center gap-1">
                  <XCircle className="w-3 h-3" /> 回退
                </button>
              </>
            )}
            {(action.review_status === 'accepted' || action.review_status === 'auto_accepted') &&
              !action.applied_at &&
              isSupportedApplyType(action.action_type) && (
              <button onClick={handleApply} disabled={applying} className="text-xs px-2 py-1 bg-brand-50 text-brand-700 border border-brand-200 hover:bg-brand-100 flex items-center gap-1 disabled:opacity-50">
                <Play className="w-3 h-3" /> {applying ? '应用中...' : applyButtonLabel(action.action_type)}
              </button>
            )}
            {action.applied_at && (
              <span className="text-xs text-emerald-600 flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" /> 已自动应用 {new Date(action.applied_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}


function isSupportedApplyType(type: string): boolean {
  return [
    'seller_fact_update',
    'buyer_intent_update',
    'buyer_seller_relation_update',
    'buyer_intent_target_exclusion',
  ].includes(type);
}

function applyButtonLabel(type: string): string {
  const labels: Record<string, string> = {
    seller_fact_update: '应用到标的',
    buyer_intent_update: '应用到买家意向',
    buyer_seller_relation_update: '应用到关系/跟进',
    buyer_intent_target_exclusion: '应用排除规则',
  };
  return labels[type] || '应用';
}

function ProcessingBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: 'bg-amber-50 text-amber-700',
    processing: 'bg-blue-50 text-blue-700',
    parsed: 'bg-blue-50 text-blue-700',
    applied: 'bg-emerald-50 text-emerald-700',
    partially_applied: 'bg-emerald-50 text-emerald-700',
    failed: 'bg-red-50 text-red-700',
  };
  return <span className={`text-xs px-1.5 py-0.5 font-medium ${colors[status] || 'bg-gray-100 text-gray-600'}`}>{status}</span>;
}

function ActionTypeBadge({ type }: { type: string }) {
  const labels: Record<string, string> = {
    seller_fact_update: '标的事实',
    seller_event: '标的事件',
    buyer_seller_relation_update: '关系更新',
    buyer_intent_target_exclusion: '排除标的',
    buyer_intent_update: '买家意向更新',
    buyer_level_blacklist_suggestion: '买家级黑名单建议',
    internal_note: '内部备注',
    unresolved_item: '待澄清事项',
  };
  return <span className="text-xs px-1.5 py-0.5 bg-gray-100 text-gray-700 font-medium">{labels[type] || type}</span>;
}

function ReviewBadge({ status }: { status: string }) {
  const map: Record<string, { color: string; icon: typeof Clock; label: string }> = {
    pending_review: { color: 'text-amber-600', icon: Clock, label: '待复核' },
    accepted: { color: 'text-emerald-600', icon: CheckCircle2, label: '已接受' },
    rejected: { color: 'text-red-500', icon: XCircle, label: '已拒绝' },
    auto_accepted: { color: 'text-emerald-600', icon: CheckCircle2, label: '自动接受' },
    ignored: { color: 'text-gray-400', icon: XCircle, label: '已忽略' },
  };
  const item = map[status] || map['pending_review'];
  const Icon = item.icon;
  return (
    <span className={`text-xs flex items-center gap-0.5 ${item.color}`}>
      <Icon className="w-3 h-3" />
      {item.label}
    </span>
  );
}

function CreateUpdateModal({ targets, onClose, onCreated }: { targets: SellerTarget[]; onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState<BusinessUpdateCreate>({ raw_text: '' });
  const [selectedTargetId, setSelectedTargetId] = useState('');
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.raw_text.trim()) return;
    setSaving(true);
    const data: BusinessUpdateCreate = {
      ...form,
      input_type: 'text',
      bound_seller_target_ids: selectedTargetId ? [selectedTargetId] : undefined,
    };
    try {
      await businessUpdates.create(data);
      onCreated();
    } catch {
      alert('创建失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title="录入业务更新" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field label="原始文本 *">
          <textarea
            value={form.raw_text}
            onChange={(e) => setForm({ ...form, raw_text: e.target.value })}
            className="input min-h-[120px] resize-y"
            placeholder="输入混合业务更新，例如：上海启元项目今天已与项目方沟通..."
            autoFocus
          />
        </Field>
        <Field label="关联标的（可选）">
          <select value={selectedTargetId} onChange={(e) => setSelectedTargetId(e.target.value)} className="input">
            <option value="">不关联</option>
            {targets.map((t) => <option key={t.id} value={t.id}>{t.target_name}</option>)}
          </select>
        </Field>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm border border-gray-200 text-gray-700">取消</button>
          <button type="submit" disabled={saving || !form.raw_text.trim()} className="px-4 py-2 text-sm bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50">
            {saving ? '提交中...' : '提交'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function CreateActionModal({ businessUpdateId, targets, onClose, onCreated }: { businessUpdateId: string; targets: SellerTarget[]; onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState<ExtractedActionCreate>({
    action_type: 'seller_fact_update',
    target_entity_type: 'seller_target',
    target_entity_id: targets[0]?.id || '',
    proposed_changes_json: {},
    raw_evidence_text: '',
  });
  const [changesText, setChangesText] = useState('{}');
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const parsed = JSON.parse(changesText);
      await extractedActions.create(businessUpdateId, { ...form, proposed_changes_json: parsed, confidence: 1 });
      onCreated();
    } catch (err) {
      alert(`创建失败: ${err}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title="人工创建动作" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <Field label="动作类型">
            <select value={form.action_type} onChange={(e) => setForm({ ...form, action_type: e.target.value })} className="input">
              <option value="seller_fact_update">标的事实更新</option>
              <option value="seller_event">标的事件</option>
              <option value="buyer_seller_relation_update">关系更新</option>
              <option value="internal_note">内部备注</option>
            </select>
          </Field>
          <Field label="目标标的">
            <select value={form.target_entity_id} onChange={(e) => setForm({ ...form, target_entity_id: e.target.value })} className="input">
              {targets.map((t) => <option key={t.id} value={t.id}>{t.target_name}</option>)}
            </select>
          </Field>
        </div>
        <Field label="证据原文">
          <textarea value={form.raw_evidence_text || ''} onChange={(e) => setForm({ ...form, raw_evidence_text: e.target.value })} className="input min-h-[60px] resize-y" placeholder="从原始输入中摘取的证据" />
        </Field>
        <Field label="proposed_changes_json">
          <textarea value={changesText} onChange={(e) => setChangesText(e.target.value)} className="input min-h-[80px] resize-y font-mono text-xs" placeholder='{"business_summary": "新值"}' />
        </Field>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm border border-gray-200 text-gray-700">取消</button>
          <button type="submit" disabled={saving} className="px-4 py-2 text-sm bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50">
            {saving ? '创建中...' : '创建'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div className="fixed inset-0 bg-black/30" onClick={onClose} />
      <div className="relative bg-white border border-gray-200 shadow-lg w-full max-w-lg mx-4 max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <h3 className="text-base font-semibold text-gray-900">{title}</h3>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      {children}
    </div>
  );
}
