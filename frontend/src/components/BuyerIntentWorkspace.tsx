import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Check,
  Download,
  FileText,
  Loader2,
  Pencil,
  RefreshCw,
  Search,
  X,
} from 'lucide-react';
import { attachments, buyerIntents, buyerParties, meta } from '../lib/api';
import type {
  AttachmentItem,
  BuyerIntent,
  BuyerIntentParseStatus,
  BuyerParty,
  IndustryOptionsResponse,
} from '../types/api';
import UpdateHistory from './UpdateHistory';
import ProgressPanel from '../features/relations/ProgressPanel';
import BuyerIntentRequirements from './BuyerIntentRequirements';
import AdministrativeAreaPicker, { type AdministrativeAreaValue } from './AdministrativeAreaPicker';
import IndustryPairsEditor, { type IndustryPairValue } from './IndustryPairsEditor';

export type BuyerWorkspaceTab = 'intent' | 'buyer' | 'progress' | 'attachments' | 'history';

interface Props {
  intent: BuyerIntent;
  party: BuyerParty | null;
  parseStatus: BuyerIntentParseStatus | null;
  activeTab: BuyerWorkspaceTab;
  onTabChange: (tab: BuyerWorkspaceTab) => void;
  /** 撮合看板 `?relation=` 深链接，透传给「推进」tab 的 ProgressPanel。 */
  progressOpenRelationId?: string | null;
  onProgressDrawerClose?: () => void;
  historyRefreshKey?: number;
  onPartySaved?: (party: BuyerParty) => void;
  onIntentSaved?: (intent: BuyerIntent) => void;
  onIntentRefresh?: () => void | Promise<void>;
}

const TABS: Array<{ key: BuyerWorkspaceTab; label: string }> = [
  { key: 'intent', label: '需求信息' },
  { key: 'buyer', label: '买家信息' },
  { key: 'progress', label: '推进' },
  { key: 'attachments', label: '附件与证据' },
  { key: 'history', label: '更新记录' },
];

