import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Download,
  FileText,
  Loader2,
  RefreshCw,
  Search,
} from 'lucide-react';
import { attachments, buyerParties } from '../lib/api';
import type {
  AttachmentItem,
  BuyerIntent,
  BuyerIntentParseStatus,
  BuyerParty,
  BuyerPartyCreate,
} from '../types/api';
import { valueLabel } from '../lib/fieldLabels';
import UpdateHistory from './UpdateHistory';
import ProgressPanel from '../features/relations/ProgressPanel';
import BuyerIntentRequirements from './BuyerIntentRequirements';

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
  onIntentRefresh?: () => void | Promise<void>;
}

const TABS: Array<{ key: BuyerWorkspaceTab; label: string }> = [
  { key: 'intent', label: '需求信息' },
  { key: 'buyer', label: '买家资料' },
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
            <BuyerInfo party={party} onSaved={onPartySaved} />
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

export function BuyerInfo({ party, onSaved }: { party: BuyerParty; onSaved?: (party: BuyerParty) => void }) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState<Partial<BuyerPartyCreate>>(() => partyDraft(party));

  useEffect(() => setDraft(partyDraft(party)), [party]);

  const save = async () => {
    setSaving(true);
    try {
      const updated = await buyerParties.update(party.id, {
        buyer_name: draft.buyer_name?.trim() || party.buyer_name,
        legal_name: nullIfEmpty(draft.legal_name),
        buyer_type: nullIfEmpty(draft.buyer_type),
        group_name: nullIfEmpty(draft.group_name),
        listed_status: draft.listed_status || 'unknown',
        region_province: nullIfEmpty(draft.region_province),
        region_city: nullIfEmpty(draft.region_city),
        main_business: nullIfEmpty(draft.main_business),
        capital_strength_summary: nullIfEmpty(draft.capital_strength_summary),
        profile_summary: nullIfEmpty(draft.profile_summary),
        notes: nullIfEmpty(draft.notes),
      });
      onSaved?.(updated);
      setEditing(false);
    } catch (error) {
      alert(error instanceof Error ? error.message : '保存买家资料失败');
    } finally {
      setSaving(false);
    }
  };

  if (!editing) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <p className="text-xs text-gray-500">买家资料由用户手工维护，不参与需求解析。</p>
          <button type="button" onClick={() => setEditing(true)} className="border border-gray-200 px-3 py-1.5 text-xs text-gray-700 hover:border-brand-500 hover:text-brand-700">
            编辑资料
          </button>
        </div>
        <div className="grid grid-cols-1 gap-x-10 gap-y-3 md:grid-cols-2">
          <Info label="买家名称" value={party.buyer_name} />
          <Info label="法人全称" value={party.legal_name} />
          <Info label="买家类型" value={party.buyer_type ? valueLabel('buyer_type', party.buyer_type) : null} />
          <Info label="所属集团" value={party.group_name} />
          <Info label="所在地区" value={`${party.region_province || ''}${party.region_city || ''}`} />
          <Info label="上市状态" value={valueLabel('listed_status', party.listed_status)} />
        </div>
        <div className="space-y-3">
          <Info label="主营业务" value={party.main_business} wide />
          <Info label="资金实力/规模" value={party.capital_strength_summary} wide />
          <Info label="资料摘要" value={party.profile_summary} wide />
          <Info label="备注" value={party.notes} wide />
        </div>
      </div>
    );
  }

  const setField = (key: keyof BuyerPartyCreate, value: string) => setDraft((current) => ({ ...current, [key]: value }));
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <EditField label="买家名称"><input className="input" value={draft.buyer_name || ''} onChange={(event) => setField('buyer_name', event.target.value)} /></EditField>
        <EditField label="法人全称"><input className="input" value={draft.legal_name || ''} onChange={(event) => setField('legal_name', event.target.value)} /></EditField>
        <EditField label="买家类型"><input className="input" value={draft.buyer_type || ''} onChange={(event) => setField('buyer_type', event.target.value)} /></EditField>
        <EditField label="所属集团"><input className="input" value={draft.group_name || ''} onChange={(event) => setField('group_name', event.target.value)} /></EditField>
        <EditField label="省份"><input className="input" value={draft.region_province || ''} onChange={(event) => setField('region_province', event.target.value)} /></EditField>
        <EditField label="城市"><input className="input" value={draft.region_city || ''} onChange={(event) => setField('region_city', event.target.value)} /></EditField>
        <EditField label="上市状态">
          <select className="input" value={draft.listed_status || 'unknown'} onChange={(event) => setField('listed_status', event.target.value)}>
            <option value="unknown">未知</option><option value="listed">已上市</option><option value="unlisted">未上市</option><option value="pre_ipo">拟上市</option>
          </select>
        </EditField>
      </div>
      <EditField label="主营业务"><textarea className="input min-h-20 resize-y" value={draft.main_business || ''} onChange={(event) => setField('main_business', event.target.value)} /></EditField>
      <EditField label="资金实力/规模"><textarea className="input min-h-20 resize-y" value={draft.capital_strength_summary || ''} onChange={(event) => setField('capital_strength_summary', event.target.value)} /></EditField>
      <EditField label="资料摘要"><textarea className="input min-h-20 resize-y" value={draft.profile_summary || ''} onChange={(event) => setField('profile_summary', event.target.value)} /></EditField>
      <EditField label="备注"><textarea className="input min-h-24 resize-y" value={draft.notes || ''} onChange={(event) => setField('notes', event.target.value)} /></EditField>
      <div className="flex justify-end gap-2">
        <button type="button" onClick={() => { setDraft(partyDraft(party)); setEditing(false); }} className="border border-gray-200 px-4 py-2 text-sm text-gray-700">取消</button>
        <button type="button" onClick={() => void save()} disabled={saving} className="bg-brand-600 px-4 py-2 text-sm text-white disabled:opacity-50">{saving ? '保存中' : '保存'}</button>
      </div>
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