export default function BuyerIntentWorkspace({
  intent,
  party,
  parseStatus,
  activeTab,
  onTabChange,
  progressOpenRelationId = null,
  onProgressDrawerClose,
  historyRefreshKey = 0,
  onPartySaved,
  onIntentSaved,
  onIntentRefresh,
}: Props) {
  return (
    <div className="border border-gray-200 bg-white">
      <div className="flex overflow-x-auto border-b border-gray-100 px-5">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => onTabChange(tab.key)}
            className={`shrink-0 border-b-2 px-4 py-3 text-sm font-medium transition-colors ${
              activeTab === tab.key
                ? 'border-brand-600 text-brand-600'
                : 'border-transparent text-gray-500 hover:text-gray-800'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className={activeTab === 'history' ? '' : 'p-5'}>
        {activeTab === 'intent' ? <BuyerIntentRequirements intent={intent} parseStatus={parseStatus} onRefresh={onIntentRefresh} /> : null}
        {activeTab === 'buyer' ? (
          party ? (
            <BuyerInfo party={party} intent={intent} onPartySaved={onPartySaved} onIntentSaved={onIntentSaved} />
          ) : (
            <EmptyState title="当前需求未关联买家" description="可在买家管理中补充关联关系。" />
          )
        ) : null}
        {activeTab === 'progress' ? (
          <ProgressPanel
            side="buyer_intent"
            entityId={intent.id}
            initialOpenId={progressOpenRelationId}
            onDrawerClose={onProgressDrawerClose}
          />
        ) : null}
        {activeTab === 'attachments' ? <IntentAttachments intentId={intent.id} onIntentRefresh={onIntentRefresh} /> : null}
        {activeTab === 'history' ? (
          <UpdateHistory
            entityType="buyer_intent"
            entityId={intent.id}
            refreshKey={historyRefreshKey}
            onRolledBack={onIntentRefresh}
            onProcessingSettled={onIntentRefresh}
          />
        ) : null}
      </div>
    </div>
  );
}

export function IntentStatusBadge({ status }: { status: string }) {
  const labels: Record<string, string> = {
    active: '持续推荐',
    paused: '暂停推荐',
    closed: '已结束',
  };
  const className = status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-600';
  return <span className={`px-2 py-0.5 text-xs font-medium ${className}`}>{labels[status] || status}</span>;
}

type BuyerInfoField = 'buyer_name' | 'location' | 'industry' | 'region' | 'contact_name' | 'contact_info' | 'notes';

export function BuyerInfo({
  party,
  intent,
  onPartySaved,
  onIntentSaved,
}: {
  party: BuyerParty;
  intent?: BuyerIntent | null;
  onPartySaved?: (party: BuyerParty) => void;
  onIntentSaved?: (intent: BuyerIntent) => void;
}) {
  const [editingField, setEditingField] = useState<BuyerInfoField | null>(null);
  const [saving, setSaving] = useState(false);
  const [textDraft, setTextDraft] = useState('');
  const [locationDraft, setLocationDraft] = useState<AdministrativeAreaValue>({ province: '' });
  const [industryDraft, setIndustryDraft] = useState<IndustryPairValue[]>([]);
  const [regionDraft, setRegionDraft] = useState<AdministrativeAreaValue & { effect: 'required' | 'preferred' | 'excluded' }>({ province: '', effect: 'preferred' });
  const [taxonomy, setTaxonomy] = useState<IndustryOptionsResponse>({ l1: [], l2: [] });

  useEffect(() => {
    let cancelled = false;
    meta.industryOptions().then((value) => { if (!cancelled) setTaxonomy(value); }).catch(() => {});
    return () => { cancelled = true; };
  }, []);
  useEffect(() => setEditingField(null), [party.id, intent?.id]);

  const startEditing = (field: BuyerInfoField) => {
    if (!intent && isIntentField(field)) return;
    if (field === 'buyer_name') setTextDraft(party.buyer_name);
    if (field === 'location') setLocationDraft({ province: party.region_province || '', city: party.region_city || undefined });
    if (field === 'industry') setIndustryDraft(intentIndustryPairs(intent, taxonomy));
    if (field === 'region') setRegionDraft(intentRegion(intent));
    if (field === 'contact_name') setTextDraft(intent?.contact_name || '');
    if (field === 'contact_info') setTextDraft(contactInfoText(intent?.contact_info_json));
    if (field === 'notes') setTextDraft(party.notes || '');
    setEditingField(field);
  };

  const saveField = async () => {
    if (!editingField) return;
    setSaving(true);
    try {
      if (editingField === 'buyer_name') {
        const buyerName = textDraft.trim();
        if (!buyerName) throw new Error('买家名称不能为空');
        onPartySaved?.(await buyerParties.update(party.id, { buyer_name: buyerName }));
      } else if (editingField === 'location') {
        onPartySaved?.(await buyerParties.update(party.id, {
          region_province: nullIfEmpty(locationDraft.province),
          region_city: nullIfEmpty(locationDraft.city),
        }));
      } else if (editingField === 'notes') {
        onPartySaved?.(await buyerParties.update(party.id, { notes: nullIfEmpty(textDraft) }));
      } else if (intent) {
        if (editingField === 'industry') {
          onIntentSaved?.(await buyerIntents.update(intent.id, {
            industries_json: [...new Set(industryDraft.map((pair) => pair.l1).filter(Boolean))],
            industry_l2_json: [...new Set(industryDraft.flatMap((pair) => pair.l2 ? [pair.l2] : []))],
          }));
        } else if (editingField === 'region') {
          onIntentSaved?.(await buyerIntents.update(intent.id, {
            region_constraints_json: regionDraft.province ? [regionDraft] : [],
          }));
        } else if (editingField === 'contact_name') {
          onIntentSaved?.(await buyerIntents.update(intent.id, { contact_name: nullIfEmpty(textDraft) }));
        } else if (editingField === 'contact_info') {
          onIntentSaved?.(await buyerIntents.update(intent.id, {
            contact_info_json: textDraft.trim() ? { text: textDraft.trim() } : {},
          }));
        }
      }
      setEditingField(null);
    } catch (error) {
      alert(error instanceof Error ? error.message : '保存买家信息失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <p className="mb-3 text-xs text-gray-500">买家主体信息与当前需求的行业、地区和联系人集中展示；每个字段独立编辑、独立保存。</p>
      <div className="divide-y divide-gray-100 border border-gray-100 px-4">
        <BuyerInfoRow label="买家名称" value={party.buyer_name} field="buyer_name" editingField={editingField} saving={saving} onEdit={startEditing} onSave={saveField} onCancel={() => setEditingField(null)}>
          <input className="input" value={textDraft} onChange={(event) => setTextDraft(event.target.value)} autoFocus />
        </BuyerInfoRow>
        <BuyerInfoRow label="所在地区" value={buyerLocationText(party)} field="location" editingField={editingField} saving={saving} onEdit={startEditing} onSave={saveField} onCancel={() => setEditingField(null)}>
          <AdministrativeAreaPicker value={locationDraft} onChange={setLocationDraft} showDistrict={false} />
        </BuyerInfoRow>
        <BuyerInfoRow label="行业" value={industryText(intent, taxonomy)} field="industry" editingField={editingField} saving={saving} disabled={!intent || !taxonomy.l1.length} onEdit={startEditing} onSave={saveField} onCancel={() => setEditingField(null)}>
          <IndustryPairsEditor value={industryDraft} options={taxonomy} onChange={setIndustryDraft} />
        </BuyerInfoRow>
        <BuyerInfoRow label="地区" value={regionText(intent)} field="region" editingField={editingField} saving={saving} disabled={!intent} onEdit={startEditing} onSave={saveField} onCancel={() => setEditingField(null)}>
          <div className="space-y-2 border border-gray-200 bg-gray-50 p-2">
            <AdministrativeAreaPicker value={regionDraft} onChange={(area) => setRegionDraft({ ...area, effect: regionDraft.effect })} />
            <p className="text-[10px] text-gray-400">变更上级会自动清空下级；筛选仍按省、市、区三个字段命中。</p>
          </div>
        </BuyerInfoRow>
        <BuyerInfoRow label="联系人" value={intent?.contact_name || ''} field="contact_name" editingField={editingField} saving={saving} disabled={!intent} onEdit={startEditing} onSave={saveField} onCancel={() => setEditingField(null)}>
          <input className="input" value={textDraft} onChange={(event) => setTextDraft(event.target.value)} autoFocus />
        </BuyerInfoRow>
        <BuyerInfoRow label="联系方式" value={contactInfoText(intent?.contact_info_json)} field="contact_info" editingField={editingField} saving={saving} disabled={!intent} onEdit={startEditing} onSave={saveField} onCancel={() => setEditingField(null)}>
          <textarea className="input min-h-20 resize-y" value={textDraft} onChange={(event) => setTextDraft(event.target.value)} placeholder="电话、邮箱、微信等" autoFocus />
        </BuyerInfoRow>
        <BuyerInfoRow label="其他" value={party.notes || ''} field="notes" editingField={editingField} saving={saving} onEdit={startEditing} onSave={saveField} onCancel={() => setEditingField(null)}>
          <textarea className="input min-h-28 resize-y" value={textDraft} onChange={(event) => setTextDraft(event.target.value)} autoFocus />
        </BuyerInfoRow>
      </div>
      {!intent ? <p className="mt-2 text-xs text-gray-400">录入并购需求后即可维护行业、目标地区、联系人和联系方式。</p> : null}
    </div>
  );
}

function BuyerInfoRow({
  label,
  value,
  field,
  editingField,
  saving,
  disabled = false,
  onEdit,
  onSave,
  onCancel,
  children,
}: {
  label: string;
  value: string;
  field: BuyerInfoField;
  editingField: BuyerInfoField | null;
  saving: boolean;
  disabled?: boolean;
  onEdit: (field: BuyerInfoField) => void;
  onSave: () => Promise<void>;
  onCancel: () => void;
  children: ReactNode;
}) {
  const editing = editingField === field;
  return (
    <div className="py-3">
      {editing ? (
        <div className="space-y-3">
          <p className="text-xs font-medium text-gray-600">{label}</p>
          {children}
          <div className="flex justify-end gap-2">
            <button type="button" disabled={saving} onClick={() => void onSave()} className="inline-flex items-center gap-1 bg-brand-600 px-3 py-1.5 text-xs text-white disabled:opacity-50">{saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}保存</button>
            <button type="button" disabled={saving} onClick={onCancel} className="inline-flex items-center gap-1 border border-gray-200 px-3 py-1.5 text-xs text-gray-600"><X className="h-3.5 w-3.5" />取消</button>
          </div>
        </div>
      ) : (
        <div className="flex items-start gap-3">
          <span className="w-24 shrink-0 text-xs text-gray-500">{label}</span>
          <span className={`min-w-0 flex-1 whitespace-pre-wrap text-sm ${value ? 'text-gray-800' : 'text-gray-300'}`}>{value || (disabled ? '录入需求后维护' : '未填写')}</span>
          <button type="button" title={`编辑${label}`} disabled={disabled} onClick={() => onEdit(field)} className="p-1.5 text-gray-400 hover:bg-gray-100 hover:text-brand-700 disabled:cursor-not-allowed disabled:opacity-30"><Pencil className="h-3.5 w-3.5" /></button>
        </div>
      )}
    </div>
  );
}

function IntentAttachments({ intentId, onIntentRefresh }: { intentId: string; onIntentRefresh?: () => void | Promise<void> }) {
  const [items, setItems] = useState<AttachmentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await attachments.list({ entity_type: 'buyer_intent', entity_id: intentId, limit: 100 }));
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '附件读取失败');
    } finally {
      setLoading(false);
    }
  }, [intentId]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!items.some((item) => ['pending', 'processing'].includes(item.content_extraction_status))) return;
    const timer = window.setInterval(() => { void load(); void onIntentRefresh?.(); }, 2500);
    return () => window.clearInterval(timer);
  }, [items, load, onIntentRefresh]);

  const download = async (item: AttachmentItem) => {
    setDownloadingId(item.id);
    try {
      const response = await attachments.download(item.id);
      const url = window.URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = item.file_name || 'attachment';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(url);
    } catch (downloadError) {
      alert(downloadError instanceof Error ? downloadError.message : '下载失败');
    } finally {
      setDownloadingId(null);
    }
  };

  const reprocess = async (item: AttachmentItem) => {
    setRetryingId(item.id);
    try {
      await attachments.reprocess(item.id);
      await Promise.all([load(), Promise.resolve(onIntentRefresh?.())]);
    } catch (retryError) {
      alert(retryError instanceof Error ? retryError.message : '重新处理失败');
    } finally {
      setRetryingId(null);
    }
  };

  if (loading) return <LoadingText text="正在读取附件" />;
  if (error) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!items.length) return <EmptyState title="暂无附件" description="录入当前并购需求更新时上传的文件会自动出现在这里。" />;
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">共 {items.length} 个附件</p>
        <button type="button" onClick={() => void load()} className="inline-flex items-center gap-1.5 border border-gray-200 px-2.5 py-1.5 text-xs text-gray-600 hover:border-brand-500 hover:text-brand-700">
          <RefreshCw className="h-3.5 w-3.5" />刷新
        </button>
      </div>
      <div className="divide-y divide-gray-100 border border-gray-100">
        {items.map((item) => (
          <div key={item.id} className="flex items-center justify-between gap-4 px-4 py-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2"><FileText className="h-4 w-4 shrink-0 text-gray-400" /><p className="truncate text-sm font-medium text-gray-900">{item.file_name}</p><AttachmentStatus item={item} /></div>
              <p className="mt-1 text-xs text-gray-400">{attachmentKindLabel(item)} · {formatBytes(item.file_size)} · {formatDateTime(item.uploaded_at)}</p>
              {item.error_message ? <p className="mt-1 max-w-2xl text-xs text-red-600">{item.error_message}</p> : null}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {item.recoverable ? <button type="button" onClick={() => void reprocess(item)} disabled={retryingId === item.id} className="inline-flex items-center gap-1.5 border border-red-200 px-2.5 py-1.5 text-xs text-red-700 hover:bg-red-50 disabled:opacity-50">{retryingId === item.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}重新处理</button> : null}
              <button type="button" onClick={() => void download(item)} disabled={downloadingId === item.id} className="inline-flex items-center gap-1.5 border border-gray-200 px-2.5 py-1.5 text-xs text-gray-600 hover:border-brand-500 hover:text-brand-700 disabled:opacity-50">
                {downloadingId === item.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}下载
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function LoadingText({ text }: { text: string }) { return <div className="flex items-center justify-center py-12 text-sm text-gray-400"><Loader2 className="mr-2 h-4 w-4 animate-spin" />{text}</div>; }
function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) { return <div className="border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"><p>{message}</p><button type="button" onClick={onRetry} className="mt-2 text-xs font-medium underline">重新加载</button></div>; }
function EmptyState({ title, description }: { title: string; description: string }) { return <div className="py-12 text-center"><Search className="mx-auto h-8 w-8 text-gray-300" /><p className="mt-2 text-sm text-gray-500">{title}</p><p className="mt-1 text-xs text-gray-400">{description}</p></div>; }

function AttachmentStatus({ item }: { item: AttachmentItem }) {
  const labels = { pending: '等待读取', processing: '读取中', succeeded: '读取成功', failed: '读取失败', skipped: '无需读取', multimodal: '模型直读' };
  const status = item.content_extraction_status;
  const color = status === 'failed' ? 'bg-red-50 text-red-700' : status === 'processing' || status === 'pending' ? 'bg-blue-50 text-blue-700' : status === 'multimodal' ? 'bg-purple-50 text-purple-700' : 'bg-gray-100 text-gray-600';
  return <span className={`shrink-0 px-1.5 py-0.5 text-[11px] ${color}`}>{labels[status]}</span>;
}

function nullIfEmpty(value: string | null | undefined): string | null { return value?.trim() || null; }
function isIntentField(field: BuyerInfoField): boolean { return ['industry', 'region', 'contact_name', 'contact_info'].includes(field); }
function buyerLocationText(party: BuyerParty): string { return [party.region_province, party.region_city].filter(Boolean).join(' '); }
function intentRegion(intent?: BuyerIntent | null): AdministrativeAreaValue & { effect: 'required' | 'preferred' | 'excluded' } {
  const regions = Array.isArray(intent?.region_constraints_json) ? intent.region_constraints_json : [];
  const region = regions.find((item) => item.effect !== 'excluded' && item.province) || regions.find((item) => item.province);
  return region ? { ...region } : { province: '', effect: 'preferred' };
}
function regionText(intent?: BuyerIntent | null): string {
  const region = intentRegion(intent);
  return [region.province, region.city, region.district].filter(Boolean).join(' / ');
}
function intentIndustryPairs(intent: BuyerIntent | null | undefined, taxonomy: IndustryOptionsResponse): IndustryPairValue[] {
  if (!intent) return [];
  const pairs: IndustryPairValue[] = (intent.industries_json || []).map((l1) => ({ l1 }));
  for (const l2 of intent.industry_l2_json || []) {
    const match = taxonomy.l2.find((item) => item.term === l2);
    if (match) pairs.push({ l1: match.l1, l2 });
  }
  const seen = new Set<string>();
  return pairs.filter((pair) => {
    const key = `${pair.l1}:${pair.l2 || ''}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
function industryText(intent: BuyerIntent | null | undefined, taxonomy: IndustryOptionsResponse): string {
  const pairs = intentIndustryPairs(intent, taxonomy);
  const grouped = new Map<string, string[]>();
  for (const pair of pairs) {
    const l2 = grouped.get(pair.l1) || [];
    if (pair.l2) l2.push(pair.l2);
    grouped.set(pair.l1, l2);
  }
  const mappedL2 = new Set(pairs.flatMap((pair) => pair.l2 ? [pair.l2] : []));
  const unmatchedL2 = (intent?.industry_l2_json || []).filter((l2) => !mappedL2.has(l2));
  return [
    ...[...grouped.entries()].map(([l1, l2]) => l2.length ? `${l1} / ${l2.join('、')}` : l1),
    ...unmatchedL2,
  ].join('；');
}
function contactInfoText(value: Record<string, unknown> | null | undefined): string {
  if (!value || !Object.keys(value).length) return '';
  if (typeof value.text === 'string') return value.text;
  const labels: Record<string, string> = { phone: '电话', mobile: '手机', email: '邮箱', wechat: '微信' };
  return Object.entries(value).flatMap(([key, item]) => {
    if (item === null || item === undefined || item === '') return [];
    const text = Array.isArray(item) ? item.join('、') : typeof item === 'object' ? JSON.stringify(item) : String(item);
    return [`${labels[key] || key}：${text}`];
  }).join('\n');
}
function attachmentKindLabel(item: AttachmentItem): string {
  const extension = (item.file_type || item.file_name.split('.').pop() || '').toLowerCase();
  if (item.extraction_strategy === 'multimodal_llm_direct') return '图片 · 模型直接读取';
  if (extension === 'doc' || extension === 'docx') return `Word 文档 · ${item.extraction_strategy === 'office_text_layer' ? '本地内容读取' : '内容读取'}`;
  if (extension === 'xls' || extension === 'xlsx') return `Excel 文档 · ${item.extraction_strategy === 'office_text_layer' ? '本地内容读取' : '内容读取'}`;
  if (extension === 'ppt' || extension === 'pptx') return `PowerPoint 文档 · ${item.extraction_strategy === 'office_text_layer' ? '本地内容读取' : '内容读取'}`;
  if (item.extraction_strategy === 'doc2x_ocr') return '扫描 PDF · OCR';
  return item.mime_type || item.file_type || '未知类型';
}
function formatBytes(value: number | null): string { if (value === null) return '未知大小'; if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`; if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`; return `${value} B`; }
function formatDateTime(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }); }