function Info({ label, value, wide = false }: { label: string; value: string | number | null | undefined; wide?: boolean }) { return <div className={`flex gap-3 ${wide ? 'items-start' : 'items-baseline'}`}><span className="w-24 shrink-0 text-xs text-gray-500">{label}</span><span className="min-w-0 whitespace-pre-wrap text-sm text-gray-800">{value || '-'}</span></div>; }
function EditField({ label, children }: { label: string; children: ReactNode }) { return <label className="block"><span className="mb-1 block text-xs font-medium text-gray-600">{label}</span>{children}</label>; }
function LoadingText({ text }: { text: string }) { return <div className="flex items-center justify-center py-12 text-sm text-gray-400"><Loader2 className="mr-2 h-4 w-4 animate-spin" />{text}</div>; }
function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) { return <div className="border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"><p>{message}</p><button type="button" onClick={onRetry} className="mt-2 text-xs font-medium underline">重新加载</button></div>; }
function EmptyState({ title, description }: { title: string; description: string }) { return <div className="py-12 text-center"><Search className="mx-auto h-8 w-8 text-gray-300" /><p className="mt-2 text-sm text-gray-500">{title}</p><p className="mt-1 text-xs text-gray-400">{description}</p></div>; }

function AttachmentStatus({ item }: { item: AttachmentItem }) {
  const labels = { pending: '等待读取', processing: '读取中', succeeded: '读取成功', failed: '读取失败', skipped: '无需读取', multimodal: '模型直读' };
  const status = item.content_extraction_status;
  const color = status === 'failed' ? 'bg-red-50 text-red-700' : status === 'processing' || status === 'pending' ? 'bg-blue-50 text-blue-700' : status === 'multimodal' ? 'bg-purple-50 text-purple-700' : 'bg-gray-100 text-gray-600';
  return <span className={`shrink-0 px-1.5 py-0.5 text-[11px] ${color}`}>{labels[status]}</span>;
}

function partyDraft(party: BuyerParty): Partial<BuyerPartyCreate> { return { buyer_name: party.buyer_name, legal_name: party.legal_name || '', buyer_type: party.buyer_type || '', group_name: party.group_name || '', listed_status: party.listed_status || 'unknown', region_province: party.region_province || '', region_city: party.region_city || '', main_business: party.main_business || '', capital_strength_summary: party.capital_strength_summary || '', profile_summary: party.profile_summary || '', notes: party.notes || '' }; }
function nullIfEmpty(value: string | null | undefined): string | null { return value?.trim() || null; }
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
